"""
订阅服务 - 异步版本
处理订阅查询、取消等业务逻辑（用于 async endpoint）
"""
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import select, func
from fastapi import HTTPException, status

from app.models.subscription import Subscription
from app.models.order import Order
from app.models.product import Product
from app.services.subscription_service import SubscriptionService
from app.services.creem_client import creem_client
from app.core.logger import logger


class SubscriptionAsyncService:

    @staticmethod
    async def get_by_uuid(
        db: AsyncSession, user_id: int, uuid_str: str
    ) -> Optional[Subscription]:
        result = await db.execute(
            select(Subscription)
            .options(
                joinedload(Subscription.creem_subscription),
                joinedload(Subscription.order).joinedload(Order.product),
            )
            .where(Subscription.uuid == uuid_str, Subscription.user_id == user_id)
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    async def list_subscriptions(
        db: AsyncSession, user_id: int, page: int, page_size: int
    ) -> Tuple[List[Subscription], int]:
        # Count
        count_result = await db.execute(
            select(func.count(Subscription.subscription_id))
            .where(Subscription.user_id == user_id)
        )
        total = count_result.scalar()

        # Items
        result = await db.execute(
            select(Subscription)
            .options(
                joinedload(Subscription.creem_subscription),
                joinedload(Subscription.order).joinedload(Order.product),
            )
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.unique().scalars().all())
        return items, total

    @staticmethod
    async def get_active_subscriptions_by_product(
        db: AsyncSession, user_id: int
    ) -> List[Subscription]:
        # 获取每个产品的最新活跃订阅
        subquery = (
            select(
                Subscription.product_id,
                func.max(Subscription.subscription_id).label("max_id"),
            )
            .where(Subscription.user_id == user_id, Subscription.status == "active")
            .group_by(Subscription.product_id)
            .subquery()
        )
        result = await db.execute(
            select(Subscription)
            .options(
                joinedload(Subscription.creem_subscription),
                joinedload(Subscription.order).joinedload(Order.product),
            )
            .join(subquery, Subscription.subscription_id == subquery.c.max_id)
            .where(Subscription.user_id == user_id, Subscription.status == "active")
        )
        return list(result.unique().scalars().all())

    @staticmethod
    async def get_customer_portal_url(
        db: AsyncSession, user_id: int, subscription_uuid: str
    ) -> str:
        subscription = await SubscriptionAsyncService.get_by_uuid(
            db, user_id, subscription_uuid
        )
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="订阅不存在"
            )

        creem_subscription_id = subscription.creem_subscription.creem_subscription_id

        # 尝试从 Creem API 获取订阅详情
        try:
            creem_sub = creem_client.get_subscription(creem_subscription_id)
            portal_url = (
                creem_sub.get("customer_portal_url")
                or creem_sub.get("portal_url")
                or creem_sub.get("manage_url")
            )
            if portal_url:
                return portal_url
        except Exception as e:
            logger.warning(f"获取 Creem 订阅详情失败，使用默认 URL: {e}")

        from app.core.config import settings

        creem_base_url = str(settings.CREEM_API_URL).replace("api.", "")
        if "api." in creem_base_url:
            creem_base_url = "https://creem.io"
        return f"{creem_base_url}/subscriptions/{creem_subscription_id}"

    @staticmethod
    async def cancel_subscription(
        db: AsyncSession,
        user_id: int,
        subscription_uuid: str,
        cancel_at_period_end: bool = True,
    ) -> Subscription:
        """取消订阅（桥接同步 SubscriptionService.cancel_subscription）"""

        def _cancel(sync_session):
            return SubscriptionService.cancel_subscription(
                db=sync_session,
                user_id=user_id,
                subscription_uuid=subscription_uuid,
                cancel_at_period_end=cancel_at_period_end,
            )

        await db.run_sync(_cancel)

        # 重新加载以获取所有关联关系（run_sync 后 lazy load 不可用）
        result = await db.execute(
            select(Subscription)
            .options(
                joinedload(Subscription.creem_subscription),
                joinedload(Subscription.order).joinedload(Order.product),
            )
            .where(
                Subscription.uuid == subscription_uuid,
                Subscription.user_id == user_id,
            )
        )
        return result.unique().scalar_one()
