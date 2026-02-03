"""
资源重新生成工具 - Regenerate Tools

提供原子化的资源清空、生成、重新生成工具
支持: character, scene, shot_start, shot_end, shot_video
"""

from typing import Dict, Any, Optional, Literal
from datetime import datetime

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger


# ==================== 类型定义 ====================

TargetType = Literal["character", "scene", "shot_start", "shot_end", "shot_video"]
GenerationMode = Literal["txt2img", "img2img", "auto"]


# ==================== 原子工具 ====================

@tool
async def clear_asset(
    target_type: str,
    target_id: int,
    save_version: bool = True,
) -> Dict[str, Any]:
    """
    清空单个资源的图片/视频（原子操作）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video)
        target_id: 资源 ID
        save_version: 是否保存历史版本到 status_details
        
    Returns:
        操作结果
    """
    logger.info(f"[Regenerate Tool] 清空资源: type={target_type}, id={target_id}, save_version={save_version}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            # 根据类型获取资源
            if target_type == "character":
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"角色不存在: {target_id}"}
                
                # 保存版本
                if save_version and resource.image_url:
                    await _save_version(resource, "image_url", resource.image_url)
                
                # 清空图片
                resource.image_url = None
                
            elif target_type == "scene":
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"场景不存在: {target_id}"}
                
                if save_version and resource.image_url:
                    await _save_version(resource, "image_url", resource.image_url)
                
                resource.image_url = None
                
            elif target_type in ["shot_start", "shot_end", "shot_video"]:
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                if target_type == "shot_start":
                    if save_version and resource.image_url:
                        await _save_version(resource, "image_url", resource.image_url)
                    resource.image_url = None
                    
                elif target_type == "shot_end":
                    extra_data = resource.extra_data or {}
                    end_frame_url = extra_data.get("end_frame_url")
                    if save_version and end_frame_url:
                        await _save_version(resource, "end_frame_url", end_frame_url)
                    extra_data["end_frame_url"] = None
                    resource.extra_data = extra_data
                    
                elif target_type == "shot_video":
                    if save_version and resource.video_url:
                        await _save_version(resource, "video_url", resource.video_url)
                    resource.video_url = None
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            await db.commit()
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "version_saved": save_version,
            }
            
        except Exception as e:
            logger.error(f"[Regenerate Tool] 清空资源失败: {e}")
            return {"success": False, "error": str(e)}


@tool
async def submit_generation(
    target_type: str,
    target_id: int,
    creation_uuid: str,
    mode: str = "auto",
    reference_image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    提交生成任务（原子操作）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video)
        target_id: 资源 ID
        creation_uuid: 创作项目 UUID
        mode: 生成模式 (txt2img | img2img | auto)
        reference_image_url: 参考图片 URL（img2img 模式需要）
        
    Returns:
        任务提交结果
    """
    logger.info(f"[Regenerate Tool] 提交生成任务: type={target_type}, id={target_id}, mode={mode}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    try:
        async with get_async_session() as db:
            # 获取资源信息以构建生成参数
            if target_type == "character":
                stmt = select(Character).where(Character.character_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"角色不存在: {target_id}"}
                
                prompt = resource.image_prompt or ""
                
                # 调用 Celery 任务
                from app.agent.tasks.image_tasks import generate_character_image_task
                task = generate_character_image_task.delay(
                    creation_uuid=creation_uuid,
                    character_id=target_id,
                    prompt=prompt,
                )
                
            elif target_type == "scene":
                stmt = select(Scene).where(Scene.scene_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"场景不存在: {target_id}"}
                
                prompt = resource.image_prompt or ""
                
                from app.agent.tasks.image_tasks import generate_scene_image_task
                task = generate_scene_image_task.delay(
                    creation_uuid=creation_uuid,
                    scene_id=target_id,
                    prompt=prompt,
                )
                
            elif target_type == "shot_start":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                from app.agent.tasks.image_tasks import generate_shot_image_task
                task = generate_shot_image_task.delay(
                    creation_uuid=creation_uuid,
                    shot_id=target_id,
                    frame_type="start",
                )
                
            elif target_type == "shot_end":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                from app.agent.tasks.image_tasks import generate_shot_image_task
                task = generate_shot_image_task.delay(
                    creation_uuid=creation_uuid,
                    shot_id=target_id,
                    frame_type="end",
                )
                
            elif target_type == "shot_video":
                stmt = select(Shot).where(Shot.shot_id == target_id)
                result = await db.execute(stmt)
                resource = result.scalar_one_or_none()
                if not resource:
                    return {"success": False, "error": f"分镜不存在: {target_id}"}
                
                from app.agent.tasks.video_tasks import generate_shot_video_task
                task = generate_shot_video_task.delay(
                    creation_uuid=creation_uuid,
                    shot_id=target_id,
                )
            else:
                return {"success": False, "error": f"不支持的资源类型: {target_type}"}
            
            return {
                "success": True,
                "target_type": target_type,
                "target_id": target_id,
                "task_id": task.id,
                "mode": mode,
            }
            
    except Exception as e:
        logger.error(f"[Regenerate Tool] 提交生成任务失败: {e}")
        return {"success": False, "error": str(e)}


@tool
async def regenerate(
    target_type: str,
    target_id: int,
    creation_uuid: str,
    save_version: bool = True,
    mode: str = "auto",
) -> Dict[str, Any]:
    """
    重新生成资源（组合操作：清空 + 提交生成）
    
    Args:
        target_type: 资源类型 (character | scene | shot_start | shot_end | shot_video)
        target_id: 资源 ID
        creation_uuid: 创作项目 UUID
        save_version: 是否保存历史版本
        mode: 生成模式 (txt2img | img2img | auto)
        
    Returns:
        操作结果
    """
    logger.info(f"[Regenerate Tool] 重新生成: type={target_type}, id={target_id}")
    
    # Step 1: 清空资源（保存版本）
    clear_result = await clear_asset.ainvoke({
        "target_type": target_type,
        "target_id": target_id,
        "save_version": save_version,
    })
    
    if not clear_result.get("success"):
        return clear_result
    
    # Step 2: 提交生成任务
    submit_result = await submit_generation.ainvoke({
        "target_type": target_type,
        "target_id": target_id,
        "creation_uuid": creation_uuid,
        "mode": mode,
    })
    
    if not submit_result.get("success"):
        return submit_result
    
    return {
        "success": True,
        "target_type": target_type,
        "target_id": target_id,
        "task_id": submit_result.get("task_id"),
        "version_saved": save_version,
        "mode": mode,
    }


@tool
async def clear_all(
    creation_uuid: str,
    target_type: str,
    save_version: bool = True,
) -> Dict[str, Any]:
    """
    批量清空指定类型的所有资源
    
    Args:
        creation_uuid: 创作项目 UUID
        target_type: 资源类型 (characters | scenes | shots | shot_images | shot_videos)
        save_version: 是否保存历史版本
        
    Returns:
        操作结果
    """
    logger.info(f"[Regenerate Tool] 批量清空: type={target_type}")
    
    from app.agent.tools.async_db import get_async_session
    from app.models.creation import Creation
    from app.models.character import Character
    from app.models.scene import Scene
    from app.models.shot import Shot
    from sqlalchemy import select
    
    async with get_async_session() as db:
        try:
            # 获取 creation
            creation_stmt = select(Creation).where(Creation.uuid == creation_uuid)
            creation_result = await db.execute(creation_stmt)
            creation = creation_result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": "创作项目不存在"}
            
            cleared_count = 0
            
            if target_type == "characters":
                stmt = select(Character).where(Character.creation_id == creation.creation_id)
                result = await db.execute(stmt)
                characters = result.scalars().all()
                
                for char in characters:
                    if char.image_url:
                        if save_version:
                            await _save_version(char, "image_url", char.image_url)
                        char.image_url = None
                        cleared_count += 1
                        
            elif target_type == "scenes":
                stmt = select(Scene).where(Scene.creation_id == creation.creation_id)
                result = await db.execute(stmt)
                scenes = result.scalars().all()
                
                for scene in scenes:
                    if scene.image_url:
                        if save_version:
                            await _save_version(scene, "image_url", scene.image_url)
                        scene.image_url = None
                        cleared_count += 1
                        
            elif target_type in ["shots", "shot_images", "shot_videos"]:
                # 获取场景 ID
                scene_stmt = select(Scene.scene_id).where(Scene.creation_id == creation.creation_id)
                scene_result = await db.execute(scene_stmt)
                scene_ids = [s[0] for s in scene_result.fetchall()]
                
                if scene_ids:
                    shot_stmt = select(Shot).where(Shot.scene_id.in_(scene_ids))
                    shot_result = await db.execute(shot_stmt)
                    shots = shot_result.scalars().all()
                    
                    for shot in shots:
                        if target_type in ["shots", "shot_images"]:
                            if shot.image_url:
                                if save_version:
                                    await _save_version(shot, "image_url", shot.image_url)
                                shot.image_url = None
                                cleared_count += 1
                            
                            # 清空尾帧
                            extra_data = shot.extra_data or {}
                            if extra_data.get("end_frame_url"):
                                if save_version:
                                    await _save_version(shot, "end_frame_url", extra_data["end_frame_url"])
                                extra_data["end_frame_url"] = None
                                shot.extra_data = extra_data
                                
                        if target_type in ["shots", "shot_videos"]:
                            if shot.video_url:
                                if save_version:
                                    await _save_version(shot, "video_url", shot.video_url)
                                shot.video_url = None
                                cleared_count += 1
            else:
                return {"success": False, "error": f"不支持的批量类型: {target_type}"}
            
            await db.commit()
            
            return {
                "success": True,
                "target_type": target_type,
                "cleared_count": cleared_count,
                "version_saved": save_version,
            }
            
        except Exception as e:
            logger.error(f"[Regenerate Tool] 批量清空失败: {e}")
            return {"success": False, "error": str(e)}


# ==================== 辅助函数 ====================

async def _save_version(resource: Any, field_name: str, value: Any) -> None:
    """
    保存资源版本到 status_details
    
    Args:
        resource: 资源对象（Character/Scene/Shot）
        field_name: 字段名
        value: 当前值
    """
    status_details = resource.status_details or {}
    versions = status_details.get("versions", [])
    
    # 创建版本记录
    version_record = {
        "version": len(versions) + 1,
        "created_at": datetime.now().isoformat(),
        "field": field_name,
        "value": value,
        "trigger": "regenerate",
    }
    
    versions.append(version_record)
    status_details["versions"] = versions
    resource.status_details = status_details
    
    logger.info(f"[Version] 保存版本: {field_name}={value[:50] if isinstance(value, str) else value}...")


# ==================== 导出 ====================

REGENERATE_TOOLS = [
    clear_asset,
    submit_generation,
    regenerate,
    clear_all,
]
