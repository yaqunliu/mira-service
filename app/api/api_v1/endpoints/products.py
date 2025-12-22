from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.schemas.product import ProductList
from app.services.product_service import ProductService
from app.models.user import User

router = APIRouter()


@router.get("", response_model=ProductList, summary="获取产品列表（根据语言自动过滤支付方式）")
def list_products(
    language: str = Query(..., description="语言代码：zh（中文，微信支付）, en/ja等（其他语言，Creem支付）"),
    billing_type: str | None = Query(None, description="onetime / recurring"),
    status: str | None = Query(None, description="active / inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    获取产品列表
    
    根据language参数自动确定支付方式：
    - language=zh → 返回微信支付产品（payment_method=wechat, currency=CNY）
    - language=en/ja等 → 返回Creem产品（payment_method=creem, currency=USD）
    
    如果当前语言没有产品，自动fallback到英文版本
    """
    items, total = ProductService.list_products(
        db=db,
        language=language,
        billing_type=billing_type,
        status=status,
        page=page,
        page_size=page_size
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# 注意：已删除产品同步接口
# 产品现在通过脚本直接创建，不再从Creem同步
# @router.post("/sync", ...) 已删除

