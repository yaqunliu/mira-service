from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class Creation(Base):
    """创作模型"""
    __tablename__ = "creations"
    
    creation_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    status = Column(String(20), default="created")  # created、character_generated、scene_generated、audio_generated、video_generated、completed、failed
    video_url = Column(String(500))  # 最终视频URL
    audio_url = Column(String(500))  # 最终音频URL
    
    # 外键
    owner_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.novel_id"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.chapter_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    owner = relationship("User", back_populates="creations")
    novel = relationship("Novel", back_populates="creations")
    chapter = relationship("Chapter", back_populates="creation")
    characters = relationship("Character", back_populates="creation")
    scenes = relationship("Scene", back_populates="creation", cascade="all, delete-orphan")
    resources = relationship("Resource", back_populates="creation")
