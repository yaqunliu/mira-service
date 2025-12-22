from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.product import Product
from app.core.logger import logger


class ProductService:
    @staticmethod
    def list_products(
        db: Session,
        language: Optional[str] = None,  # 语言代码：zh, en, ja等
        billing_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Product], int]:
        query = db.query(Product)
        
        # 根据语言自动确定支付方式
        if language:
            # 中文用户使用微信支付，其他语言使用Creem支付
            if language.lower() == "zh":
                payment_method = "wechat"
            else:
                payment_method = "creem"
            
            query = query.filter(Product.payment_method == payment_method)
            query = query.filter(Product.language == language)
        else:
            # 如果没有指定语言，默认显示所有产品（向后兼容）
            pass
        
        if billing_type:
            query = query.filter(Product.billing_type == billing_type)
        if status:
            query = query.filter(Product.status == status)
        else:
            # 默认只显示激活的产品
            query = query.filter(Product.status == "active")

        total = query.count()
        items = (
            query.order_by(Product.price.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        
        # 如果当前语言没有产品，fallback到英文版本
        if language and language.lower() != "en" and len(items) == 0:
            fallback_query = db.query(Product)
            if language.lower() == "zh":
                fallback_query = fallback_query.filter(Product.payment_method == "wechat")
            else:
                fallback_query = fallback_query.filter(Product.payment_method == "creem")
            fallback_query = fallback_query.filter(Product.language == "en")
            if billing_type:
                fallback_query = fallback_query.filter(Product.billing_type == billing_type)
            fallback_query = fallback_query.filter(Product.status == "active")
            
            total = fallback_query.count()
            items = (
                fallback_query.order_by(Product.price.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
        
        return items, total

    @staticmethod
    def get_by_uuid(db: Session, uuid_str: str) -> Optional[Product]:
        return db.query(Product).filter(Product.uuid == uuid_str).first()

    # 注意：已删除以下方法，产品现在通过脚本直接创建，不再从Creem同步：
    # - upsert_product
    # - sync_from_creem
    # - _extract_points
    # - _now

