import math
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.points_service import PointsService
from app.core.exceptions import BaseServiceException, AlreadyCheckedInError
from app.utils.response import success_response
from app.schemas.points import PointsBalance, PointsRecordList, PointsStatistics
from app.utils.model_prices import ModelPrices
from app.core.config import settings

router = APIRouter()


class AddTestPointsRequest(BaseModel):
    """测试添加积分请求"""
    user_id: int = Body(..., description="用户ID")
    points: int = Body(..., ge=1, description="要添加的积分数量（必须大于0）")
    description: Optional[str] = Body(None, description="描述（可选）")


@router.get("/balance", response_model=dict)
async def get_points_balance(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取积分余额
    
    返回：
    - 总积分余额
    - 可用积分
    - 冻结积分
    - 今日消耗
    - 本月消耗
    - 按积分类型分组的余额信息
    """
    try:
        balance = PointsService.get_account_balance(db, user.user_id)
        return success_response(data=balance, message="获取成功")
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取积分余额失败: {str(e)}")


@router.get("/records", response_model=dict)
async def get_points_records(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    record_type: Optional[str] = Query(None, description="记录类型：consume, recharge, reward, refund, expire, checkin（默认排除 freeze 和 release 类型）"),
    operation_type: Optional[str] = Query(None, description="操作类型"),
    creation_id: Optional[int] = Query(None, description="创作ID"),
    novel_id: Optional[int] = Query(None, description="小说ID"),
    start_date: Optional[str] = Query(None, description="开始日期（ISO格式）"),
    end_date: Optional[str] = Query(None, description="结束日期（ISO格式）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取积分记录列表
    
    支持筛选：
    - 记录类型
    - 操作类型
    - 创作ID
    - 小说ID
    - 时间范围
    """
    try:
        # 解析日期
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if end_date:
            end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        records, total = PointsService.get_records(
            db=db,
            user_id=user.user_id,
            page=page,
            page_size=page_size,
            record_type=record_type,
            operation_type=operation_type,
            creation_id=creation_id,
            novel_id=novel_id,
            start_date=start_datetime,
            end_date=end_datetime
        )
        
        # 转换为字典列表
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
                "metadata": record.extra_data,  # 注意：API 返回时仍使用 metadata 字段名，但数据库字段是 extra_data
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    每日签到
    
    每日只能签到一次，签到后获得积分（可能有过期时间）
    """
    try:
        record = PointsService.checkin_reward(db, user.user_id)
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
    start_date: Optional[str] = Query(None, description="开始日期（ISO格式）"),
    end_date: Optional[str] = Query(None, description="结束日期（ISO格式）"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取积分统计信息
    
    返回：
    - 总获得积分
    - 总消耗积分
    - 今日消耗
    - 本月消耗
    - 按操作类型统计的消耗
    """
    try:
        # 解析日期
        start_datetime = None
        end_datetime = None
        if start_date:
            start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if end_date:
            end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        statistics = PointsService.get_statistics(
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


# ========== 积分检查 API ==========

class PointsCheckRequest(BaseModel):
    """积分检查请求"""
    operation_type: str  # 操作类型：llm_call, generate_audio, generate_video, generate_image
    # LLM调用参数
    model_name: Optional[str] = None  # 模型名称（LLM调用需要）
    estimated_prompt_tokens: Optional[int] = None  # 预估输入token数（LLM调用需要）
    estimated_completion_tokens: Optional[int] = None  # 预估输出token数（LLM调用需要）
    # 音频生成参数
    text_bytes: Optional[int] = None  # 文本字节数（音频生成需要）
    audio_duration_seconds: Optional[float] = None  # 音频时长（秒，音频生成需要）
    audio_model_name: Optional[str] = None  # 音频模型名称（音频生成需要）
    # 视频生成参数
    shot_count: Optional[int] = None  # 视频片段数（视频生成需要）
    # 图片生成参数
    image_count: Optional[int] = None  # 图片数量（图片生成需要）
    image_model_name: Optional[str] = None  # 图片模型名称（图片生成需要）


@router.post("/check", response_model=dict)
async def check_points_availability(
    request: PointsCheckRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    检查积分是否充足，是否可以执行操作
    
    规则：
    - LLM调用（后付费）：只要积分 > 0 就可以调用
    - 其他操作（预付费）：计算需要扣除的积分，检查是否充足
    
    返回：
    - available: 是否可用
    - required_points: 需要扣除的积分（如果是LLM调用，返回0）
    - available_points: 当前可用积分
    - message: 提示信息
    """
    try:
        # 获取账户余额
        account = PointsService.get_or_create_account(db, user.user_id)
        available_points = account.available_points
        
        # 根据操作类型计算需要的积分
        required_points = 0
        operation_type = request.operation_type
        
        if operation_type == "llm_call":
            # LLM调用：后付费，只要积分 > 0 就可以
            if available_points > 0:
                return success_response(
                    data={
                        "available": True,
                        "required_points": 0,  # LLM后付费，不预扣
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
                        "message": "积分不足，无法调用（需要积分 > 0）"
                    },
                    message="检查成功"
                )
        
        elif operation_type == "generate_audio":
            # 音频生成：按文本字节数计算成本
            if not request.text_bytes:
                raise HTTPException(status_code=400, detail="音频生成需要提供 text_bytes 参数")
            
            audio_model = request.audio_model_name or settings.FISH_AUDIO_DEFAULT_VOICE_ID or "s1"
            cost = ModelPrices.calculate_audio_cost(audio_model, request.text_bytes)
            required_points = int(math.ceil(cost * 100))  # 每1元=100积分，向上取整
            # 确保至少1积分
            if required_points <= 0:
                required_points = 1
        
        elif operation_type == "generate_video":
            # 视频生成：每个片段1积分
            if not request.shot_count:
                raise HTTPException(status_code=400, detail="视频生成需要提供 shot_count 参数")
            
            required_points = request.shot_count
            # 确保至少1积分
            if required_points <= 0:
                required_points = 1
        
        elif operation_type == "generate_image":
            # 图片生成：按实际成本计算
            if not request.image_count:
                raise HTTPException(status_code=400, detail="图片生成需要提供 image_count 参数")
            
            # 如果没有指定模型，默认使用图生图模型（分镜图片通常使用图生图）
            # 如果指定了模型，使用指定的模型
            if request.image_model_name:
                image_model = request.image_model_name
            else:
                # 默认使用图生图模型（分镜图片），如果没有配置则使用文生图模型
                image_model = settings.IMAGE_MODEL_IMAGE_TO_IMAGE or settings.IMAGE_MODEL_TEXT_TO_IMAGE or settings.IMAGE_MODEL_NAME or "black-forest-labs/flux-kontext-pro/multi"
            
            cost = ModelPrices.calculate_image_cost(image_model, request.image_count)
            required_points = int(math.ceil(cost * 100))  # 每1元=100积分，向上取整
            # 确保至少1积分
            if required_points <= 0:
                required_points = 1
        
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作类型: {operation_type}")
        
        # 检查积分是否充足
        if available_points >= required_points and available_points > 0:
            return success_response(
                data={
                    "available": True,
                    "required_points": required_points,
                    "available_points": available_points,
                    "message": f"积分充足，可以执行操作（需要 {required_points} 积分）"
                },
                message="检查成功"
            )
        else:
            return success_response(
                data={
                    "available": False,
                    "required_points": required_points,
                    "available_points": available_points,
                    "message": f"积分不足，无法执行操作（需要 {required_points} 积分，当前可用 {available_points} 积分）"
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    测试接口：为指定用户添加积分（仅DEBUG模式可用）
    
    注意：此接口仅在 settings.DEBUG=True 时可用，用于测试环境
    
    Args:
        request: 请求体
            - user_id: 用户ID
            - points: 要添加的积分数量（必须大于0）
            - description: 描述（可选）
    
    Returns:
        添加积分后的账户余额信息
    """
    # 检查是否为DEBUG模式
    if not settings.DEBUG:
        raise HTTPException(
            status_code=403,
            detail="此接口仅在DEBUG模式下可用"
        )
    
    try:
        # 添加积分
        record = PointsService.add_points(
            db=db,
            user_id=request.user_id,
            points=request.points,
            record_type="reward",
            operation_type="test_add_points",
            description=request.description or f"测试添加积分：{request.points}",
            extra_data={
                "added_by": user.user_id,
                "added_by_username": user.username,
                "is_test": True
            }
        )
        
        # 获取更新后的余额
        balance = PointsService.get_account_balance(db, request.user_id)
        
        return success_response(
            data={
                "record_id": record.record_id,
                "points_added": request.points,
                "balance": balance,
                "message": f"成功为用户 {request.user_id} 添加 {request.points} 积分"
            },
            message="添加积分成功"
        )
    
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加积分失败: {str(e)}")
