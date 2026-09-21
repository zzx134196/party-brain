"""文件差异对比引擎

设计原则：
1. 「哪里有差异、是新增/删除/修改、新旧文本是什么」一律以 difflib 的规则比对为准，
   大模型只负责补充「这一处改了什么」的说明和严重程度，避免模型臆造或漏掉删除内容。
2. 送给大模型的是带编号、带 - / + 标记的差异片段（unified diff 风格），
   而不是把 «旧: xxx / 新: yyy» 截断后直接丢过去，这样模型能看清哪些行被删、哪些行被加。
"""
import asyncio
import difflib
from typing import Dict, Any, List

from loguru import logger

from app.core.llm import llm_service

# 报告里最多展示/送检的差异数量
MAX_REPORT_DIFFS = 20
# 送给大模型的差异文本上限（字符），避免超长文本挤爆上下文
MAX_DIFF_PROMPT_CHARS = 12000
# 每个差异片段携带的上下文行数
HUNK_CONTEXT_LINES = 1
# 报告中单侧（旧版/新版）文本保留的最大长度
MAX_SIDE_CHARS = 600

# difflib opcode -> 差异类型
_OPCODE_TYPE = {
    "replace": "修改",
    "delete": "删除",
    "insert": "新增",
}

_VALID_SEVERITIES = ("high", "medium", "low")

DIFF_ANALYSIS_PROMPT = """你是一个文档差异分析助手。下面给出两份文档的差异片段。

文件1：{file1_name}
文件2：{file2_name}

差异片段（已编号；`- ` 开头是文件1中被删掉的行，`+ ` 开头是文件2中新增的行，其余为上下文，未标出的行表示两侧一致）：

{numbered_diff}

请只输出如下 JSON，不要输出任何解释文字：
{{
  "diffs": [
    {{"index": 1, "summary": "一句话说明这一处改了什么", "severity": "high/medium/low"}}
  ]
}}

要求：
1. index 必须与上面的片段编号一一对应，不要新增、合并或遗漏编号；
2. 只能描述片段里真实可见的改动，禁止推测上下文之外的内容；
3. 新增/删除以 - / + 行为准；若两侧仅措辞、日期或数字不同，请在 summary 中直接点明；
4. severity 只能是 high、medium、low 三者之一。"""


# AI 语义分析超时时间（秒）。超时后自动降级为基础差异规则，避免前端长时间无响应。
DIFF_LLM_TIMEOUT = 100

FALLBACK_MESSAGE = (
    "⚠️ AI语义差异分析超时或暂不可用，已使用基础文本差异规则输出清单；"
    "部分差异说明可能不够精确，建议人工复核。"
)


def _split_lines(text: str) -> List[str]:
    return text.splitlines()


def _range_text(start: int, end: int) -> str:
    """把 0-based 半开区间转成 1-based 的「行x-y」描述"""
    if end <= start:
        return "无"
    return f"{start + 1}-{end}"


def _clip(text: str, limit: int) -> str:
    """按行截断长文本，保留首尾，中间用提示替代"""
    if len(text) <= limit:
        return text
    half = max(limit // 2, 1)
    return text[:half] + "\n...（中间差异已省略，共省略若干行）...\n" + text[-half:]


def _clip_side(text: str, limit: int = MAX_SIDE_CHARS) -> str:
    """整行裁剪单侧文本，避免把某一行截成半句造成「内容变了」的错觉"""
    if not text:
        return ""
    lines = text.split("\n")
    kept: List[str] = []
    size = 0
    for line in lines:
        if kept and size + len(line) > limit:
            break
        kept.append(line)
        size += len(line) + 1
    if len(kept) < len(lines):
        return "\n".join(kept) + f"\n…（其余 {len(lines) - len(kept)} 行省略）"
    return text


def _location(d: Dict[str, Any]) -> str:
    parts = []
    if d.get("old_range"):
        parts.append(f"旧版{d['old_range']}")
    if d.get("new_range"):
        parts.append(f"新版{d['new_range']}")
    return " → ".join(parts) if parts else "全文"


def compute_text_diff(text1: str, text2: str) -> List[str]:
    """计算两段文本的差异（unified diff格式）"""
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines1, lines2, lineterm=''))
    return diff


def compute_line_diff(text1: str, text2: str) -> List[Dict]:
    """计算逐行差异（规则比对结果，作为差异类型的唯一依据）"""
    lines1 = _split_lines(text1)
    lines2 = _split_lines(text2)

    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    diffs = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        diffs.append({
            "type": _OPCODE_TYPE[tag],
            "old_text": "\n".join(lines1[i1:i2]),
            "new_text": "\n".join(lines2[j1:j2]),
            "old_range": f"行{i1 + 1}-{i2}" if i2 > i1 else "",
            "new_range": f"行{j1 + 1}-{j2}" if j2 > j1 else "",
            "old_lines": i2 - i1,
            "new_lines": j2 - j1,
        })

    return diffs


def build_numbered_diff(
    text1: str,
    text2: str,
    max_diffs: int = MAX_REPORT_DIFFS,
    context: int = HUNK_CONTEXT_LINES,
) -> str:
    """构造带编号、带 - / + 标记的差异片段，供大模型语义分析使用"""
    lines1 = _split_lines(text1)
    lines2 = _split_lines(text2)

    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    parts: List[str] = []
    idx = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        idx += 1
        if idx > max_diffs:
            parts.append(f"（其余差异未展示，本清单最多列出前 {max_diffs} 处）")
            break

        parts.append(
            f"差异{idx} [{_OPCODE_TYPE[tag]}] "
            f"旧版行{_range_text(i1, i2)} / 新版行{_range_text(j1, j2)}"
        )
        for line in lines1[max(0, i1 - context):i1]:
            parts.append(f"  {line}")
        if tag in ("replace", "delete"):
            parts.extend(f"- {line}" for line in lines1[i1:i2])
        if tag in ("replace", "insert"):
            parts.extend(f"+ {line}" for line in lines2[j1:j2])
        for line in lines2[j2:j2 + context]:
            parts.append(f"  {line}")
        parts.append("")

    return "\n".join(parts).strip()


def compute_similarity(text1: str, text2: str) -> float:
    """计算两段文本的相似度"""
    return difflib.SequenceMatcher(None, text1, text2).ratio()


def _rule_based_report(
    line_diffs: List[Dict],
    similarity: float,
    note: str = "",
) -> Dict[str, Any]:
    """基于规则比对生成完整报告（大模型不可用时的降级结果）"""
    diffs = []
    for i, d in enumerate(line_diffs[:MAX_REPORT_DIFFS], 1):
        diffs.append({
            "index": i,
            "type": d["type"],
            "location": _location(d),
            "old_text": _clip_side(d["old_text"]),
            "new_text": _clip_side(d["new_text"]),
            "summary": f"{d['type']}内容（旧版 {d['old_lines']} 行 → 新版 {d['new_lines']} 行）",
            "severity": "medium",
        })

    report = {
        "total_diffs": len(line_diffs),
        "shown_diffs": len(diffs),
        "diffs": diffs,
        "summary": {
            "modified": sum(1 for d in line_diffs if d["type"] == "修改"),
            "added": sum(1 for d in line_diffs if d["type"] == "新增"),
            "deleted": sum(1 for d in line_diffs if d["type"] == "删除"),
        },
        "similarity": round(similarity * 100, 1),
    }
    if note:
        report["fallback"] = True
        report["message"] = note
    return report


def _apply_llm_notes(report: Dict[str, Any], llm_result: Dict[str, Any]) -> None:
    """只采信大模型的「说明」与「严重程度」，类型/新旧文本一律以规则比对为准"""
    llm_diffs = llm_result.get("diffs")
    if not isinstance(llm_diffs, list):
        return

    notes: Dict[int, Dict[str, Any]] = {}
    for item in llm_diffs:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        notes[index] = item

    for d in report["diffs"]:
        note = notes.get(d["index"])
        if not note:
            continue
        summary = str(note.get("summary") or "").strip()
        if summary:
            d["summary"] = summary
        severity = str(note.get("severity") or "").strip().lower()
        if severity in _VALID_SEVERITIES:
            d["severity"] = severity

    report["ai_analyzed"] = bool(notes)


async def analyze_diff_with_llm(
    file1_name: str,
    file2_name: str,
    text1: str,
    text2: str,
    on_thinking=None,
) -> Dict[str, Any]:
    """使用LLM分析文件差异"""
    # 先计算基础差异（规则结果是类型/新旧文本的唯一依据）
    line_diffs = compute_line_diff(text1, text2)
    similarity = compute_similarity(text1, text2)

    if not line_diffs:
        return {
            "total_diffs": 0,
            "shown_diffs": 0,
            "diffs": [],
            "summary": {"modified": 0, "added": 0, "deleted": 0},
            "similarity": round(similarity * 100, 1),
            "message": "两份文件内容完全一致，没有差异。",
        }

    report = _rule_based_report(line_diffs, similarity)

    numbered_diff = _clip(build_numbered_diff(text1, text2), MAX_DIFF_PROMPT_CHARS)
    if on_thinking:
        await on_thinking(
            f"规则比对已完成：共 {len(line_diffs)} 处差异"
            f"（修改 {report['summary']['modified']} / 新增 {report['summary']['added']} / "
            f"删除 {report['summary']['deleted']}），正在交由 AI 补充语义说明...\n"
        )

    try:
        messages = [
            {"role": "system", "content": "你是一个文档差异分析助手，只输出JSON。"},
            {"role": "user", "content": DIFF_ANALYSIS_PROMPT.format(
                file1_name=file1_name,
                file2_name=file2_name,
                numbered_diff=numbered_diff,
            )},
        ]
        llm_result = await asyncio.wait_for(
            llm_service.chat_json(messages, on_thinking=on_thinking),
            timeout=DIFF_LLM_TIMEOUT,
        )
        if isinstance(llm_result, dict) and "error" not in llm_result:
            _apply_llm_notes(report, llm_result)
            return report
        logger.warning(f"LLM差异分析返回异常结果，使用基础差异规则: {str(llm_result)[:200]}")
    except asyncio.TimeoutError:
        logger.warning(f"LLM差异分析超时（>{DIFF_LLM_TIMEOUT}s），使用基础差异规则")
    except Exception as e:
        logger.warning(f"LLM差异分析失败: {e}")

    # LLM失败时使用基础分析结果
    report["fallback"] = True
    report["message"] = FALLBACK_MESSAGE
    return report
