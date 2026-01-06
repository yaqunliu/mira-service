from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime
from app.schemas.chapter import Chapter

class NovelBase(BaseModel):
    title: str
    author: Optional[str] = None
    chapter_count: int = 0
    status: str = "uploaded"


class NovelCreate(NovelBase):
    content: Optional[str] = None
    file_path: Optional[str] = None
    type: str = "novel"  # novel or script


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None


class Novel(NovelBase):
    novel_id: int
    uuid: str
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    chapters: List[Chapter] = []
    
    class Config:
        from_attributes = True
