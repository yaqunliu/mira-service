from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


class ChapterBase(BaseModel):
    title: str
    content: str
    chapter_number: int
    word_count: int = 0


class ChapterCreate(ChapterBase):
    novel_id: int


class Chapter(ChapterBase):
    chapter_id: int
    novel_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class NovelBase(BaseModel):
    title: str
    author: Optional[str] = None
    chapter_count: int = 0
    status: str = "uploaded"


class NovelCreate(NovelBase):
    content: Optional[str] = None
    file_path: Optional[str] = None


class NovelUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    status: Optional[str] = None


class Novel(NovelBase):
    novel_id: int
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    chapters: List[Chapter] = []
    
    class Config:
        from_attributes = True
