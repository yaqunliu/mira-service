from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.schemas.subscription import SubscriptionList, SubscriptionCancelRequest, Subscription as SubscriptionSchema
from app.services.subscription_service import SubscriptionService
from app.models.user import User

router = APIRouter()


@router.get("", response_model=SubscriptionList, summary="查询当前用户订阅")
def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = SubscriptionService.list_subscriptions(db, user.user_id, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{subscription_uuid}/cancel", response_model=SubscriptionSchema, summary="取消订阅")
def cancel_subscription(
    subscription_uuid: str = Path(..., description="订阅 uuid"),
    body: SubscriptionCancelRequest = SubscriptionCancelRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    subscription = SubscriptionService.cancel_subscription(
        db=db,
        user_id=user.user_id,
        subscription_uuid=subscription_uuid,
        cancel_at_period_end=body.cancel_at_period_end,
    )
    return subscription

