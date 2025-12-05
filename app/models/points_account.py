from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class PointsAccount(Base):
    """积分账户模型"""
    __tablename__ = "points_accounts"
    
    account_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(UUID(as_uuid=False), unique=True, nullable=False, index=True, 
                  default=lambda: str(uuid.uuid4()), 
                  server_default=sa_text('gen_random_uuid()'))
    user_id = Column(Integer, ForeignKey("users.user_id"), unique=True, nullable=False, index=True)
    total_points = Column(Integer, default=0, nullable=False)  # 总积分 = permanent_points + 未过期的临时积分
    available_points = Column(Integer, default=0, nullable=False)  # 可用积分 = total_points - frozen_points
    frozen_points = Column(Integer, default=0, nullable=False)  # 冻结积分
    permanent_points = Column(Integer, default=0, nullable=False)  # 长期积分（不会过期的积分）
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 关系
    user = relationship("User", back_populates="points_account")
    # 使用字符串列名，SQLAlchemy 会自动处理
    # 注意：relationship 的 order_by 不支持 desc()，如果需要降序，在查询时使用 order_by(desc(...))
    records = relationship("PointsRecord", back_populates="account", order_by="PointsRecord.created_at")
    temporary_points = relationship("TemporaryPoints", back_populates="account", order_by="TemporaryPoints.expires_at")
