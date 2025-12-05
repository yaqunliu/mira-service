from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.utils.response import success_response

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


@router.get("/{user_uuid}")
async def get_user(user_uuid: str, db: Session = Depends(get_db)):
    """根据UUID获取用户信息"""
    from app.models.user import User as UserModel
    from app.schemas.user import User as UserSchema
    
    user = db.query(UserModel).filter(UserModel.uuid == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    return success_response(
        data=UserSchema.model_validate(user).model_dump(),
        message="获取用户成功"
    )
