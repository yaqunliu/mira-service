from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
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
    image_url = Column(String(500), nullable=True)  # 场景图片URL
    
    # 生成状态跟踪
    status = Column(String(20), default="pending")  # pending, generating, completed, failed
    status_detail = Column(JSONB, nullable=True)  # 详细状态信息
    
    # V2 扩展数据 (存储 environment_images, lighting_info 等)
    extra_data = Column(JSONB, nullable=True)

    # 外键
    novel_id = Column(Integer, ForeignKey("novels.novel_id"), nullable=True, index=True)  # 关联的小说ID,用于场景复用
    creation_id = Column(Integer, ForeignKey("creations.creation_id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)  # 软删除时间戳

    # 关系
    novel = relationship("Novel", back_populates="scenes")
    creation = relationship("Creation", back_populates="scenes")
    shots = relationship("Shot", back_populates="scene", cascade="all, delete-orphan", order_by="Shot.shot_id")
