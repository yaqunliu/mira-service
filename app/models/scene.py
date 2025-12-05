from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Scene(Base):
    """场景模型"""
    __tablename__ = "scenes"
    
    scene_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    title = Column(String(200), nullable=False)
    duration = Column(String(20))  # 时长格式: "00:00:30"
    
    # 场景设置
    time_setting = Column(String(50))  # 时间设置
    location = Column(String(200))  # 地点
    space_type = Column(String(50))  # 空间类型: 室内/室外
    atmosphere = Column(String(100))  # 氛围描述
    
    # 外键
    creation_id = Column(Integer, ForeignKey("creations.creation_id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    creation = relationship("Creation", back_populates="scenes")
    shots = relationship("Shot", back_populates="scene", cascade="all, delete-orphan", order_by="Shot.shot_id")
