# -*- coding: utf-8 -*-
"""Agent核心循环引擎 — Tool-Use Agent架构（支持Prompt模拟和原生Function Calling双模式）"""
import json
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field

from loguru import logger

from app.config import settings


# ========== 数据类 ==========

@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Agent最终返回结果"""
    reply: str
    tool_calls: List[Dict] = field(default_factory=list)
    structured_data: List[Dict] = field(default_factory=list)


@dataclass
class AgentStreamEvent:
    """Agent流式事件"""
    type: str  # "thinking" | "tool_calling" | "tool_result" | "content" | "done"
    data: Dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        return json.dumps({"type": self.type, **self.data}, ensure_ascii=False)


# ========== System Prompt ==========

AGENT_SYSTEM_PROMPT = """你是「智慧党建助手」，一个智能AI助手，专注于党务工作辅助。
你的主要职能包括：生成公文文档、检索政策法规、合规条件判断、文件差异对比，同时也可以回答用户的通识问题（如常识、生活、科技等）。

## 你的能力（通过工具调用实现）
1. **search_policy** — 检索政策知识库（查找政策条款、法规内容）
2. **check_compliance** — 合规条件判断（逐条对照，附带置信度和引用）
3. **list_templates** — 查看可用文档模板
4. **generate_document** — 生成公文（工作计划、活动方案、纪要、报告等）
5. **export_file** — 导出Word/Excel
6. **compare_texts** — 对比两段文本差异

## 工作原则
1. **先思考再行动**：分析用户请求需要哪些步骤，再依次调用工具
2. **自动串联多步任务**：
   - "写一份工作计划" → list_templates获取模板信息 → 直接调用generate_document(outline)
   - "判断某人能否转正" → check_compliance进行合规判断
3. **尽量少追问，能提取就提取**：从用户输入中尽可能提取字段信息，只有**真正缺失的关键必填字段**才追问。选填字段不需要追问，直接留空让AI自动补充即可。
4. **政策回答必须有据**：调用search_policy获取条款后，基于条款原文回答并标注来源
5. **合规判断要严谨**：调用check_compliance，基于返回结果如实呈现，不确定的标"建议人工复核"
6. **通识问题直接回答**：对于非党务的通识问题（如常识、科技、生活等），直接基于你的知识回答，无需调用工具

## 工具选择指南
| 用户意图 | 应调用的工具 |
|---------|------------|
| 写/生成/起草文档 | list_templates → generate_document |
| 政策/规定/标准/流程 | search_policy |
| 能否/是否符合/合规 | check_compliance |
| 对比/差异/不同 | compare_texts |
| 导出/下载 | export_file |
| 闲聊/通识问题/帮助 | 不调用工具，直接回复 |

## 输出格式
- 工具返回结构化数据（表格/图表/卡片）后，你只需用**简洁的文字总结**关键信息，不要重复列表数据
- 生成文档时，先用stage=outline生成大纲，告知用户"请确认大纲后生成全文"
- 合规判断结果由工具结构化返回，你总结结论和注意事项即可

## 安全约束
- 绝不执行数据修改操作
- 不编造不存在的数据，工具返回空则如实告知
- 严谨对待政治话题
- 每次请求最多调用10次工具"""


# ========== Tools Schema ==========

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "检索政策知识库，查找与问题相关的政策条款和法规内容。返回最相关的条款原文及来源。用于回答政策咨询问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "政策相关的问题或关键词，如'党费缴纳标准'、'发展党员流程'、'入党积极分子条件'"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回最相关的条款数量，默认5"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_compliance",
            "description": "合规条件判断。根据提供的人员信息和判断事项，自动检索相关政策条款，逐条对照判断是否符合条件。返回逐项核查结果、置信度和引用依据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "person_info": {
                        "type": "string",
                        "description": "被判断人的相关信息，如'李四，22岁，递交入党申请书满1年，党课已结业'"
                    },
                    "requirement": {
                        "type": "string",
                        "description": "需要判断的事项，如'能否确定为入党积极分子'、'是否符合预备党员转正条件'"
                    }
                },
                "required": ["person_info", "requirement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_templates",
            "description": "查看当前可用的文档模板列表。在生成文档前应先调用此工具了解有哪些模板可用及其必填字段。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_document",
            "description": "根据模板和用户提供的字段信息生成公文文档。需要指定模板ID和各字段值。stage=outline先生成大纲，stage=full生成完整文档，stage=modify修改已有文档。",
            "parameters": {
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "integer",
                        "description": "模板ID（从list_templates获取）"
                    },
                    "fields": {
                        "type": "object",
                        "description": "用户提供的字段值，如{\"活动主题\": \"七一建党节\", \"活动时间\": \"2026年7月1日\"}"
                    },
                    "stage": {
                        "type": "string",
                        "enum": ["outline", "full", "modify"],
                        "description": "生成阶段：outline=生成大纲, full=生成全文, modify=修改已有文档"
                    },
                    "modification_request": {
                        "type": "string",
                        "description": "修改要求（仅stage=modify时需要）"
                    },
                    "original_content": {
                        "type": "string",
                        "description": "原始文档内容（仅stage=modify时需要）"
                    }
                },
                "required": ["template_id", "fields"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_file",
            "description": "将内容导出为文件并返回下载标记。支持Word、Excel格式。调用后前端会自动触发下载。",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["word", "excel"],
                        "description": "导出格式"
                    },
                    "title": {
                        "type": "string",
                        "description": "文件标题"
                    },
                    "content": {
                        "type": "string",
                        "description": "文档内容（word时使用）"
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "表格列名（excel时使用）"
                    },
                    "rows": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "表格行数据（excel时使用）"
                    }
                },
                "required": ["format", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_texts",
            "description": "对比两段文本的差异，生成差异报告。适用于对比两个版本的政策文件、规章制度等文本内容。标注修改/新增/删除项，计算相似度，并进行语义分析。如需对比文件，用户应先通过管理后台上传文件，此工具用于对话中直接粘贴的文本对比。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text1": {
                        "type": "string",
                        "description": "第一段文本（旧版/原文）"
                    },
                    "text2": {
                        "type": "string",
                        "description": "第二段文本（新版/修改后）"
                    },
                    "name1": {
                        "type": "string",
                        "description": "第一段文本的标识名称，如'2024版'",
                        "default": "文本1"
                    },
                    "name2": {
                        "type": "string",
                        "description": "第二段文本的标识名称，如'2026版'",
                        "default": "文本2"
                    }
                },
                "required": ["text1", "text2"]
            }
        }
    },
]


# ========== Tool Registry ==========

class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, Any] = {}

    def register(self, name: str, handler):
        self._tools[name] = handler

    async def execute(self, name: str, args: dict, **kwargs) -> ToolResult:
        handler = self._tools.get(name)
        if not handler:
            return ToolResult(success=False, summary=f"未知工具: {name}", data={"error": f"Tool '{name}' not found"})
        try:
            result = await handler(**args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"工具 {name} 执行失败: {e}")
            return ToolResult(success=False, summary=f"工具执行失败: {str(e)}", data={"error": str(e)})

    @property
    def tool_names(self) -> list:
        return list(self._tools.keys())


# ========== Agent Engine ==========

class AgentEngine:
    """Agent核心循环引擎（支持 native / prompt 双模式）"""

    MAX_ITERATIONS = 10

    def __init__(self, llm_service, tool_registry: ToolRegistry):
        self.llm = llm_service
        self.tools = tool_registry
        self.mode = getattr(settings, "TOOL_CALL_MODE", "prompt")
        logger.info(f"AgentEngine 工具调用模式: {self.mode}")

    async def _call_llm(self, messages, tools):
        """根据 TOOL_CALL_MODE 选择调用方式"""
        if self.mode == "native":
            return await self.llm.chat_with_tools(messages=messages, tools=tools)
        else:
            return await self.llm.chat_with_tools_prompt(messages=messages, tools=tools)

    def _append_tool_call_messages(self, messages, response, tool_name, tool_args, result):
        """根据模式将工具调用和结果追加到消息列表"""
        tool_result_content = json.dumps(result.data, ensure_ascii=False, default=str) if result.data else result.summary

        if self.mode == "native":
            # 原生 Function Calling 协议
            tc = response["tool_calls"][0]
            messages.append({
                "role": "assistant",
                "content": response.get("content") or None,
                "tool_calls": response["tool_calls"],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result_content,
            })
        else:
            # Prompt 模拟模式
            assistant_content = response.get("content") or ""
            tool_call_text = f'<tool_call>\n{{"name": "{tool_name}", "arguments": {json.dumps(tool_args, ensure_ascii=False)}}}\n</tool_call>'
            messages.append({
                "role": "assistant",
                "content": (assistant_content + "\n" + tool_call_text).strip(),
            })
            messages.append({
                "role": "user",
                "content": f"[工具 {tool_name} 执行结果]\n{tool_result_content}",
            })

    async def run(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        db=None,
    ) -> AgentResult:
        """
        非流式Agent循环：
        1. 发送消息给LLM（根据配置选择native/prompt模式）
        2. LLM要求调用工具 → 执行 → 结果加入消息 → 继续
        3. LLM直接回复文本 → 结束
        """
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        ]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        tool_call_log = []
        structured_data_list = []
        iteration = 0

        while iteration < self.MAX_ITERATIONS:
            iteration += 1

            response = await self._call_llm(messages, AGENT_TOOLS)

            # 情况A：LLM要调用工具
            if response.get("tool_calls"):
                tc = response["tool_calls"][0]
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}

                logger.info(f"Agent调用工具: {tool_name}({tool_args})")

                result = await self.tools.execute(tool_name, tool_args, db=db)

                tool_call_log.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "success": result.success,
                    "summary": result.summary,
                })

                if result.data:
                    structured_data_list.append(result.data)

                self._append_tool_call_messages(messages, response, tool_name, tool_args, result)
                continue

            # 情况B：LLM直接回复
            reply = response.get("content", "")
            return AgentResult(
                reply=reply,
                tool_calls=tool_call_log,
                structured_data=structured_data_list,
            )

        return AgentResult(
            reply="抱歉，这个问题比较复杂，处理了多个步骤仍未完成。请尝试简化您的问题。",
            tool_calls=tool_call_log,
            structured_data=structured_data_list,
        )

    async def run_stream(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        db=None,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """
        流式Agent循环 — 思考和工具调用过程实时推送给前端
        """
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        ]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        iteration = 0

        while iteration < self.MAX_ITERATIONS:
            iteration += 1

            # 通知前端：Agent正在思考
            yield AgentStreamEvent(
                type="thinking",
                data={"message": "正在思考..." if iteration == 1 else "继续分析中..."}
            )

            # 非流式调用LLM以获取完整的tool_calls
            response = await self._call_llm(messages, AGENT_TOOLS)

            # 情况A：LLM要调用工具
            if response.get("tool_calls"):
                tc = response["tool_calls"][0]
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}

                # 通知前端：正在调用工具
                yield AgentStreamEvent(
                    type="tool_calling",
                    data={"tool": tool_name, "args": tool_args}
                )

                logger.info(f"Agent(stream)调用工具: {tool_name}({tool_args})")
                yield AgentStreamEvent(type="thinking_content", data={"text": f"正在调用工具 {tool_name}...\n"})
                result = await self.tools.execute(tool_name, tool_args, db=db)

                yield AgentStreamEvent(
                    type="tool_result",
                    data={
                        "tool": tool_name,
                        "success": result.success,
                        "summary": result.summary,
                        "structured": result.data,
                    }
                )
                yield AgentStreamEvent(type="thinking_content", data={
                    "text": f"工具 {tool_name} 执行{'成功' if result.success else '失败'}：{result.summary[:100]}\n"
                })

                self._append_tool_call_messages(messages, response, tool_name, tool_args, result)
                continue

            # 情况B：LLM不再调用工具 — 用真正的流式输出生成最终回复
            # 重新发送消息，用流式模式生成文本
            try:
                async for piece in self.llm.chat_stream_with_thinking(messages):
                    if piece["type"] == "thinking":
                        yield AgentStreamEvent(type="thinking_content", data={"text": piece["text"]})
                    else:
                        yield AgentStreamEvent(type="content", data={"text": piece["text"]})
            except Exception as e:
                # 流式失败时回退到已有的非流式响应
                content = response.get("content", "")
                if content:
                    for c in _split_to_chunks(content):
                        yield AgentStreamEvent(type="content", data={"text": c})

            yield AgentStreamEvent(type="done", data={})
            return

        # 超过最大轮次
        yield AgentStreamEvent(type="content", data={"text": "抱歉，这个问题比较复杂，已达到处理步骤上限。"})
        yield AgentStreamEvent(type="done", data={})


def _split_to_chunks(text: str, chunk_size: int = 20) -> List[str]:
    """将文本按较小的块切分，模拟流式输出效果"""
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks


# ========== Workflow 模式 ==========

WORKFLOW_SYSTEM_PROMPT = """你是「智慧党建助手」，一个智能AI助手，专注于党务工作辅助。
你的主要职能包括：生成公文文档（工作计划、活动方案、会议纪要等）、检索政策法规并解答咨询、合规条件判断、文件差异对比，同时也可以回答用户的通识问题（如常识、生活、科技、历史等各类知识问题）。
回答问题时要准确、简洁、专业。
绝对禁止提及任何工具名称、函数名称、调用过程、API接口等技术细节。你的回复应该像一个专业的工作人员直接回答问题。"""

WORKFLOW_SUMMARY_PROMPT = """你是一位专业的党务工作人员，负责根据系统提供的资料回答用户问题。

核心规则：
1. 优先使用【系统资料】中的内容来回答，这些资料来自真实的政策文件和数据库
2. 对资料中的原文内容进行整理和归纳，用通顺的语言呈现给用户
3. 如果资料中包含具体条款，请引用原文或准确概括，并标注来源文件名
4. 如果系统资料为空或未检索到相关内容，你可以基于通用党务知识回答，但必须在回答开头注明：「⚠️ 以下内容来自AI通用知识，未从本单位知识库中检索到相关文件，仅供参考，请以实际政策文件为准。」
5. 绝不编造具体的文件名、文号或条款编号
6. 直接回答问题，不描述查询过程"""


@dataclass
class WorkflowStepResult:
    """单个 Workflow 步骤的执行结果"""
    tool_calls: List[Dict] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    needs_user_input: str = ""  # 非空时表示需要用户补充信息


# ========== Workflow 函数 ==========

async def _wf_search_policy(params: dict, db=None) -> WorkflowStepResult:
    """政策检索工作流"""
    from app.core.tools import handle_search_policy
    query = params.get("query", "")
    result = await handle_search_policy(query=query)
    return WorkflowStepResult(
        tool_calls=[{"tool": "search_policy", "args": {"query": query}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def _wf_check_compliance(params: dict, db=None) -> WorkflowStepResult:
    """合规判断工作流"""
    from app.core.tools import handle_check_compliance
    person_info = params.get("person_info", "")
    requirement = params.get("requirement", "")

    # 如果 person_info 为空，用 requirement 兼任
    if not person_info:
        person_info = requirement

    result = await handle_check_compliance(person_info=person_info, requirement=requirement)
    return WorkflowStepResult(
        tool_calls=[{"tool": "check_compliance", "args": {"person_info": person_info[:100], "requirement": requirement[:100]}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


def _match_template(user_input: str, templates: list) -> Optional[int]:
    """根据用户输入关键词匹配最合适的模板"""
    keyword_map = {
        "工作计划": ["工作计划", "年度计划", "计划"],
        "活动方案": ["活动方案", "策划", "活动"],
        "工作总结": ["总结", "年度总结", "工作总结"],
        "述职报告": ["述职", "述职报告"],
        "会议纪要": ["纪要", "会议纪要", "会议记录"],
        "调研报告": ["调研", "调研报告"],
    }
    best_match = None
    best_score = 0
    for template in templates:
        tname = template["name"]
        score = 0
        if tname in user_input:
            score = 10
        else:
            for key, keywords in keyword_map.items():
                if key in tname:
                    for kw in keywords:
                        if kw in user_input:
                            score = max(score, 5)
        if score > best_score:
            best_score = score
            best_match = template["id"]
    return best_match if best_score > 0 else (templates[0]["id"] if len(templates) == 1 else None)


async def _wf_generate_document(params: dict, db=None) -> WorkflowStepResult:
    """文档生成工作流（多步：list_templates → 匹配模板 → generate_document）"""
    from app.core.tools import handle_list_templates, handle_generate_document
    fields = params.get("fields", {})
    user_input = params.get("user_input", "")
    all_calls = []
    all_results = []

    # Step 1: 获取模板列表
    list_result = await handle_list_templates()
    all_calls.append({"tool": "list_templates", "args": {}, "success": list_result.success, "summary": list_result.summary})
    all_results.append(list_result)

    if not list_result.success or not list_result.data.get("templates"):
        return WorkflowStepResult(tool_calls=all_calls, tool_results=all_results)

    # Step 2: 匹配模板（代码匹配，不依赖 LLM）
    templates = list_result.data["templates"]
    template_id = _match_template(user_input, templates)

    if template_id is None:
        return WorkflowStepResult(
            tool_calls=all_calls,
            tool_results=all_results,
            needs_user_input=f"当前有以下模板可用，请告诉我您需要哪一个：\n" +
                             "\n".join(f"  {t['id']}. {t['name']}（{t.get('description', '')}）" for t in templates),
        )

    # Step 3: 检索知识库中的同类文档作为参考范本
    matched_tpl = next((t for t in templates if t["id"] == template_id), {})
    tpl_name = matched_tpl.get("name", "")
    # 用模板名称+用户输入构建查询，确保活动方案类文档能命中知识库中的具体方案
    search_query = tpl_name + " " + user_input
    reference_docs, ref_sources = await _search_reference_docs(search_query)

    # Step 4: 生成大纲（传入参考范本）
    gen_args = {"template_id": template_id, "fields": fields, "stage": "outline", "reference_docs": reference_docs, "reference_sources": ref_sources}
    gen_result = await handle_generate_document(**gen_args)
    all_calls.append({"tool": "generate_document", "args": {"template_id": template_id, "stage": "outline"}, "success": gen_result.success, "summary": gen_result.summary})
    all_results.append(gen_result)

    return WorkflowStepResult(tool_calls=all_calls, tool_results=all_results)


async def _wf_compare_texts(params: dict, db=None) -> WorkflowStepResult:
    """文本对比工作流"""
    from app.core.tools import handle_compare_texts
    text1 = params.get("text1", "")
    text2 = params.get("text2", "")

    if not text1 or not text2:
        return WorkflowStepResult(
            tool_calls=[],
            tool_results=[],
            needs_user_input="请提供需要对比的两段文本。您可以直接粘贴到对话中，格式如：\n\n文本1：\n（粘贴第一段文本）\n\n文本2：\n（粘贴第二段文本）",
        )

    result = await handle_compare_texts(text1=text1, text2=text2)
    return WorkflowStepResult(
        tool_calls=[{"tool": "compare_texts", "args": {"text1": "...", "text2": "..."}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def _wf_export(params: dict, db=None) -> WorkflowStepResult:
    """文件导出工作流"""
    from app.core.tools import handle_export_file
    fmt = params.get("format", "word")
    title = params.get("title", "")
    content = params.get("content", "")
    columns = params.get("columns")
    rows = params.get("rows")

    # 如果有完整参数，直接导出
    if content or (columns and rows):
        args = {"format": fmt, "title": title or "导出文件"}
        if content:
            args["content"] = content
        if columns:
            args["columns"] = columns
        if rows:
            args["rows"] = rows
        result = await handle_export_file(**args)
        return WorkflowStepResult(
            tool_calls=[{"tool": "export_file", "args": {"format": fmt, "title": title}, "success": result.success, "summary": result.summary}],
            tool_results=[result],
        )

    # 没有内容，提示用户
    return WorkflowStepResult(
        tool_calls=[],
        tool_results=[],
        needs_user_input=f"请先查询数据或生成文档，再进行 {fmt.upper()} 导出。您可以先告诉我需要导出什么内容。",
    )


async def _search_reference_docs(query: str, top_k: int = 5) -> tuple:
    """从知识库检索同类文档作为参考范本，返回 (text, sources_list)"""
    try:
        from app.core.search import async_search_policy_chunks
        ref_chunks = await async_search_policy_chunks(query, top_k=top_k)
        if not ref_chunks:
            return "", []
        parts = []
        sources = []
        seen = set()
        for i, chunk in enumerate(ref_chunks, 1):
            source = chunk.get("source", "")
            content = chunk.get("content", "").strip()
            title = chunk.get("title", "")
            if content:
                header = f"--- 参考范本{i}（来源：{source}" + (f" > {title}" if title else "") + " ---"
                parts.append(f"{header}\n{content[:2000]}")
            if source and source not in seen:
                seen.add(source)
                sources.append(source)
        return "\n\n".join(parts), sources
    except Exception as e:
        logger.warning(f"参考范本检索失败: {e}")
        return "", []


# ========== Context 驱动的 Workflow（前端按钮触发，参数已确定） ==========

async def _wf_confirm_outline(params: dict, db=None) -> WorkflowStepResult:
    """确认大纲 → 生成完整文档"""
    from app.core.tools import handle_generate_document
    template_id = params.get("template_id")
    fields = params.get("fields", {})

    if not template_id:
        return WorkflowStepResult(
            tool_calls=[],
            tool_results=[],
            needs_user_input="缺少模板信息，请重新选择模板生成文档。",
        )

    # 检索参考范本
    reference_docs, ref_sources = await _search_reference_docs(str(template_id) + " " + " ".join(str(v) for v in fields.values() if v))

    gen_args = {"template_id": template_id, "fields": fields, "stage": "full", "reference_docs": reference_docs, "reference_sources": ref_sources}
    result = await handle_generate_document(**gen_args)
    return WorkflowStepResult(
        tool_calls=[{"tool": "generate_document", "args": {"template_id": template_id, "stage": "full"}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def _wf_modify_document(params: dict, db=None) -> WorkflowStepResult:
    """修改已有文档"""
    from app.core.tools import handle_generate_document
    template_id = params.get("template_id", 0)
    modification_request = params.get("modification_request", "")
    original_content = params.get("original_content", "")

    if not original_content:
        return WorkflowStepResult(
            tool_calls=[],
            tool_results=[],
            needs_user_input="缺少原始文档内容，无法执行修改。",
        )

    gen_args = {
        "template_id": template_id,
        "fields": {},
        "stage": "modify",
        "modification_request": modification_request,
        "original_content": original_content,
    }
    result = await handle_generate_document(**gen_args)
    return WorkflowStepResult(
        tool_calls=[{"tool": "generate_document", "args": {"template_id": template_id, "stage": "modify"}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def _wf_generate_with_fields(params: dict, db=None) -> WorkflowStepResult:
    """用户提供字段后生成大纲"""
    from app.core.tools import handle_generate_document
    template_id = params.get("template_id")
    fields = params.get("fields", {})

    if not template_id:
        return WorkflowStepResult(
            tool_calls=[],
            tool_results=[],
            needs_user_input="缺少模板信息，请重新选择模板。",
        )

    # 检索参考范本
    reference_docs, ref_sources = await _search_reference_docs(" ".join(str(v) for v in fields.values() if v))

    gen_args = {"template_id": template_id, "fields": fields, "stage": "outline", "reference_docs": reference_docs, "reference_sources": ref_sources}
    result = await handle_generate_document(**gen_args)
    return WorkflowStepResult(
        tool_calls=[{"tool": "generate_document", "args": {"template_id": template_id, "stage": "outline"}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def _wf_export_from_data(params: dict, db=None) -> WorkflowStepResult:
    """从已有数据导出文件（前端按钮触发，数据由 context 传入）"""
    from app.core.tools import handle_export_file
    fmt = params.get("format", "excel")
    title = params.get("title", "导出数据")
    content = params.get("content", "")
    columns = params.get("columns")
    rows = params.get("rows")

    args = {"format": fmt, "title": title}
    if content:
        args["content"] = content
    if columns:
        args["columns"] = columns
    if rows:
        args["rows"] = rows

    result = await handle_export_file(**args)
    return WorkflowStepResult(
        tool_calls=[{"tool": "export_file", "args": {"format": fmt, "title": title}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def _wf_modify_feedback(params: dict, db=None) -> WorkflowStepResult:
    """用户对上一轮生成的大纲/文档提出修改意见 — 直接走LLM对话，不重新调工具"""
    # 这个 workflow 不调用任何工具，返回空结果
    # 让 WorkflowEngine 走 _direct_chat 路径，利用对话历史中的上下文来处理修改
    return WorkflowStepResult(
        tool_calls=[],
        tool_results=[],
        needs_user_input="",  # 空字符串表示不需要追问
    )


# Workflow 路由表（意图驱动）
WORKFLOW_REGISTRY = {
    "policy_qa":         _wf_search_policy,
    "compliance_check":  _wf_check_compliance,
    "template_generate": _wf_generate_document,
    "file_diff":         _wf_compare_texts,
    "export_file":       _wf_export,
    "modify_feedback":   _wf_modify_feedback,
}

# Context 驱动的 Workflow（前端按钮/特殊操作）
CONTEXT_WORKFLOW_REGISTRY = {
    "confirm_outline":      _wf_confirm_outline,
    "modify_document":      _wf_modify_document,
    "generate_with_fields": _wf_generate_with_fields,
    "export_from_data":     _wf_export_from_data,
}


class WorkflowEngine:
    """Workflow 驱动的 Agent 引擎（适合弱模型，代码确定性调用工具）"""

    def __init__(self, llm_service):
        self.llm = llm_service
        logger.info("WorkflowEngine 初始化完成（workflow 模式，无工具层）")

    async def run(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        db=None,
    ) -> AgentResult:
        """
        非流式 Workflow 执行：
        1. 意图识别（关键词优先）
        2. 参数提取
        3. 执行 Workflow（代码确定性调用工具）
        4. LLM 基于工具结果生成回复
        """
        from app.core.intent import classify_intent_by_keywords, classify_intent, extract_params

        # Step 1: 意图识别（传入对话历史做上下文感知）
        intent_result = classify_intent_by_keywords(user_message, conversation_history)
        if intent_result["confidence"] < 0.7:
            try:
                intent_result = await classify_intent(user_message, conversation_history)
            except Exception as e:
                logger.warning(f"LLM意图识别失败: {e}")
        intent = intent_result["intent"]
        logger.info(f"[Workflow] 意图识别: '{user_message[:50]}' -> {intent} (conf={intent_result['confidence']})")

        # Step 2: 通用对话 或 修改反馈 → 直接回复（利用对话历史上下文）
        if intent in ("general_chat", "modify_feedback"):
            return await self._direct_chat(user_message, conversation_history)

        # Step 3: 参数提取
        params = extract_params(intent, user_message)
        logger.info(f"[Workflow] 参数提取: {params}")

        # Step 4: 执行 Workflow
        workflow_fn = WORKFLOW_REGISTRY.get(intent)
        if not workflow_fn:
            logger.warning(f"[Workflow] 未找到意图 {intent} 对应的 Workflow，降级为直接对话")
            return await self._direct_chat(user_message, conversation_history)

        try:
            wf_result = await workflow_fn(params, db=db)
            logger.info(f"[Workflow] 执行完成: calls={len(wf_result.tool_calls)}, results={len(wf_result.tool_results)}, needs_input={bool(wf_result.needs_user_input)}")
            for tr in wf_result.tool_results:
                logger.info(f"[Workflow]   结果: success={tr.success}, type={tr.data.get('type','?') if tr.data else '?'}, summary={tr.summary[:80]}")
        except Exception as e:
            logger.error(f"[Workflow] 执行失败: {e}", exc_info=True)
            return AgentResult(reply=f"抱歉，处理您的请求时出现问题：{str(e)}")

        # Step 5: 需要用户补充信息
        if wf_result.needs_user_input:
            return AgentResult(
                reply=wf_result.needs_user_input,
                tool_calls=wf_result.tool_calls,
            )

        # Step 6: 基于工具结果生成回复
        structured_data = []
        tool_data_text = ""
        for tr in wf_result.tool_results:
            if tr.data:
                structured_data.append(tr.data)
            tool_data_text += f"\n[查询结果: {tr.summary}]\n数据: {json.dumps(tr.data, ensure_ascii=False, default=str)[:3000]}\n"

        # 某些类型无需 LLM 总结，直接用固定回复
        reply = self._try_fixed_reply(structured_data, wf_result)
        if not reply:
            try:
                reply = await self._generate_reply(user_message, tool_data_text, conversation_history)
            except Exception as e:
                logger.error(f"[Workflow] LLM总结回复失败: {e}")
                reply = ""
            # 如果 LLM 回复被过滤为空（输出了纯工具调用），降级为 summary
            if not reply.strip():
                reply = "\n".join(tr.summary for tr in wf_result.tool_results if tr.summary)
                if not reply:
                    reply = "已完成操作。"

        return AgentResult(
            reply=reply,
            tool_calls=wf_result.tool_calls,
            structured_data=structured_data,
        )

    async def run_with_context(
        self,
        user_message: str,
        context: dict,
        conversation_history: List[Dict] = None,
        db=None,
    ) -> AgentResult:
        """
        Context 驱动的 Workflow 执行（前端按钮触发，参数已确定，不需要意图识别）。
        返回格式与 run() 完全兼容。
        """
        # 识别 context 类型
        ctx_type, params = self._parse_context(context, user_message)
        logger.info(f"[Workflow-Context] type={ctx_type}, params_keys={list(params.keys())}")

        workflow_fn = CONTEXT_WORKFLOW_REGISTRY.get(ctx_type)
        if not workflow_fn:
            # 回退到普通 run()
            logger.warning(f"[Workflow-Context] 未知 context 类型 {ctx_type}，降级为普通 run()")
            return await self.run(user_message, conversation_history, db)

        try:
            wf_result = await workflow_fn(params, db=db)
        except Exception as e:
            logger.error(f"[Workflow-Context] 执行失败: {e}")
            return AgentResult(reply=f"抱歉，处理您的请求时出现问题：{str(e)}")

        if wf_result.needs_user_input:
            return AgentResult(reply=wf_result.needs_user_input, tool_calls=wf_result.tool_calls)

        # 生成回复
        structured_data = []
        tool_data_text = ""
        for tr in wf_result.tool_results:
            if tr.data:
                structured_data.append(tr.data)
            tool_data_text += f"\n[查询结果: {tr.summary}]\n数据: {json.dumps(tr.data, ensure_ascii=False, default=str)[:3000]}\n"

        reply = self._try_fixed_reply(structured_data, wf_result)
        if not reply:
            try:
                reply = await self._generate_reply(user_message, tool_data_text, conversation_history)
            except Exception as e:
                logger.error(f"[Workflow-Context] LLM总结失败: {e}")
                reply = "\n".join(tr.summary for tr in wf_result.tool_results if tr.summary) or "操作完成。"

        return AgentResult(reply=reply, tool_calls=wf_result.tool_calls, structured_data=structured_data)

    async def run_stream_with_context(
        self,
        user_message: str,
        context: dict,
        conversation_history: List[Dict] = None,
        db=None,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """
        流式 Context 驱动的 Workflow（前端按钮触发）。
        """
        yield AgentStreamEvent(type="thinking", data={"message": "正在处理您的请求..."})

        ctx_type, params = self._parse_context(context, user_message)
        logger.info(f"[Workflow-Context-Stream] type={ctx_type}")

        workflow_fn = CONTEXT_WORKFLOW_REGISTRY.get(ctx_type)
        if not workflow_fn:
            # 回退到普通 run_stream
            async for event in self.run_stream(user_message, conversation_history, db):
                yield event
            return

        try:
            wf_result = await workflow_fn(params, db=db)
        except Exception as e:
            yield AgentStreamEvent(type="content", data={"text": f"抱歉，处理失败：{str(e)}"})
            yield AgentStreamEvent(type="done", data={})
            return

        # 推送工具事件
        for call_info in wf_result.tool_calls:
            yield AgentStreamEvent(type="tool_calling", data={"tool": call_info["tool"], "args": call_info.get("args", {})})
        for tr in wf_result.tool_results:
            yield AgentStreamEvent(type="tool_result", data={
                "tool": wf_result.tool_calls[0]["tool"] if wf_result.tool_calls else "unknown",
                "success": tr.success, "summary": tr.summary, "structured": tr.data,
            })

        if wf_result.needs_user_input:
            for c in _split_to_chunks(wf_result.needs_user_input):
                yield AgentStreamEvent(type="content", data={"text": c})
            yield AgentStreamEvent(type="done", data={})
            return

        # 流式生成回复
        ctx_structured = [tr.data for tr in wf_result.tool_results if tr.data]
        fixed_reply = self._try_fixed_reply(ctx_structured, wf_result)
        if fixed_reply:
            yield AgentStreamEvent(type="thinking_content", data={"text": "已获取结构化数据，格式化输出。\n"})
            for c in _split_to_chunks(fixed_reply):
                yield AgentStreamEvent(type="content", data={"text": c})
            yield AgentStreamEvent(type="done", data={})
            return

        tool_data_text = ""
        for tr in wf_result.tool_results:
            tool_data_text += f"\n[查询结果: {tr.summary}]\n数据: {json.dumps(tr.data, ensure_ascii=False, default=str)[:3000]}\n"

        summary_messages = self._build_summary_messages(user_message, tool_data_text, conversation_history)
        try:
            full_reply = ""
            async for piece in self.llm.chat_stream_with_thinking(summary_messages):
                if piece["type"] == "thinking":
                    yield AgentStreamEvent(type="thinking_content", data={"text": piece["text"]})
                else:
                    full_reply += piece["text"]
            cleaned = self._clean_reply(full_reply)
            for c in _split_to_chunks(cleaned, chunk_size=40):
                yield AgentStreamEvent(type="content", data={"text": c})
        except Exception:
            fallback = "\n".join(tr.summary for tr in wf_result.tool_results if tr.summary) or "操作完成。"
            for c in _split_to_chunks(fallback):
                yield AgentStreamEvent(type="content", data={"text": c})

        yield AgentStreamEvent(type="done", data={})

    @staticmethod
    def _parse_context(context: dict, user_message: str) -> tuple:
        """解析 context 字典，返回 (ctx_type, params)"""
        if context.get("_confirm_outline"):
            template_id = context.get("_template_id")
            fields = {k: v for k, v in context.items() if not k.startswith("_")}
            return "confirm_outline", {"template_id": template_id, "fields": fields}

        if context.get("_modify_document"):
            return "modify_document", {
                "template_id": context.get("_template_id", 0),
                "modification_request": user_message,
                "original_content": context.get("_original_content", ""),
            }

        if context.get("_export"):
            return "export_from_data", {
                "format": context.get("_format", "excel"),
                "title": context.get("_title", "导出数据"),
                "content": context.get("_content", ""),
                "columns": context.get("_columns"),
                "rows": context.get("_rows"),
            }

        if context.get("_template_id"):
            template_id = context.get("_template_id")
            fields = {k: v for k, v in context.items() if not k.startswith("_")}
            return "generate_with_fields", {"template_id": template_id, "fields": fields}

        # 未知 context，回退
        return "unknown", {}

    async def run_stream(
        self,
        user_message: str,
        conversation_history: List[Dict] = None,
        db=None,
    ) -> AsyncGenerator[AgentStreamEvent, None]:
        """
        流式 Workflow 执行 — 与 AgentEngine.run_stream() 接口兼容
        """
        from app.core.intent import classify_intent_by_keywords, classify_intent_stream, extract_params

        # Step 1: 通知前端正在分析
        yield AgentStreamEvent(type="thinking", data={"message": "正在分析您的问题..."})

        # Step 2: 流式意图识别（thinking 实时推送给前端）
        intent_result = None
        kw_result = classify_intent_by_keywords(user_message, conversation_history)
        if kw_result["confidence"] >= 0.85:
            intent_result = kw_result
            yield AgentStreamEvent(type="thinking_content", data={
                "text": f"识别到意图：{intent_result['intent']}（关键词匹配，置信度{kw_result['confidence']:.0%}）\n"
            })
        else:
            async for chunk in classify_intent_stream(user_message, conversation_history):
                if chunk["type"] == "thinking":
                    yield AgentStreamEvent(type="thinking_content", data={"text": chunk["text"]})
                elif chunk["type"] == "result":
                    intent_result = chunk["data"]

        if not intent_result:
            intent_result = kw_result

        intent = intent_result["intent"]
        logger.info(f"[Workflow-Stream] 意图: '{user_message[:50]}' -> {intent}")

        # Step 3: 通用对话 或 修改反馈 → 流式回复（利用对话历史上下文）
        if intent in ("general_chat", "modify_feedback"):
            messages = [{"role": "system", "content": WORKFLOW_SYSTEM_PROMPT}]
            if conversation_history:
                messages.extend(conversation_history[-8:])
            messages.append({"role": "user", "content": user_message})
            try:
                async for piece in self.llm.chat_stream_with_thinking(messages):
                    if piece["type"] == "thinking":
                        yield AgentStreamEvent(type="thinking_content", data={"text": piece["text"]})
                    else:
                        yield AgentStreamEvent(type="content", data={"text": piece["text"]})
            except Exception as e:
                yield AgentStreamEvent(type="content", data={"text": f"抱歉，回复生成失败：{str(e)}"})
            yield AgentStreamEvent(type="done", data={})
            return

        # Step 4: 参数提取
        params = extract_params(intent, user_message)

        # Step 5: 执行 Workflow
        workflow_fn = WORKFLOW_REGISTRY.get(intent)
        if not workflow_fn:
            messages = [{"role": "system", "content": WORKFLOW_SYSTEM_PROMPT}]
            if conversation_history:
                messages.extend(conversation_history[-6:])
            messages.append({"role": "user", "content": user_message})
            try:
                async for piece in self.llm.chat_stream_with_thinking(messages):
                    if piece["type"] == "thinking":
                        yield AgentStreamEvent(type="thinking_content", data={"text": piece["text"]})
                    else:
                        yield AgentStreamEvent(type="content", data={"text": piece["text"]})
            except Exception as e:
                yield AgentStreamEvent(type="content", data={"text": f"抱歉，回复生成失败：{str(e)}"})
            yield AgentStreamEvent(type="done", data={})
            return

        # 通知前端正在调用工具
        yield AgentStreamEvent(type="thinking", data={"message": "正在为您查询数据..."})

        try:
            wf_result = await workflow_fn(params, db=db)
        except Exception as e:
            logger.error(f"[Workflow-Stream] 执行失败: {e}")
            yield AgentStreamEvent(type="content", data={"text": f"抱歉，处理您的请求时出现问题：{str(e)}"})
            yield AgentStreamEvent(type="done", data={})
            return

        # 推送工具调用和结果事件
        for call_info in wf_result.tool_calls:
            yield AgentStreamEvent(type="tool_calling", data={"tool": call_info["tool"], "args": call_info.get("args", {})})
        for tr in wf_result.tool_results:
            yield AgentStreamEvent(type="tool_result", data={
                "tool": wf_result.tool_calls[0]["tool"] if wf_result.tool_calls else "unknown",
                "success": tr.success,
                "summary": tr.summary,
                "structured": tr.data,
            })

        # Step 6: 需要用户补充信息
        if wf_result.needs_user_input:
            yield AgentStreamEvent(type="thinking_content", data={
                "text": f"需要补充信息才能继续处理。\n"
            })
            for c in _split_to_chunks(wf_result.needs_user_input):
                yield AgentStreamEvent(type="content", data={"text": c})
            yield AgentStreamEvent(type="done", data={})
            return

        # Step 7: 流式生成回复
        structured_data = [tr.data for tr in wf_result.tool_results if tr.data]
        fixed_reply = self._try_fixed_reply(structured_data, wf_result)
        if fixed_reply:
            yield AgentStreamEvent(type="thinking_content", data={
                "text": f"已获取到结构化数据，直接格式化输出。\n"
            })
            for c in _split_to_chunks(fixed_reply):
                yield AgentStreamEvent(type="content", data={"text": c})
            yield AgentStreamEvent(type="done", data={})
            return

        tool_data_text = ""
        for tr in wf_result.tool_results:
            tool_data_text += f"\n[查询结果: {tr.summary}]\n数据: {json.dumps(tr.data, ensure_ascii=False, default=str)[:3000]}\n"

        summary_messages = self._build_summary_messages(user_message, tool_data_text, conversation_history)

        try:
            # thinking 实时流式推送，content 先收集再清洗输出（避免暴露工具名）
            full_reply = ""
            async for piece in self.llm.chat_stream_with_thinking(summary_messages):
                if piece["type"] == "thinking":
                    yield AgentStreamEvent(type="thinking_content", data={"text": piece["text"]})
                else:
                    full_reply += piece["text"]
            cleaned = self._clean_reply(full_reply)
            for c in _split_to_chunks(cleaned, chunk_size=40):
                yield AgentStreamEvent(type="content", data={"text": c})
        except Exception as e:
            fallback = "\n".join(tr.summary for tr in wf_result.tool_results if tr.summary) or "查询完成。"
            for c in _split_to_chunks(fallback):
                yield AgentStreamEvent(type="content", data={"text": c})

        yield AgentStreamEvent(type="done", data={})

    @staticmethod
    def _try_fixed_reply(structured_data: list, wf_result) -> str:
        """对特定数据类型返回固定回复，跳过 LLM 总结（避免编造信息）"""
        if not structured_data:
            return ""
        for item in structured_data:
            item_type = item.get("type", "")
            if item_type == "export_ready":
                fmt = item.get("format", "文件").upper()
                return f"{fmt}文件已准备就绪，请点击下方按钮下载。"
            if item_type == "document":
                name = item.get("template_name", "文档")
                reply_text = f"【{name}】已生成完毕，您可以查看下方内容。"
                # 嵌入下载链接（降级方案：即使按钮不可用，用户也可通过链接下载）
                links = []
                if item.get("word_link"):
                    links.append(f"[📄 下载Word文件]({item['word_link']})")
                if links:
                    reply_text += "\n\n" + "　　".join(links)
                reply_text += "\n\n如需修改，请直接告诉我修改要求。"
                return reply_text
            if item_type == "template_outline":
                name = item.get("template_name", "文档")
                return f"【{name}】大纲已生成，请查看下方内容。\n\n💡 如果满意，请回复「确认」生成完整文档；如需调整，请回复「重新生成大纲」或直接说明修改要求。"
            if item_type == "template_form":
                name = item.get("template_name", "文档")
                return f"已为您匹配到【{name}】模板，请在下方表单中填写相关信息后提交。"
            if item_type == "template_list":
                templates = item.get("templates", [])
                if not templates:
                    return "当前没有可用的文档模板，请联系管理员在后台添加。"
                return ""  # 模板列表通常不会单独返回，由 _wf_generate_document 后续处理
            if item_type == "diff_report":
                report = item.get("report", {})
                total = report.get("total_diffs", 0)
                sim = report.get("similarity", 0)
                return f"对比完成，共发现 {total} 处差异，文本相似度 {sim}%。详细差异请查看下方报告。"
            if item_type == "policy_search":
                clauses = item.get("clauses", [])
                if not clauses:
                    kb_status = item.get("kb_status") or {}
                    if kb_status.get("error"):
                        return (
                            f"⚠️ 政策知识库暂时无法使用：{kb_status['error'][:150]}。\n\n"
                            "未能检索到知识库依据，请稍后重试；"
                            "如多次失败，请联系管理员检查 Embedding / 向量知识库服务。"
                        )
                    return ""  # 空结果不截断，交给 LLM 回答（summary prompt 会标注来源）
                return ""  # 有检索结果时交给 LLM 基于原文总结
            if item_type == "compliance_result" and item.get("error") == "no_clauses":
                kb_status = item.get("kb_status") or {}
                if kb_status.get("error"):
                    return (
                        f"⚠️ 政策知识库调用失败：{kb_status['error'][:150]}。\n\n"
                        "无法提供政策依据进行合规判断，请稍后重试或联系管理员检查知识库服务。"
                    )
                return (
                    "⚠️ 未检索到相关政策条款，无法进行合规判断。\n\n"
                    "请确认政策知识库已上传并解析相关政策文件后重试。"
                )
        return ""  # 其他类型交给 LLM 总结

    @staticmethod
    def _clean_reply(text: str) -> str:
        """后处理过滤 LLM 回复中的工具调用痕迹、流程描述和原始 JSON 输出"""
        import re
        # 1. 去除 <tool_call>...</tool_call> 标签
        text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
        # 2. 去除裸 JSON 工具调用格式
        text = re.sub(r'\{\s*"name"\s*:\s*"[^"]*"\s*,\s*"arguments"\s*:\s*\{[^}]*\}\s*\}?', '', text, flags=re.DOTALL)
        # 3. 去除提及工具名的句子
        tool_names = 'search_policy|check_compliance|list_templates|generate_document|export_file|compare_texts'
        tool_patterns = [
            r'(?:我将|正在|已经|需要|首先)?(?:调用|触发|执行|使用)\s*\w*(?:工具|tool|api|函数)\w*.*?[。\n]',
            rf'(?:调用|触发|执行)\s*(?:{tool_names}).*?[。\n]',
            r'(?:tool_call|tool_result|function_call).*?[。\n]',
            rf'(?:{tool_names})\s*(?:工具|函数|tool)',
        ]
        for pat in tool_patterns:
            text = re.sub(pat, '', text, flags=re.IGNORECASE)
        # 4. 去除过程描述句子
        process_patterns = [
            r'[🔍📋⚠️✅❌🔎💡📌]',
            r'(?:请稍等|稍等片刻|正在检索|正在查询|正在搜索|正在获取|正在分析).*?[。\n，]',
        ]
        for pat in process_patterns:
            text = re.sub(pat, '', text)
        # 5. 去除多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    async def _direct_chat(self, user_message: str, conversation_history) -> AgentResult:
        """通用对话（不调用工具，利用对话历史上下文回复，也用于修改反馈场景）"""
        messages = [{"role": "system", "content": WORKFLOW_SYSTEM_PROMPT}]
        if conversation_history:
            messages.extend(conversation_history[-8:])
        messages.append({"role": "user", "content": user_message})
        try:
            reply = await self.llm.chat(messages)
        except Exception as e:
            reply = f"抱歉，回复生成失败：{str(e)}"
        return AgentResult(reply=reply)

    async def _generate_reply(self, user_message: str, tool_data_text: str, conversation_history) -> str:
        """基于工具结果让 LLM 生成自然语言回复"""
        messages = self._build_summary_messages(user_message, tool_data_text, conversation_history)
        logger.info(f"[Workflow] LLM总结: 输入数据{len(tool_data_text)}字, 消息数{len(messages)}")
        reply = await self.llm.chat(messages)
        cleaned = self._clean_reply(reply)
        if len(cleaned) < len(reply) * 0.5:
            logger.warning(f"[Workflow] _clean_reply 过滤了大量内容: 原{len(reply)}字 -> 过滤后{len(cleaned)}字")
        return cleaned

    def _build_summary_messages(self, user_message: str, tool_data_text: str, conversation_history) -> List[Dict]:
        """构建用于 LLM 总结回复的消息列表"""
        messages = [{"role": "system", "content": WORKFLOW_SUMMARY_PROMPT}]
        if conversation_history:
            # 过滤对话历史中可能包含工具调用格式的旧消息，避免 LLM 模仿
            clean_history = []
            for msg in conversation_history[-4:]:
                content = msg.get("content", "")
                if msg.get("role") == "assistant" and ('"name"' in content and '"arguments"' in content):
                    continue  # 跳过包含工具调用格式的旧 Assistant 消息
                if msg.get("role") == "assistant" and '<tool_call>' in content:
                    continue
                clean_history.append(msg)
            messages.extend(clean_history)
        messages.append({
            "role": "user",
            "content": f"用户问题：{user_message}\n\n【系统资料】（以下内容来自真实政策文件和数据库，请基于这些资料回答）：\n{tool_data_text}\n\n请基于上述【系统资料】回答用户问题。只使用资料中出现的内容，不要添加资料中没有的信息。",
        })
        return messages


# ========== 工厂函数 ==========

def create_engine(llm_service, tool_registry: ToolRegistry = None):
    """根据配置创建 Agent 引擎（支持 native/prompt/workflow 三种模式）"""
    mode = getattr(settings, "TOOL_CALL_MODE", "prompt")
    if mode == "workflow":
        return WorkflowEngine(llm_service)
    else:
        return AgentEngine(llm_service, tool_registry)
