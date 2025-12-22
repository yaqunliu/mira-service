from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, JSON, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class WechatSubscription(Base):
    """微信订阅详情表"""
    __tablename__ = "wechat_subscriptions"

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
    wechat_contract_id = Column(String(100), unique=True, index=True)  # 微信签约协议号
    wechat_plan_id = Column(Integer)  # 协议模板ID
    wechat_request_serial = Column(BigInteger)  # 请求序列号
    subscription_metadata = Column(JSON, name="subscription_metadata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    subscription = relationship("Subscription", back_populates="wechat_subscription")

