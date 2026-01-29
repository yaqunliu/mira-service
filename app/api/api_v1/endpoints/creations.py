import json
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.models.creation import Creation
from app.models.shot import Shot
from app.models.scene import Scene
from app.models.character import Character
from app.schemas.creation import CreationCreate, CreationUpdate, CreationStatus
from app.services.creation_async_service import CreationAsyncService
from app.core.exceptions import BaseServiceException
from app.utils.response import success_response
from app.core.logger import logger

from app.api.api_v1.endpoints.agent import (
    ChatRequest,
    ResetRequest,
    InterruptRequest,
    agent_chat,
    get_messages,
    interrupt_session,
    reset_session,
    get_session_status
)

router = APIRouter()


def parse_narration(narration_str: Optional[str]) -> List[str]:
    """解析旁白字符串为列表"""
    if not narration_str:
        return []
    try:
        data = json.loads(narration_str)
        if isinstance(data, list):
            return data
        return [str(data)]
    except (json.JSONDecodeError, TypeError):
        return [narration_str]


@router.post("/create")
async def create_creation_service(
    creation_data: CreationCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    创建新的视频创作项目或继续已存在的创作
    """
    try:
        user_id = user.user_id
    except Exception as e:
        raise HTTPException(status_code=500, detail="获取用户信息失败")

    if creation_data.creation_id:
        if creation_data.novel_id is not None or creation_data.chapter_id is not None:
            logger.warning(
                f"提供了 creation_id={creation_data.creation_id}，但同时也提供了 "
                f"novel_id={creation_data.novel_id} 和 chapter_id={creation_data.chapter_id}，"
                f"将忽略 novel_id 和 chapter_id"
            )
    else:
        if not ((creation_data.novel_id and creation_data.chapter_id) or creation_data.text_content):
            raise HTTPException(
                status_code=400,
                detail="创建新创作时必须提供 novel_id 和 chapter_id，或提供 text_content 进行文案创作，或提供 creation_id 继续已存在的创作"
            )

    novel_id_int = None
    chapter_id_int = None
    creation_id_int = None
    
    if creation_data.novel_id:
        from app.services.novel_async_service import NovelAsyncService
        novel = await NovelAsyncService.get_novel_by_uuid(db, creation_data.novel_id, user_id)
        if novel:
            novel_id_int = novel.novel_id
    
    if creation_data.chapter_id:
        from app.services.novel_async_service import NovelAsyncService
        chapter = await NovelAsyncService.get_chapter_by_uuid(db, creation_data.chapter_id, user_id)
        if chapter:
            chapter_id_int = chapter.chapter_id
    
    creation_id_int = None
    if creation_data.creation_id:
        creation = await CreationAsyncService.get_creation_by_uuid(db, creation_data.creation_id)
        if creation:
            creation_id_int = creation.creation_id
        else:
            raise HTTPException(
                status_code=404,
                detail="指定的创作项目不存在"
            )

    narration_mode = creation_data.narration_mode or "original"
    if narration_mode not in ["original", "rewrite"]:
        raise HTTPException(
            status_code=400,
            detail="narration_mode 必须是 'original'（原文模式）或 'rewrite'（爽文模式）"
        )
    
    extra_data = creation_data.extra_data or {}
    if narration_mode:
        extra_data["narration_mode"] = narration_mode
    
    try:
        from app.services.creation_async_service import CreationAsyncService
        new_creation_id = await CreationAsyncService.create_creation_service(
            db=db,
            novel_id=novel_id_int,
            chapter_id=chapter_id_int,
            user_id=user_id,
            creation_id=creation_id_int,
            narration_mode=narration_mode,
            extra_data=extra_data,
            text_content=creation_data.text_content
        )

        creation = await CreationAsyncService.get_creation_by_id(db, new_creation_id)
        creation_uuid = creation.uuid if creation else None
        
        return success_response(
            data={"creation_id": new_creation_id, "uuid": creation_uuid},
            message="创作初始化成功"
        )
    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("")
async def get_creations_service(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量，最大100"),
    status: Optional[str] = Query(None, description="过滤状态"),
    title: Optional[str] = Query(None, description="按标题筛选（模糊匹配）"),
    order_by: str = Query("created_at", description="排序字段"),
    order: str = Query("desc", description="排序方向"),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作项目列表（支持分页）
    """
    try:
        from app.services.creation_async_service import CreationAsyncService
        creations, total = await CreationAsyncService.get_creations_service(
            db=db,
            user_id=user.user_id,
            page=page,
            page_size=page_size,
            status_filter=status,
            title_filter=title,
            order_by=order_by,
            order=order,
        )

        total_pages = (total + page_size - 1) // page_size if total > 0 else 0
        items = []
        for creation in creations:
            novel = creation.novel
            chapter = creation.chapter
            scenes = creation.scenes or []

            creation_data = {
                "creation_id": creation.creation_id,
                "uuid": creation.uuid,
                "title": creation.title,
                "status": creation.status,
                "video_url": creation.video_url,
                "audio_url": creation.audio_url,
                "subtitle_url": creation.subtitle_url,
                "voice_id": creation.voice_id,
                "voice_speed": creation.voice_speed,
                "current_task_id": creation.current_task_id,
                "created_at": creation.created_at,
                "updated_at": creation.updated_at,
                "owner_id": creation.owner_id,
                "novel_id": creation.novel_id,
                "chapter_id": creation.chapter_id,
                "extra_data": creation.extra_data,
                "character_ids": creation.character_ids,
                "creation_type": creation.creation_type,
                "preview_text": creation.preview_text,
                "text_content_url": creation.text_content_url,
            }

            creation_data["characters"] = []
            if hasattr(creation, 'characters'):
                for character in (creation.characters or []):
                    character_data = {
                        "character_id": character.character_id,
                        "name": character.name,
                        "description": character.basic_info or "",
                        "image_url": character.image_url,
                    }
                    creation_data["characters"].append(character_data)

            if novel:
                creation_data["novel"] = {
                    "novel_id": novel.novel_id,
                    "uuid": novel.uuid,
                    "title": novel.title,
                }
            else:
                creation_data["novel"] = None

            if chapter:
                creation_data["chapter"] = {
                    "chapter_id": chapter.chapter_id,
                    "uuid": chapter.uuid,
                    "title": chapter.title,
                    "chapter_number": chapter.chapter_number,
                }
            else:
                creation_data["chapter"] = None

            creation_data["scene_count"] = len(scenes)
            items.append(creation_data)

        return success_response(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
            message="获取创作列表成功"
        )

    except BaseServiceException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/{creation_uuid}")
async def get_creation_detail(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作详情
    """
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此创作")
    
    creation_with_relations = await CreationAsyncService.get_creation_with_relations(db, creation.creation_id)
    
    return success_response(
        data={
            "creation_id": creation.creation_id,
            "uuid": creation.uuid,
            "title": creation.title,
            "status": creation.status,
            "video_url": creation.video_url,
            "audio_url": creation.audio_url,
            "subtitle_url": creation.subtitle_url,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
            "extra_data": creation.extra_data,
            "characters": [
                {
                    "character_id": c.character_id,
                    "name": c.name,
                    "image_url": c.image_url,
                }
                for c in (creation_with_relations.characters or [])
            ],
            "scenes": [
                {
                    "scene_id": s.scene_id,
                    "title": s.title,
                    "time_setting": s.time_setting,
                    "location": s.location,
                    "space_type": s.space_type,
                    "atmosphere": s.atmosphere,
                    "image_url": s.image_url,
                    "status": s.status,
                    "extra_data": s.extra_data,
                    "shots": [
                        {
                            "shot_id": shot.shot_id,
                            "shot_number": shot.shot_number,
                            "title": shot.title,
                            "description": shot.description,
                            "narration": shot.narration,
                            "image_url": shot.image_url,
                            "video_url": shot.video_url,
                            "status": shot.status,
                            "extra_data": shot.extra_data,
                        }
                        for shot in (s.shots or [])
                    ],
                }
                for s in (creation_with_relations.scenes or [])
            ],
        },
        message="获取创作详情成功"
    )


@router.delete("/{creation_uuid}")
async def delete_creation(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    删除创作
    """
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权删除此创作")
    
    success = await CreationAsyncService.delete_creation(db, creation.creation_id)
    
    if success:
        return success_response(message="删除创作成功")
    else:
        raise HTTPException(status_code=500, detail="删除创作失败")


@router.patch("/{creation_uuid}")
async def update_creation(
    creation_uuid: str,
    update_data: CreationUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    更新创作
    """
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权修改此创作")
    
    update_dict = update_data.model_dump(exclude_unset=True)
    updated = await CreationAsyncService.update_creation(
        db,
        creation.creation_id,
        **update_dict
    )
    
    if updated:
        return success_response(
            data={"creation_id": updated.creation_id, "uuid": updated.uuid},
            message="更新创作成功"
        )
    else:
        raise HTTPException(status_code=500, detail="更新创作失败")


@router.put("/{creation_uuid}")
async def put_creation(
    creation_uuid: str,
    update_data: CreationUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    更新创作（PUT方法，支持更新timeline_config等字段）
    """
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权修改此创作")
    
    update_dict = update_data.model_dump(exclude_unset=True)
    updated = await CreationAsyncService.update_creation(
        db,
        creation.creation_id,
        **update_dict
    )
    
    if updated:
        return success_response(
            data={"creation_id": updated.creation_id, "uuid": updated.uuid},
            message="更新创作成功"
        )
    else:
        raise HTTPException(status_code=500, detail="更新创作失败")


@router.get("/{creation_uuid}/progress")
async def get_creation_progress(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作进度
    """
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此创作")
    
    steps = (creation.extra_data or {}).get("steps", {})
    
    return success_response(
        data={
            "creation_id": creation.creation_id,
            "uuid": creation.uuid,
            "status": creation.status,
            "current_task_id": creation.current_task_id,
            "steps": steps,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
        },
        message="获取进度成功"
    )


from app.api.api_v1.endpoints.agent import (
    agent_chat,
    get_messages,
    interrupt_session,
    reset_session,
    get_session_status
)


@router.post("/{creation_uuid}/agent/chat", tags=["Agent"])
async def agent_chat_endpoint(
    creation_uuid: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    return await agent_chat(creation_uuid, request, db, current_user)


@router.get("/{creation_uuid}/agent/messages", tags=["Agent"])
async def get_messages_endpoint(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    before: Optional[str] = None,
    after: Optional[str] = None
):
    return await get_messages(creation_uuid, db, current_user, limit, before, after)


@router.post("/{creation_uuid}/agent/interrupt", tags=["Agent"])
async def interrupt_session_endpoint(
    creation_uuid: str,
    request: InterruptRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    return await interrupt_session(creation_uuid, request, db, current_user)


@router.post("/{creation_uuid}/agent/reset", tags=["Agent"])
async def reset_session_endpoint(
    creation_uuid: str,
    request: ResetRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    return await reset_session(creation_uuid, request, db, current_user)


@router.get("/{creation_uuid}/agent/status", tags=["Agent"])
async def get_session_status_endpoint(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    return await get_session_status(creation_uuid, db, current_user)
