from typing import Optional
from pydantic import BaseModel, confloat


class RefundRequest(BaseModel):
    refund_reason: Optional[str] = None
    force: bool = False  # 是否忽略使用率阈值，强制退款（管理员使用）


class RefundResponse(BaseModel):
    refund_amount: int  # 分
    refunded_points: int
    refund_ratio: confloat(ge=0, le=1)  # 0~1
    status: str
    message: Optional[str] = None

