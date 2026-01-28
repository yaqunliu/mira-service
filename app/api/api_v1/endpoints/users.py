from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.utils.response import success_response

router = APIRouter()


@router.get("/me")
async def get_current_user(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return success_response(
        data={
            "user_id": current_user.user_id,
            "uuid": current_user.uuid,
            "username": current_user.username,
            "email": current_user.email,
            "avatar": getattr(current_user, 'avatar', None),
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        message="获取用户成功"
    )


@router.put("/me")
async def update_current_user():
    """更新当前用户信息"""
    pass


@router.get("/{user_uuid}")
async def get_user(user_uuid: str, db: AsyncSession = Depends(get_async_db)):
    """根据UUID获取用户信息"""
    result = await db.execute(
        select(User).where(User.uuid == user_uuid)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return success_response(
        data={
            "user_id": user.user_id,
            "uuid": user.uuid,
            "username": user.username,
            "email": user.email,
            "avatar": getattr(user, 'avatar', None),
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        message="获取用户成功"
    )
