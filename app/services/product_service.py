from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.product import Product
from app.services.creem_client import creem_client
from app.core.logger import logger
import re


class ProductService:
    @staticmethod
    def list_products(
        db: Session,
        billing_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Product], int]:
        query = db.query(Product)
        if billing_type:
            query = query.filter(Product.billing_type == billing_type)
        if status:
            query = query.filter(Product.status == status)

        total = query.count()
        items = (
            query.order_by(Product.created_at.desc().nullslast())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def get_by_uuid(db: Session, uuid_str: str) -> Optional[Product]:
        return db.query(Product).filter(Product.uuid == uuid_str).first()

    @staticmethod
    def upsert_product(db: Session, item: dict) -> Tuple[Product, bool]:
        creem_product_id = item.get("id") or item.get("product_id")
        if not creem_product_id:
            raise ValueError("Creem product id is missing")

        product = db.query(Product).filter(Product.creem_product_id == creem_product_id).first()
        created = False
        points_amount = ProductService._extract_points(item)

        if not product:
            product = Product(
                creem_product_id=creem_product_id,
                name=item.get("name") or "",
                description=item.get("description"),
                price=item.get("price") or 0,
                currency=item.get("currency") or "USD",
                billing_type=item.get("billing_type") or item.get("billingType") or "",
                billing_period=item.get("billing_period") or item.get("billingPeriod"),
                points_amount=points_amount,
                status=item.get("status") or "active",
                image_url=item.get("image_url"),
                product_url=item.get("product_url"),
                features=item.get("features"),
                creem_mode=item.get("mode"),
                synced_at=ProductService._now(db),
            )
            db.add(product)
            created = True
        else:
            product.name = item.get("name") or product.name
            product.description = item.get("description")
            product.price = item.get("price") or product.price
            product.currency = item.get("currency") or product.currency
            product.billing_type = item.get("billing_type") or product.billing_type
            product.billing_period = item.get("billing_period") or product.billing_period
            product.points_amount = points_amount or product.points_amount
            product.status = item.get("status") or product.status
            product.image_url = item.get("image_url")
            product.product_url = item.get("product_url")
            product.features = item.get("features")
            product.creem_mode = item.get("mode")
            product.synced_at = ProductService._now(db)

        db.flush()
        return product, created

    @staticmethod
    def sync_from_creem(db: Session, page_size: int = 100) -> dict:
        page = 1
        created_count = 0
        updated_count = 0
        total_synced = 0

        while True:
            data = creem_client.search_products(page_number=page, page_size=page_size)
            items = data.get("items") or []
            if not items:
                break

            for item in items:
                product, created = ProductService.upsert_product(db, item)
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                total_synced += 1

            pagination = data.get("pagination") or {}
            next_page = pagination.get("next_page")
            if not next_page or next_page == page:
                break
            page = next_page

        db.commit()
        logger.info(f"Creem 产品同步完成: total={total_synced}, created={created_count}, updated={updated_count}")
        return {
            "synced_count": total_synced,
            "created_count": created_count,
            "updated_count": updated_count,
        }

    @staticmethod
    def _extract_points(item: dict) -> int:
        # 优先从 metadata/points_amount
        metadata = item.get("metadata") or {}
        if isinstance(metadata, dict):
            points = metadata.get("points_amount")
            if isinstance(points, (int, float)) and points > 0:
                return int(points)
        # 尝试从描述中提取数字
        desc = item.get("description") or ""
        nums = re.findall(r"(\\d+)", desc)
        if nums:
            try:
                return int(nums[0])
            except Exception:
                pass
        return item.get("points_amount") or 0

    @staticmethod
    def _now(db: Session):
        from datetime import datetime
        return datetime.utcnow()

