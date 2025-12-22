from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.schemas.order import OrderCreate, Order as OrderSchema, OrderList
from app.schemas.refund import RefundRequest, RefundResponse
from app.services.order_service import OrderService
from app.models.user import User
from fastapi import HTTPException, status

router = APIRouter()


@router.post("", response_model=OrderSchema, summary="创建订单（使用 product_uuid）")
def create_order(
    body: OrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = OrderService.create_order(
        db=db,
        user=user,
        product_uuid=body.product_uuid,
        order_type=body.order_type,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
        metadata=body.metadata,
    )
    return order


@router.get("/{order_uuid}", response_model=OrderSchema, summary="查询订单")
def get_order(
    order_uuid: str = Path(..., description="订单 uuid"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = OrderService.get_order_by_uuid(db, user, order_uuid)
    return order


@router.get("/{order_uuid}/status", summary="查询订单支付状态（主动查询支付平台）")
def query_order_status(
    order_uuid: str = Path(..., description="订单 uuid"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询订单支付状态，调用支付平台API获取最新状态"""
    from app.services.order_query_service import OrderQueryService
    
    order = OrderService.get_order_by_uuid(db, user, order_uuid)
    result = OrderQueryService.query_order_status(db, order)
    
    return {
        "order_uuid": order.uuid,
        "status": result.get("status"),
        "updated": result.get("updated", False),
        "payment_status": result,
    }


@router.get("", response_model=OrderList, summary="查询订单列表")
def list_orders(
    status: str | None = Query(None, description="订单状态"),
    order_type: str | None = Query(None, description="onetime / subscription"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = OrderService.list_orders(
        db=db,
        user=user,
        status_filter=status,
        order_type=order_type,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{order_uuid}/refund", response_model=RefundResponse, summary="订单退款（管理员）")
def refund_order(
    order_uuid: str = Path(..., description="订单 uuid"),
    body: RefundRequest = RefundRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # 简单管理员校验：要求 user.is_admin；可替换为更完善的权限体系
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权限")
    order = OrderService.get_order_by_uuid(db, user, order_uuid)
    return OrderService.refund_order(
        db=db,
        order=order,
        force=body.force,
        refund_reason=body.refund_reason,
    )

