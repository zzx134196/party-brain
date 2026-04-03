"""党员管理API路由"""
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.models.database import get_db
from app.models.user import User
from app.models.member import Member
from app.core.auth import get_current_user, require_admin
from app.core.nl2sql import desensitize_phone

router = APIRouter(prefix="/api/members", tags=["党员管理"])


class MemberResponse(BaseModel):
    id: int
    name: str
    gender: str | None
    department: str | None
    position: str | None
    education: str | None
    phone: str | None
    status: str | None
    join_party_date: str | None
    become_full_date: str | None


@router.get("/")
async def list_members(
    department: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取党员列表（分页）"""
    query = db.query(Member)
    if department:
        query = query.filter(Member.department == department)
    if status:
        query = query.filter(Member.status == status)
    if keyword:
        query = query.filter(Member.name.like(f"%{keyword}%"))

    total = query.count()
    members = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [
            {
                "id": m.id,
                "name": m.name,
                "gender": m.gender,
                "department": m.department,
                "position": m.position,
                "education": m.education,
                "phone": desensitize_phone(m.phone) if m.phone else None,
                "status": m.status,
                "join_party_date": str(m.join_party_date) if m.join_party_date else None,
                "become_full_date": str(m.become_full_date) if m.become_full_date else None,
            }
            for m in members
        ],
    }


@router.get("/stats/departments")
async def stats_by_department(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """各支部党员人数统计"""
    from sqlalchemy import func
    results = (
        db.query(Member.department, func.count(Member.id).label("count"))
        .group_by(Member.department)
        .all()
    )
    return {
        "data": [{"department": r[0], "count": r[1]} for r in results],
        "total": sum(r[1] for r in results),
    }


@router.get("/stats/age")
async def stats_by_age(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """年龄段分布统计"""
    from sqlalchemy import func, text
    from app.config import settings

    if settings.DATABASE_URL.startswith("sqlite"):
        sql = """
            SELECT
                CASE
                    WHEN (strftime('%Y','now') - strftime('%Y', birth_date)) < 30 THEN '30岁以下'
                    WHEN (strftime('%Y','now') - strftime('%Y', birth_date)) < 40 THEN '30-40岁'
                    WHEN (strftime('%Y','now') - strftime('%Y', birth_date)) < 50 THEN '40-50岁'
                    ELSE '50岁以上'
                END AS age_group,
                COUNT(*) AS count
            FROM members
            WHERE birth_date IS NOT NULL
            GROUP BY age_group
            ORDER BY
                CASE age_group
                    WHEN '30岁以下' THEN 1
                    WHEN '30-40岁' THEN 2
                    WHEN '40-50岁' THEN 3
                    ELSE 4
                END
        """
    else:
        sql = """
            SELECT
                CASE
                    WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 30 THEN '30岁以下'
                    WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 40 THEN '30-40岁'
                    WHEN TIMESTAMPDIFF(YEAR, birth_date, CURDATE()) < 50 THEN '40-50岁'
                    ELSE '50岁以上'
                END AS age_group,
                COUNT(*) AS count
            FROM members
            WHERE birth_date IS NOT NULL
            GROUP BY age_group
            ORDER BY
                CASE age_group
                    WHEN '30岁以下' THEN 1
                    WHEN '30-40岁' THEN 2
                    WHEN '40-50岁' THEN 3
                    ELSE 4
                END
        """
    results = db.execute(text(sql)).fetchall()
    total = sum(r[1] for r in results)
    return {
        "data": [
            {
                "age_group": r[0],
                "count": r[1],
                "percentage": round(r[1] / total * 100, 1) if total > 0 else 0,
            }
            for r in results
        ],
        "total": total,
    }


@router.get("/{member_id}")
async def get_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取党员详情（画像卡片）"""
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="党员不存在")
    return {
        "id": member.id,
        "name": member.name,
        "gender": member.gender,
        "birth_date": str(member.birth_date) if member.birth_date else None,
        "department": member.department,
        "position": member.position,
        "education": member.education,
        "phone": desensitize_phone(member.phone) if member.phone else None,
        "status": member.status,
        "ethnicity": member.ethnicity,
        "join_party_date": str(member.join_party_date) if member.join_party_date else None,
        "become_full_date": str(member.become_full_date) if member.become_full_date else None,
        "remark": member.remark,
    }


@router.post("/import")
async def import_members(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量导入党员数据（Excel）"""
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="仅支持Excel或CSV文件")

    try:
        import pandas as pd
        content = await file.read()

        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        else:
            df = pd.read_excel(io.BytesIO(content))

        # 列名映射
        column_map = {
            '姓名': 'name', '性别': 'gender', '出生日期': 'birth_date',
            '部门': 'department', '支部': 'department', '所属支部': 'department',
            '职务': 'position', '学历': 'education', '电话': 'phone',
            '联系电话': 'phone', '入党日期': 'join_party_date',
            '转正日期': 'become_full_date', '状态': 'status',
            '民族': 'ethnicity', '备注': 'remark',
        }
        df = df.rename(columns={k: v for k, v in column_map.items() if k in df.columns})

        count = 0
        for _, row in df.iterrows():
            if 'name' not in row or pd.isna(row.get('name')):
                continue
            member = Member(
                name=str(row.get('name', '')).strip(),
                gender=str(row.get('gender', '')).strip() if pd.notna(row.get('gender')) else None,
                birth_date=pd.to_datetime(row.get('birth_date')).date() if pd.notna(row.get('birth_date')) else None,
                department=str(row.get('department', '')).strip() if pd.notna(row.get('department')) else None,
                position=str(row.get('position', '')).strip() if pd.notna(row.get('position')) else None,
                education=str(row.get('education', '')).strip() if pd.notna(row.get('education')) else None,
                phone=str(row.get('phone', '')).strip() if pd.notna(row.get('phone')) else None,
                join_party_date=pd.to_datetime(row.get('join_party_date')).date() if pd.notna(row.get('join_party_date')) else None,
                become_full_date=pd.to_datetime(row.get('become_full_date')).date() if pd.notna(row.get('become_full_date')) else None,
                status=str(row.get('status', '正式')).strip() if pd.notna(row.get('status')) else '正式',
                ethnicity=str(row.get('ethnicity', '')).strip() if pd.notna(row.get('ethnicity')) else None,
                remark=str(row.get('remark', '')).strip() if pd.notna(row.get('remark')) else None,
            )
            db.add(member)
            count += 1

        db.commit()
        return {"message": f"成功导入 {count} 条党员数据", "count": count}
    except Exception as e:
        logger.error(f"导入党员数据失败: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")
