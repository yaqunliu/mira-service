"""
Fish Audio Voice 相关的 Schema 定义
"""

from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class VoiceTag(str, Enum):
    """语音标签枚举"""
    MALE = "male"
    FEMALE = "female"
    CARTOON = "cartoon"


class VoiceSample(BaseModel):
    """语音样本"""
    title: str
    text: str
    task_id: Optional[str] = None
    audio: Optional[str] = None


class VoiceAuthor(BaseModel):
    """语音作者信息"""
    id: str
    nickname: str
    avatar: Optional[str] = None


class VoiceItem(BaseModel):
    """语音模型项"""
    id: str
    title: str
    description: Optional[str] = None
    cover_image: Optional[str] = None
    train_mode: Optional[str] = None
    state: Optional[str] = None
    tags: List[str] = []
    samples: List[VoiceSample] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    languages: List[str] = []
    visibility: Optional[str] = None
    like_count: int = 0
    mark_count: int = 0
    shared_count: int = 0
    task_count: int = 0
    liked: bool = False
    marked: bool = False
    author: Optional[VoiceAuthor] = None


class VoiceListResponse(BaseModel):
    """语音列表响应"""
    total: int = Field(description="总数")
    items: List[VoiceItem] = Field(description="语音列表")
    page_size: int = Field(description="每页数量")
    page_number: int = Field(description="当前页码")


class VoiceQueryParams(BaseModel):
    """语音查询参数"""
    language: str = Field(default="zh", description="语言，默认中文")
    page_size: int = Field(default=10, ge=1, le=100, description="每页数量，默认10")
    page_number: int = Field(default=1, ge=1, description="页码，默认1")
    title: Optional[str] = Field(default=None, description="按标题模糊搜索")
    tag: Optional[VoiceTag] = Field(default=None, description="按标签筛选: male(男性), female(女性), cartoon(卡通)")

