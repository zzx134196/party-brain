"""文档模板模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, func
from app.models.database import Base


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="模板名称")
    category = Column(String(50), nullable=False, comment="类型: 计划/总结/方案/报告/记录")
    description = Column(String(500), nullable=True, comment="模板描述")
    required_fields = Column(Text, nullable=True, comment="必填字段JSON数组")
    optional_fields = Column(Text, nullable=True, comment="选填字段JSON数组")
    body_skeleton = Column(Text, nullable=True, comment="正文骨架/模板内容")
    prompt_template = Column(Text, nullable=True, comment="生成用的Prompt模板")
    example_output = Column(Text, nullable=True, comment="示例输出")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    template_id = Column(Integer, nullable=True)
    conversation_id = Column(Integer, nullable=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    input_fields = Column(Text, nullable=True, comment="用户输入的字段JSON")
    file_path = Column(String(500), nullable=True, comment="导出文件路径")
    created_at = Column(DateTime, server_default=func.now())
