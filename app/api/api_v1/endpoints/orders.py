from fastapi import APIRouter, Depends, Query, Path, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_async_db, get_current_user
from app.schemas.order import OrderCreate, Order as OrderSchema, OrderList
from app.schemas.refund import RefundRequest, RefundResponse
from app.services.order_service import OrderService
from app.models.user import User

router = APIRouter()


@router.post("", response_model=OrderSchema, summary="创建订单（使用 product_uuid）")
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    order = await OrderService.create_order(
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
async def get_order(
    order_uuid: str = Path(..., description="订单 uuid"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    order = await OrderService.get_order_by_uuid(db, user, order_uuid)
    return order


@router.get("/{order_uuid}/status", summary="查询订单支付状态（主动查询支付平台）")
async def query_order_status(
    order_uuid: str = Path(..., description="订单 uuid"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    from app.services.order_query_service import OrderQueryService
    
    order = await OrderService.get_order_by_uuid(db, user, order_uuid)
    result = await OrderQueryService.query_order_status(db, order)
    
    return {
        "order_uuid": order.uuid,
        "status": result.get("status"),
        "updated": result.get("updated", False),
        "payment_status": result,
    }


@router.get("", response_model=OrderList, summary="查询订单列表")
async def list_orders(
    status: str | None = Query(None, description="订单状态"),
    order_type: str | None = Query(None, description="onetime / subscription"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    items, total = await OrderService.list_orders(
        db=db,
        user=user,
        status_filter=status,
        order_type=order_type,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{order_uuid}/refund", response_model=RefundResponse, summary="订单退款（管理员）")
async def refund_order(
    order_uuid: str = Path(..., description="订单 uuid"),
    body: RefundRequest = RefundRequest(),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="无权限")
    order = await OrderService.get_order_by_uuid(db, user, order_uuid)
    return await OrderService.refund_order(
        db=db,
        order=order,
        force=body.force,
        refund_reason=body.refund_reason,
    )
