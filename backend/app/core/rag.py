"""RAG检索模块 - 政策知识库检索与合规判断"""
import json
from typing import Dict, Any, List, Optional

from loguru import logger

from app.core.llm import llm_service


POLICY_QA_PROMPT = """你是一个党务政策咨询助手。请根据以下检索到的政策条款，回答用户的问题。

检索到的相关政策条款：
{retrieved_clauses}

要求：
1. 只根据提供的条款内容回答，不要编造不存在的内容
2. 回答要准确、条理清晰
3. 必须在回答末尾标注引用来源（文件名 + 具体条款编号）
4. 如果提供的条款不足以完整回答问题，请明确说明哪些方面无法确定

用户问题：{question}"""


COMPLIANCE_CHECK_PROMPT = """你是一个党务政策合规判断助手。请根据以下政策条款，判断是否满足条件。

检索到的相关政策条款：
{retrieved_clauses}

判断对象信息：
{person_info}

判断事项：{requirement}

请严格按以下JSON格式输出判断结果：
{{
  "person_name": "判断对象姓名",
  "requirement": "判断事项",
  "overall_result": "符合/不符合/部分符合",
  "confidence": 0.85,
  "checks": [
    {{
      "condition": "条件描述",
      "result": "PASS/FAIL/UNKNOWN",
      "explanation": "说明"
    }}
  ],
  "missing_info": ["缺失的信息"],
  "suggestions": ["建议"],
  "references": [
    {{
      "source": "文件名",
      "clause": "条款编号",
      "content": "条款原文摘要"
    }}
  ]
}}"""


CLAUSE_PREVIEW_PROMPT = """你是一个政策条款检索助手。以下是检索到的相关条款，请从中筛选出与用户问题最相关的3-5条，并简要说明关联性。

检索到的条款：
{retrieved_clauses}

用户问题：{question}

请输出JSON格式：
{{
  "relevant_clauses": [
    {{
      "clause_id": "条款编号",
      "source": "文件名",
      "summary": "条款概要（一句话）",
      "relevance": "关联性说明"
    }}
  ]
}}"""


async def answer_policy_question(question: str, retrieved_clauses: List[Dict]) -> str:
    """回答政策咨询问题"""
    clauses_text = format_clauses(retrieved_clauses)

    messages = [
        {"role": "system", "content": "你是一个专业的党务政策咨询助手，回答要准确、有据可查。"},
        {"role": "user", "content": POLICY_QA_PROMPT.format(
            retrieved_clauses=clauses_text,
            question=question,
        )},
    ]
    return await llm_service.chat(messages)


async def check_compliance(
    person_info: str,
    requirement: str,
    retrieved_clauses: List[Dict],
) -> Dict:
    """合规判断"""
    clauses_text = format_clauses(retrieved_clauses)

    messages = [
        {"role": "system", "content": "你是一个严谨的党务政策合规判断助手，只输出JSON。"},
        {"role": "user", "content": COMPLIANCE_CHECK_PROMPT.format(
            retrieved_clauses=clauses_text,
            person_info=person_info,
            requirement=requirement,
        )},
    ]
    return await llm_service.chat_json(messages)


async def preview_clauses(question: str, retrieved_clauses: List[Dict]) -> Dict:
    """条款预览 - 在给出判断前先展示相关条款"""
    clauses_text = format_clauses(retrieved_clauses)

    messages = [
        {"role": "system", "content": "你是一个政策条款筛选助手，只输出JSON。"},
        {"role": "user", "content": CLAUSE_PREVIEW_PROMPT.format(
            retrieved_clauses=clauses_text,
            question=question,
        )},
    ]
    return await llm_service.chat_json(messages)


def format_clauses(clauses: List[Dict]) -> str:
    """格式化检索到的条款"""
    if not clauses:
        return "（未检索到相关条款）"

    texts = []
    for i, clause in enumerate(clauses, 1):
        source = clause.get("source", "未知来源")
        title = clause.get("title", "")
        content = clause.get("content", "")
        hierarchy = clause.get("hierarchy", "")

        text = f"[条款{i}] 来源：{source}"
        if hierarchy:
            text += f" > {hierarchy}"
        if title:
            text += f"\n标题：{title}"
        text += f"\n内容：{content}\n"
        texts.append(text)

    return "\n".join(texts)
