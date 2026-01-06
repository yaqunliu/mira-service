from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base

class Chapter(Base):
    """章节模型"""
    __tablename__ = "chapters"
    
    chapter_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    title = Column(String(200), nullable=False)
    content_url = Column(String(500))
    chapter_number = Column(Integer, nullable=False)
    word_count = Column(Integer, default=0)
    preview = Column(String(100))  # 章节内容预览，前100个字
    
    # 外键
    novel_id = Column(Integer, ForeignKey("novels.novel_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    
    # 关系
    novel = relationship("Novel", back_populates="chapters")
    creation = relationship(
        "Creation", 
        back_populates="chapter",
        primaryjoin="and_(Chapter.chapter_id == Creation.chapter_id, Creation.deleted_at.is_(None))"
    )
