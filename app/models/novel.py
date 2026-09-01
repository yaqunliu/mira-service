from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Novel(Base):
    """小说模型"""
    __tablename__ = "novels"
    
    novel_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    title = Column(String(200), nullable=False, index=True)
    author = Column(String(100))
    chapter_count = Column(Integer, default=0)
    status = Column(String(20), default="uploaded")  # uploaded, processing, completed, partial, failed
    type = Column(String(20), default="novel", nullable=False) # novel: 小说项目, script: 剧本/文案项目
    task_id = Column(String(100), nullable=True, index=True)  # Celery任务ID，用于关联任务状态查询
    
    # 外键
    owner_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    
    # 关系
    owner = relationship("User", back_populates="novels")
    chapters = relationship(
        "Chapter", 
        back_populates="novel", 
        cascade="all, delete-orphan",
        primaryjoin="and_(Novel.novel_id == Chapter.novel_id, Chapter.deleted_at.is_(None))"
    )
    creations = relationship(
        "Creation", 
        back_populates="novel",
        primaryjoin="and_(Novel.novel_id == Creation.novel_id, Creation.deleted_at.is_(None))"
    )
    characters = relationship(
        "Character",
        back_populates="novel",
        primaryjoin="and_(Novel.novel_id == Character.novel_id, Character.deleted_at.is_(None))"
    )
    scenes = relationship(
        "Scene",
        back_populates="novel",
        primaryjoin="and_(Novel.novel_id == Scene.novel_id, Scene.deleted_at.is_(None))"
    )
