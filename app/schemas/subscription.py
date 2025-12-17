from typing import Optional, List, Any
from pydantic import BaseModel, Field
from datetime import datetime
from app.schemas.product import Product


class Subscription(BaseModel):
    uuid: str
    subscription_id: int
    order_id: int
    user_id: int
    creem_subscription_id: str
    status: str
    billing_period: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    next_billing_date: Optional[datetime] = None
    points_per_period: int
    last_points_issued_at: Optional[datetime] = None
    cancel_at_period_end: Optional[bool] = None
    cancelled_at: Optional[datetime] = None
    metadata: Optional[Any] = Field(None, alias="subscription_metadata")
    product: Optional[Product] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class SubscriptionList(BaseModel):
    items: List[Subscription]
    total: int
    page: int
    page_size: int


class SubscriptionCancelRequest(BaseModel):
    cancel_at_period_end: bool = True

