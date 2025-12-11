from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime


class CharacterBrief(BaseModel):
    """角色简要信息（用于镜头响应中）"""
    character_id: int
    name: str
    
    class Config:
        from_attributes = True


class ShotBase(BaseModel):
    title: str
    shot_number: int
    description: Optional[str] = None
    narration: Optional[str] = None
    image_prompt: Optional[str] = None


class ShotCreate(BaseModel):
    """创建镜头的请求体"""
    title: str
    shot_number: Optional[int] = None  # 如果不提供，自动生成
    description: Optional[str] = None
    narration: Optional[str] = None
    image_prompt: Optional[str] = None
    scene_id: int
    character_ids: Optional[List[int]] = None  # 关联的角色ID列表


class ShotUpdate(BaseModel):
    """更新镜头的请求体"""
    title: Optional[str] = None
    shot_number: Optional[int] = None
    description: Optional[str] = None
    narration: Optional[str] = None
    image_prompt: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    character_ids: Optional[List[int]] = None  # 更新关联的角色


class Shot(ShotBase):
    """镜头响应模型"""
    shot_id: int
    uuid: str
    scene_id: int
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    audio_duration: Optional[int] = None  # 音频时长（毫秒）
    created_at: datetime
    updated_at: Optional[datetime] = None
    characters: Optional[List[CharacterBrief]] = None
    
    class Config:
        from_attributes = True


class ShotResponse(BaseModel):
    """镜头响应（前端格式）"""
    shot_id: int = Field(..., alias="shotId")
    uuid: str = Field(..., alias="uuid")
    title: str
    associated_characters: List[int] = Field(default_factory=list, alias="associatedCharacters")
    scene_description: Optional[str] = Field(None, alias="sceneDescription")
    narration: Optional[str] = None
    image_prompt: Optional[str] = Field(None, alias="imagePrompt")
    shot_image: Optional[str] = Field(None, alias="shotImage")
    shot_number: int = Field(..., alias="shotNumber")
    
    class Config:
        from_attributes = True
        populate_by_name = True
    
    @classmethod
    def from_db_model(cls, shot) -> "ShotResponse":
        """从数据库模型转换"""
        return cls(
            shotId=shot.shot_id,
            uuid=shot.uuid,
            title=shot.title,
            associatedCharacters=[char.character_id for char in shot.characters] if shot.characters else [],
            sceneDescription=shot.description,
            narration=shot.narration,
            imagePrompt=shot.image_prompt,
            shotImage=shot.image_url,
            shotNumber=shot.shot_number
        )


class ShotListResponse(BaseModel):
    """镜头列表响应"""
    items: List[ShotResponse]
    total: int


class ShotRegenerateRequest(BaseModel):
    """重新生成分镜图片的请求体"""
    image_prompt: Optional[str] = None  # 新的图片提示词（可选，不传则使用现有提示词）


class ShotCharactersUpdateRequest(BaseModel):
    """更新分镜关联角色的请求体"""
    character_ids: List[int]
