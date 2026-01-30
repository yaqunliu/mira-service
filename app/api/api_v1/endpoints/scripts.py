from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.services.novel_async_service import NovelAsyncService
from app.core.logger import logger
from app.core.exceptions import BaseServiceException
from app.utils.response import success_response
from app.schemas.novel import NovelUpdate, NovelCreate
from app.schemas.chapter import ChapterUpdate, ChapterCreate

router = APIRouter()


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_script_group(
    script_in: NovelCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    创建文案组（Copywriting Group）
    
    自动设置 type='script'
    """
    try:
        # Override type to ensure it's 'script'
        script_in.type = 'script'
        
        script = await NovelAsyncService.create_project_service(
            db=db, 
            title=script_in.title,
            user_id=user.user_id,
            author=script_in.author if hasattr(script_in, 'author') else None
        )
        return success_response(
            data={
                "script_id": script.novel_id,
                "uuid": script.uuid,
                "title": script.title,
                "type": script.type
            },
            message="文案组创建成功"
        )
        
    except Exception as e:
        logger.error(f"创建文案组失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=dict)
async def get_script_groups(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    status: Optional[str] = Query(None, description="过滤状态"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    title: Optional[str] = Query(None, description="按标题筛选"),
    order_by: str = Query("created_at", description="排序字段"),
    order: str = Query("desc", description="排序方向"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    获取文案组列表（仅返回 type='script' 的记录）
    """
    try:
        from app.models.novel import Novel
        from sqlalchemy import and_, or_, select, func
        
        # Build async query
        conditions = [
            Novel.owner_id == user.user_id,
            Novel.type == 'script',
            Novel.deleted_at.is_(None)
        ]
        
        if status:
            conditions.append(Novel.status == status)
        if search:
            conditions.append(
                or_(
                    Novel.title.ilike(f"%{search}%"),
                    Novel.author.ilike(f"%{search}%")
                )
            )
        if title:
            conditions.append(Novel.title.ilike(f"%{title}%"))
        
        # Build base query
        query = select(Novel).where(and_(*conditions))
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar()
        
        # Apply ordering
        if order_by == "created_at":
            order_column = Novel.created_at
        elif order_by == "updated_at":
            order_column = Novel.updated_at
        elif order_by == "title":
            order_column = Novel.title
        else:
            order_column = Novel.created_at
        
        if order == "desc":
            query = query.order_by(order_column.desc())
        else:
            query = query.order_by(order_column.asc())
        
        # Apply pagination
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        scripts = result.scalars().all()
        
    except Exception as e:
        logger.error(f"获取文案组列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    # Format response
    total_pages = (total + page_size - 1) // page_size
    items = []
    for script in scripts:
        creation_ids = sorted([creation.creation_id for creation in script.creations], reverse=True)
        character_ids = sorted([character.character_id for character in script.characters], reverse=True)
        
        items.append({
            "novel_id": script.novel_id,
            "uuid": script.uuid,
            "title": script.title,
            "author": script.author,
            "chapter_count": script.chapter_count,
            "status": script.status,
            "owner_id": script.owner_id,
            "created_at": script.created_at,
            "updated_at": script.updated_at,
            "creation_ids": creation_ids,
            "character_ids": character_ids,
            "type": script.type,
        })
    
    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
    )


@router.get("/{script_uuid}")
async def get_script_group(
    script_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    获取文案组详情
    """
    try:
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        
        # Verify it's a script type
        if script.type != 'script':
            raise HTTPException(status_code=404, detail="文案组不存在")
            
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    
    # Build creations list
    creations = [
        {
            "creation_id": creation.creation_id,
            "title": creation.title,
            "status": creation.status,
            "chapter_id": creation.chapter_id,
            "video_url": creation.video_url,
            "audio_url": creation.audio_url,
            "subtitle_url": creation.subtitle_url,
            "voice_id": creation.voice_id,
            "voice_speed": creation.voice_speed,
            "current_task_id": creation.current_task_id,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
        }
        for creation in sorted(script.creations, key=lambda c: c.creation_id, reverse=True)
    ]
    
    # Build characters list
    characters = [
        {
            "character_id": character.character_id,
            "name": character.name,
            "status": character.status,
            "basic_info": character.basic_info,
            "appearance": character.appearance,
            "body": character.body,
            "hair": character.hair,
            "clothing": character.clothing,
            "tags": character.tags,
            "image_prompt": character.image_prompt,
            "visual_style": character.visual_style,
            "image_url": character.image_url,
            "creation_id": character.creation_id,
            "created_at": character.created_at,
            "updated_at": character.updated_at,
        }
        for character in sorted(script.characters, key=lambda c: c.character_id, reverse=True)
    ]
    
    return success_response(
        data={
            "novel_id": script.novel_id,
            "uuid": script.uuid,
            "title": script.title,
            "author": script.author,
            "chapter_count": script.chapter_count,
            "status": script.status,
            "owner_id": script.owner_id,
            "task_id": script.task_id,
            "created_at": script.created_at,
            "updated_at": script.updated_at,
            "creations": creations,
            "characters": characters,
        },
        message="文案组获取成功"
    )


@router.get("/{script_uuid}/items")
async def get_script_items(
    script_uuid: str,
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    获取文案列表（章节列表）
    """
    try:
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        
        if script.type != 'script':
            raise HTTPException(status_code=404, detail="文案组不存在")
            
        chapters, total = await NovelAsyncService.get_novel_chapters_service(
            db=db,
            novel_id=script.novel_id,
            user_id=user.user_id,
            page=page,
            page_size=page_size
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    
    total_pages = (total + page_size - 1) // page_size
    items = [
        {
            "chapter_id": chapter.chapter_id,
            "uuid": chapter.uuid,
            "title": chapter.title,
            "chapter_number": chapter.chapter_number,
            "word_count": chapter.word_count,
            "preview": chapter.preview,
            "content_url": chapter.content_url,
            "created_at": chapter.created_at,
            "has_creation": len(chapter.creation) > 0 if chapter.creation else False,
        }
        for chapter in chapters
    ]
    
    return success_response(
        data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        },
        message="文案列表获取成功"
    )


@router.post("/{script_uuid}/items", status_code=status.HTTP_201_CREATED)
async def create_script_item(
    script_uuid: str,
    item_in: ChapterCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    创建文案（章节）
    """
    try:
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        
        if script.type != 'script':
            raise HTTPException(status_code=404, detail="文案组不存在")
        
        item_in.novel_id = script.novel_id
        
        chapter = await NovelAsyncService.create_chapter_service(
            db=db,
            novel_id=script.novel_id,
            chapter_in=item_in,
            user_id=user.user_id
        )
        return success_response(
            data={
                "chapter_id": chapter.chapter_id,
                "uuid": chapter.uuid,
                "title": chapter.title
            },
            message="文案创建成功"
        )
        
    except Exception as e:
        logger.error(f"创建文案失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{script_uuid}")
async def update_script_group(
    script_uuid: str,
    script_update: NovelUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    更新文案组信息
    """
    try:
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        
        if script.type != 'script':
            raise HTTPException(status_code=404, detail="文案组不存在")
            
        # 将 script_update 转换为字典并过滤掉 None 值
        update_data = script_update.model_dump(exclude_unset=True)
        script = await NovelAsyncService.update_novel_service(
            db=db,
            novel_id=script.novel_id,
            **update_data
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    
    return success_response(
        data={
            "novel_id": script.novel_id,
            "title": script.title,
            "author": script.author,
            "status": script.status,
            "updated_at": script.updated_at,
        },
        message="文案组更新成功"
    )


@router.put("/{script_uuid}/items/{item_uuid}")
async def update_script_item(
    script_uuid: str,
    item_uuid: str,
    item_update: ChapterUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    更新文案信息
    """
    try:
        chapter = await NovelAsyncService.get_chapter_by_uuid_service(db=db, chapter_uuid=item_uuid, user_id=user.user_id)
        chapter = await NovelAsyncService.update_chapter_service(
            db=db,
            chapter_id=chapter.chapter_id,
            chapter_update=item_update,
            user_id=user.user_id
        )
        
        # Verify belongs to script
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        if chapter.novel_id != script.novel_id or script.type != 'script':
            raise HTTPException(status_code=400, detail="文案不属于指定的文案组")
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    
    return success_response(
        data={
            "chapter_id": chapter.chapter_id,
            "title": chapter.title,
            "novel_id": chapter.novel_id,
            "chapter_number": chapter.chapter_number,
        },
        message="文案更新成功"
    )


@router.delete("/{script_uuid}")
async def delete_script_group(
    script_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    删除文案组
    """
    try:
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        
        if script.type != 'script':
            raise HTTPException(status_code=404, detail="文案组不存在")
            
        await NovelAsyncService.delete_novel_service(db=db, novel_id=script.novel_id)
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    
    return success_response(data=None, message="文案组删除成功")


@router.delete("/{script_uuid}/items/{item_uuid}")
async def delete_script_item(
    script_uuid: str,
    item_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    删除文案
    """
    try:
        chapter = await NovelAsyncService.get_chapter_by_uuid_service(db=db, chapter_uuid=item_uuid, user_id=user.user_id)
        script = await NovelAsyncService.get_novel_by_uuid_service(db=db, novel_uuid=script_uuid, user_id=user.user_id)
        
        if chapter.novel_id != script.novel_id or script.type != 'script':
            raise HTTPException(status_code=400, detail="文案不属于指定的文案组")
        
        await NovelAsyncService.delete_chapter_service(
            db=db,
            chapter_id=chapter.chapter_id,
            user_id=user.user_id
        )
    except HTTPException:
        raise
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    
    return success_response(data={"item_uuid": item_uuid}, message="文案删除成功")
