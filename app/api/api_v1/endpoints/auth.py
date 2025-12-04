from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user
from app.utils.response import success_response
from app.services.user_sync_service import UserSyncService

router = APIRouter()


# 注意：传统的注册、登录和刷新端点已废弃
# 所有认证现在都通过 Supabase 进行
# 用户注册和登录请使用前端 Supabase 客户端


@router.post("/sync")
async def sync_supabase_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
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
    user = UserSyncService.get_user_from_supabase_token(db, token)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 获取用户头像（User 模型现在有 avatar 字段）
    avatar = user.avatar if hasattr(user, 'avatar') else None
    
    # 如果没有 avatar 值，尝试从 token 中获取
    if not avatar:
        from app.services.supabase_service import supabase_service
        supabase_user_data = supabase_service.get_user_from_token(token)
        if supabase_user_data:
            avatar = supabase_user_data.get("avatar_url")
            # 如果从 token 中获取到了头像，更新数据库
            if avatar and hasattr(user, 'avatar'):
                user.avatar = avatar
                db.commit()
                db.refresh(user)
    
    from app.core.logger import logger
    logger.info(f"同步用户响应: user_id={user.user_id}, avatar={avatar}")
    
    return success_response(
        data={
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "supabase_user_id": user.supabase_user_id,
            "avatar": avatar,  # 添加 avatar 字段
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        },
        message="用户同步成功"
    )
