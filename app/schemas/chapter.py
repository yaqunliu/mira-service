from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime

class ChapterBase(BaseModel):
    title: str
    content_url: Optional[str] = None
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