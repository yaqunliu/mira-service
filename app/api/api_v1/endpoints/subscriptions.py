from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.schemas.subscription import SubscriptionList, SubscriptionCancelRequest, Subscription as SubscriptionSchema
from app.services.subscription_service import SubscriptionService
from app.models.user import User
from typing import List

router = APIRouter()


@router.get("", response_model=SubscriptionList, summary="查询当前用户订阅")
def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = SubscriptionService.list_subscriptions(db, user.user_id, page, page_size)
    # 手动设置 product 字段（从 order.product 获取）
    subscriptions = []
    for item in items:
        # 从关系对象中获取支付方式特定的ID
        creem_subscription_id = None
        if item.creem_subscription:
            creem_subscription_id = item.creem_subscription.creem_subscription_id
        
        # 确保 UUID 字段被正确转换为字符串
        sub_dict = {
            "uuid": str(item.uuid) if item.uuid else None,
            "subscription_id": item.subscription_id,
            "order_id": item.order_id,
            "user_id": item.user_id,
            "creem_subscription_id": creem_subscription_id,
            "status": item.status,
            "billing_period": item.billing_period,
            "current_period_start": item.current_period_start,
            "current_period_end": item.current_period_end,
            "next_billing_date": item.next_billing_date,
            "points_per_period": item.points_per_period,
            "last_points_issued_at": item.last_points_issued_at,
            "cancel_at_period_end": item.cancel_at_period_end,
            "cancelled_at": item.cancelled_at,
            "subscription_metadata": item.subscription_metadata,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        sub_schema = SubscriptionSchema(**sub_dict)
        # 如果 order 和 product 已加载，手动设置 product
        if item.order and item.order.product:
            from app.schemas.product import Product as ProductSchema
            sub_schema.product = ProductSchema.model_validate(item.order.product)
        subscriptions.append(sub_schema)
    return {"items": subscriptions, "total": total, "page": page, "page_size": page_size}


@router.get("/active", response_model=List[SubscriptionSchema], summary="查询当前用户活跃订阅")
def get_active_subscriptions(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取用户当前活跃的订阅列表（按产品分组，每个产品只返回最新的活跃订阅）
    用于前端显示用户已购买的订阅产品
    """
    items = SubscriptionService.get_active_subscriptions_by_product(db, user.user_id)
    # 手动设置 product 字段（从 order.product 获取）
    subscriptions = []
    for item in items:
        # 从关系对象中获取支付方式特定的ID
        creem_subscription_id = None
        if item.creem_subscription:
            creem_subscription_id = item.creem_subscription.creem_subscription_id
        
        # 确保 UUID 字段被正确转换为字符串
        sub_dict = {
            "uuid": str(item.uuid) if item.uuid else None,
            "subscription_id": item.subscription_id,
            "order_id": item.order_id,
            "user_id": item.user_id,
            "creem_subscription_id": creem_subscription_id,
            "status": item.status,
            "billing_period": item.billing_period,
            "current_period_start": item.current_period_start,
            "current_period_end": item.current_period_end,
            "next_billing_date": item.next_billing_date,
            "points_per_period": item.points_per_period,
            "last_points_issued_at": item.last_points_issued_at,
            "cancel_at_period_end": item.cancel_at_period_end,
            "cancelled_at": item.cancelled_at,
            "subscription_metadata": item.subscription_metadata,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        sub_schema = SubscriptionSchema(**sub_dict)
        # 如果 order 和 product 已加载，手动设置 product
        if item.order and item.order.product:
            from app.schemas.product import Product as ProductSchema
            sub_schema.product = ProductSchema.model_validate(item.order.product)
        subscriptions.append(sub_schema)
    return subscriptions


@router.get("/{subscription_uuid}/portal-url", summary="获取订阅客户门户 URL")
def get_subscription_portal_url(
    subscription_uuid: str = Path(..., description="订阅 uuid"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取订阅的客户门户 URL，用于在 Creem 客户门户管理订阅
    """
    portal_url = SubscriptionService.get_customer_portal_url(
        db=db,
        user_id=user.user_id,
        subscription_uuid=subscription_uuid,
    )
    return {"portal_url": portal_url}


@router.post("/{subscription_uuid}/cancel", response_model=SubscriptionSchema, summary="取消订阅")
def cancel_subscription(
    subscription_uuid: str = Path(..., description="订阅 uuid"),
    body: SubscriptionCancelRequest = SubscriptionCancelRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 检查是否为微信订阅，微信订阅不支持取消（因为没有自动续费，不需要取消）
    subscription = SubscriptionService.get_by_uuid(db, user.user_id, subscription_uuid)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在")
    
    if subscription.payment_method == "wechat":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="微信订阅不支持取消功能（手动续费，无需取消）"
        )
    
    subscription = SubscriptionService.cancel_subscription(
        db=db,
        user_id=user.user_id,
        subscription_uuid=subscription_uuid,
        cancel_at_period_end=body.cancel_at_period_end,
    )
    # 从关系对象中获取支付方式特定的ID
    creem_subscription_id = None
    if subscription.creem_subscription:
        creem_subscription_id = subscription.creem_subscription.creem_subscription_id
    
    # 确保 UUID 字段被正确转换为字符串
    sub_dict = {
        "uuid": str(subscription.uuid) if subscription.uuid else None,
        "subscription_id": subscription.subscription_id,
        "order_id": subscription.order_id,
        "user_id": subscription.user_id,
        "creem_subscription_id": creem_subscription_id,
        "status": subscription.status,
        "billing_period": subscription.billing_period,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "next_billing_date": subscription.next_billing_date,
        "points_per_period": subscription.points_per_period,
        "last_points_issued_at": subscription.last_points_issued_at,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "cancelled_at": subscription.cancelled_at,
        "subscription_metadata": subscription.subscription_metadata,
        "created_at": subscription.created_at,
        "updated_at": subscription.updated_at,
    }
    sub_schema = SubscriptionSchema(**sub_dict)
    # 如果 order 和 product 已加载，手动设置 product
    if subscription.order and subscription.order.product:
        from app.schemas.product import Product as ProductSchema
        sub_schema.product = ProductSchema.model_validate(subscription.order.product)
    return sub_schema

