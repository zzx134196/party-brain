"""系统配置模型 - 持久化key-value存储"""
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from app.models.database import Base


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True, comment="配置键")
    value = Column(Text, nullable=True, comment="配置值")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
