"""
产品服务 - 异步版本
"""
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.product import Product


class ProductAsyncService:

    @staticmethod
    async def get_by_uuid(db: AsyncSession, uuid_str: str) -> Optional[Product]:
        result = await db.execute(
            select(Product).where(Product.uuid == uuid_str)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_products(
        db: AsyncSession,
        language: Optional[str] = None,
        billing_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Product], int]:
        filters = []

        if language:
            payment_method = "wechat" if language.lower() == "zh" else "creem"
            filters.append(Product.payment_method == payment_method)
            filters.append(Product.language == language)

        if billing_type:
            filters.append(Product.billing_type == billing_type)
        if status:
            filters.append(Product.status == status)
        else:
            filters.append(Product.status == "active")

        # Count
        count_result = await db.execute(
            select(func.count(Product.product_id)).where(*filters)
        )
        total = count_result.scalar()

        # Items
        result = await db.execute(
            select(Product)
            .where(*filters)
            .order_by(Product.price.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(result.scalars().all())

        # 如果当前语言没有产品，fallback到英文版本
        if language and language.lower() != "en" and len(items) == 0:
            fallback_filters = []
            payment_method = "wechat" if language.lower() == "zh" else "creem"
            fallback_filters.append(Product.payment_method == payment_method)
            fallback_filters.append(Product.language == "en")
            if billing_type:
                fallback_filters.append(Product.billing_type == billing_type)
            fallback_filters.append(Product.status == "active")

            count_result = await db.execute(
                select(func.count(Product.product_id)).where(*fallback_filters)
            )
            total = count_result.scalar()

            result = await db.execute(
                select(Product)
                .where(*fallback_filters)
                .order_by(Product.price.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            items = list(result.scalars().all())

        return items, total
