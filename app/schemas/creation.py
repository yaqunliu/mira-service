from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class CreationBase(BaseModel):
    title: Optional[str] = None  # 可选，如果未提供则根据 novel 和 chapter 动态生成
    status: str = "created"


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
