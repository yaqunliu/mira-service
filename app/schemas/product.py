from typing import List, Optional, Any
from pydantic import BaseModel, AnyUrl
from datetime import datetime


class Product(BaseModel):
    uuid: str
    product_id: int
    payment_method: str  # creem, wechat
    language: str  # zh, en, ja等
    origin_product_id: Optional[str] = None  # 远程产品ID（用于购买对应的远程产品）
    name: str
    description: Optional[str] = None
    price: int
    currency: str
    billing_type: str
    billing_period: Optional[str] = None
    points_amount: int
    status: str
    image_url: Optional[AnyUrl | str] = None
    product_url: Optional[AnyUrl | str] = None
    features: Optional[Any] = None
    product_metadata: Optional[Any] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProductList(BaseModel):
    items: List[Product]
    total: int
    page: int
    page_size: int


class ProductSyncResult(BaseModel):
    synced_count: int
    updated_count: int
    created_count: int

