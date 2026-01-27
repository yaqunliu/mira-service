import math
import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel

from app.api.deps import get_db, get_current_user
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
from app.services.points_service import PointsService
from app.utils.model_prices import ModelPrices
from app.core.config import settings
from app.core.exceptions import InsufficientPointsError
from app.services.model_config_service import ModelConfigService

router = APIRouter()


@router.get("/scene/{scene_uuid}")
async def get_scene_shots(
    scene_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取场景的分镜列表
    
    Args:
        scene_uuid: 场景UUID
        
    Returns:
        分镜列表
    """
    # 获取场景并验证
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证权限
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    # 获取分镜列表，预加载characters关系
    shots = db.query(Shot).options(
        selectinload(Shot.characters)
    ).filter(Shot.scene_id == scene.scene_id).order_by(Shot.shot_number).all()
    
    # 转换为响应格式
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    创建新分镜
    
    Args:
        shot_data: 分镜创建数据
        
    Returns:
        创建的分镜信息
    """
    # 获取场景并验证（shot_data.scene_id是数字ID，因为它是外键）
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.scene_id == shot_data.scene_id).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证权限
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    # 如果没有提供shot_number，自动生成（获取当前最大的shot_number + 1）
    shot_number = shot_data.shot_number
    if shot_number is None:
        max_number = db.query(func.max(Shot.shot_number)).filter(
            Shot.scene_id == shot_data.scene_id
        ).scalar()
        shot_number = (max_number or 0) + 1
    
    # 创建分镜
    narration_data = shot_data.narration
    if isinstance(narration_data, list):
        narration_data = json.dumps([item.model_dump(by_alias=True) for item in narration_data], ensure_ascii=False)
        
    shot = Shot(
        title=shot_data.title,
        shot_number=shot_number,
        description=shot_data.description,
        narration=narration_data,
        image_prompt=shot_data.image_prompt,
        scene_id=shot_data.scene_id
    )
    
    db.add(shot)
    db.flush()  # 获取shot_id
    
    # 关联角色
    if shot_data.associated_characters:
        characters = db.query(Character).filter(
            Character.character_id.in_(shot_data.associated_characters)
        ).all()
        shot.characters = characters
    
    db.commit()
    db.refresh(shot)
    
    # 重新加载关系
    shot = db.query(Shot).options(
        selectinload(Shot.characters)
    ).filter(Shot.shot_id == shot.shot_id).first()
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="分镜创建成功"
    )


@router.get("/{shot_uuid}")
async def get_shot(
    shot_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    根据UUID获取分镜详情
    
    Args:
        shot_uuid: 分镜UUID
        
    Returns:
        分镜详情
    """
    # 获取分镜，预加载关系
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    更新分镜信息
    
    Args:
        shot_uuid: 分镜UUID
        shot_update: 更新数据
        
    Returns:
        更新后的分镜信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该分镜")
    
    # 更新字段
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
    
    # 更新关联场景
    if shot_update.scene_id is not None:
        # 验证场景是否存在且属于同一创作
        new_scene = db.query(Scene).filter(Scene.scene_id == shot_update.scene_id).first()
        if not new_scene:
            raise HTTPException(status_code=404, detail="目标场景不存在")
        if new_scene.creation_id != shot.scene.creation_id:
            raise HTTPException(status_code=400, detail="目标场景不属于当前创作")
        shot.scene_id = shot_update.scene_id

    # 关联角色
    if shot_update.associated_characters is not None:
        characters = db.query(Character).filter(
            Character.character_id.in_(shot_update.associated_characters)
        ).all()
        shot.characters = characters
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="分镜更新成功"
    )


@router.put("/{shot_uuid}/characters")
async def update_shot_characters(
    shot_uuid: str,
    payload: ShotCharactersUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    仅更新分镜关联的角色（用于前端弹窗编辑）
    """
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该分镜")
    
    characters = db.query(Character).filter(
        Character.character_id.in_(payload.associated_characters)
    ).all() if payload.associated_characters else []
    shot.characters = characters
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    return success_response(
        data=shot_response.model_dump(),
        message="分镜角色更新成功"
    )

@router.put("/{shot_uuid}/narration")
async def update_shot_narration(
    shot_uuid: str,
    payload: ShotNarrationUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    更新分镜旁白
    """
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该分镜")
    
    # 序列化对象数组为 JSON 字符串
    shot.narration = json.dumps([item.model_dump(by_alias=True) for item in payload.narration], ensure_ascii=False)
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    return success_response(
        data=shot_response.model_dump(),
        message="分镜旁白更新成功"
    )

@router.post("/{shot_uuid}/generate-image")
async def generate_shot_image(
    shot_uuid: str,
    request: ShotRegenerateRequest = ShotRegenerateRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    生成分镜图片
    
    启动一个 Celery 任务异步生成分镜图片。
    前端可以通过返回的 task_id 轮询查询任务状态。
    
    Args:
        shot_uuid: 分镜UUID
        
    Returns:
        {
            "task_id": "xxx",
            "shot_uuid": "xxx",
            "creation_uuid": "xxx"
        }
        
    任务状态查询：
        GET /api/v1/tasks/{task_id}
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation),
        selectinload(Shot.characters)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # 如果提供了新的提示词，则更新
    if request.image_prompt:
        shot.image_prompt = request.image_prompt
        db.commit()
        db.refresh(shot)
    
    # 检查是否有图片提示词
    if not shot.image_prompt:
        raise HTTPException(status_code=400, detail="分镜没有图片提示词，无法生成图片")
    
    creation_id = shot.scene.creation.creation_id
    
    # 计算需要的积分（提交任务时立即冻结，防止多设备并发超额使用）
    # 优先使用 request.model_name，其次 creation.extra_data 中的 image_to_image_model（没有则回退 text_to_image_model，再回退 settings）
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
    # 计算参考图数量（有图的角色）
    reference_image_count = 0
    if shot.characters:
        reference_image_count = sum(1 for c in shot.characters if getattr(c, "image_url", None))
    
    # 从模型配置获取分辨率，默认为 2K
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
    required_points = int(math.ceil(cost * 100))  # 每1元=100积分，向上取整
    # 确保至少1积分
    if required_points <= 0:
        required_points = 1
    
    # 冻结积分（提交任务时立即冻结）
    try:
        freeze_record = PointsService.freeze_points(
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
    
    # 启动 Celery 任务（传递 freeze_record_id）
    task = generate_single_shot_image_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id,
        model_name=request.model_name,
        custom_prompt=request.image_prompt,
        freeze_record_id=freeze_record.record_id  # 传递冻结记录ID
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    重新生成分镜图片

    该接口会：
    1. 更新提示词（如果提供了新的 image_prompt）
    2. 清空现有的 image_url
    3. 检查并冻结积分
    4. 启动 Celery 任务生成新图片
    5. 返回 task_id 供前端轮询查询状态

    Args:
        shot_uuid: 分镜UUID
        request: 重新生成请求
            - image_prompt: 新的图片提示词（可选，不传则使用现有提示词）

    Returns:
        {
            "task_id": "xxx",
            "shot_uuid": "xxx",
            "creation_uuid": "xxx",
            "image_prompt": "更新后的提示词",
            "freeze_record_id": xxx
        }

    任务状态查询：
        GET /api/v1/tasks/{task_id}
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation),
        selectinload(Shot.characters)
    ).filter(Shot.uuid == shot_uuid).first()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    # 是否强制重新生成提示词：如果请求中没有提供新的提示词，且数据库中也没有提示词，则标记为重新生成
    frame_type = request.frame_type or "both"
    force_regen_prompt = request.refresh_prompt
    
    if request.image_prompt is not None:
        # 只有在生成首帧时才更新首帧提示词
        if frame_type in ("start", "both"):
            shot.image_prompt = request.image_prompt
            logger.info(f"分镜 {shot_uuid} [{frame_type}] 更新首帧提示词")
        force_regen_prompt = False  # 提供了新提示词，不需要重新生成
    elif frame_type in ("start", "both") and not shot.image_prompt:
        # 只有在生成首帧时，且首帧提示词不存在，才标记为需要重新生成
        force_regen_prompt = True
    elif frame_type == "end" and not (shot.extra_data or {}).get("end_frame_image_prompt"):
        # 只生成尾帧时，如果尾帧提示词不存在，才标记为需要重新生成
        force_regen_prompt = True
    elif request.refresh_prompt:
        # 如果明确要求刷新提示词，根据 frame_type 决定清空哪些提示词
        if frame_type in ("start", "both"):
            shot.image_prompt = None
            logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空首帧提示词以便重新生成")
        if frame_type in ("end", "both"):
            # 清空尾帧提示词
            if shot.extra_data and "end_frame_image_prompt" in shot.extra_data:
                shot.extra_data["end_frame_image_prompt"] = None
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(shot, "extra_data")
                logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空尾帧提示词以便重新生成")
        force_regen_prompt = True

    # 检查是否有分镜描述（如果提示词需要重新生成，必须有描述）
    if force_regen_prompt and not shot.description:
        raise HTTPException(status_code=400, detail="分镜没有描述且没有现有提示词，无法生成提示词")

    # 检查是否有足够的提示词来生成图片
    # - frame_type="start" 或 "both"：需要首帧提示词（或重新生成）
    # - frame_type="end"：需要尾帧提示词（或重新生成）
    if not force_regen_prompt:
        if frame_type in ("start", "both") and not shot.image_prompt:
            raise HTTPException(status_code=400, detail="分镜没有首帧提示词，无法生成首帧图片")
        if frame_type in ("end", "both") and not (shot.extra_data or {}).get("end_frame_image_prompt"):
            raise HTTPException(status_code=400, detail="分镜没有尾帧提示词，无法生成尾帧图片")

    # 根据 frame_type 决定清空哪些 URL
    # - "start" 或 "both"：清空首帧 image_url
    # - "end"：只清空尾帧 URL（在 extra_data 中），保留首帧 image_url
    if frame_type in ("start", "both"):
        # 清空首帧 image_url
        shot.image_url = None
        logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空首帧 image_url")
    
    if frame_type in ("end", "both"):
        # 清空尾帧 URL（如果存在）
        if shot.extra_data and "end_frame_image_url" in shot.extra_data:
            shot.extra_data["end_frame_image_url"] = None
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(shot, "extra_data")
            logger.info(f"分镜 {shot_uuid} [{frame_type}] 清空尾帧 end_frame_image_url")

    # 保存更新
    db.commit()
    db.refresh(shot)

    creation_id = shot.scene.creation.creation_id

    # 计算需要的积分（提交任务时立即冻结，防止多设备并发超额使用）
    # 优先使用 creation.extra_data 中的 image_to_image_model（没有则回退 text_to_image_model，再回退 settings）
    extra_data = shot.scene.creation.extra_data or {}
    image_model = (
        extra_data.get("image_to_image_model")
        or extra_data.get("text_to_image_model")
        or settings.IMAGE_MODEL_IMAGE_TO_IMAGE
        or settings.IMAGE_MODEL_TEXT_TO_IMAGE
        or settings.IMAGE_MODEL_NAME
        or "black-forest-labs/flux-kontext-pro/multi"
    )
    # 计算参考图数量（有图的角色）
    reference_image_count = 0
    if shot.characters:
        reference_image_count = sum(1 for c in shot.characters if getattr(c, "image_url", None))

    # 从模型配置获取分辨率，默认为 2K
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
    required_points = int(math.ceil(cost * 100))  # 每1元=100积分，向上取整
    # 确保至少1积分
    if required_points <= 0:
        required_points = 1

    # 冻结积分（提交任务时立即冻结）
    try:
        freeze_record = PointsService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=required_points,
            operation_type="generate_shot",
            creation_id=creation_id,
            novel_id=shot.scene.creation.novel_id,
            description=f"重新生成分镜图片（{shot.title}）",
            extra_data={
                "shot_id": shot.shot_id,
                "shot_uuid": shot_uuid,
                "task_type": "shot_image_regeneration"
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 启动 Celery 任务（传递 freeze_record_id）
    logger.info(f"Generate shot image request: shot_uuid={shot_uuid}, frame_type={request.frame_type}, model={request.model_name}")
    task = generate_single_shot_image_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id,
        force_regen_prompt=force_regen_prompt,
        model_name=request.model_name,
        freeze_record_id=freeze_record.record_id,  # 传递冻结记录ID
        frame_type=request.frame_type  # 生成帧类型
    )

    logger.info(f"分镜 {shot_uuid} 重新生成任务已启动: task_id={task.id}, image_prompt已更新={request.image_prompt is not None}, freeze_record_id={freeze_record.record_id}")

    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "creation_uuid": shot.scene.creation.uuid,
            "image_prompt": shot.image_prompt,
            "freeze_record_id": freeze_record.record_id
        },
        message="分镜图片重新生成任务已启动"
    )


@router.post("/{shot_uuid}/regenerate-video")
async def regenerate_shot_video(
    shot_uuid: str,
    request: ShotRegenerateVideoRequest = ShotRegenerateVideoRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    重新生成分镜视频
    
    Args:
        shot_uuid: 分镜UUID
        
    Returns:
        任务ID
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
        
    # 启动异步任务
    task = generate_single_shot_video_task.delay(
        shot_id=shot.shot_id,
        creation_id=shot.scene.creation_id,
        model_name=request.model_name,
        last_frame_image_url=request.last_frame_image_url
    )
    
    return success_response(
        data={"task_id": str(task.id)},
        message="分镜视频重新生成任务已提交"
    )


@router.post("/{shot_uuid}/generate-audio")
async def generate_shot_audio(
    shot_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    生成分镜音频
    
    Args:
        shot_uuid: 分镜UUID
        
    Returns:
        任务启动信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # TODO: 实现音频生成逻辑（调用TTS服务）
    # 这里可以启动一个Celery任务来异步生成音频
    
    return success_response(
        data={"shot_uuid": shot_uuid, "status": "pending"},
        message="分镜音频生成任务已启动"
    )


@router.delete("/{shot_uuid}")
async def delete_shot(
    shot_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    删除分镜
    
    Args:
        shot_uuid: 分镜UUID
        
    Returns:
        删除结果
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限删除该分镜")
    
    db.delete(shot)
    db.commit()
    
    return success_response(
        data={"shot_uuid": shot_uuid},
        message="分镜删除成功"
    )


@router.post("/{shot_uuid}/characters")
async def add_shot_characters(
    shot_uuid: str,
    character_ids: List[int],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    为分镜添加关联角色
    
    Args:
        shot_uuid: 分镜UUID
        character_ids: 角色ID列表
        
    Returns:
        更新后的分镜信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # 获取要添加的角色
    characters = db.query(Character).filter(
        Character.character_id.in_(character_ids)
    ).all()
    
    # 添加角色（不重复添加）
    existing_ids = {c.character_id for c in shot.characters}
    for char in characters:
        if char.character_id not in existing_ids:
            shot.characters.append(char)
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="角色关联成功"
    )


@router.delete("/{shot_uuid}/characters/{character_uuid}")
async def remove_shot_character(
    shot_uuid: str,
    character_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    移除分镜关联的角色
    
    Args:
        shot_uuid: 分镜UUID
        character_uuid: 角色UUID
        
    Returns:
        更新后的分镜信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    # 获取角色
    character = db.query(Character).filter(Character.uuid == character_uuid).first()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # 移除角色
    shot.characters = [c for c in shot.characters if c.character_id != character.character_id]
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(),
        message="角色移除成功"
    )


@router.post("/{shot_uuid}/generate-video-prompt")
async def generate_video_prompt(
    shot_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    为分镜生成视频提示词

    Args:
        shot_uuid: 分镜UUID

    Returns:
        任务ID和信息
    """
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    # 权限检查
    creation = shot.scene.creation
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    # 计算积分（LLM调用，较小成本）
    required_points = 10  # 视频提示词生成固定10积分

    # 冻结积分
    try:
        freeze_record = PointsService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=required_points,
            operation_type="generate_video_prompt",
            creation_id=creation.creation_id,
            novel_id=creation.novel_id,
            description=f"生成视频提示词（{shot.title}）",
            extra_data={
                "shot_id": shot.shot_id,
                "shot_uuid": shot_uuid
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 启动任务
    from app.tasks.step7_video_prompt_gen_task import generate_video_prompt_task
    task = generate_video_prompt_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation.creation_id,
        freeze_record_id=freeze_record.record_id
    )

    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid
        },
        message="视频提示词生成任务已启动"
    )


@router.post("/{shot_uuid}/generate-video")
async def generate_shot_video(
    shot_uuid: str,
    request: ShotGenerateVideoRequest = ShotGenerateVideoRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    首次生成分镜视频（区别于regenerate-video）
    流程：
    1. 检查是否有video_prompt，没有则先生成
    2. 生成视频

    Args:
        shot_uuid: 分镜UUID

    Returns:
        任务ID和视频信息
    """
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation),
        selectinload(Shot.characters)
    ).filter(Shot.uuid == shot_uuid).first()

    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")

    creation = shot.scene.creation
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")

    # 检查是否有图片
    if not shot.image_url:
        raise HTTPException(status_code=400, detail="分镜必须先生成图片才能生成视频")

    # 注意：video_prompt 将在视频生成任务中自动生成，无需在此等待

    # 获取视频生成模型
    video_model = request.model_name or (creation.extra_data or {}).get('video_model', 'doubao-seedance-1-5-pro-251215')

    # 计算视频生成积分
    shot_duration = shot.video_duration if shot.video_duration else 5
    
    # 根据模型确定生成时长
    if video_model == "doubao-seedance-1-5-pro-251215":
        video_duration = 5
    elif video_model == "Wan-AI/Wan2.6-I2V":
        if shot_duration <= 5: video_duration = 5
        elif shot_duration <= 10: video_duration = 10
        else: video_duration = 15
    elif video_model in ["viduq2-pro", "viduq2-turbo"]:
        video_duration = min(max(int(shot_duration), 1), 10)
    else:
        if shot_duration <= 4: video_duration = 4
        elif shot_duration <= 8: video_duration = 8
        else: video_duration = 12

    # 从ModelPrices获取视频成本
    cost = ModelPrices.calculate_video_cost(video_model, video_duration)
    required_points = int(math.ceil(cost * 100))

    # 冻结积分
    try:
        freeze_record = PointsService.freeze_points(
            db=db,
            user_id=user.user_id,
            points=required_points,
            operation_type="generate_video",
            creation_id=creation.creation_id,
            novel_id=creation.novel_id,
            description=f"生成分镜视频（{shot.title}，{video_duration}秒，{video_model}）",
            extra_data={
                "shot_id": shot.shot_id,
                "shot_uuid": shot_uuid,
                "video_duration": video_duration,
                "video_model": video_model
            }
        )
    except InsufficientPointsError as e:
        raise HTTPException(status_code=402, detail=str(e))

    # 立即设置视频生成状态（在启动任务前）
    from datetime import datetime, timezone
    if not shot.status_detail:
        shot.status_detail = {}
    shot.status_detail['video_status'] = 'generating'
    shot.status_detail['video_updated_at'] = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(shot)

    # 启动视频生成任务
    task = generate_single_shot_video_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation.creation_id,
        freeze_record_id=freeze_record.record_id,
        model_name=video_model,
        last_frame_image_url=request.last_frame_image_url
    )

    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "video_duration": video_duration,
            "required_points": required_points,
            "video_model": video_model
        },
        message="视频生成任务已启动"
    )


@router.get("/{shot_uuid}/image-history")
async def get_shot_image_history(
    shot_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取分镜图片生成历史
    
    Args:
        shot_uuid: 分镜UUID
        
    Returns:
        图片生成历史列表
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该分镜")
    
    # 获取图片历史
    image_history = []
    if shot.extra_data and "image_history" in shot.extra_data:
        image_history = shot.extra_data["image_history"]
    
    # 标记当前使用的版本
    current_image_url = shot.image_url
    current_end_frame_url = None
    if shot.extra_data:
        current_end_frame_url = shot.extra_data.get("end_frame_image_url")
    
    for item in image_history:
        # 检查是否为当前使用的版本
        if item.get("image_url") == current_image_url and \
           item.get("end_frame_image_url") == current_end_frame_url:
            item["is_current"] = True
        else:
            item["is_current"] = False
    
    return success_response(
        data={"image_history": image_history},
        message="获取分镜图片历史成功"
    )


class ApplyImageVersionRequest(BaseModel):
    version_id: str
    image_url: str
    end_frame_image_url: Optional[str] = None
    image_prompt: Optional[str] = None


@router.post("/{shot_uuid}/apply-image-version")
async def apply_shot_image_version(
    shot_uuid: str,
    request: ApplyImageVersionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    应用分镜历史图片版本为最终效果
    
    Args:
        shot_uuid: 分镜UUID
        request: 应用版本请求
            - version_id: 版本ID
            - image_url: 图片URL
            - end_frame_image_url: 尾帧图片URL（可选）
            - image_prompt: 图片提示词（可选）
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.uuid == shot_uuid).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # 更新分镜信息
    shot.image_url = request.image_url
    if request.image_prompt:
        shot.image_prompt = request.image_prompt
    
    # 更新尾帧信息
    if not shot.extra_data:
        shot.extra_data = {}
    
    if request.end_frame_image_url:
        shot.extra_data["end_frame_image_url"] = request.end_frame_image_url
    else:
        # 如果没有尾帧URL，从extra_data中删除
        if "end_frame_image_url" in shot.extra_data:
            del shot.extra_data["end_frame_image_url"]
    
    # 标记字段为已修改
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(shot, "extra_data")
    
    db.commit()
    db.refresh(shot)
    
    return success_response(
        data={"shot_uuid": shot_uuid, "image_url": shot.image_url},
        message="应用分镜图片版本成功"
    )
