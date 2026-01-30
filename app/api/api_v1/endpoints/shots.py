import math
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from pydantic import BaseModel

from app.api.deps import get_async_db, get_current_user
from app.models.user import User
from app.models.scene import Scene
from app.models.shot import Shot
from app.models.character import Character
from app.schemas.shot import (
    ShotCreate,
    ShotUpdate,
    ShotResponse,
    ShotListResponse,
    ShotRegenerateRequest,
    ShotCharactersUpdateRequest,
    ShotNarrationUpdateRequest,
    ShotRegenerateVideoRequest,
    ShotGenerateVideoRequest,
)
from app.utils.response import success_response
from app.tasks.shot_task import generate_single_shot_image_task
from app.tasks.step8_video_gen_task import generate_single_shot_video_task
from app.core.logger import logger
from app.services.points_async_service import PointsAsyncService
from app.utils.model_prices import ModelPrices
from app.core.config import settings
from app.core.exceptions import InsufficientPointsError
from app.services.model_config_service import ModelConfigService

router = APIRouter()


@router.get("/scene/{scene_uuid}")
async def get_scene_shots(
    scene_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取场景的分镜列表"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.characters)
        ).where(Shot.scene_id == scene.scene_id).order_by(Shot.shot_number)
    )
    shots = result.scalars().all()
    
    shot_responses = [ShotResponse.from_db_model(shot) for shot in shots]
    
    return success_response(
        data={
            "items": [shot.model_dump() for shot in shot_responses],
            "total": len(shot_responses)
        },
        message="获取分镜列表成功"
    )


@router.post("/")
async def create_shot(
    shot_data: ShotCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """创建新分镜"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.creation)
        ).where(Scene.scene_id == shot_data.scene_id)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    shot_number = shot_data.shot_number
    if shot_number is None:
        result = await db.execute(
            select(func.max(Shot.shot_number)).where(Shot.scene_id == shot_data.scene_id)
        )
        max_number = result.scalar()
        shot_number = (max_number or 0) + 1
    
    narration_data = shot_data.narration
    if isinstance(narration_data, list):
        narration_data = json.dumps([item.model_dump(by_alias=True) for item in narration_data], ensure_ascii=False)
        
    shot = Shot(
        title=shot_data.title,
        shot_number=shot_number,
        description=shot_data.description,
        narration=narration_data,
        image_prompt=shot_data.image_prompt,
        scene_id=shot_data.scene_id,
        creation_id=scene.creation_id
    )
    
    db.add(shot)
    await db.flush()
    
    if shot_data.associated_characters:
        result = await db.execute(
            select(Character).where(Character.character_id.in_(shot_data.associated_characters))
        )
        characters = result.scalars().all()
        shot.characters = characters
    
    await db.commit()
    await db.refresh(shot)
    
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.characters)
        ).where(Shot.shot_id == shot.shot_id)
    )
    shot = result.scalar_one_or_none()
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="分镜创建成功"
    )


@router.get("/{shot_uuid}")
async def get_shot(
    shot_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """根据UUID获取分镜详情"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.characters),
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该分镜")
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="获取分镜成功"
    )


@router.put("/{shot_uuid}")
async def update_shot(
    shot_uuid: str,
    shot_update: ShotUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """更新分镜信息"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.characters),
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该分镜")
    
    if shot_update.title is not None:
        shot.title = shot_update.title
    if shot_update.shot_number is not None:
        shot.shot_number = shot_update.shot_number
    if shot_update.description is not None:
        shot.description = shot_update.description
    if shot_update.narration is not None:
        if isinstance(shot_update.narration, list):
            shot.narration = json.dumps([item.model_dump(by_alias=True) for item in shot_update.narration], ensure_ascii=False)
        else:
            shot.narration = shot_update.narration
    if shot_update.image_prompt is not None:
        shot.image_prompt = shot_update.image_prompt
    if shot_update.image_url is not None:
        shot.image_url = shot_update.image_url
    if shot_update.video_duration is not None:
        shot.video_duration = shot_update.video_duration
    if shot_update.extra_data is not None:
        shot.extra_data = shot_update.extra_data
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(shot, 'extra_data')
    
    if shot_update.scene_id is not None:
        result = await db.execute(
            select(Scene).where(Scene.scene_id == shot_update.scene_id)
        )
        new_scene = result.scalar_one_or_none()
        if not new_scene:
            raise HTTPException(status_code=404, detail="目标场景不存在")
        if new_scene.creation_id != shot.scene.creation_id:
            raise HTTPException(status_code=400, detail="目标场景不属于当前创作")
        shot.scene_id = shot_update.scene_id

    if shot_update.associated_characters is not None:
        result = await db.execute(
            select(Character).where(Character.character_id.in_(shot_update.associated_characters))
        )
        characters = result.scalars().all()
        shot.characters = characters
    
    await db.commit()
    await db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="分镜更新成功"
    )


@router.put("/{shot_uuid}/characters")
async def update_shot_characters(
    shot_uuid: str,
    payload: ShotCharactersUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """仅更新分镜关联的角色"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.characters),
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该分镜")
    
    if payload.associated_characters:
        result = await db.execute(
            select(Character).where(Character.character_id.in_(payload.associated_characters))
        )
        characters = result.scalars().all()
        shot.characters = characters
    else:
        shot.characters = []
    
    await db.commit()
    await db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    return success_response(
        data=shot_response.model_dump(),
        message="分镜角色更新成功"
    )


@router.put("/{shot_uuid}/narration")
async def update_shot_narration(
    shot_uuid: str,
    payload: ShotNarrationUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user),
):
    """更新分镜旁白"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.characters),
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该分镜")
    
    shot.narration = json.dumps([item.model_dump(by_alias=True) for item in payload.narration], ensure_ascii=False)
    
    await db.commit()
    await db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    return success_response(
        data=shot_response.model_dump(),
        message="分镜旁白更新成功"
    )


@router.post("/{shot_uuid}/generate-image")
async def generate_shot_image(
    shot_uuid: str,
    request: ShotRegenerateRequest = ShotRegenerateRequest(),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """生成分镜图片"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation),
            selectinload(Shot.characters)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    if request.image_prompt:
        shot.image_prompt = request.image_prompt
        await db.commit()
        await db.refresh(shot)
    
    if not shot.image_prompt:
        raise HTTPException(status_code=400, detail="分镜没有图片提示词，无法生成图片")
    
    creation_id = shot.scene.creation.creation_id
    
    extra_data = shot.scene.creation.extra_data or {}
    image_model = (
        request.model_name
        or extra_data.get("image_to_image_model")
        or extra_data.get("text_to_image_model")
        or settings.IMAGE_MODEL_IMAGE_TO_IMAGE
        or settings.IMAGE_MODEL_TEXT_TO_IMAGE
        or settings.IMAGE_MODEL_NAME
        or "black-forest-labs/flux-kontext-pro/multi"
    )
    
    reference_image_count = 0
    if shot.characters:
        reference_image_count = sum(1 for c in shot.characters if getattr(c, "image_url", None))
    
    try:
        model_config = ModelConfigService.get_model_config(image_model, "image_to_image")
        image_size = model_config.get("image_size", "2K") if model_config else "2K"
    except Exception:
        image_size = "2K"
    
    cost = ModelPrices.calculate_image_cost(
        image_model,
        1,
        reference_image_count=reference_image_count,
        image_size=image_size
    )
    required_points = int(math.ceil(cost * 100))
    if required_points <= 0:
        required_points = 1
    
    try:
        freeze_record = await PointsAsyncService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=required_points,
            operation_type="generate_shot",
            creation_id=creation_id,
            novel_id=shot.scene.creation.novel_id,
            description=f"生成分镜图片（{shot.title}）",
            extra_data={
                "shot_id": shot.shot_id,
                "shot_uuid": shot_uuid,
                "task_type": "shot_image_generation"
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))
    
    task = generate_single_shot_image_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id,
        model_name=request.model_name,
        freeze_record_id=freeze_record.record_id
    )
    
    logger.info(f"分镜 {shot_uuid} 图片生成任务已启动: task_id={task.id}, freeze_record_id={freeze_record.record_id}")
    
    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "creation_uuid": shot.scene.creation.uuid,
            "freeze_record_id": freeze_record.record_id
        },
        message="分镜图片生成任务已启动"
    )


@router.post("/{shot_uuid}/regenerate")
async def regenerate_shot_image(
    shot_uuid: str,
    request: ShotRegenerateRequest = ShotRegenerateRequest(),
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """重新生成分镜图片"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation),
            selectinload(Shot.characters)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    frame_type = request.frame_type or "both"
    force_regen_prompt = request.refresh_prompt
    
    if request.image_prompt is not None:
        if frame_type in ("start", "both"):
            shot.image_prompt = request.image_prompt
            logger.info(f"分镜 {shot_uuid} [{frame_type}] 更新首帧提示词")
        force_regen_prompt = False
    elif frame_type in ("start", "both") and not shot.image_prompt:
        force_regen_prompt = True
    elif frame_type == "end" and not (shot.extra_data or {}).get("end_frame_image_prompt"):
        force_regen_prompt = True
    elif request.refresh_prompt:
        if frame_type in ("start", "both"):
            shot.image_prompt = None
            logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空首帧提示词以便重新生成")
        if frame_type in ("end", "both"):
            if shot.extra_data and "end_frame_image_prompt" in shot.extra_data:
                shot.extra_data["end_frame_image_prompt"] = None
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(shot, "extra_data")
                logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空尾帧提示词以便重新生成")
        force_regen_prompt = True

    if force_regen_prompt and not shot.description:
        raise HTTPException(status_code=400, detail="分镜没有描述且没有现有提示词，无法生成提示词")

    if not force_regen_prompt:
        if frame_type in ("start", "both") and not shot.image_prompt:
            raise HTTPException(status_code=400, detail="分镜没有首帧提示词，无法生成首帧图片")
        if frame_type in ("end", "both") and not (shot.extra_data or {}).get("end_frame_image_prompt"):
            raise HTTPException(status_code=400, detail="分镜没有尾帧提示词，无法生成尾帧图片")

    if frame_type in ("start", "both"):
        shot.image_url = None
        logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空首帧 image_url")
    
    if frame_type in ("end", "both"):
        if shot.extra_data and "end_frame_image_url" in shot.extra_data:
            shot.extra_data["end_frame_image_url"] = None
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(shot, "extra_data")
            logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空尾帧 end_frame_image_url")

    await db.commit()
    await db.refresh(shot)

    creation_id = shot.scene.creation.creation_id

    extra_data = shot.scene.creation.extra_data or {}
    image_model = (
        request.model_name
        or extra_data.get("image_to_image_model")
        or extra_data.get("text_to_image_model")
        or settings.IMAGE_MODEL_IMAGE_TO_IMAGE
        or settings.IMAGE_MODEL_TEXT_TO_IMAGE
        or settings.IMAGE_MODEL_NAME
        or "black-forest-labs/flux-kontext-pro/multi"
    )
    
    reference_image_count = 0
    if shot.characters:
        reference_image_count = sum(1 for c in shot.characters if getattr(c, "image_url", None))
    
    try:
        model_config = ModelConfigService.get_model_config(image_model, "image_to_image")
        image_size = model_config.get("image_size", "2K") if model_config else "2K"
    except Exception:
        image_size = "2K"
    
    cost = ModelPrices.calculate_image_cost(
        image_model,
        1,
        reference_image_count=reference_image_count,
        image_size=image_size
    )
    required_points = int(math.ceil(cost * 100))
    if required_points <= 0:
        required_points = 1
    
    try:
        freeze_record = await PointsAsyncService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=required_points,
            operation_type="regenerate_shot",
            creation_id=creation_id,
            novel_id=shot.scene.creation.novel_id,
            description=f"重新生成分镜图片（{shot.title}）",
            extra_data={
                "shot_id": shot.shot_id,
                "shot_uuid": shot_uuid,
                "task_type": "shot_image_regeneration",
                "frame_type": frame_type,
                "force_regen_prompt": force_regen_prompt
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))
    
    task = generate_single_shot_image_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id,
        model_name=request.model_name,
        freeze_record_id=freeze_record.record_id,
        frame_type=frame_type,
        force_regen_prompt=force_regen_prompt
    )
    
    logger.info(f"分镜 {shot_uuid} [{frame_type}] 图片重新生成任务已启动: task_id={task.id}, freeze_record_id={freeze_record.record_id}")
    
    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "creation_uuid": shot.scene.creation.uuid,
            "image_prompt": shot.image_prompt if frame_type in ("start", "both") else None,
            "end_frame_image_prompt": (shot.extra_data or {}).get("end_frame_image_prompt") if frame_type in ("end", "both") else None,
            "freeze_record_id": freeze_record.record_id
        },
        message="分镜图片重新生成任务已启动"
    )


@router.delete("/{shot_uuid}")
async def delete_shot(
    shot_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """删除分镜"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限删除该分镜")
    
    await db.delete(shot)
    await db.commit()
    
    return success_response(
        data={"shot_uuid": shot_uuid},
        message="分镜删除成功"
    )


class ApplyShotImageVersionRequest(BaseModel):
    version_id: str
    image_url: str
    image_prompt: Optional[str] = None


@router.get("/{shot_uuid}/image-history")
async def get_shot_image_history(
    shot_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取分镜图片生成历史"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该分镜")
    
    image_history = shot.extra_data.get('image_history', []) if shot.extra_data else []
    
    return success_response(
        data={
            "current_image_url": shot.image_url,
            "current_image_prompt": shot.image_prompt,
            "image_history": image_history
        },
        message="获取分镜图片历史成功"
    )


@router.post("/{shot_uuid}/apply-image-version")
async def apply_shot_image_version(
    shot_uuid: str,
    request: ApplyShotImageVersionRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """将历史图片应用为分镜的当前图片"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    image_history = shot.extra_data.get('image_history', []) if shot.extra_data else []
    
    version_found = any(v.get('version_id') == request.version_id for v in image_history)
    
    if not version_found:
        raise HTTPException(status_code=404, detail="指定的版本不存在")
    
    shot.image_url = request.image_url
    if request.image_prompt:
        shot.image_prompt = request.image_prompt

    for version in image_history:
        version['is_current'] = version.get('version_id') == request.version_id
    
    if shot.extra_data is None:
        shot.extra_data = {}
    shot.extra_data['image_history'] = image_history
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(shot, "extra_data")
    
    await db.commit()
    await db.refresh(shot)

    return success_response(
        data={
            "shot_uuid": shot_uuid,
            "image_url": shot.image_url,
            "image_prompt": shot.image_prompt
        },
        message="应用历史图片成功"
    )


@router.post("/{shot_uuid}/generate-video")
async def generate_shot_video(
    shot_uuid: str,
    request: ShotGenerateVideoRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    生成分镜视频
    """
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    if not shot.image_url:
        raise HTTPException(status_code=400, detail="分镜没有图片，无法生成视频")

    # 计算所需积分
    creation_id = shot.scene.creation.creation_id
    video_duration = shot.video_duration or 5

    try:
        freeze_record = await PointsAsyncService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=int(video_duration * 10),  # 每秒10积分
            operation_type="generate_video",
            extra_data={
                "shot_id": shot.shot_id,
                "creation_id": creation_id,
                "video_duration": video_duration,
                "task_type": "video_generation"
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 启动视频生成任务
    task = generate_single_shot_video_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id,
        freeze_record_id=freeze_record.record_id,
        model_name=request.model_name,
        last_frame_image_url=request.last_frame_image_url
    )

    logger.info(f"分镜 {shot_uuid} 视频生成任务已启动: task_id={task.id}, freeze_record_id={freeze_record.record_id}")

    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "video_duration": video_duration,
            "required_points": freeze_record.points
        },
        message="视频生成任务已启动"
    )


@router.post("/{shot_uuid}/regenerate-video")
async def regenerate_shot_video(
    shot_uuid: str,
    request: ShotRegenerateVideoRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    重新生成分镜视频
    """
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    if not shot.image_url:
        raise HTTPException(status_code=400, detail="分镜没有图片，无法生成视频")

    # 清除视频URL
    shot.video_url = None
    await db.commit()

    # 计算所需积分
    creation_id = shot.scene.creation.creation_id
    video_duration = shot.video_duration or 5

    try:
        freeze_record = await PointsAsyncService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=int(video_duration * 10),  # 每秒10积分
            operation_type="generate_video",
            extra_data={
                "shot_id": shot.shot_id,
                "creation_id": creation_id,
                "video_duration": video_duration,
                "task_type": "video_regeneration"
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 启动视频生成任务
    task = generate_single_shot_video_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id,
        freeze_record_id=freeze_record.record_id,
        model_name=request.model_name,
        last_frame_image_url=request.last_frame_image_url
    )

    logger.info(f"分镜 {shot_uuid} 视频重新生成任务已启动: task_id={task.id}, freeze_record_id={freeze_record.record_id}")

    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "video_duration": video_duration,
            "required_points": freeze_record.points
        },
        message="视频重新生成任务已启动"
    )
