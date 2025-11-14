from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.creation import CreationCreate
from app.models.chapter import Chapter
from app.models.creation import Creation
from app.models.novel import Novel
from app.tasks.creation_task import process_creation_init
from app.core.logger import logger
router = APIRouter()


@router.post("/create")
async def create_creation(
    creation_data: CreationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """创建新的视频创作项目"""
    logger.info(f"创建新的视频创作项目: {creation_data}")
    novel_id = creation_data.novel_id
    chapter_id = creation_data.chapter_id
    # 根据chapter_id获取chapter内容
    novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
    chapter = db.query(Chapter).filter(Chapter.chapter_id == chapter_id).first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    chapter_content_url = chapter.content_url

    try:
        task = process_creation_init.delay(
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_content_url=chapter_content_url
        )
        return {
            "task_id": task.id,
            "message": "创作初始化成功"
        }
    except Exception as e:
        logger.error(f"创作初始化任务失败: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创作初始化失败")
    
   


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
