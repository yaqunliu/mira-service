from __future__ import annotations

from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime


class CreationStatus(str, Enum):
    """创作状态枚举"""
    CREATED = "created"  # 已创建
    PLAYBOOK_GENERATED = "playbook_generated"  # 剧本已生成
    CHARACTER_GENERATED = "character_generated"  # 角色已生成
    SCENE_GENERATED = "scene_generated"  # 分镜已生成
    VOICE_SELECTED = "voice_selected"  # 音色已选择
    AUDIO_GENERATED = "audio_generated"  # 音频已生成
    VIDEO_GENERATED = "video_generated"  # 视频已生成
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class CreationBase(BaseModel):
    title: Optional[str] = None  # 可选，如果未提供则根据 novel 和 chapter 动态生成
    status: str = CreationStatus.CREATED


class CreationCreate(CreationBase):
    novel_id: Optional[str] = None  # 小说UUID，如果提供了 creation_id，则可以为 None
    chapter_id: Optional[str] = None  # 章节UUID，如果提供了 creation_id，则可以为 None
    creation_id: Optional[str] = None  # 可选的创作UUID，用于继续已存在但未成功的创作
    voice_id: Optional[str] = None  # Fish Audio 语音模型ID
    voice_speed: Optional[float] = Field(default=1.0, ge=0.0, le=10.0, description="语速设置，范围 0-10，默认 1.0")


class CreationUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    subtitle_url: Optional[str] = None
    voice_id: Optional[str] = None  # Fish Audio 语音模型ID
    voice_speed: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="语速设置，范围 0-10")


class Creation(CreationBase):
    creation_id: int
    uuid: str
    owner_id: int
    novel_id: int
    chapter_id: int
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    subtitle_url: Optional[str] = None  # 字幕文件URL
    voice_id: Optional[str] = None  # Fish Audio 语音模型ID
    voice_speed: float = Field(default=1.0, ge=0.0, le=10.0, description="语速设置，范围 0-10，默认 1.0")
    current_task_id: Optional[str] = None  # Celery任务ID
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 关系字段（可选，只有在使用 selectinload 预加载时才会有数据）
    characters: Optional[List["Character"]] = None
    scenes: Optional[List["Scene"]] = None
    novel: Optional["Novel"] = None
    chapter: Optional["Chapter"] = None
    owner: Optional["User"] = None
    
    class Config:
        from_attributes = True
