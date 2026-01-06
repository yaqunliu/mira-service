from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


class CharacterBase(BaseModel):
    name: str
    status: str = "new"
    basic_info: Optional[str] = None
    appearance: Optional[str] = None
    body: Optional[str] = None
    hair: Optional[str] = None
    clothing: Optional[str] = None
    tags: Optional[List[str]] = None  # JSON数组
    voice_description: Optional[str] = None
    image_prompt: Optional[str] = None
    visual_style: Optional[str] = None


class CharacterCreate(CharacterBase):
    creation_id: int
    novel_id: Optional[int] = None


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    basic_info: Optional[str] = None
    appearance: Optional[str] = None
    body: Optional[str] = None
    hair: Optional[str] = None
    clothing: Optional[str] = None
    tags: Optional[List[str]] = None  # JSON数组
    voice_description: Optional[str] = None
    image_prompt: Optional[str] = None
    visual_style: Optional[str] = None
    image_url: Optional[str] = None


class CharacterGenerateImagesRequest(BaseModel):
    """生成角色图片请求"""
    character_ids: List[str]  # UUID列表
    visual_style: str
    creation_uuid: str  # 创作UUID，用于在Celery任务中获取creation
    force_regenerate: bool = False  # 是否强制重新生成（False: 跳过已有图片的角色，True: 强制生成所有）


class CharacterRegenerateImageRequest(BaseModel):
    """单个角色重新生成图片请求"""
    character_uuid: str
    visual_style: str
    creation_uuid: str


class Character(CharacterBase):
    character_id: int
    uuid: str
    novel_id: Optional[int] = None
    creation_id: Optional[int] = None
    image_url: Optional[str] = None
    voice_description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
