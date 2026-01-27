from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional
from pydantic import BaseModel

from app.api.deps import get_db, get_current_user
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取小说的所有场景列表（用于场景复用）

    该接口返回指定小说下所有未删除的场景，用于在创作时选择复用已有场景。

    Args:
        novel_id: 小说ID

    Returns:
        场景列表
        {
            "items": [
                {
                    "sceneId": 1,
                    "title": "场景1",
                    "timeSettings": "白天",
                    "location": "书房",
                    "spaceType": "室内",
                    "atmosphere": "安静"
                },
                ...
            ],
            "total": 10
        }
    """
    # 查询该小说的所有场景（未删除）
    scenes = db.query(Scene).filter(
        Scene.novel_id == novel_id,
        Scene.deleted_at.is_(None)
    ).order_by(Scene.scene_id.desc()).all()

    # 验证权限：检查用户是否有权访问这些场景
    # 通过检查场景关联的创作项目的所有者
    if scenes:
        # 获取第一个场景关联的创作，检查权限
        first_scene_creation = db.query(Creation).filter(
            Creation.creation_id == scenes[0].creation_id
        ).first()

        if first_scene_creation and first_scene_creation.owner_id != user.user_id:
            raise HTTPException(status_code=403, detail="无权限访问该小说的场景")

    # 转换为响应格式
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取创作项目的场景列表
    
    Args:
        creation_uuid: 创作项目UUID
        
    Returns:
        场景列表
    """
    # 验证创作项目是否存在
    creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    # 验证权限
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    # 获取场景列表，预加载shots关系
    scenes = db.query(Scene).options(
        selectinload(Scene.shots)
    ).filter(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id).all()
    
    # 转换为响应格式
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    获取创作项目的场景列表（包含完整分镜详情）
    
    该接口返回的分镜信息包含 image_url、image_prompt 等详细信息，
    适用于前端需要显示分镜图片和生成状态的场景。
    
    Args:
        creation_uuid: 创作项目UUID
        
    Returns:
        场景列表，每个场景包含完整的分镜详情
        {
            "items": [
                {
                    "sceneId": 1,
                    "title": "场景1",
                    "duration": "00:00:30",
                    "sceneSetting": {...},
                    "shots": [
                        {
                            "shotId": 1,
                            "title": "分镜1",
                            "shotNumber": 1,
                            "imageUrl": "https://...",
                            "imagePrompt": "...",
                            "narration": "..."
                        },
                        ...
                    ]
                },
                ...
            ],
            "total": 5
        }
    """
    # 验证创作项目是否存在
    creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    # 验证权限
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    # 获取场景列表，预加载shots关系
    scenes = db.query(Scene).options(
        selectinload(Scene.shots)
    ).filter(Scene.creation_id == creation.creation_id).order_by(Scene.scene_id).all()
    
    # 转换为包含完整分镜详情的响应格式
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    创建新场景
    
    Args:
        scene_data: 场景创建数据
        
    Returns:
        创建的场景信息
    """
    # 验证创作项目是否存在
    creation = db.query(Creation).filter(Creation.creation_id == scene_data.creation_id).first()
    if not creation:
        raise HTTPException(status_code=404, detail="创作项目不存在")
    
    # 验证权限
    if creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该创作项目")
    
    # 解析场景设置
    scene_setting = scene_data.scene_setting
    
    # 创建场景
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
    db.commit()
    db.refresh(scene)
    
    # 重新加载关系
    scene = db.query(Scene).options(
        selectinload(Scene.shots)
    ).filter(Scene.scene_id == scene.scene_id).first()
    
    scene_response = SceneResponse.from_db_model(scene)
    
    return success_response(
        data=scene_response.model_dump(),
        message="场景创建成功"
    )


@router.get("/{scene_uuid}")
async def get_scene(
    scene_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    根据UUID获取场景详情
    
    Args:
        scene_uuid: 场景UUID
        
    Returns:
        场景详情
    """
    # 获取场景，预加载关系
    scene = db.query(Scene).options(
        selectinload(Scene.shots),
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证权限
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    根据UUID获取场景详情（包含完整分镜详情）
    """
    scene = db.query(Scene).options(
        selectinload(Scene.shots),
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    return success_response(
        data=SceneWithShotsResponse.from_db_model(scene).model_dump(),
        message="获取场景详情成功"
    )


@router.put("/{scene_uuid}")
async def update_scene(
    scene_uuid: str,
    scene_update: SceneUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    更新场景信息
    
    Args:
        scene_uuid: 场景UUID
        scene_update: 更新数据
        
    Returns:
        更新后的场景信息
    """
    # 获取场景
    scene = db.query(Scene).options(
        selectinload(Scene.shots),
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证权限
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限修改该场景")
    
    # 更新字段
    if scene_update.title is not None:
        scene.title = scene_update.title
    if scene_update.duration is not None:
        scene.duration = scene_update.duration
    
    # 更新场景设置
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
        # 仅保存到 extra_data 中
        if scene.extra_data is None:
            scene.extra_data = {}
        scene.extra_data["image_prompt"] = scene_update.image_prompt
        flag_modified(scene, "extra_data")
    
    db.commit()
    db.refresh(scene)
    
    scene_response = SceneResponse.from_db_model(scene)
    
    return success_response(
        data=scene_response.model_dump(),
        message="场景更新成功"
    )


@router.post("/{scene_uuid}/regenerate-image")
async def regenerate_scene_image(
    scene_uuid: str,
    request: SceneRegenerateRequest = SceneRegenerateRequest(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    重新生成场景图片
    """
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该场景")
    
    # 清空现有图片
    scene.image_url = None
    if request.image_prompt is not None:
        if scene.extra_data is None:
            scene.extra_data = {}
        # 如果传入了提示词（即使是空字符串），也更新到 extra_data
        # 空字符串在 Task 中会被视为需要重新生成
        scene.extra_data["image_prompt"] = request.image_prompt if request.image_prompt else None
        flag_modified(scene, "extra_data")
    elif request.refresh_prompt:
        if scene.extra_data and "image_prompt" in scene.extra_data:
            scene.extra_data["image_prompt"] = None
            flag_modified(scene, "extra_data")
    db.commit()
    
    # 启动任务
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    重新生成场景下所有分镜的视频
    """
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该场景")
    
    # 启动任务
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    删除场景
    
    Args:
        scene_uuid: 场景UUID
        
    Returns:
        删除结果
    """
    # 获取场景
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 验证权限
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限删除该场景")
    
    db.delete(scene)
    db.commit()
    
    return success_response(
        data={"scene_uuid": scene_uuid},
        message="场景删除成功"
    )


class ApplySceneImageVersionRequest(BaseModel):
    """应用场景历史图片版本请求"""
    version_id: str
    image_url: str
    image_prompt: Optional[str] = None


@router.get("/{scene_uuid}/image-history")
async def get_scene_image_history(
    scene_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """获取场景图片生成历史"""
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限访问该场景")
    
    image_history = scene.extra_data.get('image_history', []) if scene.extra_data else []
    
    return success_response(
        data={
            "current_image_url": scene.image_url,
            "current_image_prompt": scene.extra_data.get('image_prompt') if scene.extra_data else None,
            "image_history": image_history
        },
        message="获取场景图片历史成功"
    )


@router.post("/{scene_uuid}/apply-image-version")
async def apply_scene_image_version(
    scene_uuid: str,
    request: ApplySceneImageVersionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """将历史图片应用为场景的当前图片"""
    scene = db.query(Scene).options(
        selectinload(Scene.creation)
    ).filter(Scene.uuid == scene_uuid).first()
    
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if scene.creation.owner_id != user.user_id:
        raise HTTPException(status_code=403, detail="无权限操作该场景")
    
    image_history = scene.extra_data.get('image_history', []) if scene.extra_data else []
    
    version_found = False
    for version in image_history:
        if version.get('version_id') == request.version_id:
            version_found = True
            break
    
    if not version_found:
        raise HTTPException(status_code=404, detail="指定的版本不存在")
    
    scene.image_url = request.image_url
    if request.image_prompt:
        if scene.extra_data is None:
            scene.extra_data = {}
        scene.extra_data['image_prompt'] = request.image_prompt
        flag_modified(scene, "extra_data")
    
    for version in image_history:
        version['is_current'] = version.get('version_id') == request.version_id
    
    if scene.extra_data is None:
        scene.extra_data = {}
    scene.extra_data['image_history'] = image_history
    flag_modified(scene, "extra_data")
    
    db.commit()
    db.refresh(scene)

    return success_response(
        data={
            "scene_uuid": scene_uuid,
            "image_url": scene.image_url,
            "image_prompt": scene.extra_data.get('image_prompt') if scene.extra_data else None
        },
        message="应用历史图片成功"
    )
