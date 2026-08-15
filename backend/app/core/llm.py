"""LLM服务封装 - 支持流式和非流式调用"""
import json
import re
from uuid import uuid4
from typing import AsyncGenerator, Optional, List, Dict

from openai import AsyncOpenAI
from loguru import logger

from app.config import settings


class LLMService:
    """大语言模型服务"""

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
        )
        self.model = settings.LLM_MODEL

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
    ) -> str:
        """非流式对话"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                stream=False,
                extra_body={"enable_thinking": False},
            )
            raw = response.choices[0].message.content or ""
            return _strip_think_tags(raw)
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
    ) -> AsyncGenerator[str, None]:
        """流式对话（自动过滤 <think> 标签内容）"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                stream=True,
            )
            # 流式过滤 <think>...</think> 标签
            in_think = False
            buffer = ""
            async for chunk in response:
                text = chunk.choices[0].delta.content
                if not text:
                    continue
                buffer += text
                # 检查是否进入 <think> 区域
                while buffer:
                    if in_think:
                        # 正在 think 区域内，寻找 </think>
                        end_idx = buffer.find("</think>")
                        if end_idx != -1:
                            # 找到闭合标签，跳过 think 内容
                            buffer = buffer[end_idx + 8:]
                            in_think = False
                        else:
                            # 还没闭合，继续等待
                            buffer = ""
                            break
                    else:
                        # 不在 think 区域，寻找 <think>
                        start_idx = buffer.find("<think>")
                        if start_idx != -1:
                            # 输出 <think> 之前的内容
                            before = buffer[:start_idx]
                            if before:
                                yield before
                            buffer = buffer[start_idx + 7:]
                            in_think = True
                        elif "<think" in buffer and not buffer.endswith(">"):
                            # 可能是 <think 标签还没接收完，暂存
                            safe_end = buffer.rfind("<")
                            if safe_end > 0:
                                yield buffer[:safe_end]
                                buffer = buffer[safe_end:]
                            break
                        else:
                            # 没有 think 标签，正常输出
                            yield buffer
                            buffer = ""
                            break
            # 输出剩余缓冲
            if buffer and not in_think:
                yield buffer
        except Exception as e:
            logger.error(f"LLM流式调用失败: {e}")
            raise

    async def chat_stream_with_thinking(
        self,
        messages: List[Dict[str, str]],
        temperature: float = None,
        max_tokens: int = None,
    ) -> AsyncGenerator[Dict, None]:
        """流式对话，同时输出思考内容和正文。
        每次 yield 一个字典：
          {"type": "thinking", "text": "..."}  — 思考文字（增量）
          {"type": "content", "text": "..."}   — 正文（增量）

        支持两种思考模式：
        1. Qwen3 原生 reasoning_content 字段（优先）
        2. <think>...</think> 文本标签（兼容兜底）
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                stream=True,
                extra_body={"enable_thinking": True},
            )
            # 标记是否检测到 reasoning_content 字段（原生模式）
            native_thinking = False
            in_think = False
            buffer = ""
            async for chunk in response:
                delta = chunk.choices[0].delta
                # 优先：Qwen3 原生 reasoning_content 字段
                reasoning = getattr(delta, 'reasoning_content', None)
                if reasoning:
                    native_thinking = True
                    yield {"type": "thinking", "text": reasoning}
                    continue
                text = delta.content
                if not text:
                    continue
                # 如果已经检测到原生 thinking，后续 content 直接输出
                if native_thinking:
                    yield {"type": "content", "text": text}
                    continue
                # 兜底：解析 <think> 文本标签
                buffer += text
                while buffer:
                    if in_think:
                        end_idx = buffer.find("</think>")
                        if end_idx != -1:
                            think_piece = buffer[:end_idx]
                            if think_piece:
                                yield {"type": "thinking", "text": think_piece}
                            buffer = buffer[end_idx + 8:]
                            in_think = False
                        else:
                            if buffer:
                                yield {"type": "thinking", "text": buffer}
                            buffer = ""
                            break
                    else:
                        start_idx = buffer.find("<think>")
                        if start_idx != -1:
                            before = buffer[:start_idx]
                            if before:
                                yield {"type": "content", "text": before}
                            buffer = buffer[start_idx + 7:]
                            in_think = True
                        elif "<think" in buffer and not buffer.endswith(">"):
                            safe_end = buffer.rfind("<")
                            if safe_end > 0:
                                yield {"type": "content", "text": buffer[:safe_end]}
                                buffer = buffer[safe_end:]
                            break
                        else:
                            yield {"type": "content", "text": buffer}
                            buffer = ""
                            break
            if buffer:
                yield_type = "thinking" if in_think else "content"
                yield {"type": yield_type, "text": buffer}
        except Exception as e:
            logger.error(f"LLM流式调用(with_thinking)失败: {e}")
            raise

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.1,
        on_thinking=None,
    ) -> dict:
        """JSON格式输出的对话（低温度确保格式稳定）"""
        if on_thinking:
            content_buf = ""
            async for piece in self.chat_stream_with_thinking(messages, temperature=temperature):
                if piece["type"] == "thinking":
                    await on_thinking(piece["text"])
                else:
                    content_buf += piece["text"]
            result = content_buf
        else:
            result = await self.chat(messages, temperature=temperature)
        # 尝试提取JSON
        try:
            # 处理可能被markdown包裹的JSON
            text = result.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text.strip())
        except json.JSONDecodeError:
            logger.warning(f"LLM输出非法JSON: {result[:200]}")
            return {"error": "解析失败", "raw": result}


    async def chat_with_tools(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float = None,
        max_tokens: int = None,
    ) -> Dict:
        """带Function Calling的调用，返回解析后的字典"""
        try:
            kwargs = dict(
                model=self.model,
                messages=messages,
                temperature=temperature or settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                stream=False,
                extra_body={"enable_thinking": False},
            )
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = await self.client.chat.completions.create(**kwargs)
            msg = response.choices[0].message

            result = {"content": msg.content or ""}
            if msg.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            return result
        except Exception as e:
            logger.error(f"LLM Function Calling调用失败: {e}")
            raise

    async def chat_with_tools_prompt(
        self,
        messages: List[Dict],
        tools: List[Dict],
        temperature: float = None,
        max_tokens: int = None,
    ) -> Dict:
        """
        Prompt 模拟 Function Calling（兼容不支持 tools 参数的模型）

        将工具定义注入 System Prompt，要求 LLM 用 <tool_call> 标签输出工具调用，
        然后从文本中解析出工具调用信息。
        返回格式与 chat_with_tools() 完全一致。
        """
        # 构建带工具描述的消息列表
        augmented_messages = _inject_tools_into_messages(messages, tools)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=augmented_messages,
                temperature=temperature or settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or settings.LLM_MAX_TOKENS,
                stream=False,
                extra_body={"enable_thinking": False},
            )
            raw_content = response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM调用失败(prompt模式): {e}")
            raise

        # 剥离 <think> 标签
        content = _strip_think_tags(raw_content)

        # 尝试解析 <tool_call> 标签
        tool_calls = _parse_tool_calls_from_text(content)

        if tool_calls:
            # 移除 <tool_call> 标签部分，剩余作为 content
            clean_content = re.sub(
                r'<tool_call>.*?</tool_call>', '', content, flags=re.DOTALL
            ).strip()
            return {"content": clean_content, "tool_calls": tool_calls}
        else:
            return {"content": content}

    def reinitialize(self, base_url: str, api_key: str, model: str):
        """运行时重新初始化LLM客户端"""
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        logger.info(f"LLM客户端已重新初始化: base_url={base_url}, model={model}")


# ========== Prompt 模拟工具调用的辅助函数 ==========

TOOL_CALL_FORMAT_INSTRUCTION = """

## 工具调用格式（极其重要，必须严格遵守）

你拥有真实的工具可以调用。当用户的请求涉及查询数据、生成文档、检索政策、合规判断等操作时，你**必须**通过工具来完成，**绝对禁止**自己编造回答。

调用工具时，**只输出**以下格式，不要输出任何其他内容：

<tool_call>
{"name": "工具名称", "arguments": {"参数1": "值1"}}
</tool_call>

**强制规则：**
1. 涉及数据、文档、政策、合规等任务时，**必须调用工具**，不能自己回答
2. 每次只输出一个 <tool_call> 块，然后**立即停止**，等待系统返回工具执行结果
3. **绝不编造**工具返回结果，你无法直接访问数据库，必须通过工具
4. 只有纯粹的闲聊（如"你好"、"谢谢"）才不调用工具

### 必须调用工具的场景和对应输出

用户说"党费缴纳标准"或任何政策咨询：
<tool_call>
{"name": "search_policy", "arguments": {"query": "党费缴纳标准"}}
</tool_call>

用户说"帮我写工作计划"或生成文档：
<tool_call>
{"name": "list_templates", "arguments": {}}
</tool_call>

用户说"党费标准"或政策相关问题：
<tool_call>
{"name": "search_policy", "arguments": {"query": "党费缴纳标准"}}
</tool_call>

用户说"能否转正"或合规判断：
<tool_call>
{"name": "check_compliance", "arguments": {"person_info": "相关信息", "requirement": "判断事项"}}
</tool_call>

**再次强调：看到用户请求后，如果涉及以上场景，直接输出 <tool_call> 标签，不要输出其他文字。**
"""


def _format_tools_for_prompt(tools: List[Dict]) -> str:
    """将 OpenAI tools JSON Schema 转为人类可读的文本描述"""
    lines = ["\n## 可用工具列表\n"]
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        required = func.get("parameters", {}).get("required", [])

        lines.append(f"### {name}")
        lines.append(f"功能：{desc}")

        if params:
            lines.append("参数：")
            for pname, pinfo in params.items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                req_mark = "（必填）" if pname in required else "（选填）"
                enum_str = ""
                if "enum" in pinfo:
                    enum_str = f"，可选值: {pinfo['enum']}"
                lines.append(f"  - {pname}: {ptype}{req_mark} — {pdesc}{enum_str}")
        else:
            lines.append("参数：无")
        lines.append("")

    return "\n".join(lines)


def _inject_tools_into_messages(messages: List[Dict], tools: List[Dict]) -> List[Dict]:
    """将工具描述注入到 System Prompt 中"""
    tools_text = _format_tools_for_prompt(tools)
    tool_instruction = tools_text + TOOL_CALL_FORMAT_INSTRUCTION

    augmented = []
    system_injected = False

    for msg in messages:
        if msg.get("role") == "system" and not system_injected:
            augmented.append({
                "role": "system",
                "content": msg["content"] + tool_instruction,
            })
            system_injected = True
        else:
            augmented.append(msg)

    # 如果没有 system 消息，在最前面插入一条
    if not system_injected:
        augmented.insert(0, {
            "role": "system",
            "content": "你是一个智能助手。" + tool_instruction,
        })

    return augmented


def _strip_think_tags(text: str) -> str:
    """剥离 <think>...</think> 标签内容"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _parse_tool_calls_from_text(text: str) -> Optional[List[Dict]]:
    """
    从 LLM 输出文本中解析 <tool_call>...</tool_call> 标签。
    返回与 OpenAI Function Calling 兼容的 tool_calls 列表，解析失败返回 None。
    """
    pattern = r'<tool_call>\s*(.*?)\s*</tool_call>'
    matches = re.findall(pattern, text, re.DOTALL)

    if not matches:
        return None

    tool_calls = []
    for raw_json in matches:
        parsed = _safe_parse_json(raw_json)
        if parsed and "name" in parsed:
            tool_calls.append({
                "id": f"call_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": parsed["name"],
                    "arguments": json.dumps(
                        parsed.get("arguments", {}), ensure_ascii=False
                    ),
                },
            })

    return tool_calls if tool_calls else None


def _safe_parse_json(text: str) -> Optional[Dict]:
    """安全解析 JSON，包含常见格式修复"""
    text = text.strip()

    # 剥离 markdown 代码块包裹
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # 第一次尝试：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 第二次尝试：修复尾逗号
    try:
        fixed = re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 第三次尝试：单引号替换为双引号
    try:
        fixed = text.replace("'", '"')
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 第四次尝试：提取第一个 JSON 对象
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except json.JSONDecodeError:
        pass

    logger.warning(f"JSON解析失败: {text[:200]}")
    return None


# 全局单例
llm_service = LLMService()
