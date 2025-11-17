from typing import Optional
from enum import Enum
from pydantic import BaseModel
from datetime import datetime


class CreationStatus(str, Enum):
    """创作状态枚举"""
    CREATED = "created"  # 已创建
    PLAYBOOK_GENERATED = "playbook_generated"  # 剧本已生成
    CHARACTER_GENERATED = "character_generated"  # 角色已生成
    SCENE_GENERATED = "scene_generated"  # 场景已生成
    AUDIO_GENERATED = "audio_generated"  # 音频已生成
    VIDEO_GENERATED = "video_generated"  # 视频已生成
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class CreationBase(BaseModel):
    title: Optional[str] = None  # 可选，如果未提供则根据 novel 和 chapter 动态生成
    status: str = CreationStatus.CREATED


class CreationCreate(CreationBase):
    novel_id: int
    chapter_id: int


class CreationUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None


class Creation(CreationBase):
    creation_id: int
    owner_id: int
    novel_id: int
    chapter_id: int
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
