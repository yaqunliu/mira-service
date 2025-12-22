from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class CreemPayment(Base):
    """Creem支付详情表"""
    __tablename__ = "creem_payments"

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
    creem_checkout_id = Column(String(100), unique=True, index=True)
    creem_transaction_id = Column(String(100), index=True)
    checkout_url = Column(String(500))
    payment_metadata = Column(JSON, name="payment_metadata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    order = relationship("Order", back_populates="creem_payment")

