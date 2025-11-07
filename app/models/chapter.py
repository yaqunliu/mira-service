from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base

class Chapter(Base):
    """章节模型"""
    __tablename__ = "chapters"
    
    chapter_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content_url = Column(String(500))
    chapter_number = Column(Integer, nullable=False)
    word_count = Column(Integer, default=0)
    
    # 外键
    novel_id = Column(Integer, ForeignKey("novels.novel_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    novel = relationship("Novel", back_populates="chapters")
    creation = relationship("Creation", back_populates="chapter")
