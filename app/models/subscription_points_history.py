from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class SubscriptionPointsHistory(Base):
    __tablename__ = "subscription_points_history"

    history_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    subscription_id = Column(Integer, ForeignKey("subscriptions.subscription_id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.order_id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    points_record_id = Column(Integer, ForeignKey("points_records.record_id"), index=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    points_amount = Column(Integer, nullable=False)
    issued_at = Column(DateTime(timezone=True), server_default=func.now())
    payment_method = Column(String(20), index=True)  # creem, wechat
    invoice_id = Column(String(100), index=True)  # 通用发票ID（替代creem_invoice_id）
    
    # 保留旧字段以便数据迁移（后续可删除）
    creem_invoice_id = Column(String(100), index=True, nullable=True)

    subscription = relationship("Subscription", back_populates="histories")
    order = relationship("Order")
    user = relationship("User")

