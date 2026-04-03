"""模板管理API路由"""
import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.user import User
from app.models.template import Template, GeneratedDocument
from app.core.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/templates", tags=["模板管理"])


class TemplateCreate(BaseModel):
    name: str
    category: str
    description: str = ""
    required_fields: List[str] = []
    optional_fields: List[str] = []
    body_skeleton: str = ""
    prompt_template: str = ""
    example_output: str = ""


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    required_fields: Optional[List[str]] = None
    optional_fields: Optional[List[str]] = None
    body_skeleton: Optional[str] = None
    prompt_template: Optional[str] = None
    example_output: Optional[str] = None
    is_active: Optional[bool] = None


class TemplateResponse(BaseModel):
    id: int
    name: str
    category: str
    description: str | None
    required_fields: list
    optional_fields: list
    is_active: bool
    created_at: str
    updated_at: str


@router.get("/")
async def list_templates(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取模板列表"""
    query = db.query(Template)
    if category:
        query = query.filter(Template.category == category)
    templates = query.order_by(Template.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "required_fields": json.loads(t.required_fields) if t.required_fields else [],
            "optional_fields": json.loads(t.optional_fields) if t.optional_fields else [],
            "is_active": t.is_active,
            "created_at": str(t.created_at),
            "updated_at": str(t.updated_at),
        }
        for t in templates
    ]


@router.get("/{template_id}")
async def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取模板详情"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {
        "id": template.id,
        "name": template.name,
        "category": template.category,
        "description": template.description,
        "required_fields": json.loads(template.required_fields) if template.required_fields else [],
        "optional_fields": json.loads(template.optional_fields) if template.optional_fields else [],
        "body_skeleton": template.body_skeleton,
        "prompt_template": template.prompt_template,
        "example_output": template.example_output,
        "is_active": template.is_active,
        "created_at": str(template.created_at),
        "updated_at": str(template.updated_at),
    }


@router.post("/")
async def create_template(
    data: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """创建模板（管理员）"""
    template = Template(
        name=data.name,
        category=data.category,
        description=data.description,
        required_fields=json.dumps(data.required_fields, ensure_ascii=False),
        optional_fields=json.dumps(data.optional_fields, ensure_ascii=False),
        body_skeleton=data.body_skeleton,
        prompt_template=data.prompt_template,
        example_output=data.example_output,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return {"id": template.id, "message": "模板创建成功"}


@router.put("/{template_id}")
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新模板（管理员）"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "required_fields" in update_data:
        update_data["required_fields"] = json.dumps(update_data["required_fields"], ensure_ascii=False)
    if "optional_fields" in update_data:
        update_data["optional_fields"] = json.dumps(update_data["optional_fields"], ensure_ascii=False)

    for key, value in update_data.items():
        setattr(template, key, value)
    db.commit()
    return {"message": "模板更新成功"}


@router.delete("/{template_id}")
async def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除模板（管理员）"""
    template = db.query(Template).filter(Template.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(template)
    db.commit()
    return {"message": "模板删除成功"}
