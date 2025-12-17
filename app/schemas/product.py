from typing import List, Optional, Any
from pydantic import BaseModel, AnyUrl
from datetime import datetime


class Product(BaseModel):
    uuid: str
    product_id: int
    creem_product_id: str
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
    creem_mode: Optional[str] = None
    synced_at: Optional[datetime] = None
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

