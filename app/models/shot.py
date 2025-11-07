from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Table
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base

# 分镜与角色的多对多关系表
shot_characters = Table(
    'shot_characters',
    Base.metadata,
    Column('shot_id', Integer, ForeignKey('shots.shot_id'), primary_key=True),
    Column('character_id', Integer, ForeignKey('characters.character_id'), primary_key=True)
)


class Shot(Base):
    """分镜模型"""
    __tablename__ = "shots"
    
    shot_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    shot_number = Column(Integer, nullable=False)  # 分镜编号
    
    # 分镜内容
    description = Column(Text)  # 分镜描述
    narration = Column(Text)  # 旁白/解说词
    image_prompt = Column(Text)  # 图片生成提示词
    
    # 生成的资源
    image_url = Column(String(500))  # 分镜图片URL
    
    # 外键
    scene_id = Column(Integer, ForeignKey("scenes.scene_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    scene = relationship("Scene", back_populates="shots")
    characters = relationship("Character", secondary=shot_characters, back_populates="shots")
