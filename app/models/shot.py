from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Table, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
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
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    title = Column(String(200), nullable=False)
    shot_number = Column(Integer, nullable=False)  # 分镜编号
    # 分镜内容
    description = Column(Text)  # 分镜描述
    narration = Column(Text)  # 旁白/解说词 (JSON字符串格式: [{"角色": "旁白", "内容": "..."}])
    image_prompt = Column(Text)  # 图片生成提示词
    image_url = Column(String(500), nullable=True)  # 分镜图片URL
    audio_url = Column(String(500), nullable=True)  # shot audio URL
    video_url = Column(String(500), nullable=True)  # shot video URL
    # 视频生成状态
    video_status = Column(String(20), nullable=True)  # pending, generating, completed, failed
    
    # 时长信息 (秒)
    video_duration = Column(Integer, default=5)

    # 生成状态跟踪
    status = Column(String(20), default="pending")  # pending, generating, completed, failed
    status_detail = Column(JSONB, nullable=True)  # 详细状态信息
    
    # V2 扩展数据 (存储 video_prompt, script_content, camera_movement 等)
    extra_data = Column(JSONB, nullable=True)
    
    # 外键
    scene_id = Column(Integer, ForeignKey("scenes.scene_id"), nullable=False)
    creation_id = Column(Integer, ForeignKey("creations.creation_id"), nullable=True)  # 关联的创作ID，用于区分不同创作的分镜
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    scene = relationship("Scene", back_populates="shots")
    characters = relationship("Character", secondary=shot_characters, back_populates="shots")
