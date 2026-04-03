"""对话API路由 — Agent架构版本，替代原有管道式路由"""
import json
import os
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.models.database import get_db, SessionLocal
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.core.auth import get_current_user
from app.core.llm import llm_service
from app.core.agent import AgentEngine, AgentStreamEvent, create_engine, WorkflowEngine

router = APIRouter(prefix="/api/chat", tags=["对话"])

# 全局Agent引擎实例（启动时初始化）
_agent_engine = None


def get_agent_engine():
    global _agent_engine
    if _agent_engine is None:
        _agent_engine = create_engine(llm_service)
    return _agent_engine


def reset_agent_engine():
    """重置Agent引擎（LLM配置变更时调用，下次请求会重新初始化）"""
    global _agent_engine
    _agent_engine = None
    logger.info("Agent引擎已重置，下次请求将重新初始化")


# ========== Pydantic Models ==========

class ChatRequest(BaseModel):
    conversation_id: Optional[int] = None
    message: str
    context: Optional[dict] = None
    attachment_text: Optional[str] = None   # 用户上传的附件提取文本
    attachment_name: Optional[str] = None   # 附件文件名


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    intent: str = "agent"
    data: Optional[dict] = None
    actions: Optional[list] = None
    tool_calls: Optional[list] = None


class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: str

    class Config:
        from_attributes = True


# ========== 对话管理接口（保持不变） ==========

@router.get("/conversations")
async def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取用户的对话列表"""
    conversations = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )
    return [
        {"id": c.id, "title": c.title, "created_at": str(c.created_at)}
        for c in conversations
    ]


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除对话及其消息"""
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"message": "对话已删除"}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取对话的消息历史"""
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")

    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .all()
    )
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "intent": m.intent,
            "metadata": json.loads(m.metadata_json) if m.metadata_json else None,
            "created_at": str(m.created_at),
        }
        for m in messages
    ]


# ========== 核心：Agent对话接口 ==========

@router.post("/send", response_model=ChatResponse)
async def send_message(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息 — 使用Agent引擎处理"""
    # 1. 获取或创建对话
    if req.conversation_id:
        conv = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.user_id == current_user.id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
    else:
        conv = Conversation(user_id=current_user.id, title=req.message[:50])
        db.add(conv)
        db.commit()
        db.refresh(conv)

    # 2. 保存用户消息
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=req.message,
        intent="agent",
    )
    db.add(user_msg)
    db.commit()

    # 3. 构建对话历史
    history = _build_conversation_history(db, conv.id, limit=10)

    # 4. 运行Agent
    reply = ""
    data = None
    actions = None
    tool_calls = None

    try:
        agent = get_agent_engine()

        # Workflow 模式：context 驱动的操作直接调用工具，不拼自然语言
        if req.context and isinstance(agent, WorkflowEngine):
            result = await agent.run_with_context(
                user_message=req.message,
                context=req.context,
                conversation_history=history,
                db=db,
            )
        else:
            # 非 Workflow 模式或无 context：兼容旧逻辑
            actual_message = req.message
            if req.context:
                ctx = req.context
                if ctx.get("_confirm_outline"):
                    actual_message = f"用户确认了大纲，请调用generate_document工具生成完整文档，template_id={ctx.get('_template_id')}，stage=full，fields={json.dumps({k: v for k, v in ctx.items() if not k.startswith('_')}, ensure_ascii=False)}"
                elif ctx.get("_modify_document"):
                    actual_message = f"用户要求修改文档，修改要求：{req.message}。请调用generate_document工具，stage=modify，template_id={ctx.get('_template_id', 0)}，original_content已提供，modification_request={req.message}"
                elif ctx.get("_template_id"):
                    fields_str = json.dumps({k: v for k, v in ctx.items() if not k.startswith("_")}, ensure_ascii=False)
                    actual_message = f"用户提供了模板字段信息：{fields_str}。请调用generate_document工具生成大纲，template_id={ctx.get('_template_id')}，fields={fields_str}"
            result = await agent.run(
                user_message=actual_message,
                conversation_history=history,
                db=db,
            )
        reply = result.reply
        tool_calls = result.tool_calls

        # 从structured_data中提取最重要的数据用于前端渲染
        if result.structured_data:
            data = _merge_structured_data(result.structured_data)
            actions = _extract_actions(result.structured_data)

    except Exception as e:
        logger.error(f"Agent处理失败: {e}")
        reply = _fallback_reply(req.message, e)

    # 6. 保存AI回复
    ai_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=reply,
        intent="agent",
        metadata_json=json.dumps({
            "data": data,
            "tool_calls": tool_calls,
        }, ensure_ascii=False, default=str) if (data or tool_calls) else None,
    )
    db.add(ai_msg)
    db.commit()

    return ChatResponse(
        conversation_id=conv.id,
        reply=reply,
        intent="agent",
        data=data,
        actions=actions,
        tool_calls=tool_calls,
    )


@router.post("/send/stream")
async def send_message_stream(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """流式Agent对话 — 实时展示思考和工具调用过程"""
    # 创建/获取对话
    if req.conversation_id:
        conv = db.query(Conversation).filter(
            Conversation.id == req.conversation_id,
            Conversation.user_id == current_user.id,
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
    else:
        conv = Conversation(user_id=current_user.id, title=req.message[:50])
        db.add(conv)
        db.commit()
        db.refresh(conv)

    conv_id = conv.id

    # 保存用户消息
    user_msg = Message(conversation_id=conv_id, role="user", content=req.message, intent="agent")
    db.add(user_msg)
    db.commit()

    # 构建历史
    history = _build_conversation_history(db, conv_id, limit=10)

    # 处理context
    has_context = bool(req.context)

    # 非 Workflow 模式时，保留旧的 context → 自然语言拼接逻辑
    actual_message = req.message

    # 如果用户上传了附件，将文件内容拼入消息（截取前 6000 字避免超出 token 限制）
    if req.attachment_text:
        att_name = req.attachment_name or "附件"
        att_text = req.attachment_text[:6000]
        actual_message = f"{req.message}\n\n【用户上传的参考文件「{att_name}」内容如下】\n{att_text}"

    if req.context:
        agent_tmp = get_agent_engine()
        if not isinstance(agent_tmp, WorkflowEngine):
            ctx = req.context
            if ctx.get("_confirm_outline"):
                actual_message = f"用户确认了大纲，请调用generate_document工具生成完整文档，template_id={ctx.get('_template_id')}，stage=full，fields={json.dumps({k: v for k, v in ctx.items() if not k.startswith('_')}, ensure_ascii=False)}"
            elif ctx.get("_modify_document"):
                actual_message = f"用户要求修改文档，修改要求：{req.message}。请调用generate_document工具，stage=modify，template_id={ctx.get('_template_id', 0)}，original_content已提供，modification_request={req.message}"
            elif ctx.get("_template_id"):
                fields_str = json.dumps({k: v for k, v in ctx.items() if not k.startswith("_")}, ensure_ascii=False)
                actual_message = f"用户提供了模板字段信息：{fields_str}。请调用generate_document工具生成大纲，template_id={ctx.get('_template_id')}，fields={fields_str}"
            has_context = False  # 已转换为自然语言，不再作为 context 处理

    async def generate():
        full_reply = ""
        all_structured = []
        all_tool_calls = []

        try:
            agent = get_agent_engine()

            # Workflow 模式 + context → 使用 run_stream_with_context
            if has_context and isinstance(agent, WorkflowEngine):
                stream = agent.run_stream_with_context(
                    user_message=req.message,
                    context=req.context,
                    conversation_history=history,
                    db=db,
                )
            else:
                stream = agent.run_stream(
                    user_message=actual_message,
                    conversation_history=history,
                    db=db,
                )

            async for event in stream:
                if event.type == "thinking":
                    yield f"data: {json.dumps({'type': 'thinking', 'message': event.data.get('message', '正在思考...')}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)

                elif event.type == "tool_calling":
                    yield f"data: {json.dumps({'type': 'tool_calling', 'tool': event.data.get('tool', ''), 'args': event.data.get('args', {})}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)
                    all_tool_calls.append({"tool": event.data.get("tool"), "args": event.data.get("args")})

                elif event.type == "tool_result":
                    structured = event.data.get("structured")
                    if structured:
                        all_structured.append(structured)
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool': event.data.get('tool', ''), 'success': event.data.get('success', False), 'summary': event.data.get('summary', ''), 'structured': structured}, ensure_ascii=False, default=str)}\n\n"
                    await asyncio.sleep(0)

                elif event.type == "thinking_content":
                    thinking_text = event.data.get("text", "")
                    yield f"data: {json.dumps({'type': 'thinking_content', 'text': thinking_text}, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0)

                elif event.type == "content":
                    text_chunk = event.data.get("text", "")
                    full_reply += text_chunk
                    yield f"data: {json.dumps({'content': text_chunk}, ensure_ascii=False)}\n\n"

                elif event.type == "done":
                    pass

        except Exception as e:
            logger.error(f"Agent流式处理失败: {e}")
            error_msg = _fallback_reply(req.message, e)
            full_reply = error_msg
            yield f"data: {json.dumps({'content': error_msg}, ensure_ascii=False)}\n\n"

        # 保存完整回复
        try:
            save_db = SessionLocal()
            merged = _merge_structured_data(all_structured) if all_structured else None
            ai_msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content=full_reply,
                intent="agent",
                metadata_json=json.dumps({
                    "data": merged,
                    "tool_calls": all_tool_calls,
                }, ensure_ascii=False, default=str) if (merged or all_tool_calls) else None,
            )
            save_db.add(ai_msg)
            save_db.commit()
            save_db.close()
        except Exception as e:
            logger.error(f"保存Agent流式回复失败: {e}")

        # 发送完成的结构化数据和done信号
        merged_data = _merge_structured_data(all_structured) if all_structured else None
        actions = _extract_actions(all_structured) if all_structured else None
        yield f"data: {json.dumps({'done': True, 'conversation_id': conv_id, 'data': merged_data, 'actions': actions, 'tool_calls': all_tool_calls}, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ========== 辅助函数 ==========

def _build_conversation_history(db: Session, conversation_id: int, limit: int = 10) -> list:
    """构建对话历史（最近N条消息，不包括最新的用户消息）"""
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit + 1)
        .all()
    )
    messages = list(reversed(messages))

    # 去掉最后一条（刚保存的用户消息）
    if messages and messages[-1].role == "user":
        messages = messages[:-1]

    history = []
    for m in messages:
        if m.role in ("user", "assistant"):
            history.append({"role": m.role, "content": m.content or ""})
    return history


def _merge_structured_data(structured_list: list) -> Optional[dict]:
    """合并多个工具返回的结构化数据，优先返回最重要的"""
    if not structured_list:
        return None

    # 优先级：document > compliance_result > table > template_outline > others
    priority = {
        "document": 1,
        "compliance_result": 2,
        "table": 3,
        "template_outline": 5,
        "template_list": 6,
        "export_ready": 7,
        "policy_search": 8,
    }

    # 返回优先级最高的
    best = None
    best_priority = 999
    for item in structured_list:
        item_type = item.get("type", "")
        p = priority.get(item_type, 100)
        if p < best_priority:
            best_priority = p
            best = item

    return best


def _extract_actions(structured_list: list) -> Optional[list]:
    """从结构化数据中提取可用的动作按钮"""
    if not structured_list:
        return None

    actions = []
    for item in structured_list:
        item_type = item.get("type", "")

        if item_type == "document":
            actions.extend([
                {"type": "download_word", "label": "下载Word"},
                {"type": "download_pdf", "label": "下载PDF"},
                {"type": "modify", "label": "继续修改"},
            ])
        elif item_type == "template_outline":
            actions.extend([
                {"type": "confirm_outline", "label": "确认，生成全文"},
                {"type": "regenerate_outline", "label": "重新生成大纲"},
            ])
        elif item_type == "table":
            actions.append({"type": "export_excel", "label": "导出Excel"})
            if item.get("is_stats"):
                actions.append({"type": "show_chart", "label": "查看图表"})
        elif item_type == "compliance_result":
            actions.extend([
                {"type": "export_report", "label": "导出判断书"},
                {"type": "supplement_info", "label": "补充材料重新判断"},
            ])
        elif item_type == "export_ready":
            actions.append({"type": f"download_{item.get('format', 'file')}", "label": f"下载{item.get('format', '').upper()}"})

    return actions if actions else None


def _fallback_reply(user_message: str, error: Exception = None) -> str:
    """LLM不可用时的降级回复"""
    return (
        "您好！我是智慧党建助手。\n\n"
        "当前AI模型服务未连接，请管理员在【管理后台 → LLM配置】中配置正确的模型服务地址。\n\n"
        "配置完成后，我可以为您提供以下服务：\n"
        "1. 📄 文档模板生成 — 自动填充工作计划、活动方案等\n"
        "2. 📖 政策法规咨询 — 检索政策条款、合规判断\n"
        "3. 📝 文件差异对比 — 比较两份文件的不同\n\n"
        f"错误详情：{str(error)[:200]}" if error else ""
    )


# ========== 聊天附件上传 ==========

@router.post("/upload-attachment")
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传聊天附件，提取文本内容返回给前端

    支持格式: pdf / docx / doc / txt / wps
    前端拿到提取的文本后，发送消息时通过 attachment_text 字段一同传入。
    """
    from app.core.document_processor import extract_text_from_file
    from app.config import settings

    ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt", ".wps", ".md"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}，仅支持 {', '.join(ALLOWED_EXT)}")

    # 保存到临时文件
    upload_dir = getattr(settings, "UPLOAD_DIR", "./uploads")
    os.makedirs(upload_dir, exist_ok=True)
    tmp_path = os.path.join(upload_dir, f"_att_{current_user.id}_{file.filename}")

    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        # 提取文本
        text = extract_text_from_file(tmp_path)
        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="文件内容为空或无法提取文本")

        logger.info(f"附件上传成功: {file.filename}, 提取文本 {len(text)} 字")
        return {
            "filename": file.filename,
            "text": text,
            "char_count": len(text),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"附件文本提取失败: {e}")
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
