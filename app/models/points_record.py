from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class PointsRecord(Base):
    """积分记录模型"""
    __tablename__ = "points_records"
    
    record_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    account_id = Column(Integer, ForeignKey("points_accounts.account_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    
    record_type = Column(String(20), nullable=False, index=True)  # consume, recharge, reward, refund, expire, checkin
    operation_type = Column(String(50), index=True)  # create_creation, generate_character, etc.
    
    points = Column(Integer, nullable=False)  # 正数增加，负数减少
    points_type = Column(String(20), default="normal")  # normal, daily_checkin
    expires_at = Column(DateTime(timezone=True), index=True, nullable=True)
    
    balance_before = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    
    creation_id = Column(Integer, ForeignKey("creations.creation_id"), index=True, nullable=True)
    novel_id = Column(Integer, ForeignKey("novels.novel_id"), index=True, nullable=True)
    
    description = Column(String(500))
    extra_data = Column(JSON)  # PostgreSQL JSON 类型（扩展信息，metadata 是 SQLAlchemy 保留字）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # 关系
    account = relationship("PointsAccount", back_populates="records")
    user = relationship("User")
    creation = relationship("Creation")
    novel = relationship("Novel")
