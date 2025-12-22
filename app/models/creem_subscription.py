from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class CreemSubscription(Base):
    """Creem订阅详情表"""
    __tablename__ = "creem_subscriptions"

    subscription_detail_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    subscription_id = Column(Integer, ForeignKey("subscriptions.subscription_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    creem_subscription_id = Column(String(100), unique=True, nullable=False, index=True)
    subscription_metadata = Column(JSON, name="subscription_metadata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    subscription = relationship("Subscription", back_populates="creem_subscription")

