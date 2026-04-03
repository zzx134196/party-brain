"""意图识别与参数提取模块（Workflow 模式核心）"""
import re
from typing import Dict, List, Optional
from loguru import logger

from app.core.llm import llm_service


# ========== 意图识别 ==========

INTENT_PROMPT = """你是一个意图分类助手。根据用户的输入，判断其意图属于以下哪个类别：

1. template_generate - 辅助生成/模板填充（用户想生成工作计划、活动方案、总结、报告等文档）
2. policy_qa - 政策法规咨询（询问某个政策的内容、规定、流程等）
3. compliance_check - 合规判断（判断某人/某事是否满足某个条件/规定）
4. file_diff - 文件差异对比（对比两份文件的不同之处）
5. export_file - 导出文件（导出Word/PDF/Excel）
6. general_chat - 通用对话/通识问题/闲聊（打招呼、闲聊、常识问题、天气、科技、历史等非党务专业问题）

请严格按以下JSON格式输出，不要输出其他内容：
{"intent": "分类名称", "confidence": 0.95, "keywords": ["关键词1", "关键词2"]}

用户输入：{user_input}"""


VALID_INTENTS = [
    "template_generate", "policy_qa", "compliance_check",
    "file_diff", "export_file", "general_chat"
]


def _detect_last_action(conversation_history: Optional[List[Dict]] = None) -> Optional[str]:
    """从对话历史中检测上一轮系统执行了什么动作
    
    返回值：
    - 'outline_generated' : 上一轮生成了文档大纲
    - 'document_generated': 上一轮生成了完整文档
    - 'policy_answered'   : 上一轮回答了政策问题
    - None               : 无法判断或无相关历史
    """
    if not conversation_history:
        return None
    # 从后向前找最近的 assistant 消息
    for msg in reversed(conversation_history):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        # 检测大纲生成标志
        if any(kw in content for kw in ["大纲已生成", "确认后生成全文", "确认，生成全文", "请确认大纲", "以下是大纲"]):
            return "outline_generated"
        # 检测完整文档生成标志
        if any(kw in content for kw in ["已生成完毕", "全文如下", "以下是完整", "文档已生成"]):
            return "document_generated"
        # 检测政策回答标志
        if any(kw in content for kw in ["根据", "依据", "条款", "规定"]):
            return "policy_answered"
        # 只看最近一条 assistant 消息
        break
    return None


def _is_modification_feedback(user_input: str, last_action: Optional[str]) -> bool:
    """判断用户消息是否是对上一轮生成内容的修改反馈
    
    场景举例：
    - 上一轮生成了大纲，用户说"需要六个章节" → True
    - 上一轮生成了文档，用户说"第三部分太短了" → True
    - 独立的新请求"帮我写工作计划" → False
    """
    if last_action not in ("outline_generated", "document_generated"):
        return False
    
    text = user_input.strip()
    
    # 明确的修改指令
    modify_keywords = [
        "修改", "改成", "改为", "换成", "调整", "更改",
        "增加", "添加", "加上", "补充", "加入",
        "删除", "去掉", "移除", "删掉", "不要", "不需要",
        "太长", "太短", "太多", "太少", "简短", "详细",
        "重新", "再写", "重写",
        "章节", "部分", "段落", "标题", "内容",
    ]
    if any(kw in text for kw in modify_keywords):
        return True
    
    # 数量/结构调整（如"要六个章节"、"分五部分"、"三个要点"）
    if re.search(r'[要需分改][一二三四五六七八九十\d]+[个章节部分段条点项]', text):
        return True
    
    # 短消息（<30字）且不含明确的新任务关键词 → 大概率是反馈
    new_task_keywords = ["帮我写", "写一份", "生成", "起草", "查询", "搜索", "检索", "是否符合", "能否"]
    if len(text) < 30 and not any(kw in text for kw in new_task_keywords):
        return True
    
    return False


def classify_intent_by_keywords(user_input: str, conversation_history: Optional[List[Dict]] = None) -> Dict:
    """基于关键词的意图识别（增强版，支持上下文感知）"""
    text = user_input

    # === 优先级 0：上下文感知 — 检测是否为修改反馈 ===
    last_action = _detect_last_action(conversation_history)
    if _is_modification_feedback(text, last_action):
        logger.info(f"[Intent] 检测到修改反馈（上一轮: {last_action}）: '{text[:50]}'")
        return {"intent": "modify_feedback", "confidence": 0.9, "keywords": [], "last_action": last_action}

    # === 优先级从高到低 ===

    # 1. 文档生成（最明确的意图）
    template_keywords = ["写一份", "生成", "起草", "拟一份", "帮我写", "撰写", "草拟",
                         "模板", "工作计划", "活动方案", "策划", "总结", "报告", "述职", "纪要"]
    if any(kw in text for kw in template_keywords):
        return {"intent": "template_generate", "confidence": 0.85, "keywords": []}

    # 2. 合规判断
    compliance_keywords = ["能否", "是否满足", "是否符合", "合规", "能不能", "可以吗",
                           "符不符合", "够不够", "满不满足", "条件", "转正"]
    if any(kw in text for kw in compliance_keywords):
        return {"intent": "compliance_check", "confidence": 0.85, "keywords": []}

    # 3. 导出
    export_keywords = ["导出", "下载", "生成excel", "生成word", "导出pdf", "导出excel"]
    if any(kw in text.lower() for kw in export_keywords):
        return {"intent": "export_file", "confidence": 0.85, "keywords": []}

    # 4. 文件对比
    diff_keywords = ["对比", "差异", "不同", "区别", "变更", "比较"]
    if any(kw in text for kw in diff_keywords):
        return {"intent": "file_diff", "confidence": 0.85, "keywords": []}

    # 5. 政策咨询（扩大覆盖范围，避免政策问题被误判为通用对话）
    policy_keywords = [
        "政策", "规定", "标准", "流程", "党费", "党章", "细则", "条例",
        "制度", "规章", "怎么办", "程序", "办法", "通知", "文件",
        # 常见党务/行政关键词
        "入党", "转正", "党员", "党支部", "党组织", "发展对象", "积极分子",
        "三会一课", "主题党日", "组织生活", "民主评议", "党纪", "处分",
        # 行政办公关键词
        "公务", "接待", "差旅", "报销", "会议费", "培训费", "出差",
        "编制", "考核", "述职", "任免", "回避", "交流", "轮岗",
        # 法规文件关键词
        "GB", "国标", "要求", "依据", "哪些", "如何", "什么条件",
        "是否可以", "允许", "禁止", "不得", "应当", "必须",
    ]
    if any(kw in text for kw in policy_keywords):
        return {"intent": "policy_qa", "confidence": 0.8, "keywords": []}

    # 6. 兜底 — 通用对话（低置信度，让 LLM 二次判断）
    return {"intent": "general_chat", "confidence": 0.4, "keywords": []}


async def classify_intent(user_input: str, conversation_history: Optional[List[Dict]] = None) -> Dict:
    """识别用户意图（上下文感知 > 关键词 > LLM）"""
    # 先用关键词+上下文做快速判断（关键词已内置上下文感知逻辑）
    kw_result = classify_intent_by_keywords(user_input, conversation_history)
    # 如果关键词阶段已高置信度命中（含修改反馈），直接返回
    if kw_result["confidence"] >= 0.85:
        return kw_result

    # 低置信度时尝试 LLM
    try:
        messages = [
            {"role": "system", "content": "你是一个精确的意图分类助手，只输出JSON。"},
            {"role": "user", "content": INTENT_PROMPT.format(user_input=user_input)},
        ]
        result = await llm_service.chat_json(messages, temperature=0.1)

        if "error" in result:
            logger.warning(f"LLM意图识别失败，使用关键词结果")
            return kw_result

        intent = result.get("intent", "general_chat")
        confidence = result.get("confidence", 0.5)

        if intent not in VALID_INTENTS:
            intent = "general_chat"

        logger.info(f"意图识别(LLM): '{user_input[:50]}...' -> {intent} (confidence={confidence})")
        return {"intent": intent, "confidence": confidence, "keywords": result.get("keywords", [])}
    except Exception as e:
        logger.warning(f"LLM意图识别异常，使用关键词结果: {e}")
        return kw_result


async def classify_intent_stream(user_input: str, conversation_history: Optional[List[Dict]] = None):
    """流式意图识别 — thinking 实时推送，content（JSON）收集后解析

    Yields:
        {"type": "thinking", "text": "..."} — 思考过程（实时推送）
        {"type": "result", "data": {...}}   — 最终意图识别结果（最后一个）
    """
    import json as _json

    kw_result = classify_intent_by_keywords(user_input, conversation_history)
    if kw_result["confidence"] >= 0.85:
        # 关键词高置信度命中，无需 LLM
        yield {"type": "result", "data": kw_result}
        return

    # 低置信度 → 用流式 LLM 识别（thinking 实时推送）
    try:
        messages = [
            {"role": "system", "content": "你是一个精确的意图分类助手，只输出JSON。"},
            {"role": "user", "content": INTENT_PROMPT.format(user_input=user_input)},
        ]
        content_buf = ""
        async for piece in llm_service.chat_stream_with_thinking(messages):
            if piece["type"] == "thinking":
                yield {"type": "thinking", "text": piece["text"]}
            else:
                content_buf += piece["text"]

        # 解析 JSON
        try:
            # 清理可能的 markdown 包装
            clean = content_buf.strip()
            if clean.startswith("```"):
                clean = re.sub(r'^```\w*\n?', '', clean)
                clean = re.sub(r'\n?```$', '', clean)
            result = _json.loads(clean)
        except _json.JSONDecodeError:
            logger.warning(f"流式意图识别JSON解析失败: {content_buf[:200]}")
            yield {"type": "result", "data": kw_result}
            return

        intent = result.get("intent", "general_chat")
        confidence = result.get("confidence", 0.5)
        if intent not in VALID_INTENTS:
            intent = "general_chat"

        logger.info(f"意图识别(LLM-stream): '{user_input[:50]}...' -> {intent} (confidence={confidence})")
        yield {"type": "result", "data": {"intent": intent, "confidence": confidence, "keywords": result.get("keywords", [])}}
    except Exception as e:
        logger.warning(f"流式意图识别异常: {e}")
        yield {"type": "result", "data": kw_result}


# ========== 参数提取 ==========

def extract_params(intent: str, user_input: str) -> dict:
    """根据意图从用户输入中提取工具参数（规则优先，不依赖 LLM）"""
    extractors = {
        "policy_qa":         _extract_policy_params,
        "compliance_check":  _extract_compliance_params,
        "template_generate": _extract_template_params,
        "file_diff":         _extract_diff_params,
        "export_file":       _extract_export_params,
    }
    extractor = extractors.get(intent)
    if extractor:
        return extractor(user_input)
    return {}


def _extract_policy_params(text: str) -> dict:
    """提取政策查询参数"""
    return {"query": text}


def _extract_compliance_params(text: str) -> dict:
    """提取合规判断参数"""
    # 合规判断比较复杂，需要 person_info 和 requirement
    # 尝试从文本中拆分人员信息和判断事项
    person_info = ""
    requirement = text

    # 尝试提取姓名作为 person_info 的一部分
    m = re.search(r'([\u4e00-\u9fa5]{2,4})(?:能否|是否|可以|能不能|符不符合)', text)
    if m:
        person_info = m.group(1)
        requirement = text

    return {"person_info": person_info, "requirement": requirement}


def _extract_template_params(text: str) -> dict:
    """提取文档生成参数"""
    fields = {}
    # 提取年度
    year_match = re.search(r'(20\d{2})\s*年', text)
    if year_match:
        fields["年度"] = year_match.group(1)
    # 提取部门
    dept_patterns = ["机关党委", "第一党支部", "第二党支部", "第三党支部",
                     "第四党支部", "第五党支部", "办公室", "组织部"]
    for dept in dept_patterns:
        if dept in text:
            fields["部门名称"] = dept
            break
    return {"fields": fields, "user_input": text}


def _extract_diff_params(text: str) -> dict:
    """提取文本对比参数 — 从用户消息中拆分文本1和文本2"""
    text1 = ""
    text2 = ""

    # 尝试多种分隔模式
    # 模式1: "文本1：xxx 文本2：xxx" 或 "文本1（xxx）：\nxxx 文本2（xxx）：\nxxx"
    patterns = [
        r'文本[1１一](?:[（\(][^）\)]*[）\)])?[：:]\s*\n?(.*?)(?:\n\s*文本[2２二](?:[（\(][^）\)]*[）\)])?[：:]\s*\n?)(.*)',
        r'第一段[：:]\s*\n?(.*?)(?:\n\s*第二段[：:]\s*\n?)(.*)',
        r'旧版[：:]\s*\n?(.*?)(?:\n\s*新版[：:]\s*\n?)(.*)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            text1 = m.group(1).strip()
            text2 = m.group(2).strip()
            break

    return {"text1": text1, "text2": text2, "user_input": text}


def _extract_export_params(text: str) -> dict:
    """提取导出参数"""
    text_lower = text.lower()
    fmt = "word"
    if any(kw in text_lower for kw in ["excel", "表格", "xlsx"]):
        fmt = "excel"
    elif any(kw in text_lower for kw in ["pdf"]):
        fmt = "pdf"
    return {"format": fmt, "user_input": text}
