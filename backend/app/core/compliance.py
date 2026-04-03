"""合规判断模块 - 封装完整的合规判断流程"""
from typing import Dict, Any, List

from loguru import logger

from app.core.rag import answer_policy_question, check_compliance, preview_clauses


async def run_compliance_check(
    question: str,
    retrieved_clauses: List[Dict],
) -> Dict[str, Any]:
    """
    完整的合规判断流程：
    1. 条款预览（展示检索到的相关条款）
    2. 逐条对照判断
    3. 置信度评估
    4. 引用溯源
    """
    # Step 1: 条款预览
    clause_preview = await preview_clauses(question, retrieved_clauses)

    # Step 2: 从问题中提取判断对象和事项
    person_info, requirement = extract_check_params(question)

    # Step 3: 执行合规判断
    check_result = await check_compliance(
        person_info=person_info,
        requirement=requirement,
        retrieved_clauses=retrieved_clauses,
    )

    # Step 4: 置信度评估
    confidence = check_result.get("confidence", 0.5)
    needs_human_review = confidence < 0.8

    return {
        "clause_preview": clause_preview,
        "check_result": check_result,
        "confidence": confidence,
        "needs_human_review": needs_human_review,
        "review_message": "置信度低于80%，建议人工复核" if needs_human_review else None,
    }


def extract_check_params(question: str) -> tuple:
    """从问题中提取判断对象信息和判断事项（简单提取，复杂场景由LLM处理）"""
    # 这里使用简单的启发式提取，实际可以用LLM来提取
    person_info = question  # 暂时将整个问题作为人员信息
    requirement = question  # 暂时将整个问题作为判断事项
    return person_info, requirement
