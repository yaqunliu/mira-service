from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from datetime import datetime


class PointsBalance(BaseModel):
    """积分余额信息"""
    total_points: int
    available_points: int
    frozen_points: int
    today_consumed: int
    month_consumed: int
    points_by_type: List[Dict[str, Any]]
    
    class Config:
        from_attributes = True


class PointsRecordBase(BaseModel):
    """积分记录基础模型"""
    record_type: str
    operation_type: Optional[str] = None
    points: int
    points_type: str = "normal"
    expires_at: Optional[datetime] = None
    balance_before: int
    balance_after: int
    creation_id: Optional[int] = None
    novel_id: Optional[int] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class PointsRecord(PointsRecordBase):
    """积分记录"""
    record_id: int
    account_id: int
    user_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class PointsRecordList(BaseModel):
    """积分记录列表"""
    items: List[PointsRecord]
    total: int
    page: int
    page_size: int


class PointsStatistics(BaseModel):
    """积分统计信息"""
    total_earned: int
    total_consumed: int
    today_consumed: int
    month_consumed: int
    by_operation_type: Dict[str, int]
