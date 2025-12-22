from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class WechatPayment(Base):
    """微信支付详情表"""
    __tablename__ = "wechat_payments"

    payment_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    order_id = Column(Integer, ForeignKey("orders.order_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    wechat_transaction_id = Column(String(100), index=True)  # 微信支付订单号
    out_trade_no = Column(String(100), unique=True, nullable=False, index=True)  # 商户订单号
    code_url = Column(String(500))  # 二维码链接(Native支付)
    prepay_id = Column(String(100))  # 预支付交易会话ID
    payment_metadata = Column(JSON, name="payment_metadata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    order = relationship("Order", back_populates="wechat_payment")

