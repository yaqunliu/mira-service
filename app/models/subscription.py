from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    subscription_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    order_id = Column(Integer, ForeignKey("orders.order_id"), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    creem_subscription_id = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, index=True)  # active / cancelled / expired / past_due
    billing_period = Column(String(50), nullable=False)
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))
    next_billing_date = Column(DateTime(timezone=True))
    points_per_period = Column(Integer, nullable=False)
    last_points_issued_at = Column(DateTime(timezone=True))
    cancel_at_period_end = Column(Boolean, default=False)
    cancelled_at = Column(DateTime(timezone=True))
    subscription_metadata = Column(JSON, name="metadata")  # 数据库列名保持为metadata，避免迁移
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    order = relationship("Order", back_populates="subscription")
    user = relationship("User")
    histories = relationship("SubscriptionPointsHistory", back_populates="subscription")

