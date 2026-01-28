from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_async_db
from app.models.user import User
from app.core.logger import logger
from app.services.supabase_service import supabase_service
from app.services.user_async_service import UserAsyncService

security = HTTPBearer(auto_error=False)


async def get_default_user(db: AsyncSession) -> User:
    """
    获取默认用户（admin）
    如果不存在则创建
    
    Returns:
        User对象
    """
    result = await db.execute(select(User).where(User.username == "admin"))
    user = result.scalar_one_or_none()
    
    if not user:
        from app.core.security import get_password_hash
        user = User(
            username="admin",
            email="admin@example.com",
            hashed_password=get_password_hash("admin123")
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("创建默认admin用户")
    
    return user


async def get_current_user(
    db: AsyncSession = Depends(get_async_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """
    获取当前用户
    只支持 Supabase JWT token 认证
    
    如果无法获取当前用户（token无效或未提供），则抛出401未授权异常
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌，请使用 Supabase 登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    supabase_user_data = supabase_service.get_user_from_token(token)
    if not supabase_user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌，请使用 Supabase 登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = await UserAsyncService.get_user_from_supabase_token(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法获取用户信息",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


async def get_current_user_optional(
    db: AsyncSession = Depends(get_async_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[User]:
    """
    获取当前用户（可选）
    如果无法获取用户，返回 None 而不是抛出异常
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    supabase_user_data = supabase_service.get_user_from_token(token)
    if not supabase_user_data:
        return None
    
    user = await UserAsyncService.get_user_from_supabase_token(db, token)
    return user
