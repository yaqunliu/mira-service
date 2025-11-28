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
    ShotRegenerateRequest
)
from app.utils.response import success_response
from app.tasks.shot_task import generate_single_shot_image_task
from app.core.logger import logger

router = APIRouter()


@router.get("/scene/{scene_id}")
async def get_scene_shots(
    scene_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取场景的分镜列表
    
    Args:
        scene_id: 场景ID
        
    Returns:
        分镜列表
    """
    # 获取场景并验证
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.scene_id == scene_id).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证权限
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    # 获取分镜列表，预加载characters关系
    shots = db.query(Shot).options(
        selectinload(Shot.characters)
    ).filter(Shot.scene_id == scene_id).order_by(Shot.shot_number).all()
    
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
    # 获取场景并验证
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


@router.get("/{shot_id}")
async def get_shot(
    shot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    根据ID获取分镜详情
    
    Args:
        shot_id: 分镜ID
        
    Returns:
        分镜详情
    """
    # 获取分镜，预加载关系
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
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


@router.put("/{shot_id}")
async def update_shot(
    shot_id: int,
    shot_update: ShotUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    更新分镜信息
    
    Args:
        shot_id: 分镜ID
        shot_update: 更新数据
        
    Returns:
        更新后的分镜信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
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


@router.post("/{shot_id}/generate-image")
async def generate_shot_image(
    shot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    生成分镜图片
    
    启动一个 Celery 任务异步生成分镜图片。
    前端可以通过返回的 task_id 轮询查询任务状态。
    
    Args:
        shot_id: 分镜ID
        
    Returns:
        {
            "task_id": "xxx",
            "shot_id": 123,
            "creation_id": 456
        }
        
    任务状态查询：
        GET /api/v1/tasks/{task_id}
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # 检查是否有图片提示词
    if not shot.image_prompt:
        raise HTTPException(status_code=400, detail="分镜没有图片提示词，无法生成图片")
    
    creation_id = shot.scene.creation.creation_id
    
    # 启动 Celery 任务
    task = generate_single_shot_image_task.delay(
        shot_id=shot_id,
        creation_id=creation_id
    )
    
    logger.info(f"分镜 {shot_id} 图片生成任务已启动: task_id={task.id}")
    
    return success_response(
        data={
            "task_id": task.id,
            "shot_id": shot_id,
            "creation_id": creation_id
        },
        message="分镜图片生成任务已启动"
    )


@router.post("/{shot_id}/regenerate")
async def regenerate_shot_image(
    shot_id: int,
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
        shot_id: 分镜ID
        request: 重新生成请求
            - image_prompt: 新的图片提示词（可选，不传则使用现有提示词）
        
    Returns:
        {
            "task_id": "xxx",
            "shot_id": 123,
            "creation_id": 456,
            "image_prompt": "更新后的提示词"
        }
        
    任务状态查询：
        GET /api/v1/tasks/{task_id}
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
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
        shot_id=shot_id,
        creation_id=creation_id
    )
    
    logger.info(f"分镜 {shot_id} 重新生成任务已启动: task_id={task.id}, image_prompt已更新={request.image_prompt is not None}")
    
    return success_response(
        data={
            "task_id": task.id,
            "shot_id": shot_id,
            "creation_id": creation_id,
            "image_prompt": shot.image_prompt
        },
        message="分镜图片重新生成任务已启动"
    )


@router.post("/{shot_id}/generate-audio")
async def generate_shot_audio(
    shot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    生成分镜音频
    
    Args:
        shot_id: 分镜ID
        
    Returns:
        任务启动信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # TODO: 实现音频生成逻辑（调用TTS服务）
    # 这里可以启动一个Celery任务来异步生成音频
    
    return success_response(
        data={"shot_id": shot_id, "status": "pending"},
        message="分镜音频生成任务已启动"
    )


@router.delete("/{shot_id}")
async def delete_shot(
    shot_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    删除分镜
    
    Args:
        shot_id: 分镜ID
        
    Returns:
        删除结果
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限删除该分镜")
    
    db.delete(shot)
    db.commit()
    
    return success_response(
        data={"shot_id": shot_id},
        message="分镜删除成功"
    )


@router.post("/{shot_id}/characters")
async def add_shot_characters(
    shot_id: int,
    character_ids: List[int],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    为分镜添加关联角色
    
    Args:
        shot_id: 分镜ID
        character_ids: 角色ID列表
        
    Returns:
        更新后的分镜信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
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


@router.delete("/{shot_id}/characters/{character_id}")
async def remove_shot_character(
    shot_id: int,
    character_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    移除分镜关联的角色
    
    Args:
        shot_id: 分镜ID
        character_id: 角色ID
        
    Returns:
        更新后的分镜信息
    """
    # 获取分镜
    shot = db.query(Shot).options(
        selectinload(Shot.characters),
        selectinload(Shot.scene).selectinload(Scene.creation)
    ).filter(Shot.shot_id == shot_id).first()
    
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    
    # 验证权限
    if shot.scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该分镜")
    
    # 移除角色
    shot.characters = [c for c in shot.characters if c.character_id != character_id]
    
    db.commit()
    db.refresh(shot)
    
    shot_response = ShotResponse.from_db_model(shot)
    
    return success_response(
        data=shot_response.model_dump(by_alias=True),
        message="角色移除成功"
    )
