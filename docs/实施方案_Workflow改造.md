# Workflow 工作流改造实施方案

> 目标：将 Agent 引擎从"模型自主决策调用工具"改为"代码驱动工具调用"，彻底解决本地弱模型不遵循 `<tool_call>` 格式的问题。

---

## 一、问题背景

### 1.1 当前状态

系统先后经历了两种工具调用模式：

| 版本 | 模式 | 问题 |
|------|------|------|
| v1 | 原生 Function Calling | 本地模型不支持 `tools` 参数，工具无法触发 |
| v2 | ReAct Prompt 模拟 | Prompt 要求模型输出 `<tool_call>` 标签，但模型不遵循，直接编造答案 |

**根本原因**：无论 Function Calling 还是 ReAct，都依赖模型"自主决定"何时调用工具、调用哪个工具、传什么参数。本地 Qwen2.5 模型在这种开放式决策上能力不足。

### 1.2 典型失败场景

```
用户：第三党支部有多少预备党员？
期望：模型输出 <tool_call>{"name":"query_members","arguments":{"query":"第三党支部的预备党员"}}</tool_call>
实际：模型直接编造回答"第三党支部共有预备党员2人"（数据是假的）
```

### 1.3 Workflow 方案的核心思路

**不再让模型决定调用什么工具** → 改为 **代码根据意图确定性地执行预定义工作流**。

模型只需完成两个简单任务：
1. **意图分类**：从固定选项中选一个（分类比生成格式简单得多）
2. **生成回复**：基于工具返回的真实数据，用自然语言总结

```
用户输入
  → [Step 1] 意图识别（关键词优先 + LLM兜底）
  → [Step 2] 参数提取（正则 + 关键词提取）
  → [Step 3] 匹配 Workflow → 代码确定性调用工具
  → [Step 4] LLM 基于真实数据生成回复
```

---

## 二、架构对比

### 2.1 ReAct 模式（当前，有问题）

```
用户输入 → LLM（决定是否调用工具 + 选工具 + 生成参数 + 输出格式化标签）
                ↓ 解析 <tool_call>
           执行工具 → 结果返回 LLM → LLM 决定下一步...
```

**问题**：模型需要同时完成"决策 + 格式化输出"，弱模型做不到。

### 2.2 Workflow 模式（新方案）

```
用户输入 → 意图识别（关键词/LLM分类）
              ↓
         Workflow 路由表（代码 switch-case）
              ↓
         参数提取（正则/关键词/简单LLM提取）
              ↓
         确定性调用工具（代码直接调用 handler）
              ↓
         LLM 总结回复（给模型真实数据，让它组织语言）
```

**优势**：每一步对模型的要求都很简单，弱模型也能胜任。

### 2.3 详细对比

| 维度 | ReAct | Workflow |
|------|-------|---------|
| 工具调用决策 | 模型自主决定 | 代码确定性驱动 |
| 对模型能力要求 | 高（需遵循特定输出格式） | 低（只需分类 + 总结） |
| 多步串联 | 模型自主串联（不稳定） | 代码预定义流程（稳定） |
| 新工具扩展 | 只改 Prompt | 需新增 Workflow 定义 |
| 灵活性 | 高（适合强模型） | 中（覆盖已知场景） |
| 稳定性 | 低（弱模型） | 高 |
| 未知意图处理 | 模型兜底 | 降级为普通对话 |

---

## 三、改造范围

### 3.1 需要修改/新增的文件

| 文件 | 改动内容 | 预计改动量 |
|------|----------|-----------|
| `core/intent.py` | 增强意图识别 + 新增参数提取函数 | ~80 行新增 |
| `core/agent.py` | 新增 `WorkflowEngine` 类 | ~200 行新增 |
| `config.py` | `TOOL_CALL_MODE` 新增 `"workflow"` 选项 | 1 行改注释 |

### 3.2 完全不改的文件

| 文件 | 不改原因 |
|------|----------|
| `core/tools.py` | 所有 handler 函数接口不变，直接复用 |
| `core/llm.py` | `chat()`, `chat_json()`, `chat_stream()` 直接复用 |
| `core/nl2sql.py` | `query_members` 内部调用，不受影响 |
| `core/rag.py` | `check_compliance` 内部调用，不受影响 |
| `core/search.py` | 纯检索逻辑 |
| `core/template_gen.py` | 纯生成逻辑 |
| `core/diff_engine.py` | 纯对比逻辑 |
| `api/chat_agent.py` | `agent.run()` / `agent.run_stream()` 接口保持兼容 |
| `frontend/src/**` | SSE 事件格式不变 |

---

## 四、详细技术方案

### 4.1 意图识别增强（intent.py）

当前意图识别已有 7 个类别，但需要增强：

#### 4.1.1 增加细分意图

```python
INTENT_WORKFLOW_MAP = {
    # 意图 → 对应的 Workflow 名称
    "member_query":       "wf_query_members",       # 党员查询
    "member_detail":      "wf_member_detail",        # 党员详情（新增细分）
    "member_stats":       "wf_statistics",           # 统计分析
    "policy_qa":          "wf_search_policy",        # 政策检索
    "compliance_check":   "wf_check_compliance",     # 合规判断
    "template_generate":  "wf_generate_document",    # 文档生成（多步）
    "file_diff":          "wf_compare_texts",        # 文本对比
    "export_file":        "wf_export",               # 文件导出
    "general_chat":       None,                       # 不调用工具，直接对话
}
```

#### 4.1.2 增强关键词匹配

关键词匹配作为**主要方式**（不依赖 LLM），LLM 作为补充：

```python
def classify_intent_by_keywords(user_input: str) -> Dict:
    """增强版关键词匹配 — 覆盖更多表达"""
    text = user_input

    # === 优先级从高到低 ===

    # 1. 文档生成（最明确的意图）
    if any(kw in text for kw in ["写一份", "生成", "起草", "拟一份", "帮我写", "撰写", "草拟"]):
        return {"intent": "template_generate", "confidence": 0.85}

    # 2. 合规判断
    if any(kw in text for kw in ["能否", "是否满足", "是否符合", "合规", "能不能", "可以吗", "符不符合", "够不够"]):
        return {"intent": "compliance_check", "confidence": 0.85}

    # 3. 导出
    if any(kw in text for kw in ["导出", "下载", "生成Excel", "生成Word", "导出PDF"]):
        return {"intent": "export_file", "confidence": 0.85}

    # 4. 文件对比
    if any(kw in text for kw in ["对比", "差异", "不同", "区别", "变更", "比较"]):
        return {"intent": "file_diff", "confidence": 0.85}

    # 5. 统计分析（"多少"容易和查询混淆，需特殊处理）
    if any(kw in text for kw in ["统计", "分布", "占比", "柱状图", "饼图"]):
        return {"intent": "member_stats", "confidence": 0.85}
    # "多少人/多少个" + 支部/党员 → 统计
    if ("多少" in text) and any(kw in text for kw in ["支部", "部门", "各"]):
        return {"intent": "member_stats", "confidence": 0.8}

    # 6. 查某人详情
    # 模式："查一下张三"、"张三的信息"、"张三是谁"
    if any(kw in text for kw in ["详细信息", "详情", "画像", "是谁"]):
        return {"intent": "member_detail", "confidence": 0.8}

    # 7. 党员查询（范围查询）
    if any(kw in text for kw in ["查询", "查一下", "哪些", "名单", "列表", "预备党员",
                                   "正式党员", "多少", "有几个"]):
        return {"intent": "member_query", "confidence": 0.8}

    # 8. 政策咨询
    if any(kw in text for kw in ["政策", "规定", "标准", "流程", "党费", "党章",
                                   "细则", "条例", "制度", "规章", "怎么办"]):
        return {"intent": "policy_qa", "confidence": 0.8}

    # 9. 兜底 — 通用对话
    return {"intent": "general_chat", "confidence": 0.5}
```

#### 4.1.3 新增参数提取函数

每种意图有对应的参数提取逻辑，**以正则和规则为主，不依赖 LLM**：

```python
import re

def extract_params(intent: str, user_input: str) -> dict:
    """根据意图从用户输入中提取工具参数"""
    extractors = {
        "member_query":      _extract_query_params,
        "member_detail":     _extract_detail_params,
        "member_stats":      _extract_stats_params,
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


def _extract_query_params(text: str) -> dict:
    """提取党员查询参数"""
    # 直接把用户原文作为 NL2SQL 的输入（NL2SQL 内部会处理）
    return {"query": text}


def _extract_detail_params(text: str) -> dict:
    """提取党员详情参数 — 需要提取姓名"""
    # 尝试提取中文姓名（2-4个字）
    # 常见模式：查一下张三、张三的信息、查询李四详情
    # 排除常见非姓名词
    exclude = {"党员", "信息", "详情", "详细", "支部", "查询", "查一下", "帮我", "请"}
    # 提取2-4字中文词
    names = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
    for name in names:
        if name not in exclude and not any(kw in name for kw in exclude):
            return {"name": name}
    # 回退：整个输入作为query走 query_members
    return {"name": text.strip()[:10]}


def _extract_stats_params(text: str) -> dict:
    """提取统计参数"""
    if any(kw in text for kw in ["年龄", "年龄段", "年龄分布"]):
        return {"stat_type": "age"}
    if any(kw in text for kw in ["支部", "部门", "各支部"]):
        return {"stat_type": "department"}
    # 兜底：自定义统计
    return {"stat_type": "custom", "custom_query": text}


def _extract_policy_params(text: str) -> dict:
    """提取政策查询参数"""
    return {"query": text}


def _extract_compliance_params(text: str) -> dict:
    """提取合规判断参数"""
    # 合规判断比较复杂，需要 person_info 和 requirement
    # 简单策略：整句作为 requirement，person_info 尝试从上下文提取
    return {"person_info": "", "requirement": text}


def _extract_template_params(text: str) -> dict:
    """提取文档生成参数"""
    # 文档生成是多步流程，第一步只需要触发 list_templates
    # 后续参数在交互中逐步收集
    fields = {}
    # 尝试提取年度
    year_match = re.search(r'(20\d{2})\s*年', text)
    if year_match:
        fields["年度"] = year_match.group(1)
    # 尝试提取部门
    dept_patterns = ["机关党委", "第一党支部", "第二党支部", "第三党支部"]
    for dept in dept_patterns:
        if dept in text:
            fields["部门名称"] = dept
            break
    return {"fields": fields, "user_input": text}


def _extract_diff_params(text: str) -> dict:
    """提取文本对比参数"""
    # 文本对比通常需要用户粘贴两段文本，这里先返回空
    return {"text1": "", "text2": "", "user_input": text}


def _extract_export_params(text: str) -> dict:
    """提取导出参数"""
    fmt = "word"
    if any(kw in text for kw in ["excel", "表格", "xlsx"]):
        fmt = "excel"
    elif any(kw in text for kw in ["pdf"]):
        fmt = "pdf"
    return {"format": fmt, "user_input": text}
```

### 4.2 Workflow 定义与执行（agent.py 新增）

#### 4.2.1 Workflow 路由表

```python
# 意图 → Workflow 函数映射
WORKFLOW_REGISTRY = {
    "member_query":      workflow_query_members,
    "member_detail":     workflow_member_detail,
    "member_stats":      workflow_statistics,
    "policy_qa":         workflow_search_policy,
    "compliance_check":  workflow_check_compliance,
    "template_generate": workflow_generate_document,
    "file_diff":         workflow_compare_texts,
    "export_file":       workflow_export,
}
```

#### 4.2.2 各 Workflow 实现

每个 Workflow 是一个异步函数，接收参数、执行工具、返回结果：

```python
async def workflow_query_members(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    党员查询工作流
    流程：直接调用 query_members 工具
    """
    query = params.get("query", "")
    result = await tool_registry.execute("query_members", {"query": query}, db=db)
    return WorkflowResult(
        tool_calls=[{"tool": "query_members", "args": {"query": query}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def workflow_member_detail(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    党员详情工作流
    流程：调用 get_member_detail 工具
    """
    name = params.get("name", "")
    result = await tool_registry.execute("get_member_detail", {"name": name}, db=db)
    # 如果精确查找失败，回退到 query_members
    if not result.success:
        result = await tool_registry.execute("query_members", {"query": f"查询{name}的信息"}, db=db)
    return WorkflowResult(
        tool_calls=[{"tool": "get_member_detail", "args": {"name": name}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def workflow_statistics(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    统计分析工作流
    流程：调用 get_statistics 工具
    """
    stat_type = params.get("stat_type", "department")
    custom_query = params.get("custom_query")
    args = {"stat_type": stat_type}
    if custom_query:
        args["custom_query"] = custom_query
    result = await tool_registry.execute("get_statistics", args, db=db)
    return WorkflowResult(
        tool_calls=[{"tool": "get_statistics", "args": args, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def workflow_search_policy(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    政策检索工作流
    流程：调用 search_policy 工具
    """
    query = params.get("query", "")
    result = await tool_registry.execute("search_policy", {"query": query}, db=db)
    return WorkflowResult(
        tool_calls=[{"tool": "search_policy", "args": {"query": query}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def workflow_check_compliance(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    合规判断工作流
    流程：
    1. 如果缺少 person_info，尝试从对话历史中提取
    2. 调用 check_compliance 工具
    """
    person_info = params.get("person_info", "")
    requirement = params.get("requirement", "")

    # 如果 person_info 为空但 requirement 包含人名，尝试先查人
    if not person_info and requirement:
        # 用 requirement 同时作为 person_info（工具内部会处理）
        person_info = requirement

    result = await tool_registry.execute("check_compliance", {
        "person_info": person_info,
        "requirement": requirement,
    }, db=db)
    return WorkflowResult(
        tool_calls=[{"tool": "check_compliance", "args": {"person_info": person_info, "requirement": requirement}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def workflow_generate_document(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    文档生成工作流（多步）
    流程：
    Step 1: list_templates → 获取模板列表
    Step 2: 用 LLM 匹配最合适的模板
    Step 3: generate_document(stage=outline) → 生成大纲
    """
    fields = params.get("fields", {})
    user_input = params.get("user_input", "")
    all_calls = []

    # Step 1: 获取模板列表
    list_result = await tool_registry.execute("list_templates", {}, db=db)
    all_calls.append({"tool": "list_templates", "args": {}, "success": list_result.success, "summary": list_result.summary})

    if not list_result.success or not list_result.data.get("templates"):
        return WorkflowResult(tool_calls=all_calls, tool_results=[list_result])

    # Step 2: 匹配模板（关键词匹配，不依赖 LLM）
    templates = list_result.data["templates"]
    template_id = _match_template(user_input, templates)

    if template_id is None:
        # 无法自动匹配，返回模板列表让用户选择
        return WorkflowResult(
            tool_calls=all_calls,
            tool_results=[list_result],
            needs_user_input="请选择要使用的模板",
        )

    # Step 3: 生成大纲
    gen_result = await tool_registry.execute("generate_document", {
        "template_id": template_id,
        "fields": fields,
        "stage": "outline",
    }, db=db)
    all_calls.append({"tool": "generate_document", "args": {"template_id": template_id, "fields": fields, "stage": "outline"}, "success": gen_result.success, "summary": gen_result.summary})

    return WorkflowResult(
        tool_calls=all_calls,
        tool_results=[list_result, gen_result],
    )


async def workflow_compare_texts(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    文本对比工作流
    注意：如果用户没有提供两段文本，需要追问
    """
    text1 = params.get("text1", "")
    text2 = params.get("text2", "")

    if not text1 or not text2:
        return WorkflowResult(
            tool_calls=[],
            tool_results=[],
            needs_user_input="请提供需要对比的两段文本",
        )

    result = await tool_registry.execute("compare_texts", {
        "text1": text1,
        "text2": text2,
    }, db=db)
    return WorkflowResult(
        tool_calls=[{"tool": "compare_texts", "args": {"text1": "...", "text2": "..."}, "success": result.success, "summary": result.summary}],
        tool_results=[result],
    )


async def workflow_export(params: dict, tool_registry, db, **ctx) -> WorkflowResult:
    """
    文件导出工作流
    注意：导出通常需要先有内容（来自前一步的查询/生成），
    如果缺少内容则提示用户
    """
    fmt = params.get("format", "word")
    return WorkflowResult(
        tool_calls=[],
        tool_results=[],
        needs_user_input=f"请先查询数据或生成文档，再进行{fmt.upper()}导出",
    )
```

#### 4.2.3 模板匹配辅助函数

```python
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
        # 直接匹配模板名
        if tname in user_input:
            score = 10
        else:
            # 关键词匹配
            for key, keywords in keyword_map.items():
                if key in tname:
                    for kw in keywords:
                        if kw in user_input:
                            score = max(score, 5)
        if score > best_score:
            best_score = score
            best_match = template["id"]

    return best_match if best_score > 0 else (templates[0]["id"] if len(templates) == 1 else None)
```

### 4.3 WorkflowEngine 类

新增 `WorkflowEngine`，保持与 `AgentEngine` 相同的 `run()` / `run_stream()` 接口：

```python
@dataclass
class WorkflowResult:
    """Workflow 执行结果"""
    tool_calls: List[Dict] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    needs_user_input: str = ""  # 非空时表示需要用户补充信息


class WorkflowEngine:
    """Workflow 驱动的 Agent 引擎"""

    def __init__(self, llm_service, tool_registry: ToolRegistry):
        self.llm = llm_service
        self.tools = tool_registry

    async def run(self, user_message: str, conversation_history=None, db=None) -> AgentResult:
        """
        非流式 Workflow 执行：
        1. 意图识别
        2. 参数提取
        3. 执行 Workflow
        4. LLM 基于工具结果生成回复
        """
        # Step 1: 意图识别（关键词优先）
        intent_result = classify_intent_by_keywords(user_message)
        if intent_result["confidence"] < 0.7:
            # 关键词不确定时用 LLM 补充
            intent_result = await classify_intent(user_message)
        intent = intent_result["intent"]
        logger.info(f"Workflow意图识别: '{user_message[:50]}' -> {intent}")

        # Step 2: 通用对话直接回复
        if intent == "general_chat":
            return await self._direct_chat(user_message, conversation_history)

        # Step 3: 参数提取
        params = extract_params(intent, user_message)
        logger.info(f"Workflow参数提取: {params}")

        # Step 4: 执行 Workflow
        workflow_fn = WORKFLOW_REGISTRY.get(intent)
        if not workflow_fn:
            return await self._direct_chat(user_message, conversation_history)

        wf_result = await workflow_fn(params, self.tools, db)

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
            tool_data_text += f"\n工具返回: {tr.summary}\n数据: {json.dumps(tr.data, ensure_ascii=False, default=str)[:2000]}\n"

        reply = await self._generate_reply(user_message, tool_data_text, conversation_history)

        return AgentResult(
            reply=reply,
            tool_calls=wf_result.tool_calls,
            structured_data=structured_data,
        )

    async def _direct_chat(self, user_message, conversation_history) -> AgentResult:
        """通用对话（不调用工具）"""
        messages = [{"role": "system", "content": WORKFLOW_SYSTEM_PROMPT}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        reply = await self.llm.chat(messages)
        return AgentResult(reply=reply)

    async def _generate_reply(self, user_message, tool_data_text, conversation_history) -> str:
        """基于工具结果让 LLM 生成自然语言回复"""
        messages = [
            {"role": "system", "content": WORKFLOW_SUMMARY_PROMPT},
        ]
        if conversation_history:
            messages.extend(conversation_history[-4:])  # 只保留最近几轮
        messages.append({
            "role": "user",
            "content": f"用户问题：{user_message}\n\n以下是系统查询到的真实数据：\n{tool_data_text}\n\n请基于以上真实数据回答用户问题，不要编造数据。如果数据为空，请如实告知。",
        })
        return await self.llm.chat(messages)

    async def run_stream(self, user_message, conversation_history=None, db=None):
        """流式版本 — 与 AgentEngine.run_stream() 接口兼容"""
        # ... 实现与 run() 类似，但用 yield AgentStreamEvent 推送过程
        pass
```

### 4.4 System Prompt（大幅简化）

Workflow 模式下，System Prompt 不再需要工具调用格式说明：

```python
WORKFLOW_SYSTEM_PROMPT = """你是「党政工作智脑」，一个专业的党务工作AI智能助手，服务于机关党委。
你可以帮助用户查询党员信息、检索政策法规、生成公文文档、进行统计分析等。
回答问题时要准确、简洁、专业。"""

WORKFLOW_SUMMARY_PROMPT = """你是「党政工作智脑」，请根据系统提供的真实数据回答用户问题。

规则：
1. 只使用系统提供的数据，绝不编造
2. 用简洁的文字总结关键信息
3. 如果是表格数据，简要说明查询结果（数量、关键特征），不要重复列出所有数据
4. 如果数据为空，如实告知"未查询到相关数据"
5. 语气专业友好"""
```

### 4.5 配置切换

`config.py` 中 `TOOL_CALL_MODE` 支持三种模式：

```python
# 工具调用模式
# "native"   = 使用模型原生 Function Calling（OpenAI 兼容）
# "prompt"   = 使用 Prompt 模拟（ReAct，兼容所有模型）
# "workflow"  = 使用 Workflow 驱动（最稳定，适合弱模型）
TOOL_CALL_MODE: str = "workflow"
```

`agent.py` 中根据配置选择引擎：

```python
def create_agent_engine(llm_service, tool_registry):
    mode = settings.TOOL_CALL_MODE
    if mode == "workflow":
        return WorkflowEngine(llm_service, tool_registry)
    else:
        return AgentEngine(llm_service, tool_registry)
```

---

## 五、9 个工具在 Workflow 模式下的工作流程

### 5.1 query_members（党员查询）

```
意图: member_query
参数提取: {"query": 用户原文}  ← 直接把原文传给 NL2SQL
工具调用: query_members(query=用户原文)
LLM总结: 基于查询结果生成回复
```

**示例**：
```
用户: 第三党支部有多少预备党员？
→ 意图: member_query (关键词匹配: "预备党员")
→ 参数: {"query": "第三党支部有多少预备党员？"}
→ 工具: query_members → NL2SQL → 执行SQL → 返回2条记录
→ LLM: "第三党支部共有2名预备党员，分别是..."
```

### 5.2 get_member_detail（党员详情）

```
意图: member_detail
参数提取: {"name": "张三"}  ← 正则提取姓名
工具调用: get_member_detail(name="张三")
LLM总结: 基于详情生成回复
```

### 5.3 get_statistics（统计分析）

```
意图: member_stats
参数提取: {"stat_type": "department" | "age" | "custom"}  ← 关键词判断
工具调用: get_statistics(stat_type=...)
LLM总结: 基于统计数据生成回复
```

### 5.4 search_policy（政策检索）

```
意图: policy_qa
参数提取: {"query": 用户原文}
工具调用: search_policy(query=用户原文)
LLM总结: 基于检索到的政策条款回答
```

### 5.5 check_compliance（合规判断）

```
意图: compliance_check
参数提取: {"person_info": 提取的人员信息, "requirement": 用户原文}
工具调用: check_compliance(person_info=..., requirement=...)
LLM总结: 基于合规判断结果回复
```

### 5.6 list_templates + generate_document（文档生成，多步）

```
意图: template_generate
参数提取: {"fields": {"年度": "2026", ...}, "user_input": 原文}
工具调用:
  Step 1: list_templates() → 获取模板列表
  Step 2: _match_template() → 代码匹配模板
  Step 3: generate_document(template_id=X, fields=..., stage="outline")
LLM总结: "已为您生成大纲，请确认后生成全文"
```

### 5.7 compare_texts（文本对比）

```
意图: file_diff
参数提取: {"text1": ..., "text2": ...}
→ 如果用户没提供文本，返回追问
工具调用: compare_texts(text1=..., text2=...)
LLM总结: 基于对比结果回复
```

### 5.8 export_file（文件导出）

```
意图: export_file
参数提取: {"format": "word" | "excel" | "pdf"}
→ 需要先有内容，通常在多轮对话中
工具调用: export_file(format=..., title=..., content=...)
```

---

## 六、多步串联场景处理

Workflow 模式下，多步串联由代码显式编排，不依赖模型自主决策：

| 场景 | Workflow 处理方式 |
|------|------------------|
| "帮我写一份年度工作计划" | `workflow_generate_document` 内部：list_templates → 匹配模板 → generate_document(outline) |
| "查完预备党员再判断能否转正" | 目前作为单次查询处理。如需自动串联，可在 member_query 返回后检测后续意图 |
| "统计各支部人数并导出Excel" | 目前作为统计处理。导出需用户在下一轮触发 |

**设计决策**：对于"A然后B"的复合请求：
- **方案A（简单，推荐）**：先完成A，在回复中引导用户继续操作B
- **方案B（复杂，可选）**：在意图识别层检测"并且/然后"连接词，拆分为多个 Workflow 顺序执行

初期采用方案A，稳定后可升级为方案B。

---

## 七、对话历史中的上下文继承

### 7.1 问题

Workflow 模式每次都是独立的"意图→工具→回复"流程，但用户可能有上下文依赖：

```
用户: 查一下第三支部的预备党员
AI: 第三支部共有2名预备党员：张三、李四
用户: 帮我判断张三能否转正
→ 这里"张三"的信息来自上一轮
```

### 7.2 方案

在 `_generate_reply()` 中传入对话历史，LLM 自然会参考上下文。同时，对于合规判断等需要 person_info 的场景，可以从对话历史中提取：

```python
async def _enrich_params_from_history(self, intent, params, conversation_history):
    """从对话历史中补充缺失参数"""
    if intent == "compliance_check" and not params.get("person_info"):
        # 从最近的工具结果中提取人员信息
        for msg in reversed(conversation_history or []):
            if msg["role"] == "assistant" and "党员" in msg.get("content", ""):
                params["person_info"] = msg["content"][:500]
                break
    return params
```

---

## 八、流式输出兼容

`WorkflowEngine.run_stream()` 需要与 `AgentEngine.run_stream()` 产出相同的 `AgentStreamEvent` 格式：

```python
async def run_stream(self, user_message, conversation_history=None, db=None):
    # 1. 通知前端：正在识别意图
    yield AgentStreamEvent(type="thinking", data={"message": "正在分析您的问题..."})

    intent_result = classify_intent_by_keywords(user_message)
    intent = intent_result["intent"]

    # 2. 通用对话
    if intent == "general_chat":
        messages = [...]
        async for chunk in self.llm.chat_stream(messages):
            yield AgentStreamEvent(type="content", data={"text": chunk})
        yield AgentStreamEvent(type="done", data={})
        return

    # 3. 参数提取
    params = extract_params(intent, user_message)

    # 4. 执行 Workflow（通知前端工具调用）
    workflow_fn = WORKFLOW_REGISTRY.get(intent)
    # ... 执行工具，yield tool_calling / tool_result 事件

    # 5. 流式生成回复
    async for chunk in self.llm.chat_stream(summary_messages):
        yield AgentStreamEvent(type="content", data={"text": chunk})
    yield AgentStreamEvent(type="done", data={})
```

---

## 九、风险评估

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| 意图识别错误 | 中 | 调用了错误的工具 | 关键词优先 + LLM补充 + 结果为空时降级重试 |
| 参数提取不完整 | 低 | 工具执行可能报错或结果不准 | 大部分工具接受原文作为参数（如 NL2SQL），容错性好 |
| 复合意图无法处理 | 中 | 只处理了第一个意图 | 引导用户分步操作，后续可升级 |
| 模板匹配不准 | 低 | 选错模板 | 返回模板列表让用户选择 |
| LLM 总结回复质量差 | 低 | 回复不够好 | 给 LLM 清晰的数据和指令，这是弱模型最擅长的任务 |

---

## 十、回滚方案

三种模式完全独立，通过 `TOOL_CALL_MODE` 配置切换：

- `"native"` → 原生 Function Calling
- `"prompt"` → ReAct Prompt 模拟
- `"workflow"` → Workflow 工作流驱动

回滚只需修改 `.env` 中的 `TOOL_CALL_MODE` 值，无需改代码。

---

## 十一、实施步骤

### 步骤 1: 增强 intent.py（~30分钟）
- 增强关键词匹配覆盖面
- 新增 `member_detail` 意图
- 新增 `extract_params()` 参数提取函数族
- 保留原有 LLM 意图识别作为补充

### 步骤 2: 新增 WorkflowEngine（~40分钟）
- 在 `agent.py` 中新增 `WorkflowResult` 数据类
- 新增 `WorkflowEngine` 类（`run()` + `run_stream()`）
- 实现 8 个 Workflow 函数
- 新增模板匹配辅助函数
- 新增 `WORKFLOW_SYSTEM_PROMPT` 和 `WORKFLOW_SUMMARY_PROMPT`

### 步骤 3: 配置集成（~5分钟）
- `config.py` 注释更新
- `agent.py` 中 `create_agent_engine()` 支持 workflow 模式

### 步骤 4: 测试验证（~30分钟）
1. ✅ 普通问候 → general_chat → 直接回复
2. ✅ "第三党支部有多少预备党员" → member_query → query_members
3. ✅ "查一下张三" → member_detail → get_member_detail
4. ✅ "各支部人数统计" → member_stats → get_statistics
5. ✅ "党费缴纳标准" → policy_qa → search_policy
6. ✅ "帮我写一份工作计划" → template_generate → list_templates → generate_document
7. ✅ 合规判断场景
8. ✅ 流式 SSE 输出

### 预计总时间：约 1.5 小时

---

## 十二、后续优化方向

1. **复合意图拆分**：识别"并且/然后"等连接词，拆分为多个 Workflow 顺序执行
2. **参数提取增强**：对复杂场景（如合规判断）使用专门的 LLM 提取 prompt
3. **Workflow 可配置化**：将 Workflow 定义抽到配置文件，支持不改代码新增 Workflow
4. **意图置信度阈值**：低于阈值时追问用户确认意图
5. **对话状态管理**：记住当前 Workflow 进行到哪一步，支持多轮补充参数
