from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Character(Base):
    """角色模型"""
    __tablename__ = "characters"
    
    character_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default="new")  # new, generated, confirmed
    basic_info = Column(String(500))  # 基本信息描述
    
    # 特征描述 (JSON格式存储)
    appearance = Column(Text)  # 外貌描述
    body = Column(Text)  # 身材描述
    hair = Column(Text)  # 发型描述
    clothing = Column(Text)  # 服装描述
    tags = Column(ARRAY(String))  # 标签 (字符串数组)
    
    # 图片相关
    image_prompt = Column(Text)  # 图片生成提示词
    visual_style = Column(String(100))  # 视觉风格
    image_url = Column(String(500))  # 角色图片URL
    
    # 外键
    novel_id = Column(Integer, ForeignKey("novels.novel_id"))
    creation_id = Column(Integer, ForeignKey("creations.creation_id"))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳
    
    # 关系
    novel = relationship("Novel", back_populates="characters")
    creation = relationship("Creation", back_populates="characters")
    shots = relationship("Shot", secondary="shot_characters", back_populates="characters")
