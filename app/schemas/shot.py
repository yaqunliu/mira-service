from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class ShotBase(BaseModel):
    title: str
    shot_number: int
    description: Optional[str] = None
    narration: Optional[str] = None
    image_prompt: Optional[str] = None


class ShotCreate(ShotBase):
    scene_id: int


class ShotUpdate(BaseModel):
    title: Optional[str] = None
    shot_number: Optional[int] = None
    description: Optional[str] = None
    narration: Optional[str] = None
    image_prompt: Optional[str] = None
    image_url: Optional[str] = None


class Shot(ShotBase):
    shot_id: int
    scene_id: int
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
