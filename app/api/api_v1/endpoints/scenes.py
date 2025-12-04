from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload
from typing import List

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.scene import Scene
from app.models.creation import Creation
from app.schemas.scene import (
    SceneCreate, 
    SceneUpdate, 
    SceneResponse,
    SceneListResponse,
    SceneWithShotsResponse
)
from app.utils.response import success_response

router = APIRouter()


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
            "items": [scene.model_dump(by_alias=True) for scene in scene_responses],
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
        data=scene_response.model_dump(by_alias=True),
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
        data=scene_response.model_dump(by_alias=True),
        message="获取场景成功"
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
    
    db.commit()
    db.refresh(scene)
    
    scene_response = SceneResponse.from_db_model(scene)
    
    return success_response(
        data=scene_response.model_dump(by_alias=True),
        message="场景更新成功"
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
