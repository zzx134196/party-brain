"""文件差异对比引擎"""
import asyncio
import difflib
from typing import Dict, Any, List

from loguru import logger

from app.core.llm import llm_service


DIFF_ANALYSIS_PROMPT = """你是一个文档差异分析助手。以下是两份文档的文本差异，请分析并输出结构化的差异报告。

文件1标题：{file1_name}
文件2标题：{file2_name}

文本差异（unified diff格式）：
{diff_text}

请输出JSON格式的差异分析：
{{
  "total_diffs": 差异总数,
  "diffs": [
    {{
      "index": 序号,
      "type": "修改/新增/删除",
      "location": "差异位置描述",
      "old_text": "旧版文本（删除/修改时）",
      "new_text": "新版文本（新增/修改时）",
      "summary": "变更说明（一句话）",
      "severity": "high/medium/low"
    }}
  ],
  "summary": {{
    "modified": 修改数,
    "added": 新增数,
    "deleted": 删除数
  }}
}}"""


# AI 语义分析超时时间（秒）。超时后自动降级为基础差异规则，避免前端长时间无响应。
DIFF_LLM_TIMEOUT = 100


def compute_text_diff(text1: str, text2: str) -> List[str]:
    """计算两段文本的差异（unified diff格式）"""
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = list(difflib.unified_diff(lines1, lines2, lineterm=''))
    return diff


def compute_line_diff(text1: str, text2: str) -> List[Dict]:
    """计算逐行差异"""
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()

    matcher = difflib.SequenceMatcher(None, lines1, lines2)
    diffs = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
        elif tag == 'replace':
            diffs.append({
                "type": "修改",
                "old_text": "\n".join(lines1[i1:i2]),
                "new_text": "\n".join(lines2[j1:j2]),
                "old_range": f"行{i1+1}-{i2}",
                "new_range": f"行{j1+1}-{j2}",
            })
        elif tag == 'delete':
            diffs.append({
                "type": "删除",
                "old_text": "\n".join(lines1[i1:i2]),
                "new_text": "",
                "old_range": f"行{i1+1}-{i2}",
                "new_range": "",
            })
        elif tag == 'insert':
            diffs.append({
                "type": "新增",
                "old_text": "",
                "new_text": "\n".join(lines2[j1:j2]),
                "old_range": "",
                "new_range": f"行{j1+1}-{j2}",
            })

    return diffs


def compute_similarity(text1: str, text2: str) -> float:
    """计算两段文本的相似度"""
    return difflib.SequenceMatcher(None, text1, text2).ratio()


async def analyze_diff_with_llm(
    file1_name: str,
    file2_name: str,
    text1: str,
    text2: str,
) -> Dict[str, Any]:
    """使用LLM分析文件差异"""
    # 先计算基础差异
    line_diffs = compute_line_diff(text1, text2)
    similarity = compute_similarity(text1, text2)

    if not line_diffs:
        return {
            "total_diffs": 0,
            "diffs": [],
            "summary": {"modified": 0, "added": 0, "deleted": 0},
            "similarity": round(similarity * 100, 1),
            "message": "两份文件内容完全一致，没有差异。",
        }

    # 构建简化的diff文本给LLM分析
    diff_text_parts = []
    for i, d in enumerate(line_diffs[:20], 1):  # 最多分析20处差异
        diff_text_parts.append(f"差异{i} [{d['type']}]:")
        if d['old_text']:
            diff_text_parts.append(f"  旧: {d['old_text'][:200]}")
        if d['new_text']:
            diff_text_parts.append(f"  新: {d['new_text'][:200]}")
    diff_text = "\n".join(diff_text_parts)

    try:
        messages = [
            {"role": "system", "content": "你是一个文档差异分析助手，只输出JSON。"},
            {"role": "user", "content": DIFF_ANALYSIS_PROMPT.format(
                file1_name=file1_name,
                file2_name=file2_name,
                diff_text=diff_text,
            )},
        ]
        result = await asyncio.wait_for(
            llm_service.chat_json(messages),
            timeout=DIFF_LLM_TIMEOUT,
        )
        if "error" not in result:
            result["similarity"] = round(similarity * 100, 1)
            return result
    except asyncio.TimeoutError:
        logger.warning(f"LLM差异分析超时（>{DIFF_LLM_TIMEOUT}s），使用基础差异规则")
    except Exception as e:
        logger.warning(f"LLM差异分析失败: {e}")

    # LLM失败时使用基础分析结果
    modified = sum(1 for d in line_diffs if d['type'] == '修改')
    added = sum(1 for d in line_diffs if d['type'] == '新增')
    deleted = sum(1 for d in line_diffs if d['type'] == '删除')

    fallback_result = {
        "total_diffs": len(line_diffs),
        "diffs": [
            {
                "index": i + 1,
                "type": d["type"],
                "location": d.get("old_range") or d.get("new_range", ""),
                "old_text": d["old_text"][:300] if d["old_text"] else "",
                "new_text": d["new_text"][:300] if d["new_text"] else "",
                "summary": f"{d['type']}了内容",
                "severity": "medium",
            }
            for i, d in enumerate(line_diffs[:20])
        ],
        "summary": {"modified": modified, "added": added, "deleted": deleted},
        "similarity": round(similarity * 100, 1),
        "fallback": True,
        "message": (
            "⚠️ AI语义差异分析超时或暂不可用，已使用基础文本差异规则输出清单；"
            "部分差异说明可能不够精确，建议人工复核。"
        ),
    }
    return fallback_result
