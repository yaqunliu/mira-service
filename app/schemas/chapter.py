from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime

class ChapterBase(BaseModel):
    title: str
    content_url: Optional[str] = None
    chapter_number: Optional[int] = None
    word_count: int = 0
    preview: Optional[str] = None  # 章节内容预览，前100个字


class ChapterCreate(ChapterBase):
    novel_id: Optional[int] = None
    content: Optional[str] = Field(None, max_length=3000)  # Added for creating chapter from text, max length 3000
    chapter_number: Optional[int] = None # Optional, can be auto-generated


class ChapterUpdate(BaseModel):
    title: Optional[str] = None


class Chapter(ChapterBase):
    chapter_id: int
    uuid: str
    novel_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True