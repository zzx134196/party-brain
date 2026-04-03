"""认证与权限模块 — 对接总系统 JWT 统一认证

总系统签发 JWT Token，子系统验证并提取用户信息。
Token 通过前端 URL ?token=xxx 传入，存储在 localStorage 中，
每次请求通过 Authorization: Bearer <token> 传递。
"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from loguru import logger

from app.config import settings
from app.models.database import get_db
from app.models.user import User

security = HTTPBearer(auto_error=False)


def get_password_hash(password: str) -> str:
    """生成密码哈希（保留用于初始化默认管理员）"""
    import bcrypt
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def decode_jwt_token(token: str) -> dict:
    """解码并验证总系统签发的 JWT Token"""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT 验证失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token 无效或已过期: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """验证 JWT Token 并返回/创建本地用户。

    流程：
    1. 从 Authorization header 提取 Bearer token
    2. 解码验证 JWT（密钥 + issuer + audience + 过期时间）
    3. 根据 payload 中的 sub+username 查找本地用户
    4. 用户不存在则自动创建（首次从总系统登录时）
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息，请从总系统登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_jwt_token(credentials.credentials)

    # 提取 payload 字段
    user_id_str = payload.get("sub", "")
    username = payload.get("username", "")
    is_admin = payload.get("is_admin", False)

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 中缺少用户名信息",
        )

    # 查找或创建本地用户
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            hashed_password="jwt-managed",  # 密码由总系统管理
            real_name=username,
            role="admin" if is_admin else "user",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"自动创建用户（来自总系统）: {username}, admin={is_admin}")
    else:
        # 同步管理员状态
        new_role = "admin" if is_admin else "user"
        if user.role != new_role:
            user.role = new_role
            db.commit()

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求管理员权限"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
