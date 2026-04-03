# ReAct Prompt 改造实施方案

> 目标：将 Agent 引擎从依赖 OpenAI Function Calling 协议改为 Prompt 模拟工具调用，兼容所有不支持 Function Calling 的本地模型。

---

## 一、问题背景

当前系统的 Agent 引擎（`agent.py`）通过 OpenAI 的 `tools` + `tool_choice` 参数实现工具调用，但用户本地部署的模型（如通过 llama.cpp / vLLM / Ollama 部署的 Qwen2.5）不支持 Function Calling 协议，导致工具无法被真正执行，模型只能"假装"调用工具并编造结果。

## 二、改造范围

### 2.1 需要修改的文件（仅 2 个）

| 文件 | 改动内容 | 预计改动量 |
|------|----------|-----------|
| `backend/app/core/llm.py` | 新增 `chat_with_tools_prompt()` 方法 | +70 行 |
| `backend/app/core/agent.py` | 替换调用方式，修改消息格式，更新 System Prompt | ~100 行修改 |

### 2.2 完全不改的文件

| 模块 | 文件 | 不改的原因 |
|------|------|-----------|
| 工具实现 | `core/tools.py` | `ToolRegistry.execute()` 接口不变 |
| API 路由 | `api/chat_agent.py` | 调用的是 `AgentEngine.run()`，接口不变 |
| NL2SQL | `core/nl2sql.py` | 使用 `llm.chat_json()`，不涉及 tools |
| RAG 检索 | `core/rag.py` | 使用 `llm.chat()` / `llm.chat_json()` |
| 政策检索 | `core/search.py` | 纯检索逻辑，不调用 LLM |
| 模板生成 | `core/template_gen.py` | 使用 `llm.chat()` / `llm.chat_json()` |
| 差异对比 | `core/diff_engine.py` | 使用 `llm.chat_json()` |
| 意图识别 | `core/intent.py` | 使用 `llm.chat_json()`（当前未在 Agent 模式中使用） |
| 数据模型 | `models/*.py` | 纯数据库模型 |
| 前端全部 | `frontend/src/**` | SSE 事件格式保持不变 |

---

## 三、9 个工具功能验证

逐一分析每个工具在 ReAct Prompt 模式下是否能正常工作：

### 3.1 query_members（党员查询）

- **调用方式**：Agent 输出 `<tool_call>{"name":"query_members","arguments":{"query":"第三支部的预备党员"}}</tool_call>`
- **执行流程**：代码解析 → `handle_query_members()` → NL2SQL → 执行 SQL → 返回结构化数据
- **兼容性**：✅ 完全兼容。工具内部用 `llm.chat_json()` 做 NL2SQL，不涉及 Function Calling
- **降级兜底**：LLM NL2SQL 失败时有 `_fallback_member_query()` 关键词匹配

### 3.2 search_policy（政策检索）

- **调用方式**：`<tool_call>{"name":"search_policy","arguments":{"query":"党费缴纳标准"}}</tool_call>`
- **执行流程**：代码解析 → `handle_search_policy()` → Milvus 向量检索 / SQLite 关键词检索
- **兼容性**：✅ 完全兼容。检索逻辑不涉及 LLM 的 Function Calling
- **降级兜底**：Milvus 不可用时回退到 SQLite 关键词检索

### 3.3 check_compliance（合规判断）

- **调用方式**：`<tool_call>{"name":"check_compliance","arguments":{"person_info":"李四，22岁...","requirement":"能否确定为入党积极分子"}}</tool_call>`
- **执行流程**：代码解析 → 检索相关条款 → `rag.check_compliance()` → LLM 逐条对照判断
- **兼容性**：✅ 完全兼容。内部用 `llm.chat_json()` 做合规判断
- **注意点**：参数较复杂（person_info + requirement），需要在 Prompt 中给出清晰的示例

### 3.4 list_templates（模板列表）

- **调用方式**：`<tool_call>{"name":"list_templates","arguments":{}}</tool_call>`
- **执行流程**：代码解析 → 直接查数据库 → 返回模板列表
- **兼容性**：✅ 完全兼容。无参数，最简单的工具

### 3.5 generate_document（文档生成）

- **调用方式**：`<tool_call>{"name":"generate_document","arguments":{"template_id":1,"fields":{"年度":"2026","部门名称":"机关党委"},"stage":"outline"}}</tool_call>`
- **执行流程**：代码解析 → 查模板 → `template_gen.generate_outline/full/modify()` → LLM 生成
- **兼容性**：✅ 完全兼容。内部用 `llm.chat()` 生成文档
- **注意点**：参数结构较深（fields 是嵌套对象），需要验证 LLM 能否正确输出嵌套 JSON
- **多步串联**：Agent 需要先调 `list_templates` 获取 template_id，再调 `generate_document`。ReAct 模式天然支持这种多步流程

### 3.6 get_statistics（统计分析）

- **调用方式**：`<tool_call>{"name":"get_statistics","arguments":{"stat_type":"department"}}</tool_call>`
- **执行流程**：代码解析 → 直接 SQL 查询 → 返回统计数据
- **兼容性**：✅ 完全兼容

### 3.7 get_member_detail（党员详情）

- **调用方式**：`<tool_call>{"name":"get_member_detail","arguments":{"name":"张三"}}</tool_call>`
- **执行流程**：代码解析 → 数据库精确/模糊查询 → 返回画像数据
- **兼容性**：✅ 完全兼容

### 3.8 export_file（文件导出）

- **调用方式**：`<tool_call>{"name":"export_file","arguments":{"format":"word","title":"年度工作计划","content":"..."}}</tool_call>`
- **执行流程**：代码解析 → 构造导出标记 → 前端触发下载
- **兼容性**：✅ 完全兼容
- **注意点**：content 参数可能很长（整篇文档），但这在 ReAct 模式中 Agent 通常会在上一步 generate_document 拿到内容后传递

### 3.9 compare_texts（文本差异）

- **调用方式**：`<tool_call>{"name":"compare_texts","arguments":{"text1":"旧版内容...","text2":"新版内容...","name1":"2024版","name2":"2026版"}}</tool_call>`
- **执行流程**：代码解析 → difflib 差异计算 → LLM 语义分析
- **兼容性**：✅ 完全兼容。内部用 `llm.chat_json()` 做语义分析
- **注意点**：text1/text2 可能很长，但工具内部会截断处理（最多 20 处差异，每处 200 字符）

### 3.10 多步串联场景验证

| 场景 | 工具调用链 | ReAct 兼容性 |
|------|-----------|-------------|
| "帮我写一份年度工作计划" | list_templates → generate_document(outline) | ✅ LLM 先调 list_templates 获取 ID，再调 generate_document |
| "查完预备党员再判断能否转正" | query_members → check_compliance | ✅ 第一步返回人员信息，LLM 在第二步传入 person_info |
| "统计各支部人数并导出Excel" | get_statistics → export_file | ✅ 第一步返回数据，LLM 在第二步传入 columns/rows |
| "查张三的详细信息" | get_member_detail | ✅ 单步调用 |
| "查政策：党费缴纳标准" | search_policy | ✅ 单步调用 |
| "对比两版制度差异" | compare_texts | ✅ 单步调用 |

**结论：所有 9 个工具 + 所有多步串联场景在 ReAct Prompt 模式下均可正常工作。**

---

## 四、详细技术方案

### 4.1 llm.py 新增方法

```python
async def chat_with_tools_prompt(
    self,
    messages: List[Dict],
    tools: List[Dict],
    temperature: float = None,
    max_tokens: int = None,
) -> Dict:
    """
    Prompt 模拟 Function Calling（兼容不支持 tools 参数的模型）
    
    原理：
    1. 将 tools 的 JSON Schema 转为人类可读的文本描述
    2. 注入到 System Prompt 末尾，要求 LLM 用 <tool_call> 标签输出工具调用
    3. 从 LLM 输出中正则解析 <tool_call> 标签
    4. 返回与 chat_with_tools() 相同格式的字典
    
    返回格式：
    - 有工具调用：{"content": "思考内容", "tool_calls": [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}]}
    - 无工具调用：{"content": "回复内容"}
    """
```

**关键设计点：**

1. **工具描述格式**：将 JSON Schema 转为简洁的文本表格
2. **<tool_call> 标签**：选用 XML 标签而非纯 JSON，因为 XML 标签更容易用正则精确提取，不会与回复内容中的 JSON 混淆
3. **<think> 过滤**：模型输出的 `<think>...</think>` 思考过程需要剥离，不作为回复内容
4. **JSON 修复**：常见问题如尾逗号、单引号等自动修复
5. **tool_call_id 生成**：使用 `f"call_{uuid4().hex[:8]}"` 生成，保持与原格式兼容

### 4.2 agent.py 修改

#### 4.2.1 System Prompt 追加工具格式说明

在现有 `AGENT_SYSTEM_PROMPT` 末尾追加：

```
## 工具调用格式

当你需要调用工具时，请严格按以下格式输出，不要添加任何其他内容：

<tool_call>
{"name": "工具名称", "arguments": {"参数1": "值1", "参数2": "值2"}}
</tool_call>

每次只调用一个工具。调用后请等待工具返回结果，再决定下一步操作。
如果不需要调用工具，直接用自然语言回复用户，不要输出 <tool_call> 标签。

### 示例

用户：帮我写一份年度工作计划
助手思考：需要先查看可用模板 →
<tool_call>
{"name": "list_templates", "arguments": {}}
</tool_call>

[工具返回模板列表后]
助手思考：选择"年度工作计划"模板，生成大纲 →
<tool_call>
{"name": "generate_document", "arguments": {"template_id": 1, "fields": {"年度": "2026"}, "stage": "outline"}}
</tool_call>
```

#### 4.2.2 消息格式调整

**改前（Function Calling 协议）：**
```python
# assistant 消息带 tool_calls 对象
messages.append({"role": "assistant", "content": None, "tool_calls": [...]})
# 工具结果用 tool role
messages.append({"role": "tool", "tool_call_id": "xxx", "content": "..."})
```

**改后（Prompt 模拟）：**
```python
# assistant 消息是普通文本（包含 <tool_call> 标签）
messages.append({"role": "assistant", "content": "<tool_call>...</tool_call>"})
# 工具结果用 user role 包装
messages.append({"role": "user", "content": "[工具 query_members 执行结果]\n{...}"})
```

#### 4.2.3 循环逻辑

```
while iteration < MAX_ITERATIONS:
    1. 调用 llm.chat_with_tools_prompt(messages, tools)
    2. 返回值中有 tool_calls？
       - 是：将 assistant 消息加入 messages
              → 执行工具 → 将结果以 user role 加入 messages → continue
       - 否：返回 content 作为最终回复 → break
```

与原来逻辑完全一致，只是调用方法和消息格式不同。

### 4.3 配置项支持（可选增强）

在 `config.py` 中新增：

```python
# Function Calling 模式
# "native" = 使用模型原生 Function Calling（OpenAI 兼容）
# "prompt" = 使用 Prompt 模拟（兼容所有模型）
TOOL_CALL_MODE: str = "prompt"
```

这样未来更换支持 Function Calling 的模型时，只需改配置即可切回原生模式。

---

## 五、JSON 解析稳定性保障

这是 ReAct 方案最大的风险点，需要多层保障：

### 5.1 第一层：正则提取

```python
import re
pattern = r'<tool_call>\s*(.*?)\s*</tool_call>'
matches = re.findall(pattern, text, re.DOTALL)
```

### 5.2 第二层：JSON 修复

常见问题及修复：
- 尾逗号：`{"a": 1,}` → `{"a": 1}`
- 单引号：`{'a': 'b'}` → `{"a": "b"}`
- 未闭合括号：尝试补全
- Markdown 包裹：剥离 ```json ... ```

### 5.3 第三层：重试

JSON 解析失败时，发送一条提示消息要求 LLM 重新输出：
```
你刚才的工具调用格式有误，请严格按以下格式重新输出：
<tool_call>
{"name": "工具名", "arguments": {...}}
</tool_call>
```

### 5.4 第四层：降级

连续 2 次解析失败，则将 LLM 原始输出作为普通文本回复返回（不调用工具）。

---

## 六、<think> 标签处理

从 a.txt 可以看到模型会输出 `<think>...</think>` 包裹的思考过程。处理策略：

1. 在解析工具调用**之前**，先剥离 `<think>` 标签内容
2. `<think>` 内容不作为回复发送给用户
3. 但可以记录到日志中用于调试

```python
def strip_think_tags(text: str) -> str:
    """剥离 <think>...</think> 标签"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
```

---

## 七、实施步骤

### 步骤 1：修改 llm.py（新增方法，不动原有方法）

- 新增 `chat_with_tools_prompt()` 方法
- 新增 `_format_tools_for_prompt()` 辅助函数（将 tools JSON Schema 转文本）
- 新增 `_parse_tool_calls_from_text()` 辅助函数（正则解析 + JSON 修复）
- 新增 `_strip_think_tags()` 辅助函数
- 保留原 `chat_with_tools()` 方法不动

### 步骤 2：修改 agent.py

- 更新 `AGENT_SYSTEM_PROMPT`：追加工具调用格式说明和示例
- 修改 `AgentEngine.run()`：替换 LLM 调用方法，调整消息格式
- 修改 `AgentEngine.run_stream()`：同上
- 每轮只解析一个工具调用（简化解析难度）

### 步骤 3：修改 config.py（可选）

- 新增 `TOOL_CALL_MODE` 配置项

### 步骤 4：测试验证

测试场景清单：
1. ✅ 普通问候（不调用工具）
2. ✅ 单工具调用：查张三的信息
3. ✅ 单工具调用：统计各支部人数
4. ✅ 单工具调用：查询党费缴纳标准
5. ✅ 多步串联：写一份年度工作计划（list_templates → generate_document）
6. ✅ 多步串联：查预备党员并判断转正条件
7. ✅ 合规判断场景
8. ✅ 文本差异对比
9. ✅ 导出文件
10. ✅ 流式 SSE 输出

---

## 八、风险评估

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| LLM 输出 JSON 格式不稳定 | 中 | 工具调用失败 | 4 层解析保障 + few-shot 示例 |
| 嵌套 JSON 参数出错 | 低 | generate_document 的 fields 解析失败 | JSON 修复 + 重试 |
| 模型不遵循 <tool_call> 格式 | 低 | 工具无法被识别 | Prompt 中强化格式要求 + 降级为文本回复 |
| 多步串联中间步骤出错 | 低 | 流程中断 | 每步独立，失败不影响前面的结果 |
| <think> 标签干扰解析 | 中 | 解析出错 | 预处理时先剥离 <think> |

---

## 九、回滚方案

原 `chat_with_tools()` 方法完全保留不动。如果需要回滚：
1. 将 `agent.py` 中的调用从 `chat_with_tools_prompt()` 改回 `chat_with_tools()`
2. 恢复消息格式为 `tool` role
3. 或通过 `TOOL_CALL_MODE` 配置项切换

---

## 十、时间估计

| 步骤 | 预计时间 |
|------|---------|
| 修改 llm.py | 15 分钟 |
| 修改 agent.py | 20 分钟 |
| 测试验证 | 15 分钟 |
| **合计** | **约 50 分钟** |
