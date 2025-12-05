from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

class ChapterBase(BaseModel):
    title: str
    content_url: Optional[str] = None
    chapter_number: int
    word_count: int = 0
    preview: Optional[str] = None  # 章节内容预览，前30个字


class ChapterCreate(ChapterBase):
    novel_id: int


class ChapterUpdate(BaseModel):
    title: Optional[str] = None


class Chapter(ChapterBase):
    chapter_id: int
    uuid: str
    novel_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True