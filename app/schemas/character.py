from typing import Optional
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
    tags: Optional[str] = None
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
    tags: Optional[str] = None
    image_prompt: Optional[str] = None
    visual_style: Optional[str] = None
    image_url: Optional[str] = None


class Character(CharacterBase):
    character_id: int
    novel_id: Optional[int] = None
    creation_id: Optional[int] = None
    image_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True
