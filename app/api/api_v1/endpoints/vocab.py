"""
Vocab API - 英语单词视频生成接口

API:
- POST /vocab/create - 创建单词视频任务
- GET /vocab/{task_uuid}/status - 查询任务状态
- GET /vocab/{task_uuid}/download - 下载视频
"""
from typing import Optional
from uuid import uuid4
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.models.creation import Creation
from app.core.logger import logger

router = APIRouter(prefix="/vocab", tags=["Vocab Video"])


class CreateVocabRequest(BaseModel):
    """创建单词视频请求"""
    words: list[str] = Field(..., description="单词列表", min_length=1, max_length=10)
    word_repeat_count: Optional[int] = Field(None, ge=1, le=5, description="单词重复次数，默认2")
    translation_repeat_count: Optional[int] = Field(None, ge=1, le=3, description="翻译重复次数，默认1")
    voice_gender: Optional[str] = Field("female", description="声音性别")
    voice_age: Optional[str] = Field("child", description="声音年龄")
    sentence_level: Optional[str] = Field("primary", description="句子难度")
    video_model: Optional[str] = Field("doubao-seedance-1-5-pro-251215", description="视频生成模型")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_uuid: str
    status: str
    progress: int
    current_step: str
    step_status: Optional[str] = None
    video_url: Optional[str] = None
    error_message: Optional[str] = None


def _get_status_from_creation(creation: Creation) -> dict:
    """从 Creation 获取状态"""
    extra = creation.extra_data or {}
    return {
            "status": creation.status,
            "progress": extra.get("progress", 0) if creation.status != "completed" else 100,
            "current_step": extra.get("current_step", "初始化"),
            "step_status": extra.get("step_status", ""),
            "video_url": extra.get("video_url"),
            "error_message": extra.get("error_message"),
        }


@router.post("/create")
async def create_vocab_video(
    request: CreateVocabRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """创建英语单词视频生成任务"""
    
    config = {
        "words": request.words,
    }
    
    if request.word_repeat_count is not None:
        config["word_repeat_count"] = request.word_repeat_count
    if request.translation_repeat_count is not None:
        config["translation_repeat_count"] = request.translation_repeat_count
    if request.voice_gender is not None:
        config["voice_gender"] = request.voice_gender
    if request.voice_age is not None:
        config["voice_age"] = request.voice_age
    if request.sentence_level is not None:
        config["sentence_level"] = request.sentence_level
    if request.video_model is not None:
        config["video_model"] = request.video_model
    
    task_uuid = str(uuid4())
    
    creation = Creation(
        uuid=task_uuid,
        title=f"单词视频: {', '.join(request.words[:3])}",
        creation_type="vocab",
        status="processing",
        owner_id=current_user.user_id,
        extra_data={
            "config": config,
            "progress": 0,
            "current_step": "等待处理",
        }
    )
    
    db.add(creation)
    await db.commit()
    await db.refresh(creation)
    
    import asyncio
    from app.agent.triggers.vocab_trigger import trigger_agent_for_vocab
    
    asyncio.create_task(
        trigger_agent_for_vocab(
            user_id=current_user.user_id,
            task_uuid=creation.uuid,
            creation_id=creation.creation_id,
            config=config,
        )
    )
    
    return {
        "task_uuid": creation.uuid,
        "status": "processing",
        "message": "任务已创建，正在生成视频"
    }


@router.get("/uuid/{task_uuid}/status", response_model=TaskStatusResponse)
async def get_task_status_by_uuid(
    task_uuid: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """通过UUID查询任务状态"""
    import logging
    logger = logging.getLogger(__name__)
    
    from sqlalchemy import select
    
    result = await db.execute(
        select(Creation).where(
            Creation.uuid == task_uuid,
            Creation.owner_id == current_user.user_id
        )
    )
    creation = result.scalar_one_or_none()
    
    if not creation:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    extra = creation.extra_data or {}
    logger.info(f"[get_task_status_by_uuid] uuid={task_uuid}, status={creation.status}, extra={extra}")
    
    status_info = _get_status_from_creation(creation)
    
    return TaskStatusResponse(
        task_uuid=creation.uuid,
        status=status_info["status"],
        progress=status_info["progress"],
        current_step=status_info["current_step"],
        step_status=status_info.get("step_status"),
        video_url=status_info["video_url"],
        error_message=status_info["error_message"],
    )


@router.get("/uuid/{task_uuid}/download")
async def download_video_by_uuid(
    task_uuid: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """通过UUID下载视频"""
    from fastapi.responses import RedirectResponse
    
    result = await db.execute(
        select(Creation).where(
            Creation.uuid == task_uuid,
            Creation.owner_id == current_user.user_id
        )
    )
    creation = result.scalar_one_or_none()
    
    if not creation:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    extra = creation.extra_data or {}
    video_url = extra.get("video_url")
    
    if not video_url:
        raise HTTPException(status_code=400, detail="视频未生成完成")
    
    return RedirectResponse(url=video_url)
