from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.creation import CreationCreate
from app.services.creation_service import CreationService
from app.core.exceptions import BaseServiceException

router = APIRouter()


@router.post("/create")
async def create_creation(
    creation_data: CreationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    创建新的视频创作项目
    
    参数验证：
    - 验证 novel_id 和 chapter_id 是否有效
    - 验证用户权限
    """
    # 获取用户ID
    try:
        user_id = user.user_id
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="获取用户信息失败"
        )
    
    # 调用服务层处理业务逻辑
    try:
        creation_id = CreationService.create_creation(
            db=db,
            novel_id=creation_data.novel_id,
            chapter_id=creation_data.chapter_id,
            user_id=user_id
        )
        
        # 转换为响应格式
        return {
            "creation_id": creation_id,
            "message": "创作初始化成功"
        }
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(
            status_code=e.status_code,
            detail=e.detail
        )
    
   


@router.get("/")
async def get_creations():
    """获取创作项目列表"""
    # TODO: 实现获取创作列表逻辑
    pass


@router.get("/{creation_id}")
async def get_creation(creation_id: int):
    """根据ID获取创作项目详情"""
    # TODO: 实现获取创作详情逻辑
    pass


@router.put("/{creation_id}")
async def update_creation(creation_id: int):
    """更新创作项目"""
    # TODO: 实现更新创作逻辑
    pass


@router.delete("/{creation_id}")
async def delete_creation(creation_id: int):
    """删除创作项目"""
    # TODO: 实现删除创作逻辑
    pass


@router.post("/{creation_id}/generate")
async def start_generation(creation_id: int):
    """开始生成视频"""
    # TODO: 实现开始生成逻辑
    pass


@router.get("/{creation_id}/progress")
async def get_generation_progress(creation_id: int):
    """获取生成进度"""
    # TODO: 实现获取进度逻辑
    pass
