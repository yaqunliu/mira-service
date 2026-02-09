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
        ).where(Shot.scene_id == scene.scene_id)
        .order_by(Shot.sequence_number)
    )
    shots = result.scalars().all()
    
    return success_response(
        data=[ShotResponse.model_validate(shot) for shot in shots],
        message="获取分镜列表成功"
    )


@router.get("/{shot_uuid}")
async def get_shot(
    shot_uuid: str,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """获取分镜详情"""
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
        raise HTTPException(status_code=403, detail="无权限访问该分镜")
    
    return success_response(
        data=ShotResponse.model_validate(shot),
        message="获取分镜详情成功"
    )


@router.post("/scene/{scene_uuid}")
async def create_shot(
    scene_uuid: str,
    shot_data: ShotCreate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """创建分镜"""
    result = await db.execute(
        select(Scene).options(
            selectinload(Scene.creation)
        ).where(Scene.uuid == scene_uuid)
    )
    scene = result.scalar_one_or_none()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限在该场景下创建分镜")
    
    # 获取当前最大序号
    result = await db.execute(
        select(func.max(Shot.sequence_number))
        .where(Shot.scene_id == scene.scene_id)
    )
    max_sequence = result.scalar() or 0
    
    shot = Shot(
        scene_id=scene.scene_id,
        creation_id=scene.creation_id,
        title=shot_data.title,
        description=shot_data.description,
        sequence_number=max_sequence + 1,
        narration=shot_data.narration,
        character_ids=shot_data.character_ids,
        video_duration=shot_data.video_duration or 5
    )
    
    db.add(shot)
    await db.commit()
    await db.refresh(shot)
    
    # 关联角色
    if shot_data.character_ids:
        result = await db.execute(
            select(Character).where(
                Character.character_id.in_(shot_data.character_ids),
                Character.creation_id == scene.creation_id
            )
        )
        characters = result.scalars().all()
        shot.characters = characters
        await db.commit()
    
    return success_response(
        data=ShotResponse.model_validate(shot),
        message="分镜创建成功"
    )


@router.put("/{shot_identifier}")
async def update_shot(
    shot_identifier: str,
    shot_data: ShotUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """更新分镜"""
    # 支持 uuid 或 shot_id（数字）
    if shot_identifier.isdigit():
        result = await db.execute(
            select(Shot).options(
                selectinload(Shot.scene).selectinload(Scene.creation),
                selectinload(Shot.characters)
            ).where(Shot.shot_id == int(shot_identifier))
        )
    else:
        result = await db.execute(
            select(Shot).options(
                selectinload(Shot.scene).selectinload(Scene.creation),
                selectinload(Shot.characters)
            ).where(Shot.uuid == shot_identifier)
        )
    
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限更新该分镜")
    
    # 更新字段
    if shot_data.title is not None:
        shot.title = shot_data.title
    if shot_data.description is not None:
        shot.description = shot_data.description
    if shot_data.narration is not None:
        import json
        shot.narration = json.dumps([item.model_dump(by_alias=True) for item in shot_data.narration], ensure_ascii=False)
    if shot_data.associated_characters is not None:
        result = await db.execute(
            select(Character).where(
                Character.character_id.in_(shot_data.associated_characters),
                Character.creation_id == shot.scene.creation_id
            )
        )
        characters = result.scalars().all()
        shot.characters = characters
    if shot_data.video_duration is not None:
        shot.video_duration = shot_data.video_duration

    if shot_data.image_prompt is not None:
        shot.image_prompt = shot_data.image_prompt
    
    # 直接更新图片URL
    if shot_data.image_url is not None:
        shot.image_url = shot_data.image_url

    # 直接更新视频URL
    if shot_data.video_url is not None:
        logger.info(f"Updating video_url for shot {shot_identifier}: {shot_data.video_url}")
        shot.video_url = shot_data.video_url

    # 直接更新音频URL
    if shot_data.audio_url is not None:
        logger.info(f"Updating audio_url for shot {shot_identifier}: {shot_data.audio_url}")
        shot.audio_url = shot_data.audio_url

    # 如果直接更新了 extra_data 中的视频提示词相关字段
    if shot_data.extra_data is not None:
        if shot.extra_data is None:
            shot.extra_data = {}
        for key, value in shot_data.extra_data.items():
            shot.extra_data[key] = value
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(shot, "extra_data")

    await db.commit()
    await db.refresh(shot)
    
    return success_response(
        data=ShotResponse.model_validate(shot),
        message="分镜更新成功"
    )


@router.put("/{shot_uuid}/characters")
async def update_shot_characters(
    shot_uuid: str,
    request: ShotCharactersUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """更新分镜关联的角色"""
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
        raise HTTPException(status_code=403, detail="无权限更新该分镜")

    # 更新角色关联
    if request.character_ids is not None:
        # 手动操作关联表：先删除旧的关联，再添加新的关联
        from app.models.shot import shot_characters

        # 1. 删除该分镜的所有旧角色关联
        await db.execute(
            shot_characters.delete().where(shot_characters.c.shot_id == shot.shot_id)
        )

        # 2. 添加新的角色关联
        valid_character_ids = request.character_ids 
        # if request.character_ids:
        #     # 验证角色是否属于同一个 creation
        #     result = await db.execute(
        #         select(Character).where(
        #             Character.character_id.in_(request.character_ids),
        #             Character.creation_id == shot.scene.creation_id
        #         )
        #     )
        #     valid_characters = result.scalars().all()
        #     valid_character_ids = [c.character_id for c in valid_characters]

        # 批量插入新的关联关系
        if valid_character_ids:
            await db.execute(
                shot_characters.insert(),
                [{"shot_id": shot.shot_id, "character_id": char_id} for char_id in valid_character_ids]
            )

        await db.commit()

        # 重新查询以获取完整的角色数据
        result = await db.execute(
            select(Shot).options(
                selectinload(Shot.characters)
            ).where(Shot.uuid == shot_uuid)
        )
        shot = result.scalar_one_or_none()

    return success_response(
        data=ShotResponse.from_db_model(shot),
        message="分镜角色更新成功"
    )


@router.put("/{shot_uuid}/narration")
async def update_shot_narration(
    shot_uuid: str,
    request: ShotNarrationUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """更新分镜旁白"""
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation)
        ).where(Shot.uuid == shot_uuid)
    )
    shot = result.scalar_one_or_none()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限更新该分镜")
    
    # 更新旁白
    if request.narration is not None:
        shot.narration = request.narration
        await db.commit()
    
    return success_response(
        data=ShotResponse.model_validate(shot),
        message="分镜旁白更新成功"
    )


@router.post("/{shot_uuid}/generate")
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

    if not shot.description:
        raise HTTPException(status_code=400, detail="分镜没有描述，无法生成图片")

    # 计算所需积分
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

    # 如果没有提示词，自动设置 force_regen_prompt 为 True 来生成提示词
    if frame_type in ("start", "both") and not shot.image_prompt:
        force_regen_prompt = True
        logger.info(f"分镜 {shot_uuid} 首帧提示词为空，将自动生成提示词")
    if frame_type in ("end", "both") and not (shot.extra_data or {}).get("end_frame_image_prompt"):
        force_regen_prompt = True
        logger.info(f"分镜 {shot_uuid} 尾帧提示词为空，将自动生成提示词")

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


# ==================== Narration Audio Generation API ====================

class GenerateNarrationAudioRequest(BaseModel):
    """生成 narration 音频请求"""
    narration_index: int
    speaker: str
    text: str


@router.post("/{shot_id}/generate-narration-audio")
async def generate_narration_audio(
    shot_id: int,
    request: GenerateNarrationAudioRequest,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(get_current_user)
):
    """
    为 narration 生成音频

    - shot_id: 分镜 ID
    - narration_index: narration 数组索引
    - speaker: 说话者名称
    - text: 文本内容
    """
    from app.agent.tools.audio_tools import GenerateNarrationAudioBatchTool
    from app.agent.state.schemas import ComicDramaState

    # 获取 shot
    result = await db.execute(
        select(Shot).options(
            selectinload(Shot.scene).selectinload(Scene.creation),
            selectinload(Shot.characters)
        ).where(Shot.shot_id == shot_id)
    )
    shot = result.scalar_one_or_none()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    try:
        # 创建工具实例
        audio_batch_tool = GenerateNarrationAudioBatchTool()

        # 创建状态对象
        state = ComicDramaState(creation_uuid=shot.scene.creation.uuid)

        # 生成音频（传入已存在的 db 会话）
        result = await audio_batch_tool.execute(
            state=state,
            shot_id=shot_id,
            force_regenerate=True,  # 强制重新生成
            db=db  # 使用 API 的 db 会话
        )

        if result.get("success"):
            data = result.get("data", {})
            narrations = data.get("narrations", [])

            # 找到对应的 narration
            if request.narration_index < len(narrations):
                narration_data = narrations[request.narration_index]
                return success_response(
                    data={
                        "audio_url": narration_data.get("audio_url"),
                        "audio_historys": narration_data.get("audio_historys", [])
                    },
                    message="音频生成成功"
                )
            else:
                raise HTTPException(status_code=500, detail="narration 索引超出范围")
        else:
            error_msg = result.get("error", "音频生成失败")
            logger.error(f"生成 narration 音频失败: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    except Exception as e:
        logger.exception(f"生成 narration 音频异常: {e}")
        raise HTTPException(status_code=500, detail=f"音频生成失败: {str(e)}")
