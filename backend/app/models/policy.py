"""政策知识库模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from app.models.database import Base


class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False, comment="文件名")
    title = Column(String(255), nullable=True, comment="政策标题")
    file_path = Column(String(500), nullable=False, comment="文件存储路径")
    file_type = Column(String(20), nullable=True, comment="文件类型: pdf/docx")
    status = Column(String(20), default="pending", comment="状态: pending/processing/indexed/failed")
    chunk_count = Column(Integer, default=0, comment="切片数量")
    version = Column(String(20), default="v1", comment="版本号")
    department = Column(String(200), default="", comment="所属科室")
    is_active = Column(String(20), default="有效", comment="有效性: 有效/废止")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, nullable=False, index=True, comment="所属文档ID")
    chunk_index = Column(Integer, nullable=False, comment="切片序号")
    title = Column(String(255), nullable=True, comment="章节/条款标题")
    content = Column(Text, nullable=False, comment="切片内容")
    hierarchy = Column(String(255), nullable=True, comment="层级路径,如:第二章>第6条")
    milvus_id = Column(String(100), nullable=True, comment="Milvus中的向量ID")
    created_at = Column(DateTime, server_default=func.now())


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True)
    query_type = Column(String(50), nullable=False, comment="查询类型: template/member/policy/compliance/diff")
    query_text = Column(Text, nullable=False, comment="用户原始查询")
    result_summary = Column(Text, nullable=True, comment="结果摘要")
    created_at = Column(DateTime, server_default=func.now())
