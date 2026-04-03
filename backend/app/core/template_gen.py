"""模板生成模块 - 辅助生成文档"""
import json
from typing import Dict, Any, List, Optional

from loguru import logger

from app.core.llm import llm_service


TEMPLATE_MATCH_PROMPT = """你是一个模板匹配助手。根据用户的请求，判断应该使用哪个模板。

可用模板列表：
{templates_info}

请根据用户输入，选择最匹配的模板，并提取用户已经提供的信息。

输出JSON格式：
{{
  "template_id": 模板ID（整数，如果没有匹配的模板则为null）,
  "template_name": "模板名称",
  "provided_fields": {{"字段名": "用户提供的值"}},
  "missing_required_fields": ["缺失的必填字段名"],
  "missing_optional_fields": ["缺失的选填字段名"]
}}

用户输入：{user_input}"""


GENERATE_OUTLINE_PROMPT = """你是一个专业的公文写作助手。请根据以下模板和用户提供的信息，生成文档大纲。

模板名称：{template_name}
模板骨架：
{body_skeleton}

用户提供的信息：
{user_fields}
{reference_section}
请生成一份结构清晰的大纲（只需要标题和要点，不要展开写正文内容），方便用户确认结构后再生成完整文档。"""


GENERATE_FULL_PROMPT = """你是一个专业的公文写作助手。请根据以下模板和用户提供的信息，生成完整的文档内容。

模板名称：{template_name}
模板骨架：
{body_skeleton}

用户提供的信息：
{user_fields}
{reference_section}
要求：
1. 严格按照模板骨架的结构来写
2. 内容要专业、规范，符合党政公文写作风格
3. 所有用户提供的信息必须准确嵌入
4. 数据和金额要前后一致
5. 生成完整、可直接使用的文档，不要留空或用省略号
6. 参考范本的格式、用语风格和内容深度

{extra_instructions}"""


MODIFY_PROMPT = """你是一个专业的公文写作助手。以下是之前生成的文档内容，用户要求进行修改。

原文档：
{original_content}

用户修改要求：{modification_request}

请根据修改要求，输出修改后的完整文档（不是只输出修改部分，而是输出完整的修改后文档）。"""


async def match_template(user_input: str, templates: List[Dict]) -> Dict:
    """匹配最佳模板并提取已有信息"""
    templates_info = "\n".join([
        f"- ID:{t['id']}, 名称:{t['name']}, 类型:{t['category']}, "
        f"必填字段:{t.get('required_fields', '[]')}, "
        f"选填字段:{t.get('optional_fields', '[]')}"
        for t in templates
    ])

    messages = [
        {"role": "system", "content": "你是一个精确的模板匹配助手，只输出JSON。"},
        {"role": "user", "content": TEMPLATE_MATCH_PROMPT.format(
            templates_info=templates_info, user_input=user_input
        )},
    ]
    return await llm_service.chat_json(messages)


async def generate_outline(template_name: str, body_skeleton: str, user_fields: Dict, reference_docs: str = "") -> str:
    """生成文档大纲（第一阶段）"""
    ref_section = ""
    if reference_docs:
        ref_section = f"\n以下是同类文档的参考范本（请参考其格式和内容风格）：\n{reference_docs}\n"
    messages = [
        {"role": "system", "content": "你是一个专业的公文写作助手。"},
        {"role": "user", "content": GENERATE_OUTLINE_PROMPT.format(
            template_name=template_name,
            body_skeleton=body_skeleton,
            user_fields=json.dumps(user_fields, ensure_ascii=False, indent=2),
            reference_section=ref_section,
        )},
    ]
    return await llm_service.chat(messages)


async def generate_full_document(
    template_name: str,
    body_skeleton: str,
    user_fields: Dict,
    extra_instructions: str = "",
    reference_docs: str = "",
) -> str:
    """生成完整文档（第二阶段）"""
    ref_section = ""
    if reference_docs:
        ref_section = f"\n以下是同类文档的参考范本（请参考其格式和内容风格）：\n{reference_docs}\n"
    messages = [
        {"role": "system", "content": "你是一个专业的公文写作助手，生成的文档要完整、规范。"},
        {"role": "user", "content": GENERATE_FULL_PROMPT.format(
            template_name=template_name,
            body_skeleton=body_skeleton,
            user_fields=json.dumps(user_fields, ensure_ascii=False, indent=2),
            extra_instructions=extra_instructions,
            reference_section=ref_section,
        )},
    ]
    return await llm_service.chat(messages, max_tokens=8192)


async def modify_document(original_content: str, modification_request: str) -> str:
    """修改已生成的文档"""
    messages = [
        {"role": "system", "content": "你是一个专业的公文写作助手。"},
        {"role": "user", "content": MODIFY_PROMPT.format(
            original_content=original_content,
            modification_request=modification_request,
        )},
    ]
    return await llm_service.chat(messages, max_tokens=8192)
