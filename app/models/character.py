from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class Character(Base):
    """角色模型"""
    __tablename__ = "characters"
    
    character_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default="new")  # new, generated, confirmed
    basic_info = Column(String(500))  # 基本信息描述
    
    # 特征描述 (JSON格式存储)
    appearance = Column(Text)  # 外貌描述
    body = Column(Text)  # 身材描述
    hair = Column(Text)  # 发型描述
    clothing = Column(Text)  # 服装描述
    tags = Column(Text)  # 标签 (JSON数组)
    
    # 图片相关
    image_prompt = Column(Text)  # 图片生成提示词
    visual_style = Column(String(100))  # 视觉风格
    image_url = Column(String(500))  # 角色图片URL
    
    # 外键
    novel_id = Column(Integer, ForeignKey("novels.novel_id"))
    creation_id = Column(Integer, ForeignKey("creations.creation_id"))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    novel = relationship("Novel", back_populates="characters")
    creation = relationship("Creation", back_populates="characters")
    shots = relationship("Shot", secondary="shot_characters", back_populates="characters")
