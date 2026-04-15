from fastapi import APIRouter, Depends, Query, Path, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_async_db, get_current_user
from app.schemas.subscription import SubscriptionList, SubscriptionCancelRequest, Subscription as SubscriptionSchema
from app.services.subscription_async_service import SubscriptionAsyncService
from app.models.user import User
from typing import List

router = APIRouter()


@router.get("", response_model=SubscriptionList, summary="查询当前用户订阅")
async def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    items, total = await SubscriptionAsyncService.list_subscriptions(db, user.user_id, page, page_size)
    subscriptions = []
    for item in items:
        creem_subscription_id = None
        if item.creem_subscription:
            creem_subscription_id = item.creem_subscription.creem_subscription_id

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
        if item.order and item.order.product:
            from app.schemas.product import Product as ProductSchema
            sub_schema.product = ProductSchema.model_validate(item.order.product)
        subscriptions.append(sub_schema)
    return {"items": subscriptions, "total": total, "page": page, "page_size": page_size}


@router.get("/active", response_model=List[SubscriptionSchema], summary="查询当前用户活跃订阅")
async def get_active_subscriptions(
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    items = await SubscriptionAsyncService.get_active_subscriptions_by_product(db, user.user_id)
    subscriptions = []
    for item in items:
        creem_subscription_id = None
        if item.creem_subscription:
            creem_subscription_id = item.creem_subscription.creem_subscription_id

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
        if item.order and item.order.product:
            from app.schemas.product import Product as ProductSchema
            sub_schema.product = ProductSchema.model_validate(item.order.product)
        subscriptions.append(sub_schema)
    return subscriptions


@router.get("/{subscription_uuid}/portal-url", summary="获取订阅客户门户 URL")
async def get_subscription_portal_url(
    subscription_uuid: str = Path(..., description="订阅 uuid"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    portal_url = await SubscriptionAsyncService.get_customer_portal_url(
        db=db,
        user_id=user.user_id,
        subscription_uuid=subscription_uuid,
    )
    return {"portal_url": portal_url}


@router.post("/{subscription_uuid}/cancel", response_model=SubscriptionSchema, summary="取消订阅")
async def cancel_subscription(
    subscription_uuid: str = Path(..., description="订阅 uuid"),
    body: SubscriptionCancelRequest = SubscriptionCancelRequest(),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    subscription = await SubscriptionAsyncService.get_by_uuid(db, user.user_id, subscription_uuid)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")

    if subscription.payment_method == "wechat":
        raise HTTPException(
            status_code=400,
            detail="微信订阅不支持取消功能（手动续费，无需取消）"
        )

    subscription = await SubscriptionAsyncService.cancel_subscription(
        db=db,
        user_id=user.user_id,
        subscription_uuid=subscription_uuid,
        cancel_at_period_end=body.cancel_at_period_end,
    )
    creem_subscription_id = None
    if subscription.creem_subscription:
        creem_subscription_id = subscription.creem_subscription.creem_subscription_id

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
    if subscription.order and subscription.order.product:
        from app.schemas.product import Product as ProductSchema
        sub_schema.product = ProductSchema.model_validate(subscription.order.product)
    return sub_schema
