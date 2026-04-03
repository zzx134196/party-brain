"""对话与消息模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from app.models.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="user/assistant/system")
    content = Column(Text, nullable=False)
    intent = Column(String(50), nullable=True, comment="意图分类")
    metadata_json = Column(Text, nullable=True, comment="附加信息JSON")
    created_at = Column(DateTime, server_default=func.now())
