from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Creation(Base):
    """创作模型"""
    __tablename__ = "creations"
    
    creation_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    title = Column(String(200), nullable=False, index=True)
    status = Column(String(20), default="created")  # created、character_generated、scene_generated、audio_generated、video_generated、completed、failed
    video_url = Column(String(500))  # 最终视频URL
    audio_url = Column(String(500))  # 最终音频URL（合并后的完整音频）
    subtitle_url = Column(String(500))  # 字幕文件URL（SRT格式）
    voice_id = Column(String(100), nullable=True)  # Fish Audio 语音模型ID，用于TTS生成
    voice_speed = Column(Float, default=1.0, nullable=False)  # 语速设置，范围 0-10，默认 1.0
    
    # 视频生成配置
    video_generation_mode = Column(String(20), default="old")  # old: 旧版快速生成, new: 新版高质量生成
    video_generation_strategy = Column(String(20), default="ai_video")  # ai_video: AI图生视频, image_effects: 静态图片+特效
    
    # 音频策略
    audio_strategy = Column(String(20), default="tts")  # tts: 纯TTS, ai_audio: AI生成音频（优先）+ TTS备选
    
    # 外键
    owner_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.novel_id"), default=0, nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.chapter_id"), default=0, nullable=False)
    
    # 新增字段
    creation_type = Column(String(20), default="chapter", nullable=False)  # chapter: 章节创作, script: 文案创作
    preview_text = Column(String(500), nullable=True)  # 文本预览，最多500字符
    text_content_url = Column(String(500), nullable=True)  # 文本内容在US3上的存储URL
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    current_task_id = Column(String(100), nullable=True, index=True)  # Celery任务ID，用于关联当前正在执行任务的状态
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    extra_data = Column(JSONB, nullable=True)  # 扩展数据，存储创作配置（如模型选择、模式选择等）
    character_ids = Column(JSONB, nullable=True)  # 关联的角色ID列表，包括新建和复用的角色
    scene_ids = Column(JSONB, nullable=True)  # 关联的场景ID列表，包括新建和复用的场景

    # 新版高质量生成流程字段
    timeline_config = Column(JSONB, nullable=True)  # 多轨道编辑配置（存储视频轨、音频轨、文案轨等信息）
    editing_status = Column(String(20), nullable=True)  # 编辑状态：editing, previewing, completed
    
    # 关系
    owner = relationship("User", back_populates="creations")
    novel = relationship(
        "Novel", 
        back_populates="creations",
        primaryjoin="and_(Creation.novel_id == Novel.novel_id, Creation.deleted_at.is_(None))"
    )
    chapter = relationship(
        "Chapter", 
        back_populates="creation",
        primaryjoin="and_(Creation.chapter_id == Chapter.chapter_id, Chapter.deleted_at.is_(None))"
    )
    characters = relationship("Character", back_populates="creation", order_by="Character.character_id")
    scenes = relationship("Scene", back_populates="creation", cascade="all, delete-orphan", order_by="Scene.scene_id")
