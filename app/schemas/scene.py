from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


class SceneBase(BaseModel):
    title: str
    duration: Optional[str] = None
    time_setting: Optional[str] = None
    location: Optional[str] = None
    space_type: Optional[str] = None
    atmosphere: Optional[str] = None


class SceneCreate(SceneBase):
    creation_id: int


class SceneUpdate(BaseModel):
    title: Optional[str] = None
    duration: Optional[str] = None
    time_setting: Optional[str] = None
    location: Optional[str] = None
    space_type: Optional[str] = None
    atmosphere: Optional[str] = None


class Scene(SceneBase):
    scene_id: int
    creation_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 关系字段（可选，只有在使用 selectinload 预加载时才会有数据）
    shots: Optional[List["Shot"]] = None
    
    class Config:
        from_attributes = True
