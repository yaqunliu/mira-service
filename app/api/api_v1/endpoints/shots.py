import math
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func
from typing import List

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
)
from app.utils.response import success_response
from app.tasks.shot_task import generate_single_shot_image_task
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
            "items": [shot.model_dump(by_alias=True) for shot in shot_responses],
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
    shot = Shot(
        title=shot_data.title,
        shot_number=shot_number,
        description=shot_data.description,
        narration=shot_data.narration,
        image_prompt=shot_data.image_prompt,
        scene_id=shot_data.scene_id
    )
    
    db.add(shot)
    db.flush()  # 获取shot_id
    
    # 关联角色
    if shot_data.character_ids:
        characters = db.query(Character).filter(
            Character.character_id.in_(shot_data.character_ids)
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
        data=shot_response.model_dump(by_alias=True),
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
        data=shot_response.model_dump(by_alias=True),
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
        shot.narration = shot_update.narration
    if shot_update.image_prompt is not None:
        shot.image_prompt = shot_update.image_prompt
    if shot_update.image_url is not None:
        shot.image_url = shot_update.image_url
    
    # 更新关联角色
    if shot_update.character_ids is not None:
        characters = db.query(Character).filter(
            Character.character_id.in_(shot_update.character_ids)
        ).all()
        shot.characters = characters
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(by_alias=True),
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
        Character.character_id.in_(payload.character_ids)
    ).all() if payload.character_ids else []
    shot.characters = characters
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    return success_response(
        data=shot_response.model_dump(by_alias=True),
        message="分镜角色更新成功"
    )

@router.post("/{shot_uuid}/generate-image")
async def generate_shot_image(
    shot_uuid: str,
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
    
    # 检查是否有图片提示词
    if not shot.image_prompt:
        raise HTTPException(status_code=400, detail="分镜没有图片提示词，无法生成图片")
    
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
    3. 启动 Celery 任务生成新图片
    4. 返回 task_id 供前端轮询查询状态
    
    Args:
        shot_uuid: 分镜UUID
        request: 重新生成请求
            - image_prompt: 新的图片提示词（可选，不传则使用现有提示词）
        
    Returns:
        {
            "task_id": "xxx",
            "shot_uuid": "xxx",
            "creation_uuid": "xxx",
            "image_prompt": "更新后的提示词"
        }
        
    任务状态查询：
        GET /api/v1/tasks/{task_id}
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
    
    # 更新提示词（如果提供了新的）
    if request.image_prompt is not None:
        shot.image_prompt = request.image_prompt
    
    # 检查是否有图片提示词
    if not shot.image_prompt:
        raise HTTPException(status_code=400, detail="分镜没有图片提示词，无法生成图片")
    
    # 清空现有的 image_url
    shot.image_url = None
    
    # 保存更新
    db.commit()
    db.refresh(shot)
    
    creation_id = shot.scene.creation.creation_id
    
    # 启动 Celery 任务
    task = generate_single_shot_image_task.delay(
        shot_id=shot.shot_id,
        creation_id=creation_id
    )
    
    logger.info(f"分镜 {shot_uuid} 重新生成任务已启动: task_id={task.id}, image_prompt已更新={request.image_prompt is not None}")
    
    return success_response(
        data={
            "task_id": task.id,
            "shot_uuid": shot_uuid,
            "creation_uuid": shot.scene.creation.uuid,
            "image_prompt": shot.image_prompt
        },
        message="分镜图片重新生成任务已启动"
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
        data=shot_response.model_dump(by_alias=True),
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
        data=shot_response.model_dump(by_alias=True),
        message="角色移除成功"
    )
