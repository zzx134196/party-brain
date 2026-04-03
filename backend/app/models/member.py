"""党员信息模型"""
from sqlalchemy import Column, Integer, String, Date, DateTime, func
from app.models.database import Base


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, index=True, comment="姓名")
    gender = Column(String(10), nullable=True, comment="性别")
    birth_date = Column(Date, nullable=True, comment="出生日期")
    department = Column(String(100), nullable=True, index=True, comment="所属部门/支部")
    position = Column(String(100), nullable=True, comment="职务")
    education = Column(String(50), nullable=True, comment="学历")
    phone = Column(String(20), nullable=True, comment="联系电话")
    join_party_date = Column(Date, nullable=True, comment="入党日期")
    become_full_date = Column(Date, nullable=True, comment="转正日期")
    status = Column(String(20), default="正式", comment="状态: 正式/预备/转出/其他")
    id_card = Column(String(20), nullable=True, comment="身份证号")
    ethnicity = Column(String(20), nullable=True, comment="民族")
    address = Column(String(200), nullable=True, comment="住址")
    remark = Column(String(500), nullable=True, comment="备注")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
