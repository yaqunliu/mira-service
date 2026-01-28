import math
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.services.points_async_service import PointsAsyncService
from app.core.exceptions import BaseServiceException, AlreadyCheckedInError
from app.utils.response import success_response
from app.core.config import settings

router = APIRouter()


class AddTestPointsRequest(BaseModel):
    user_id: int = Body(..., description="用户ID")
    points: int = Body(..., ge=1, description="积分数量")
    description: Optional[str] = Body(None, description="描述")


class PointsCheckRequest(BaseModel):
    operation_type: str
    model_name: Optional[str] = None
    estimated_prompt_tokens: Optional[int] = None
    estimated_completion_tokens: Optional[int] = None
    text_bytes: Optional[int] = None
    audio_duration_seconds: Optional[float] = None
    audio_model_name: Optional[str] = None
    shot_count: Optional[int] = None
    image_count: Optional[int] = None
    image_model_name: Optional[str] = None


@router.get("/balance", response_model=dict)
async def get_points_balance(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取积分余额
    """
    try:
        balance = await PointsAsyncService.get_balance(db, user.user_id)
        return success_response(data=balance, message="获取成功")
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取积分余额失败: {str(e)}")


@router.get("/records", response_model=dict)
async def get_points_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    record_type: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    creation_id: Optional[int] = Query(None),
    novel_id: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取积分记录列表
    """
    try:
        from app.services.points_async_service import PointsAsyncService
        
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if end_date:
            end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        records, total = await PointsAsyncService.get_points_history(
            db=db,
            user_id=user.user_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            record_type=record_type,
            operation_type=operation_type,
            creation_id=creation_id,
            novel_id=novel_id,
            start_date=start_datetime,
            end_date=end_datetime
        )
        
        items = []
        for record in records:
            item = {
                "record_id": record.record_id,
                "account_id": record.account_id,
                "user_id": record.user_id,
                "record_type": record.record_type,
                "operation_type": record.operation_type,
                "points": record.points,
                "points_type": record.points_type,
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
                "balance_before": record.balance_before,
                "balance_after": record.balance_after,
                "creation_id": record.creation_id,
                "novel_id": record.novel_id,
                "description": record.description,
                "metadata": record.extra_data,
                "created_at": record.created_at.isoformat()
            }
            items.append(item)
        
        return success_response(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size
            },
            message="获取成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取积分记录失败: {str(e)}")


@router.post("/checkin", response_model=dict)
async def checkin(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    每日签到
    """
    try:
        from app.services.points_async_service import PointsAsyncService
        record = await PointsAsyncService.checkin_reward(db, user.user_id)
        return success_response(
            data={
                "record_id": record.record_id,
                "points": record.points,
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
                "balance_after": record.balance_after
            },
            message="签到成功"
        )
    except AlreadyCheckedInError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"签到失败: {str(e)}")


@router.get("/statistics", response_model=dict)
async def get_points_statistics(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取积分统计信息
    """
    try:
        from app.services.points_async_service import PointsAsyncService
        
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if end_date:
            end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        statistics = await PointsAsyncService.get_statistics(
            db=db,
            user_id=user.user_id,
            start_date=start_datetime,
            end_date=end_datetime
        )
        
        return success_response(data=statistics, message="获取成功")
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取积分统计失败: {str(e)}")


@router.post("/check", response_model=dict)
async def check_points_availability(
    request: PointsCheckRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    检查积分是否充足
    """
    try:
        account = await PointsAsyncService.get_or_create_account(db, user.user_id)
        available_points = account.available_points
        
        required_points = 0
        operation_type = request.operation_type
        
        if operation_type == "llm_call":
            if available_points > 0:
                return success_response(
                    data={
                        "available": True,
                        "required_points": 0,
                        "available_points": available_points,
                        "message": "积分充足，可以调用"
                    },
                    message="检查成功"
                )
            else:
                return success_response(
                    data={
                        "available": False,
                        "required_points": 0,
                        "available_points": available_points,
                        "message": "积分不足，无法调用"
                    },
                    message="检查成功"
                )
        
        elif operation_type == "generate_video":
            if not request.shot_count:
                raise HTTPException(status_code=400, detail="视频生成需要提供 shot_count 参数")
            required_points = request.shot_count or 1
        
        elif operation_type == "generate_image":
            required_points = request.image_count or 1
        
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作类型: {operation_type}")
        
        if available_points >= required_points and available_points > 0:
            return success_response(
                data={
                    "available": True,
                    "required_points": required_points,
                    "available_points": available_points,
                    "message": f"积分充足，可以执行操作"
                },
                message="检查成功"
            )
        else:
            return success_response(
                data={
                    "available": False,
                    "required_points": required_points,
                    "available_points": available_points,
                    "message": f"积分不足（需要 {required_points} 积分）"
                },
                message="检查成功"
            )
    
    except HTTPException:
        raise
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检查积分失败: {str(e)}")


@router.post("/test/add-points", response_model=dict)
async def add_test_points(
    request: AddTestPointsRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    测试接口：为指定用户添加积分
    """
    if not settings.DEBUG:
        raise HTTPException(status_code=403, detail="此接口仅在DEBUG模式下可用")
    
    try:
        from app.services.points_async_service import PointsAsyncService
        
        record = await PointsAsyncService.add_points(
            db=db,
            user_id=request.user_id,
            points=request.points,
            record_type="reward",
            operation_type="test_add_points",
            description=request.description or f"测试添加积分",
            extra_data={
                "added_by": user.user_id,
                "added_by_username": user.username,
                "is_test": True
            }
        )
        
        balance = await PointsAsyncService.get_balance(db, request.user_id)
        
        return success_response(
            data={
                "record_id": record.record_id,
                "points_added": request.points,
                "balance": balance,
                "message": f"成功添加 {request.points} 积分"
            },
            message="添加积分成功"
        )
    
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加积分失败: {str(e)}")
