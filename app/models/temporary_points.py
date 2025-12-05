from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class TemporaryPoints(Base):
    """临时积分表（会过期的积分，如签到、活动等）"""
    __tablename__ = "temporary_points"
    
    temp_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    account_id = Column(Integer, ForeignKey("points_accounts.account_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    
    points = Column(Integer, nullable=False)  # 积分数量（正数）
    source_type = Column(String(20), nullable=False, index=True)  # 来源类型：checkin（签到）、activity（活动）等
    source_id = Column(Integer, nullable=True)  # 来源ID（如签到记录的record_id，活动ID等）
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)  # 过期时间（必须）
    expire_record_id = Column(Integer, ForeignKey("points_records.record_id"), nullable=True, index=True)  # 关联的过期记录ID（如果已创建过期记录）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # 关系
    account = relationship("PointsAccount", back_populates="temporary_points")
    user = relationship("User")
    expire_record = relationship("PointsRecord", foreign_keys=[expire_record_id])
