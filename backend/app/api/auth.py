"""认证API路由（统一认证模式 — JWT由总管理系统签发）"""
from pydantic import BaseModel
from typing import List, Optional
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.models.user import User
from app.core.auth import get_current_user, decode_jwt_token

router = APIRouter(prefix="/api/auth", tags=["认证"])

security = HTTPBearer(auto_error=False)


def _to_string_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


class UserResponse(BaseModel):
    id: int
    username: str
    real_name: str | None
    role: str
    is_admin: bool = False
    department_ids: List[str] = []
    collection_names: List[str] = []

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """获取当前用户信息（验证JWT有效性）

    返回本地用户信息 + JWT payload 中的总系统字段
    """
    # 从 JWT payload 补充总系统字段
    extra = {}
    if credentials:
        try:
            payload = decode_jwt_token(credentials.credentials)
            extra = {
                "is_admin": payload.get("is_admin", False),
                "department_ids": _to_string_list(payload.get("department_ids", [])),
                "collection_names": _to_string_list(payload.get("collection_names", [])),
            }
        except Exception:
            pass

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        real_name=current_user.real_name,
        role=current_user.role,
        **extra,
    )
