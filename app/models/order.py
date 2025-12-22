from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Order(Base):
    """统一订单表 - 不包含任何支付方式特定字段"""
    __tablename__ = "orders"

    order_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    order_number = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.product_id"), nullable=False, index=True)
    payment_method = Column(String(20), nullable=False, index=True)  # creem, wechat
    order_type = Column(String(20), nullable=False, index=True)  # onetime, subscription
    status = Column(String(20), nullable=False, index=True)  # pending, paid, failed, cancelled, refunded
    amount = Column(Integer, nullable=False)  # 金额(分)
    currency = Column(String(10), nullable=False, default="USD")
    points_amount = Column(Integer, nullable=False)
    points_issued = Column(Integer, nullable=False, default=0)  # 0/1 用整数兼容旧版本
    success_url = Column(String(500))
    cancel_url = Column(String(500))
    paid_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))
    order_metadata = Column(JSON, name="order_metadata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    product = relationship("Product", back_populates="orders")
    subscription = relationship("Subscription", back_populates="order", uselist=False)
    user = relationship("User")
    creem_payment = relationship("CreemPayment", back_populates="order", uselist=False, cascade="all, delete-orphan")
    wechat_payment = relationship("WechatPayment", back_populates="order", uselist=False, cascade="all, delete-orphan")

