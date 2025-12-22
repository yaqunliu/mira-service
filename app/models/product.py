from sqlalchemy import Column, DateTime, Integer, String, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
from app.db.base import Base


class Product(Base):
    """产品表 - 支持多语言和多支付方式"""
    __tablename__ = "products"

    product_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    payment_method = Column(String(20), nullable=False, index=True)  # creem, wechat
    language = Column(String(10), nullable=False, index=True)  # zh, en, ja等
    origin_product_id = Column(String(100), index=True)  # 远程产品ID（用于购买对应的远程产品，如Creem需要传递产品ID）
    name = Column(String(200), nullable=False)
    description = Column(Text)
    price = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False, index=True)  # USD, CNY
    billing_type = Column(String(20), nullable=False, index=True)  # onetime, recurring
    billing_period = Column(String(50))
    points_amount = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, index=True)  # active, inactive
    image_url = Column(String(500))
    product_url = Column(String(500))
    features = Column(JSON)
    product_metadata = Column(JSON, name="product_metadata")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    orders = relationship("Order", back_populates="product")

