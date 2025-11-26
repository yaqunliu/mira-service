from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/me")
async def get_current_user(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    # TODO: 实现获取当前用户逻辑
    pass


@router.put("/me")
async def update_current_user():
    """更新当前用户信息"""
    # TODO: 实现更新用户信息逻辑
    pass


@router.get("/{user_id}")
async def get_user(user_id: int):
    """根据ID获取用户信息"""
    # TODO: 实现获取用户逻辑
    pass
