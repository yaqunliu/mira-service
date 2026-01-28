from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_async_db
from app.schemas.product import ProductList
from app.services.product_service import ProductService

router = APIRouter()


@router.get("", response_model=ProductList, summary="获取产品列表（根据语言自动过滤支付方式）")
async def list_products(
    language: str = Query(..., description="语言代码：zh（中文，微信支付）, en/ja等（其他语言，Creem支付）"),
    billing_type: str | None = Query(None, description="onetime / recurring"),
    status: str | None = Query(None, description="active / inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
):
    items, total = await ProductService.list_products(
        db=db,
        language=language,
        billing_type=billing_type,
        status=status,
        page=page,
        page_size=page_size
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}
