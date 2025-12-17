from typing import Optional, List, Any
from pydantic import BaseModel, AnyUrl, Field
from datetime import datetime
from app.schemas.product import Product


class OrderCreate(BaseModel):
    product_uuid: str
    order_type: str  # onetime / subscription
    success_url: Optional[AnyUrl | str] = None
    cancel_url: Optional[AnyUrl | str] = None
    metadata: Optional[Any] = Field(None, alias="order_metadata")
    
    class Config:
        populate_by_name = True


class Order(BaseModel):
    uuid: str
    order_id: int
    order_number: str
    user_id: int
    product_id: int
    order_type: str
    status: str
    amount: int
    currency: str
    points_amount: int
    points_issued: int
    checkout_url: Optional[AnyUrl | str] = None
    creem_checkout_id: Optional[str] = None
    creem_transaction_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    success_url: Optional[AnyUrl | str] = None
    cancel_url: Optional[AnyUrl | str] = None
    metadata: Optional[Any] = Field(None, alias="order_metadata")
    product: Optional[Product] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class OrderList(BaseModel):
    items: List[Order]
    total: int
    page: int
    page_size: int

