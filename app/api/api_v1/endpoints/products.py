from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.schemas.product import ProductList, ProductSyncResult
from app.services.product_service import ProductService
from app.models.user import User

router = APIRouter()


@router.get("", response_model=ProductList, summary="获取产品列表（包含 Creem 同步数据）")
def list_products(
    billing_type: str | None = Query(None, description="onetime / recurring"),
    status: str | None = Query(None, description="active / inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = ProductService.list_products(db, billing_type=billing_type, status=status, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/sync", response_model=ProductSyncResult, summary="手动同步 Creem 产品（需要登录）")
def sync_products(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = ProductService.sync_from_creem(db)
    return result

