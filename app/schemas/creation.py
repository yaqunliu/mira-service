from __future__ import annotations

from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, computed_field
from datetime import datetime


class CreationStatus(str, Enum):
    """创作状态枚举"""
    CREATED = "created"  # 已创建
    CHARACTER_ANALYZED = "character_analyzed"  # 角色已分析
    SCENES_ANALYZED = "scenes_analyzed"  # 场景已分析 (Step 2: 场景拆解)
    PLAYBOOK_GENERATED = "playbook_generated"  # 剧本已生成 (Step 3: 分镜拆解)
    CHARACTER_GENERATED = "character_generated"  # 角色已生成
    SCENE_GENERATED = "scene_generated"  # 分镜已生成
    VOICE_SELECTED = "voice_selected"  # 音色已选择
    AUDIO_GENERATED = "audio_generated"  # 音频已生成
    VIDEO_GENERATED = "video_generated"  # 视频已生成
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败


class CreationBase(BaseModel):
    title: Optional[str] = None  # 可选，如果未提供则根据 novel 和 chapter 动态生成
    status: str = CreationStatus.CREATED
    creation_type: str = "chapter"  # chapter: 章节创作, script: 文案创作
    preview_text: Optional[str] = None  # 文本预览，最多500字符
    text_content_url: Optional[str] = None  # 文本内容在US3上的存储URL


class CreationCreate(CreationBase):
    novel_id: Optional[int] = None  # 小说ID，如果是文案创作则为0
    chapter_id: Optional[int] = None  # 章节ID，如果是文案创作则为0
    creation_id: Optional[str] = None  # 可选的创作UUID，用于继续已存在但未成功的创作
    voice_id: Optional[str] = None  # Fish Audio 语音模型ID
    voice_speed: Optional[float] = Field(default=1.0, ge=0.0, le=10.0, description="语速设置，范围 0-10，默认 1.0")
    narration_mode: Optional[str] = Field(default="original", description="解说词模式：original（原文模式）或 rewrite（爽文模式），默认 original")
    extra_data: Optional[dict] = Field(default=None, description="扩展数据，存储创作配置（如模型选择等）")
    text_content: Optional[str] = None  # 临时字段，用于接收上传的文本内容，将被转换为预览和US3存储


class CreationUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    subtitle_url: Optional[str] = None
    voice_id: Optional[str] = None  # Fish Audio 语音模型ID
    voice_speed: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="语速设置，范围 0-10")
    extra_data: Optional[dict] = None
    timeline_config: Optional[dict] = None
    editing_status: Optional[str] = None
    character_ids: Optional[List[int]] = None


class Creation(CreationBase):
    creation_id: int
    uuid: str
    owner_id: int
    novel_id: int = 0
    chapter_id: int = 0
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    subtitle_url: Optional[str] = None  # 字幕文件URL
    voice_id: Optional[str] = None  # Fish Audio 语音模型ID
    voice_speed: float = Field(default=1.0, ge=0.0, le=10.0, description="语速设置，范围 0-10，默认 1.0")
    current_task_id: Optional[str] = None  # Celery任务ID
    created_at: datetime
    updated_at: Optional[datetime] = None
    # 关系字段（可选，只有在使用 selectinload 预加载时才会有数据）
    characters: Optional[List["Character"]] = None
    scenes: Optional[List["Scene"]] = None
    novel: Optional["Novel"] = None
    chapter: Optional["Chapter"] = None
    owner: Optional["User"] = None
    
    @computed_field
    @property
    def novel_uuid(self) -> Optional[str]:
        """从 novel 关系对象获取 UUID"""
        if self.novel and hasattr(self.novel, 'uuid'):
            return self.novel.uuid
        return None
    
    @computed_field
    @property
    def chapter_uuid(self) -> Optional[str]:
        """从 chapter 关系对象获取 UUID"""
        if self.chapter and hasattr(self.chapter, 'uuid'):
            return self.chapter.uuid
        return None
    
    class Config:
        from_attributes = True
