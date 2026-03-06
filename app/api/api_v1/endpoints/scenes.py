from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional
from pydantic import BaseModel

from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.models.scene import Scene
from app.models.creation import Creation
from app.schemas.scene import (
    SceneCreate, 
    SceneUpdate, 
    SceneResponse,
    SceneListResponse,
    SceneWithShotsResponse,
    SceneRegenerateRequest
)
from app.utils.response import success_response

from app.tasks.step4_scene_image_gen_task import generate_single_scene_image_task
from app.tasks.step8_video_gen_task import generate_scene_videos_task
from app.core.logger import logger

router = APIRouter()


@router.get("/novel/{novel_id}")
async def get_novel_scenes(
    novel_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取小说的所有场景列表（用于场景复用）"""
    result = await db.execute(
        select(Scene).where(
            Scene.novel_id == novel_id,
            Scene.deleted_at.is_(None)
        ).order_by(Scene.scene_id.desc())
    )
    scenes = result.scalars().all()

    if scenes:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == scenes[0].creation_id)
        )
        first_scene_creation = result.scalar_one_or_none()
        
        if first_scene_creation and first_scene_creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该小说的场景")

    scene_responses = [SceneResponse.from_db_model(scene) for scene in scenes]

    return success_response(
        data={
            "items": [scene.model_dump() for scene in scene_responses],
            "total": len(scene_responses)
        },
        message="获取小说场景列表成功"
    )


@router.get("/creation/{creation_uuid}")
async def get_creation_scenes(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取创作项目的场景列表"""
    result = await db.execute(
        select(Creation).where(Creation.uuid == creation_uuid)
    )
    creation = result.scalar_one_or_none()
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.shots)
        ).where(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id)
    )
    scenes = result.scalars().all()
    
    scene_responses = [SceneResponse.from_db_model(scene) for scene in scenes]
    
    return success_response(
        data={
            "items": [scene.model_dump() for scene in scene_responses],
            "total": len(scene_responses)
        },
        message="获取场景列表成功"
    )


@router.get("/creation/{creation_uuid}/with-shots")
async def get_creation_scenes_with_shots(
    creation_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取创作项目的场景列表（包含完整分镜详情）"""
    result = await db.execute(
        select(Creation).where(Creation.uuid == creation_uuid)
    )
    creation = result.scalar_one_or_none()
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.shots)
        ).where(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id)
    )
    scenes = result.scalars().all()
    
    scene_responses = [SceneWithShotsResponse.from_db_model(scene) for scene in scenes]
    
    return success_response(
        data={
            "items": [scene.model_dump() for scene in scene_responses],
            "total": len(scene_responses)
        },
        message="获取场景列表成功"
    )


@router.post("/")
async def create_scene(
    scene_data: SceneCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """创建新场景"""
    result = await db.execute(
        select(Creation).where(Creation.creation_id == scene_data.creation_id)
    )
    creation = result.scalar_one_or_none()
    
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    scene_setting = scene_data.scene_setting
    
    scene = Scene(
        title=scene_data.title,
        duration=scene_data.duration,
        time_setting=scene_setting.time if scene_setting else None,
        location=scene_setting.location if scene_setting else None,
        space_type=scene_setting.space if scene_setting else None,
        atmosphere=scene_setting.atmosphere if scene_setting else None,
        creation_id=scene_data.creation_id
    )
    
    db.add(scene)
    await db.commit()
    await db.refresh(scene)
    
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.shots)
        ).where(Scene.scene_id == scene.scene_id)
    )
    scene = result.scalar_one_or_none()
    
    scene_response = SceneResponse.from_db_model(scene)
    
    return success_response(
        data=scene_response.model_dump(),
        message="场景创建成功"
    )


@router.get("/{scene_uuid}")
async def get_scene(
    scene_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """根据UUID获取场景详情"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.shots),
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    scene_response = SceneResponse.from_db_model(scene)
    
    return success_response(
        data=scene_response.model_dump(),
        message="获取场景成功"
    )


@router.get("/{scene_uuid}/with-shots")
async def get_scene_with_shots(
    scene_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """根据UUID获取场景详情（包含完整分镜详情）"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.shots),
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    return success_response(
        data=SceneWithShotsResponse.from_db_model(scene).model_dump(),
        message="获取场景详情成功"
    )


@router.put("/{scene_identifier}")
async def update_scene(
    scene_identifier: str,
    scene_update: SceneUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """更新场景信息"""
    # 支持 uuid 或 scene_id（数字）
    if scene_identifier.isdigit():
        result = await db.execute(
            select(Scene).options(
                selectinload(Scene.shots),
                selectinload(Scene.creation)
            ).where(Scene.scene_id == int(scene_identifier))
        )
    else:
        result = await db.execute(
            select(Scene).options(
                selectinload(Scene.shots),
                selectinload(Scene.creation)
            ).where(Scene.uuid == scene_identifier)
        )
    
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该场景")
    
    if scene_update.title is not None:
        scene.title = scene_update.title
    if scene_update.duration is not None:
        scene.duration = scene_update.duration
    
    if scene_update.scene_setting is not None:
        setting = scene_update.scene_setting
        if setting.time is not None:
            scene.time_setting = setting.time
        if setting.location is not None:
            scene.location = setting.location
        if setting.space is not None:
            scene.space_type = setting.space
        if setting.atmosphere is not None:
            scene.atmosphere = setting.atmosphere
    
    if scene_update.image_prompt is not None:
        if scene.extra_data is None:
            scene.extra_data = {}
        scene.extra_data["image_prompt"] = scene_update.image_prompt
        flag_modified(scene, "extra_data")
    
    if scene_update.image_url is not None:
        scene.image_url = scene_update.image_url
    
    await db.commit()
    await db.refresh(scene)
    
    scene_response = SceneResponse.from_db_model(scene)
    
    return success_response(
        data=scene_response.model_dump(),
        message="场景更新成功"
    )


@router.post("/{scene_uuid}/regenerate-image")
async def regenerate_scene_image(
    scene_uuid: str,
    request: SceneRegenerateRequest = SceneRegenerateRequest(),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """重新生成场景图片"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该场景")
    
    scene.image_url = None
    if request.image_prompt is not None:
        if scene.extra_data is None:
            scene.extra_data = {}
        scene.extra_data["image_prompt"] = request.image_prompt if request.image_prompt else None
        flag_modified(scene, "extra_data")
    elif request.refresh_prompt:
        if scene.extra_data and "image_prompt" in scene.extra_data:
            scene.extra_data["image_prompt"] = None
            flag_modified(scene, "extra_data")
    await db.commit()
    
    task = generate_single_scene_image_task.delay(
        scene_id=scene.scene_id,
        creation_id=scene.creation_id,
        model_name=request.model_name
    )
    
    logger.info(f"Scene {scene_uuid} image regeneration started: task_id={task.id}")
    
    return success_response(
        data={
            "task_id": task.id,
            "scene_uuid": scene_uuid
        },
        message="场景图片重新生成任务已启动"
    )


@router.post("/{scene_uuid}/regenerate-videos")
async def regenerate_scene_videos(
    scene_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """重新生成场景下所有分镜的视频"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该场景")
    
    task = generate_scene_videos_task.delay(
        scene_id=scene.scene_id,
        creation_id=scene.creation_id
    )
    
    logger.info(f"Scene {scene_uuid} video regeneration started: task_id={task.id}")
    
    return success_response(
        data={
            "task_id": task.id,
            "scene_uuid": scene_uuid
        },
        message="场景视频重新生成任务已启动"
    )


@router.delete("/{scene_uuid}")
async def delete_scene(
    scene_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """删除场景"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限删除该场景")
    
    await db.delete(scene)
    await db.commit()
    
    return success_response(
        data={"scene_uuid": scene_uuid},
        message="场景删除成功"
    )
