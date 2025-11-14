from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class Novel(Base):
    """小说模型"""
    __tablename__ = "novels"
    
    novel_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, index=True)
    author = Column(String(100))
    chapter_count = Column(Integer, default=0)
    status = Column(String(20), default="uploaded")  # uploaded, processing, completed
    task_id = Column(String(100), nullable=True, index=True)  # Celery任务ID，用于关联任务状态查询
    
    # 外键
    owner_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    owner = relationship("User", back_populates="novels")
    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan")
    creations = relationship("Creation", back_populates="novel")
    characters = relationship("Character", back_populates="novel")
