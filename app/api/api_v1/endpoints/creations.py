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
from app.tasks.creation_task import character_analysis_task, scene_analysis_task, shot_analysis_task

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
                        "uuid": character.uuid,
                        "name": character.name,
                        "status": character.status,
                        "basic_info": character.basic_info,
                        "appearance": character.appearance,
                        "body": character.body,
                        "hair": character.hair,
                        "clothing": character.clothing,
                        "voice_description": character.voice_description,
                        "image_prompt": character.image_prompt,
                        "visual_style": character.visual_style,
                        "image_url": character.image_url,
                        "novel_id": character.novel_id,
                        "creation_id": character.creation_id,
                        "created_at": character.created_at,
                        "updated_at": character.updated_at,
                    }
                    creation_data["characters"].append(character_data)

            creation_data["scenes"] = []
            if hasattr(creation, 'scenes'):
                for scene in (creation.scenes or []):
                    scene_data = {
                        "scene_id": scene.scene_id,
                        "title": scene.title,
                        "image_url": scene.image_url,
                        "shots": []
                    }
                    if hasattr(scene, 'shots'):
                        for shot in (scene.shots or []):
                            shot_data = {
                                "shot_id": shot.shot_id,
                                "title": shot.title,
                                "image_url": shot.image_url,
                            }
                            scene_data["shots"].append(shot_data)
                    creation_data["scenes"].append(scene_data)

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

    # 根据 character_ids 获取角色列表（包括复用的角色）
    characters = []
    if creation.character_ids:
        from sqlalchemy import select
        result = await db.execute(
            select(Character)
            .where(Character.character_id.in_(creation.character_ids))
            .order_by(Character.created_at.asc())
        )
        characters = result.scalars().all()

    # 根据 scene_ids 获取场景列表（包括复用的场景）
    # 但每个场景下的 shots 只返回属于当前 creation 的分镜
    scenes_data = []
    if creation.scene_ids:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.shot import Shot

        # 获取所有场景，按创建时间排序
        scenes_result = await db.execute(
            select(Scene)
            .where(Scene.scene_id.in_(creation.scene_ids))
            .order_by(Scene.created_at.asc())
        )
        scenes = scenes_result.scalars().all()

        # 获取当前 creation 的所有分镜，预加载角色关系，按创建时间排序
        shots_result = await db.execute(
            select(Shot)
            .options(selectinload(Shot.characters))
            .where(Shot.creation_id == creation.creation_id)
            .order_by(Shot.created_at.asc())
        )
        creation_shots = {s.shot_id: s for s in shots_result.scalars().all()}

        for scene in scenes:
            # 只返回属于当前 creation 的分镜，按 shot_number 排序
            scene_shots = []
            # 筛选属于当前 creation 的分镜并按 shot_number 排序
            sorted_shots = sorted(
                [s for s in creation_shots.values() if s.scene_id == scene.scene_id],
                key=lambda x: x.shot_number
            )
            for shot in sorted_shots:
                # 解析 narration JSON 字符串为数组
                narration_data = shot.narration
                if narration_data and isinstance(narration_data, str):
                    try:
                        narration_data = json.loads(narration_data)
                    except json.JSONDecodeError:
                        narration_data = [{"角色": "旁白", "内容": narration_data}]
                elif not narration_data:
                    narration_data = []

                # 获取关联的角色
                shot_characters = []
                if shot.characters:
                    for char in shot.characters:
                        shot_characters.append({
                            "character_id": char.character_id,
                            "uuid": char.uuid,
                            "name": char.name,
                            "image_url": char.image_url,
                        })

                scene_shots.append({
                    "shot_id": shot.shot_id,
                    "uuid": shot.uuid,
                    "scene_id": shot.scene_id,
                    "shot_number": shot.shot_number,
                    "title": shot.title,
                    "description": shot.description,
                    "narration": narration_data,
                    "image_url": shot.image_url,
                    "video_url": shot.video_url,
                    "audio_url": shot.audio_url,
                    "status": shot.status,
                    "video_status": shot.video_status,
                    "status_detail": shot.status_detail,
                    "extra_data": shot.extra_data,
                    "characters": shot_characters,
                    "image_prompt": shot.image_prompt,
                })

            scenes_data.append({
                "scene_id": scene.scene_id,
                "uuid": scene.uuid,
                "title": scene.title,
                "time_setting": scene.time_setting,
                "location": scene.location,
                "space_type": scene.space_type,
                "atmosphere": scene.atmosphere,
                "image_url": scene.image_url,
                "status": scene.status,
                "extra_data": scene.extra_data,
                "shots": scene_shots,
            })

    return success_response(
        data={
            "creation_id": creation.creation_id,
            "uuid": creation.uuid,
            "title": creation.title,
            "status": creation.status,
            "novel_id": creation.novel_id,
            "chapter_id": creation.chapter_id,
            "video_url": creation.video_url,
            "audio_url": creation.audio_url,
            "subtitle_url": creation.subtitle_url,
            "created_at": creation.created_at,
            "updated_at": creation.updated_at,
            "extra_data": creation.extra_data,
            "character_ids": creation.character_ids or [],  # 返回 character_ids 列表
            "characters": [
                {
                    "character_id": c.character_id,
                    "uuid": c.uuid,
                    "name": c.name,
                    "status": c.status,
                    "basic_info": c.basic_info,
                    "appearance": c.appearance,
                    "body": c.body,
                    "hair": c.hair,
                    "clothing": c.clothing,
                    "voice_description": c.voice_description,
                    "image_prompt": c.image_prompt,
                    "visual_style": c.visual_style,
                    "image_url": c.image_url,
                    "novel_id": c.novel_id,
                    "creation_id": c.creation_id,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                }
                for c in characters
            ],
            "scenes": scenes_data,
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
        return success_response(data={}, message="删除创作成功")
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


@router.get("/{creation_uuid}/novel-characters")
async def get_creation_novel_characters(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    获取创作所属小说的所有角色

    通过 creation_uuid 获取 novel_id，然后返回该小说下的所有角色
    """
    # 1. 获取 creation
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)

    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")

    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此创作")

    if not creation.novel_id:
        raise HTTPException(status_code=400, detail="创作未关联小说")

    # 2. 根据 novel_id 获取该小说下的所有角色
    from sqlalchemy import select
    result = await db.execute(
        select(Character)
        .where(Character.novel_id == creation.novel_id)
        .order_by(Character.created_at.asc())
    )
    characters = result.scalars().all()

    # 3. 构建角色列表
    characters_data = [
        {
            "character_id": character.character_id,
            "uuid": character.uuid,
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
            "novel_id": character.novel_id,
            "created_at": character.created_at,
            "updated_at": character.updated_at,
        }
        for character in characters
    ]

    return success_response(
        data={
            "creation_uuid": creation_uuid,
            "novel_id": creation.novel_id,
            "characters": characters_data,
        },
        message="获取角色列表成功"
    )


@router.post("/{creation_uuid}/analyze-characters")
async def analyze_characters(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """
    重新触发角色分析任务
    """
    creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权访问此创作")
    
    # 获取内容 URL
    content_url = creation.text_content_url
    if not content_url and creation.chapter_id:
        from app.services.novel_async_service import ChapterAsyncService
        chapter = await ChapterAsyncService.get_chapter_by_id(db, creation.chapter_id)
        if chapter:
            content_url = chapter.content_url
            
    if not content_url:
        raise HTTPException(status_code=400, detail="未找到创作内容，无法进行分析")

    # 提交任务
    task = character_analysis_task.delay(
        novel_id=creation.novel_id or 0,
        chapter_id=creation.chapter_id or 0,
        creation_id=creation.creation_id,
        chapter_content_url=content_url
    )
    
    task_id = str(task.id)
    
    # 更新 current_task_id
    creation.current_task_id = task_id
    await db.flush()
    await db.commit()
    
    logger.info(f"手动提交角色分析任务: creation_uuid={creation_uuid}, task_id={task_id}")
    
    return success_response(
        data={"task_id": task_id, "message": "角色分析任务已提交"},
        message="任务提交成功"
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


class GeneratePlaybookRequest(BaseModel):
    narration_mode: str = "original"


@router.post("/{creation_uuid}/generate-playbook")
async def generate_playbook(
    creation_uuid: str,
    request: GeneratePlaybookRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    手动启动分镜拆分任务（剧本生成）
    
    Args:
        creation_uuid: 创作项目UUID
        narration_mode: 旁白模式，默认 "original"
    """
    try:
        # 获取创作项目
        creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 检查权限
        if creation.owner_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作此创作项目")
        
        # 获取章节内容URL
        chapter_content_url = None
        if creation.chapter_id:
            from app.services.novel_async_service import ChapterAsyncService
            chapter = await ChapterAsyncService.get_chapter_by_id(db, creation.chapter_id)
            if chapter:
                chapter_content_url = chapter.content_url
        
        if not chapter_content_url:
            raise HTTPException(status_code=400, detail="未找到章节内容，无法生成分镜")
        
        # 启动场景分析任务（第二步）
        task = scene_analysis_task.delay(
            novel_id=creation.novel_id or 0,
            chapter_id=creation.chapter_id or 0,
            creation_id=creation.creation_id,
            chapter_content_url=chapter_content_url
        )
        
        logger.info(f"分镜拆分任务已启动: creation_uuid={creation_uuid}, task_id={task.id}")
        
        return success_response(
            data={
                "task_id": task.id,
                "creation_uuid": creation_uuid,
                "message": "分镜拆分任务已启动"
            },
            message="任务启动成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动分镜拆分任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.post("/{creation_uuid}/generate-scene-images")
async def start_generate_scene_images(
    creation_uuid: str,
    force_regenerate: bool = False,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    启动批量生成场景图片任务
    
    Args:
        creation_uuid: 创作项目UUID
        force_regenerate: 是否强制重新生成，默认False
    """
    try:
        # 获取创作项目
        creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")
        
        # 检查权限
        if creation.owner_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作此创作项目")
        
        # 检查是否有场景
        if not creation.scene_ids:
            raise HTTPException(status_code=400, detail="未找到场景，请先进行场景分析")
        
        # 导入任务函数
        from app.tasks.step4_scene_image_gen_task import batch_generate_scene_images_task
        
        # 启动批量生成场景图片任务
        task = batch_generate_scene_images_task.delay(
            creation_id=creation.creation_id,
            force_regenerate=force_regenerate
        )
        
        logger.info(f"批量生成场景图片任务已启动: creation_uuid={creation_uuid}, task_id={task.id}, force_regenerate={force_regenerate}")
        
        return success_response(
            data={
                "task_id": task.id,
                "creation_uuid": creation_uuid,
                "message": "场景图片生成任务已启动"
            },
            message="任务启动成功"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动场景图片生成任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@router.post("/{creation_uuid}/analyze-shots")
async def analyze_shots(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    手动启动分镜分析任务（第三步：分镜拆解）
    """
    try:
        # 获取创作项目
        creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")

        # 检查权限
        if creation.owner_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作此创作项目")

        # 获取章节内容URL
        chapter_content_url = None
        if creation.chapter_id:
            from app.services.novel_async_service import ChapterAsyncService
            chapter = await ChapterAsyncService.get_chapter_by_id(db, creation.chapter_id)
            if chapter:
                chapter_content_url = chapter.content_url

        if not chapter_content_url:
            raise HTTPException(status_code=400, detail="未找到章节内容，无法解析分镜")

        # 检查是否有场景
        if not creation.scene_ids:
            raise HTTPException(status_code=400, detail="未找到场景，请先进行场景分析")

        # 启动分镜分析任务（第三步）
        task = shot_analysis_task.delay(
            novel_id=creation.novel_id or 0,
            chapter_id=creation.chapter_id or 0,
            creation_id=creation.creation_id,
            chapter_content_url=chapter_content_url
        )

        logger.info(f"分镜分析任务已启动: creation_uuid={creation_uuid}, task_id={task.id}")

        return success_response(
            data={
                "task_id": task.id,
                "message": "分镜分析任务已启动"
            },
            message="任务启动成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动分镜分析任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


class GenerateShotsRequest(BaseModel):
    force_regenerate: bool = False
    shot_ids: Optional[List[str]] = None


@router.post("/{creation_uuid}/generate-shots")
async def generate_shots(
    creation_uuid: str,
    request: GenerateShotsRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user)
):
    """
    启动批量生成分镜图片任务
    
    Args:
        creation_uuid: 创作项目UUID
        force_regenerate: 是否强制重新生成，默认False
        shot_ids: 指定分镜UUID列表（可选，不传则生成所有分镜）
    """
    try:
        # 获取创作项目
        creation = await CreationAsyncService.get_creation_by_uuid(db, creation_uuid)
        if not creation:
            raise HTTPException(status_code=404, detail="创作项目不存在")

        # 检查权限
        if creation.owner_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="无权限操作此创作项目")

        # 检查是否有分镜
        from sqlalchemy import select
        from app.models.shot import Shot
        
        shots_query = select(Shot).where(Shot.creation_id == creation.creation_id)
        if request.shot_ids:
            shots_query = shots_query.where(Shot.uuid.in_(request.shot_ids))
        
        shots_result = await db.execute(shots_query)
        shots = shots_result.scalars().all()
        
        if not shots:
            raise HTTPException(status_code=400, detail="未找到分镜，无法生成图片")

        # 导入任务函数
        from app.tasks.shot_task import generate_creation_shots_task

        # 启动批量生成分镜图片任务
        task = generate_creation_shots_task.delay(
            creation_id=creation.creation_id,
            force_regenerate=request.force_regenerate
        )

        logger.info(f"批量生成分镜图片任务已启动: creation_uuid={creation_uuid}, task_id={task.id}, shots_count={len(shots)}")

        return success_response(
            data={
                "task_id": task.id,
                "creation_uuid": creation_uuid,
                "message": "分镜图片生成任务已启动"
            },
            message="任务启动成功"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动分镜图片生成任务失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")
