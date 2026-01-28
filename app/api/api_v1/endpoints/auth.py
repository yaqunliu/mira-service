from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.db.session import get_async_db
from app.models.user import User
from app.api.deps import get_current_user
from app.utils.response import success_response
from app.services.user_async_service import UserAsyncService

router = APIRouter()


@router.post("/sync")
async def sync_supabase_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_async_db)
):
    """
    同步 Supabase 用户到本地数据库
    前端在登录后调用此接口
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少或无效的认证头",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = authorization.replace("Bearer ", "")
    user = await UserAsyncService.get_user_from_supabase_token(db, token)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    avatar = user.avatar if hasattr(user, 'avatar') else None
    
    if not avatar:
        from app.services.supabase_service import supabase_service
        supabase_user_data = supabase_service.get_user_from_token(token)
        if supabase_user_data:
            avatar = supabase_user_data.get("avatar_url")
            if avatar and hasattr(user, 'avatar'):
                user.avatar = avatar
                await db.commit()
                await db.refresh(user)
    
    return success_response(
        data={
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "supabase_user_id": user.supabase_user_id,
            "avatar": avatar,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        },
        message="用户同步成功"
    )


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户信息
    """
    return success_response(
        data={
            "user_id": current_user.user_id,
            "username": current_user.username,
            "email": current_user.email,
            "supabase_user_id": current_user.supabase_user_id,
            "avatar": getattr(current_user, 'avatar', None),
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        message="获取用户信息成功"
    )
