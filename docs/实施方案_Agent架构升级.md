# 党政工作智脑 — Agent架构升级实施方案

> 版本：v2.0 | 日期：2026年2月28日
> 基于v1.0代码现状，升级为真正的智能体架构

---

## 一、现状分析与改造动机

### 1.1 当前架构的核心问题

当前系统采用**管道式架构**（Pipeline），本质是一个"LLM增强的传统Web应用"，而非真正的智能体：

```
用户输入 → 意图分类(7个标签) → if/elif硬编码路由 → 单一处理器 → 固定格式返回
```

| 问题 | 具体表现 |
|------|---------|
| AI无自主决策能力 | 代码硬编码决定调用什么，LLM只做文本填空 |
| 无Tool Calling | LLM不能主动选择"我要查数据库"或"我要检索政策" |
| 无推理循环 | 一问一答，不能"思考→行动→观察→再思考" |
| 无多步任务能力 | "查完数据再生成报告"这种串联任务做不到 |
| 7个意图是天花板 | 跨功能、复合型问题无法处理 |
| 关键词回退是补丁 | 设计时就不信任AI，用代码兜底 |

### 1.2 目标架构：Tool-Use Agent

```
用户输入 → Agent（LLM + System Prompt + Tools） ⇄ 工具调用循环 → 综合回答
```

**核心转变**：从"代码告诉AI做什么"变为"AI自己决定做什么，代码提供能力"。

### 1.3 改造范围评估

| 模块 | 改造程度 | 说明 |
|------|---------|------|
| 核心对话（chat.py） | **重写** | 从管道式改为Agent循环 |
| 意图识别（intent.py） | **删除** | Agent自行判断，不再需要分类 |
| LLM服务（llm.py） | **扩展** | 增加Function Calling支持 |
| NL2SQL（nl2sql.py） | **改造为Tool** | 封装为Agent可调用的工具 |
| 模板生成（template_gen.py） | **改造为Tool** | 封装为Agent可调用的工具 |
| RAG检索（rag.py + search.py） | **改造为Tool** | 封装为Agent可调用的工具 |
| 合规判断（compliance.py） | **改造为Tool** | 封装为Agent可调用的工具 |
| 差异对比（diff_engine.py） | **改造为Tool** | 封装为Agent可调用的工具 |
| 前端对话页 | **适配** | 适配Agent返回的结构化数据 |
| 数据模型/管理后台 | **保留** | 基本不变 |

---

## 二、Agent架构详细设计

### 2.1 整体架构

```
+================================================================+
|                        用户层                                    |
|  Web对话界面（流式输出 + 结构化数据渲染 + 工具调用过程展示）       |
+================================+===============================+
                                 |
+================================v===============================+
|                     Agent 调度层                                 |
|                                                                  |
|  +----------------------------------------------------------+   |
|  |              Agent Core（核心循环引擎）                     |   |
|  |                                                           |   |
|  |  System Prompt（角色定义 + 工具使用规范 + 安全约束）        |   |
|  |       ↓                                                   |   |
|  |  User Message + 对话历史                                   |   |
|  |       ↓                                                   |   |
|  |  LLM（Function Calling模式）                               |   |
|  |       ↓                                                   |   |
|  |  ┌─────────────────────────────────────┐                  |   |
|  |  │  推理循环（ReAct Loop, 最多10轮）    │                  |   |
|  |  │                                      │                  |   |
|  |  │  LLM思考 → 选择Tool → 执行Tool      │                  |   |
|  |  │      ↑          → 观察结果 ──────┘   │                  |   |
|  |  │      └──── 需要更多信息? ────────┘    │                  |   |
|  |  │                                      │                  |   |
|  |  │  直到LLM决定不再调用Tool，直接回答    │                  |   |
|  |  └─────────────────────────────────────┘                  |   |
|  +----------------------------------------------------------+   |
|                           |                                      |
+===========================|======================================+
                            |
+===========================v======================================+
|                      工具层 (Tools)                               |
|                                                                   |
|  +------------------+  +------------------+  +------------------+ |
|  | query_members    |  | search_policy    |  | check_compliance | |
|  | 查询党员数据库   |  | 检索政策知识库   |  | 合规条件判断     | |
|  +------------------+  +------------------+  +------------------+ |
|                                                                   |
|  +------------------+  +------------------+  +------------------+ |
|  | generate_doc     |  | compare_files    |  | get_statistics   | |
|  | 生成文档         |  | 文件差异对比     |  | 统计分析         | |
|  +------------------+  +------------------+  +------------------+ |
|                                                                   |
|  +------------------+  +------------------+  +------------------+ |
|  | export_file      |  | list_templates   |  | get_member_detail| |
|  | 导出Word/PDF/XLS |  | 查看可用模板     |  | 获取党员详情     | |
|  +------------------+  +------------------+  +------------------+ |
+===================================================================+
                            |
+===========================v======================================+
|                   数据与知识层                                    |
|  +-----------+  +----------+  +----------------------------+     |
|  | 模板库    |  | 党员数据库|  | 政策向量知识库              |     |
|  | (SQLite)  |  | (SQLite) |  | (Milvus + SQLite回退)      |     |
|  +-----------+  +----------+  +----------------------------+     |
+===================================================================+
```

### 2.2 Agent Core 详细设计

#### 2.2.1 System Prompt

```python
AGENT_SYSTEM_PROMPT = """你是「党政工作智脑」，一个专业的党务工作AI智能助手，服务于机关党委。

## 你的能力
你可以通过调用工具来完成以下任务：
1. 查询党员数据库（按姓名、支部、状态等条件，也可以做统计分析）
2. 检索政策知识库（查找政策条款、法规内容）
3. 进行合规条件判断（逐条对照判断是否符合某项条件）
4. 生成公文文档（工作计划、活动方案、会议纪要等）
5. 对比文件差异（比较两份文件的不同之处）
6. 导出文件（将查询结果或生成的文档导出为Word/PDF/Excel）

## 工作原则
1. **先思考再行动**：收到用户请求后，先分析需要哪些步骤，再逐步调用工具
2. **多步任务自动串联**：如果任务需要多个步骤（如先查数据再做判断），自动依次执行
3. **信息不足时追问**：如果缺少关键信息，主动追问用户
4. **结果有据可查**：政策相关回答必须附带引用来源
5. **安全合规**：不执行任何数据修改操作，手机号等敏感信息自动脱敏

## 输出格式
- 查询结果以表格形式展示
- 统计数据同时提供表格和图表
- 政策咨询附带条款引用
- 合规判断附带逐条核查和置信度
- 文档生成先提供大纲确认

## 注意事项
- 你是党务工作助手，对政治话题要保持严谨
- 不确定的内容必须明确标注"仅供参考，建议人工复核"
- 党员个人信息需要脱敏处理（手机号等）
"""
```

#### 2.2.2 Tools定义（Function Calling Schema）

```python
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_members",
            "description": "查询党员数据库。支持按条件查询党员列表，也支持统计分析（如各支部人数、年龄分布等）。输入自然语言查询描述，系统会自动转换为SQL执行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言查询描述，如'第三支部的预备党员'、'统计各支部人数'、'查询王五的详细信息'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "检索政策知识库，查找与问题相关的政策条款和法规内容。返回最相关的条款原文及来源。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "政策相关的问题或关键词，如'党费缴纳标准'、'发展党员流程'、'入党积极分子条件'"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回最相关的条款数量，默认5",
                        "default": 5
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
            "description": "合规条件判断。根据提供的人员信息和判断事项，检索相关政策条款，逐条对照判断是否符合条件。返回逐项核查结果、置信度和引用依据。",
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
            "description": "查看当前可用的文档模板列表，包括模板名称、类型、必填字段和选填字段。在生成文档前应先调用此工具了解有哪些模板可用。",
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
            "description": "根据模板和用户提供的字段信息生成公文文档。需要指定模板ID和各字段的值。如果是第一次生成，先生成大纲；用户确认后再生成全文。",
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
                        "description": "生成阶段：outline=生成大纲, full=生成全文, modify=修改已有文档",
                        "default": "outline"
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
            "name": "get_statistics",
            "description": "获取党员数据的统计分析结果，支持按支部人数统计、年龄段分布等。返回结构化数据，前端会自动渲染为图表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "stat_type": {
                        "type": "string",
                        "enum": ["department", "age", "education", "status", "custom"],
                        "description": "统计类型：department=按支部, age=按年龄段, education=按学历, status=按状态, custom=自定义SQL"
                    },
                    "custom_query": {
                        "type": "string",
                        "description": "自定义统计查询（仅stat_type=custom时使用）"
                    }
                },
                "required": ["stat_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_member_detail",
            "description": "获取某个党员的详细信息（画像卡片），包括姓名、性别、出生日期、支部、职务、学历、入党日期、转正日期等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "党员姓名"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "export_file",
            "description": "将内容导出为文件。支持Word、PDF、Excel格式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["word", "pdf", "excel"],
                        "description": "导出格式"
                    },
                    "title": {
                        "type": "string",
                        "description": "文件标题"
                    },
                    "content": {
                        "type": "string",
                        "description": "文档内容（word/pdf时使用）"
                    },
                    "table_data": {
                        "type": "object",
                        "description": "表格数据（excel时使用），格式{columns: [...], rows: [...]}"
                    }
                },
                "required": ["format", "title"]
            }
        }
    }
]
```

#### 2.2.3 Agent循环引擎（核心代码设计）

```python
class AgentEngine:
    """Agent核心循环引擎"""

    MAX_ITERATIONS = 10  # 最大工具调用轮次，防止死循环
    
    def __init__(self, llm_service, tool_registry):
        self.llm = llm_service
        self.tools = tool_registry
    
    async def run(self, user_message: str, conversation_history: list, db: Session) -> AgentResult:
        """
        执行Agent循环：
        1. 将用户消息+历史+System Prompt发送给LLM（带Tools定义）
        2. 如果LLM返回tool_calls → 执行工具 → 将结果加入消息 → 回到1
        3. 如果LLM返回文本回复 → 结束循环，返回结果
        """
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            *conversation_history,
            {"role": "user", "content": user_message},
        ]
        
        tool_call_log = []  # 记录工具调用过程（展示给用户）
        iteration = 0
        
        while iteration < self.MAX_ITERATIONS:
            iteration += 1
            
            # 调用LLM（带Function Calling）
            response = await self.llm.chat_with_tools(
                messages=messages,
                tools=AGENT_TOOLS,
            )
            
            # 情况A：LLM决定调用工具
            if response.tool_calls:
                # 将assistant的tool_calls消息加入
                messages.append(response.to_message())
                
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    # 执行工具
                    tool_result = await self.tools.execute(
                        tool_name, tool_args, db=db
                    )
                    
                    # 记录调用过程
                    tool_call_log.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result_summary": tool_result.summary,
                        "iteration": iteration,
                    })
                    
                    # 将工具结果加入消息
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result.data, ensure_ascii=False),
                    })
                
                continue  # 回到循环顶部，让LLM看到工具结果后继续思考
            
            # 情况B：LLM直接回复文本（不再需要调用工具）
            return AgentResult(
                reply=response.content,
                tool_calls=tool_call_log,
                structured_data=self._extract_structured_data(tool_call_log),
            )
        
        # 超过最大轮次
        return AgentResult(
            reply="抱歉，这个问题比较复杂，我处理了多个步骤但仍未完成。请尝试简化您的问题。",
            tool_calls=tool_call_log,
        )
    
    async def run_stream(self, user_message, conversation_history, db):
        """流式Agent循环 — 思考和工具调用过程实时展示给用户"""
        messages = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            *conversation_history,
            {"role": "user", "content": user_message},
        ]
        
        iteration = 0
        while iteration < self.MAX_ITERATIONS:
            iteration += 1
            
            # 流式调用LLM
            async for event in self.llm.chat_with_tools_stream(messages, AGENT_TOOLS):
                if event.type == "tool_call":
                    # 通知前端：Agent正在调用工具
                    yield AgentStreamEvent(
                        type="tool_calling",
                        data={"tool": event.tool_name, "args": event.tool_args}
                    )
                    
                    # 执行工具
                    result = await self.tools.execute(event.tool_name, event.tool_args, db=db)
                    
                    # 通知前端：工具调用结果
                    yield AgentStreamEvent(
                        type="tool_result",
                        data={"tool": event.tool_name, "result": result.summary, "structured": result.data}
                    )
                    
                    # 将结果加入消息继续循环
                    messages.append(event.to_assistant_message())
                    messages.append({
                        "role": "tool",
                        "tool_call_id": event.tool_call_id,
                        "content": json.dumps(result.data, ensure_ascii=False),
                    })
                    break  # 跳出内层for，回到while继续下一轮
                    
                elif event.type == "content":
                    # Agent正在输出最终回复（流式文本）
                    yield AgentStreamEvent(type="content", data={"text": event.text})
                    
                elif event.type == "done":
                    yield AgentStreamEvent(type="done")
                    return
```

### 2.3 Tool Registry（工具注册与执行）

```python
class ToolRegistry:
    """工具注册中心 — 管理所有Agent可调用的工具"""
    
    def __init__(self):
        self._tools = {}
    
    def register(self, name: str, handler, description: str):
        self._tools[name] = {"handler": handler, "description": description}
    
    async def execute(self, name: str, args: dict, **kwargs) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, summary=f"未知工具: {name}")
        
        try:
            result = await tool["handler"](**args, **kwargs)
            return result
        except Exception as e:
            return ToolResult(
                success=False,
                summary=f"工具执行失败: {str(e)}",
                data={"error": str(e)}
            )

# 初始化工具注册
tool_registry = ToolRegistry()
tool_registry.register("query_members", handle_query_members, "查询党员数据库")
tool_registry.register("search_policy", handle_search_policy, "检索政策知识库")
tool_registry.register("check_compliance", handle_check_compliance, "合规条件判断")
tool_registry.register("list_templates", handle_list_templates, "查看模板列表")
tool_registry.register("generate_document", handle_generate_document, "生成文档")
tool_registry.register("get_statistics", handle_get_statistics, "统计分析")
tool_registry.register("get_member_detail", handle_get_member_detail, "党员详情")
tool_registry.register("export_file", handle_export_file, "导出文件")
```

### 2.4 各Tool Handler实现设计

#### Tool 1: query_members（查询党员数据库）

```python
async def handle_query_members(query: str, db: Session = None) -> ToolResult:
    """
    将自然语言查询转为SQL执行
    复用现有 nl2sql.py 的能力，但包装为Tool返回格式
    """
    # 1. NL2SQL
    sql_result = await natural_language_to_sql(query)
    if not sql_result["success"]:
        return ToolResult(
            success=False,
            summary=f"无法理解查询: {sql_result.get('error', '')}",
            data={"error": sql_result.get("error")}
        )
    
    # 2. 执行SQL
    query_result = execute_query(db, sql_result["sql"])
    if not query_result["success"]:
        return ToolResult(
            success=False,
            summary=f"查询执行失败: {query_result.get('error', '')}",
            data={"error": query_result.get("error")}
        )
    
    # 3. 返回结构化结果
    return ToolResult(
        success=True,
        summary=f"查询成功，共{query_result['count']}条记录",
        data={
            "type": "table",
            "columns": query_result["columns"],
            "rows": query_result["rows"],
            "count": query_result["count"],
            "is_stats": sql_result.get("is_stats", False),
            "description": sql_result.get("description", ""),
            "sql": sql_result["sql"],  # 供Agent参考
        }
    )
```

#### Tool 2: search_policy（检索政策知识库）

```python
async def handle_search_policy(query: str, top_k: int = 5, db: Session = None) -> ToolResult:
    """
    检索政策知识库，返回相关条款
    复用现有 search.py 的检索能力
    """
    from app.core.search import search_policy_chunks
    
    clauses = search_policy_chunks(query, top_k=top_k)
    
    if not clauses:
        return ToolResult(
            success=True,
            summary="未检索到相关政策条款",
            data={"clauses": [], "count": 0}
        )
    
    return ToolResult(
        success=True,
        summary=f"检索到{len(clauses)}条相关政策条款",
        data={
            "type": "policy_search",
            "clauses": clauses,
            "count": len(clauses),
        }
    )
```

#### Tool 3: check_compliance（合规判断）

```python
async def handle_check_compliance(
    person_info: str, requirement: str, db: Session = None
) -> ToolResult:
    """
    完整的合规判断流程：
    1. 自动检索相关政策条款
    2. 逐条对照判断
    3. 评估置信度
    4. 引用溯源
    """
    from app.core.search import search_policy_chunks
    from app.core.rag import check_compliance, preview_clauses
    
    # 1. 检索相关条款
    clauses = search_policy_chunks(f"{person_info} {requirement}", top_k=8)
    
    # 2. 条款预览
    clause_preview = await preview_clauses(f"{person_info} {requirement}", clauses) if clauses else {}
    
    # 3. 执行判断
    check_result = await check_compliance(
        person_info=person_info,
        requirement=requirement,
        retrieved_clauses=clauses,
    )
    
    # 4. 置信度评估
    confidence = check_result.get("confidence", 0.5)
    
    return ToolResult(
        success=True,
        summary=f"合规判断完成，结论：{check_result.get('overall_result', '未知')}，置信度{int(confidence*100)}%",
        data={
            "type": "compliance_result",
            "clause_preview": clause_preview,
            "check_result": check_result,
            "confidence": confidence,
            "needs_human_review": confidence < 0.8,
        }
    )
```

#### Tool 4-8: 其他工具（简述）

```python
# Tool 4: list_templates — 直接查询数据库返回模板列表
# Tool 5: generate_document — 复用template_gen.py的能力
# Tool 6: get_statistics — 复用member.py的统计API
# Tool 7: get_member_detail — 按姓名查询单人详情
# Tool 8: export_file — 复用export.py的导出能力，返回下载链接
```

---

## 三、LLM服务层升级

### 3.1 新增Function Calling支持

当前`llm.py`只有`chat`、`chat_stream`、`chat_json`三个方法，需要新增：

```python
class LLMService:
    """升级后的LLM服务"""
    
    async def chat_with_tools(
        self, messages: list, tools: list, **kwargs
    ) -> LLMResponse:
        """带Function Calling的非流式调用"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",  # 让模型自己决定是否调用工具
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return self._parse_response(response)
    
    async def chat_with_tools_stream(
        self, messages: list, tools: list, **kwargs
    ):
        """带Function Calling的流式调用"""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        # 解析流式响应中的tool_calls和content
        async for chunk in response:
            yield self._parse_stream_chunk(chunk)
```

### 3.2 模型兼容性

Function Calling需要模型支持，以下模型均支持OpenAI兼容的Function Calling：

| 模型 | Function Calling | 推荐度 |
|------|-----------------|--------|
| Qwen2.5 (7B/14B/72B) | ✅ 支持 | ⭐⭐⭐⭐⭐ 首选 |
| DeepSeek-V3 | ✅ 支持 | ⭐⭐⭐⭐⭐ |
| GLM-4 | ✅ 支持 | ⭐⭐⭐⭐ |
| Llama 3.1 (70B+) | ✅ 支持 | ⭐⭐⭐ |
| GPT-4o / GPT-4o-mini | ✅ 支持 | ⭐⭐⭐⭐⭐（非私有化） |

**Ollama部署Qwen2.5即可支持Function Calling**，无需额外配置。

---

## 四、前端适配设计

### 4.1 Agent过程可视化

当前前端只展示最终回答，升级后需要展示Agent的思考和工具调用过程：

```
+=========================================================================+
|  [用户] 帮我查下第三支部有哪些预备党员快转正了，然后看看他们是否符合条件  |
|                                                                         |
|  [智脑]                                                                 |
|  🔍 正在查询党员数据库...                                               |
|  ┌─────────────────────────────────────────────────────────┐           |
|  │ 📌 调用工具: query_members                               │           |
|  │ 查询: "第三支部的预备党员及转正日期"                       │           |
|  │ ✅ 查询成功，找到3条记录                                  │           |
|  └─────────────────────────────────────────────────────────┘           |
|                                                                         |
|  +------+------+------+------------+------------+                      |
|  | 姓名 | 性别 | 年龄 |  入党时间  | 预计转正   |                      |
|  +------+------+------+------------+------------+                      |
|  | 王五 |  男  |  28  | 2025-12-01 | 2026-12-01 |                      |
|  | 赵六 |  女  |  25  | 2026-01-15 | 2027-01-15 |                      |
|  | 钱七 |  男  |  32  | 2026-03-20 | 2027-03-20 |                      |
|  +------+------+------+------------+------------+                      |
|                                                                         |
|  ⚖️ 正在对王五进行合规判断（最接近转正日期）...                          |
|  ┌─────────────────────────────────────────────────────────┐           |
|  │ 📌 调用工具: check_compliance                            │           |
|  │ 人员: "王五，28岁，2025-12-01入党，预备党员"              │           |
|  │ 事项: "是否符合预备党员转正条件"                           │           |
|  │ ✅ 判断完成，结论：基本符合，置信度85%                     │           |
|  └─────────────────────────────────────────────────────────┘           |
|                                                                         |
|  第三支部共有3名预备党员，其中王五将在2026年12月最先到期。              |
|                                                                         |
|  经合规判断，王五基本符合转正条件：                                     |
|  ✅ 预备期满1年                                                        |
|  ✅ 按时缴纳党费                                                       |
|  ❓ 民主评议记录 — 未提供相关信息                                       |
|  ❓ 转正申请书 — 未提供相关信息                                         |
|                                                                         |
|  建议：请确认王五已完成民主评议和提交转正申请书。                       |
|  赵六和钱七的转正日期较远，建议届时再行评估。                           |
|                                                                         |
|  [导出Excel]  [逐一判断所有人]                                          |
+=========================================================================+
```

### 4.2 SSE流式事件协议

前端需要处理的SSE事件类型：

```typescript
interface AgentStreamEvent {
  type: "thinking" | "tool_calling" | "tool_result" | "content" | "done"
  data: {
    // type=thinking: Agent正在思考
    thought?: string
    
    // type=tool_calling: 正在调用工具
    tool?: string
    args?: object
    description?: string  // "正在查询党员数据库..."
    
    // type=tool_result: 工具调用结果
    tool?: string
    success?: boolean
    summary?: string
    structured?: object  // 结构化数据（表格/图表/卡片）
    
    // type=content: 最终回复文本（逐字流式）
    text?: string
    
    // type=done: 完成
    conversation_id?: number
  }
}
```

### 4.3 前端新增组件

| 组件 | 用途 |
|------|------|
| `ToolCallCard.jsx` | 展示单次工具调用的过程（折叠/展开） |
| `AgentThinking.jsx` | 展示Agent思考过程的动画 |
| `AgentTimeline.jsx` | 多步骤执行的时间线视图 |

---

## 五、对话历史与上下文管理

### 5.1 对话上下文注入

当前系统每次请求是独立的，升级后需要将对话历史传入Agent：

```python
# 获取最近N轮对话历史（含工具调用记录）
history_messages = get_conversation_history(conversation_id, limit=10)

# Agent可以引用之前的查询结果
# 例如用户问"上面那些人里谁学历最高？"，Agent可以看到之前的查询结果
```

### 5.2 工具调用结果缓存

```python
# 同一对话中，相同的工具调用结果可以缓存
# 避免重复查询数据库
class ToolResultCache:
    def __init__(self):
        self.cache = {}  # key: (tool_name, args_hash) → value: ToolResult
    
    def get_or_execute(self, tool_name, args, handler):
        key = (tool_name, hash(json.dumps(args, sort_keys=True)))
        if key in self.cache:
            return self.cache[key]
        result = handler(**args)
        self.cache[key] = result
        return result
```

---

## 六、安全与兜底设计

### 6.1 工具调用安全

```python
# 1. 工具调用次数限制
MAX_TOOL_CALLS_PER_REQUEST = 10

# 2. 工具调用白名单（只有注册的工具才能调用）
ALLOWED_TOOLS = {"query_members", "search_policy", "check_compliance", ...}

# 3. 参数校验（每个Tool Handler内部校验）

# 4. SQL安全（复用现有validate_sql，只允许SELECT）

# 5. 敏感信息脱敏（复用现有desensitize_phone）
```

### 6.2 LLM不可用时的降级

```python
# Agent引擎检测到LLM不可用时，回退到简化模式
class AgentEngine:
    async def run(self, user_message, ...):
        try:
            # 尝试Agent模式
            return await self._run_agent_mode(user_message, ...)
        except LLMConnectionError:
            # 降级到关键词模式
            return await self._run_fallback_mode(user_message, ...)
    
    async def _run_fallback_mode(self, user_message, ...):
        """LLM不可用时的降级模式 — 关键词匹配 + 直接执行"""
        # 复用现有的关键词匹配逻辑和预设查询
        ...
```

### 6.3 成本控制

```python
# Agent循环可能产生多次LLM调用，需要控制成本
class AgentEngine:
    MAX_ITERATIONS = 10          # 最大循环次数
    MAX_TOKENS_PER_REQUEST = 16000  # 单次请求最大token
    MAX_TOOL_CALLS = 10          # 最大工具调用次数
    
    # 超过限制时优雅退出，给出已有结果
```

---

## 七、改造实施计划

### 7.1 整体时间线

```
阶段:   1        2        3        4        5
天数:  1-2天   3-4天    5-6天    7-8天    9-10天
      |========|========|========|========|========|
阶段一 |########|         Agent引擎 + LLM升级
阶段二          |########|  Tools封装 + 测试
阶段三                   |########|  前端适配
阶段四                            |########|  联调 + 降级
阶段五                                     |########| 优化 + 文档
```

### 7.2 阶段一：Agent引擎 + LLM层升级（第1-2天）

**目标**：搭建Agent循环引擎，LLM服务支持Function Calling

1. **新建 `app/core/agent.py`**
   - `AgentEngine` 类：核心循环逻辑
   - `ToolRegistry` 类：工具注册中心
   - `ToolResult` / `AgentResult` 数据类
   - `AgentStreamEvent` 流式事件类

2. **升级 `app/core/llm.py`**
   - 新增 `chat_with_tools()` 方法
   - 新增 `chat_with_tools_stream()` 方法
   - 解析Function Calling响应

3. **编写 `AGENT_SYSTEM_PROMPT`**

4. **编写 `AGENT_TOOLS` 定义**（8个工具的JSON Schema）

**验证**：用单元测试验证Agent循环能正确调用工具并返回结果

### 7.3 阶段二：Tools封装 + 注册（第3-4天）

**目标**：将现有功能封装为8个Tool Handler

1. **新建 `app/core/tools.py`**
   - `handle_query_members()` — 封装nl2sql + execute_query
   - `handle_search_policy()` — 封装search_policy_chunks
   - `handle_check_compliance()` — 封装compliance流程
   - `handle_list_templates()` — 封装模板查询
   - `handle_generate_document()` — 封装模板生成（大纲/全文/修改）
   - `handle_get_statistics()` — 封装统计查询
   - `handle_get_member_detail()` — 封装单人查询
   - `handle_export_file()` — 封装导出（返回下载URL）

2. **注册所有Tools到 `ToolRegistry`**

3. **每个Tool编写独立测试**

**验证**：每个Tool独立可用，输入输出格式正确

### 7.4 阶段三：API层 + 前端适配（第5-6天）

**目标**：改造chat.py API，前端展示Agent过程

1. **改造 `app/api/chat.py`**
   - `/api/chat/send` → 使用 `AgentEngine.run()`
   - `/api/chat/send/stream` → 使用 `AgentEngine.run_stream()`
   - 删除旧的意图分类 + 硬编码路由逻辑
   - 保留对话管理相关代码不变

2. **前端Chat.jsx适配**
   - 处理新的SSE事件类型（tool_calling, tool_result等）
   - 新增 `ToolCallCard` 组件
   - 新增 `AgentThinking` 组件
   - 结构化数据渲染保持不变（DataTable, StatsChart等）

3. **删除 `app/core/intent.py`**（不再需要意图分类）

**验证**：前端能展示完整的Agent调用过程

### 7.5 阶段四：降级机制 + 联调（第7-8天）

1. LLM不可用时的降级模式
2. 工具调用安全校验
3. 成本控制（循环次数、token限制）
4. 对话上下文注入（历史消息）
5. 全链路联调测试

### 7.6 阶段五：优化 + 文档（第9-10天）

1. System Prompt调优（基于测试结果）
2. 工具调用结果缓存
3. 性能优化（并行工具调用）
4. 更新用户操作手册和管理员手册
5. 更新README

---

## 八、改造前后对比

### 8.1 用户体验对比

| 场景 | 改造前 | 改造后 |
|------|--------|--------|
| "帮我查下第三支部预备党员，判断能否转正" | 只能处理"查预备党员"，无法串联判断 | Agent自动：查数据库→合规判断→综合回答 |
| "写一份工作计划" | 意图分类→匹配模板→追问字段 | Agent：查模板列表→追问字段→生成大纲→确认→生成全文 |
| "党费标准是什么？按这个标准月薪8000应交多少？" | 只能回答标准，无法计算 | Agent：检索政策→提取标准→计算具体金额 |
| "查一下王五的信息，然后帮他生成一份述职报告" | 只能处理一个意图 | Agent：查党员详情→获取信息→匹配述职报告模板→自动填充生成 |
| "统计各支部人数，导出Excel" | 需要分两步操作 | Agent：查统计→导出Excel→返回下载链接 |

### 8.2 架构对比

```
改造前（管道式）：
用户 → 意图分类(7类) → if/elif → 处理器A/B/C → 返回

改造后（Agent式）：
用户 → Agent(LLM+Tools) ⇄ 自主调用Tools(N次) → 综合回答
```

### 8.3 代码变更量评估

| 文件 | 操作 | 预计行数 |
|------|------|---------|
| `app/core/agent.py` | **新建** | ~300行 |
| `app/core/tools.py` | **新建** | ~400行 |
| `app/core/llm.py` | **扩展** | +80行 |
| `app/api/chat.py` | **简化重写** | 从719行→~300行 |
| `app/core/intent.py` | **删除** | -89行 |
| `frontend/src/pages/Chat.jsx` | **适配** | +100行 |
| `frontend/src/components/ToolCallCard.jsx` | **新建** | ~80行 |
| 其他文件（models/其他api/管理后台） | **不变** | 0 |

**总变更量**：新增约960行，删除约89行，修改约200行。改动集中在核心对话链路，不影响管理后台和数据模型。

---

## 九、风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| 模型不支持Function Calling | 低 | 高 | Qwen2.5/DeepSeek-V3均支持；备选：用prompt模拟工具调用 |
| Agent循环死循环 | 中 | 中 | MAX_ITERATIONS=10 硬限制 + token预算 |
| 工具调用延迟叠加 | 中 | 中 | 并行执行独立工具 + 结果缓存 + 流式展示过程 |
| Function Calling准确率不足 | 中 | 中 | 工具描述优化 + few-shot示例 + 降级回退 |
| 多步任务结果一致性 | 低 | 低 | 同一对话共享上下文 + 结果校验 |

---

## 十、总结

本方案将当前系统从**管道式LLM应用**升级为**真正的Tool-Use Agent架构**：

1. **核心改变**：去掉硬编码的意图分类路由，让LLM通过Function Calling自主决策调用什么工具
2. **新增能力**：多步任务串联、自主推理、错误自修复、上下文引用
3. **复用现有**：所有业务逻辑（NL2SQL、RAG、模板生成等）只需封装为Tool，不需要重写
4. **改动可控**：核心改动集中在对话链路（agent.py + tools.py + chat.py），管理后台/数据模型/知识库流水线完全不变
5. **预计工期**：10天（5个阶段）
6. **降级保证**：LLM不可用时仍可回退到关键词匹配模式

这才是一个真正的"智能体"应该有的样子。
