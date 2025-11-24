from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.creation import CreationCreate, Creation as CreationSchema
from app.services.creation_service import CreationService
from app.core.exceptions import BaseServiceException
from app.utils.response import success_response

router = APIRouter()


@router.post("/create")
async def create_creation_service(
    creation_data: CreationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    创建新的视频创作项目

    参数验证：
    - 验证 novel_id 和 chapter_id 是否有效
    - 验证用户权限
    """
    # 获取用户ID
    try:
        user_id = user.user_id
    except Exception as e:
        raise HTTPException(status_code=500, detail="获取用户信息失败")

    # 调用服务层处理业务逻辑
    try:
        creation_id = CreationService.create_creation_service(
            db=db,
            novel_id=creation_data.novel_id,
            chapter_id=creation_data.chapter_id,
            user_id=user_id,
        )

        # 转换为响应格式
        return success_response(
            data={"creation_id": creation_id},
            message="创作初始化成功"
        )
    except BaseServiceException as e:
        # 将业务异常转换为HTTP异常
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/")
async def get_creations_service(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    status: Optional[str] = Query(None, description="过滤状态"),
    order_by: str = Query(
        "created_at", description="排序字段：created_at, updated_at, title"
    ),
    order: str = Query("desc", description="排序方向：asc, desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作项目列表（支持分页）

    支持功能：
    - 分页查询
    - 状态过滤（status）
    - 排序（按创建时间、更新时间、标题）

    Args:
        page: 页码，从1开始
        page_size: 每页数量，最大100
        status: 过滤状态
        order_by: 排序字段
        order: 排序方向（asc/desc）
        db: 数据库会话
        user: 当前用户

    Returns:
        包含创作列表和分页信息的字典
    """
    try:
        creations, total = CreationService.get_creations_service(
            db=db,
            user_id=user.user_id,
            page=page,
            page_size=page_size,
            status_filter=status,
            order_by=order_by,
            order=order,
        )

        # 转换为响应格式
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        items = [
            CreationSchema.model_validate(creation).model_dump()
            for creation in creations
        ]

        return success_response(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            }
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/{creation_id}")
async def get_creation(
    creation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """根据ID获取创作项目详情"""
    try:
        creation = CreationService.get_creation_service(db=db, creation_id=creation_id)
        if creation is None:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        if creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该创作项目")
        # 将 SQLAlchemy 模型对象转换为 Pydantic schema 对象，然后转换为字典
        return success_response(
            data=CreationSchema.model_validate(creation).model_dump(),
            message="创作项目获取成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/{creation_id}")
async def delete_creation(creation_id: int):
    """删除创作项目"""
    # TODO: 实现删除创作逻辑
    pass


@router.post("/{creation_id}/generate")
async def start_generation(creation_id: int):
    """开始生成视频"""
    # TODO: 实现开始生成逻辑
    pass


@router.get("/{creation_id}/progress")
async def get_generation_progress(creation_id: int):
    """获取生成进度"""
    # TODO: 实现获取进度逻辑
    pass
