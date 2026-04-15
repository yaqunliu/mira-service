"""
订单服务 - 异步版本
处理订单创建、查询等业务逻辑（用于 async endpoint）
"""
import uuid as uuid_mod
from datetime import timedelta
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import desc, select, func
from fastapi import HTTPException, status

from app.models.order import Order
from app.models.product import Product
from app.models.subscription import Subscription
from app.services.product_async_service import ProductAsyncService
from app.services.payment_service_factory import PaymentServiceFactory
from app.services.order_service import OrderService
from app.models.user import User
from app.core.logger import logger
from app.core.timezone_utils import now as shanghai_now


class OrderAsyncService:

    @staticmethod
    async def create_order(
        db: AsyncSession,
        user: User,
        product_uuid: str,
        order_type: str,
        success_url: Optional[str],
        cancel_url: Optional[str],
        metadata: Optional[dict] = None,
    ) -> Order:
        product = await ProductAsyncService.get_by_uuid(db, product_uuid)
        if not product:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="产品不存在")

        if product.status != "active":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="产品未激活")

        if order_type not in ("onetime", "subscription"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="订单类型不支持")
        if order_type == "subscription" and product.billing_type != "recurring":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择订阅类产品")
        if order_type == "onetime" and product.billing_type != "onetime":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择一次性产品")

        # 检查订阅产品是否已存在活跃订阅（防止重复购买）
        # 注意：微信订阅允许重复购买（续费就是新订单），Creem订阅不允许重复购买
        if order_type == "subscription" and product.payment_method != "wechat":
            result = await db.execute(
                select(Subscription)
                .join(Order, Subscription.order_id == Order.order_id)
                .where(
                    Subscription.user_id == user.user_id,
                    Order.product_id == product.product_id,
                    Subscription.status.in_(["active", "past_due"]),
                )
            )
            existing_subscription = result.scalar_one_or_none()
            if existing_subscription:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"您已拥有该产品的活跃订阅，无法重复购买。订阅状态：{existing_subscription.status}"
                )

        payment_method = product.payment_method
        if not payment_method:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="产品未配置支付方式"
            )

        if payment_method == "creem" and not product.origin_product_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="产品未配置远程产品ID（origin_product_id），Creem支付需要此字段"
            )

        order_number = OrderService._generate_order_number()
        order = Order(
            order_number=order_number,
            user_id=user.user_id,
            product_id=product.product_id,
            payment_method=payment_method,
            order_type=order_type,
            status="pending",
            amount=product.price,
            currency=product.currency or "USD",
            points_amount=product.points_amount,
            points_issued=0,
            success_url=success_url,
            cancel_url=cancel_url,
            expires_at=shanghai_now() + timedelta(minutes=30),
            order_metadata=metadata,
        )
        db.add(order)
        await db.flush()

        # 调用同步支付服务（通过 run_sync 桥接）
        payment_service = PaymentServiceFactory.get_service(payment_method)

        def _create_payment(sync_session):
            return payment_service.create_payment(
                db=sync_session,
                order=order,
                success_url=success_url,
                cancel_url=cancel_url,
            )

        payment_info = await db.run_sync(_create_payment)

        # 将 payment_info 保存到 order_metadata 中
        if metadata is None:
            metadata = {}
        else:
            metadata = dict(metadata)

        metadata["payment_info"] = payment_info
        metadata["payment_info_created_at"] = shanghai_now().isoformat()
        order.order_metadata = metadata

        await db.commit()

        # 重新加载订单以获取关联的支付信息和产品信息
        result = await db.execute(
            select(Order)
            .options(
                joinedload(Order.creem_payment),
                joinedload(Order.wechat_payment),
                joinedload(Order.product),
            )
            .where(Order.order_id == order.order_id)
        )
        order = result.unique().scalar_one_or_none()

        logger.info(
            f"创建订单成功: order_uuid={order.uuid}, "
            f"payment_method={payment_method}, "
            f"payment_info={payment_info}"
        )

        return OrderService._build_order_with_payment_info(order)

    @staticmethod
    async def get_order_by_uuid(db: AsyncSession, user: User, order_uuid: str) -> Order:
        result = await db.execute(
            select(Order)
            .options(
                joinedload(Order.creem_payment),
                joinedload(Order.wechat_payment),
                joinedload(Order.product),
            )
            .where(Order.uuid == order_uuid, Order.user_id == user.user_id)
        )
        order = result.unique().scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
        return OrderService._build_order_with_payment_info(order)

    @staticmethod
    async def list_orders(
        db: AsyncSession,
        user: User,
        status_filter: Optional[str],
        order_type: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[Order], int]:
        # Count query
        count_query = select(func.count(Order.order_id)).where(Order.user_id == user.user_id)
        if status_filter:
            count_query = count_query.where(Order.status == status_filter)
        if order_type:
            count_query = count_query.where(Order.order_type == order_type)
        count_result = await db.execute(count_query)
        total = count_result.scalar()

        # Items query
        items_query = (
            select(Order)
            .options(
                joinedload(Order.creem_payment),
                joinedload(Order.wechat_payment),
                joinedload(Order.product),
            )
            .where(Order.user_id == user.user_id)
        )
        if status_filter:
            items_query = items_query.where(Order.status == status_filter)
        if order_type:
            items_query = items_query.where(Order.order_type == order_type)

        items_query = (
            items_query.order_by(desc(Order.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(items_query)
        items = result.unique().scalars().all()
        items = [OrderService._build_order_with_payment_info(order) for order in items]
        return items, total

    @staticmethod
    async def query_order_status(db: AsyncSession, order: Order) -> dict:
        """查询订单支付状态（桥接同步 OrderQueryService）"""
        from app.services.order_query_service import OrderQueryService

        def _query(sync_session):
            return OrderQueryService.query_order_status(sync_session, order)

        return await db.run_sync(_query)

    @staticmethod
    async def refund_order(
        db: AsyncSession,
        order: Order,
        force: bool = False,
        refund_reason: str | None = None,
    ):
        """退款（桥接同步 OrderService.refund_order）"""
        def _refund(sync_session):
            return OrderService.refund_order(
                db=sync_session,
                order=order,
                force=force,
                refund_reason=refund_reason,
            )

        return await db.run_sync(_refund)
