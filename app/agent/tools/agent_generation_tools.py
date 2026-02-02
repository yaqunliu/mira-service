"""
Agent 生成类 Tools

封装 Agent 专用 Celery Tasks，提供给 LangGraph 节点调用
这些 Tools 负责异步任务的提交、进度轮询和结果返回
"""

import asyncio
from typing import Dict, Any, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.logger import logger


# ==================== 辅助函数 ====================

async def wait_for_task_with_progress(
    task,
    poll_interval: float = 1.0,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    """
    等待 Celery 任务完成，同时可获取进度信息
    
    Args:
        task: Celery AsyncResult 对象
        poll_interval: 轮询间隔（秒）
        timeout: 超时时间（秒）
        
    Returns:
        任务结果
    """
    elapsed = 0.0
    
    while not task.ready() and elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        
        # 获取进度（如果有）
        if task.state == 'PROGRESS':
            meta = task.info
            logger.debug(f"Task progress: {meta}")
    
    if elapsed >= timeout:
        return {
            "status": "timeout",
            "error": f"任务超时（{timeout}秒）",
            "task_id": task.id,
        }
    
    if task.successful():
        return task.result
    else:
        return {
            "status": "failed",
            "error": str(task.result) if task.result else "未知错误",
            "task_id": task.id,
        }


# ==================== 图片生成 Tools ====================

@tool
async def generate_character_image(
    creation_uuid: str,
    character_id: int,
    prompt: str,
    style: Optional[Dict[str, Any]] = None,
    model: str = "doubao",
) -> Dict[str, Any]:
    """
    生成角色图片
    
    Args:
        creation_uuid: 创作项目 UUID
        character_id: 角色 ID
        prompt: 图片生成提示词
        style: 风格参数（可选）
        model: 生成模型（默认 doubao）
        
    Returns:
        生成结果，包含 image_url
    """
    logger.info(f"[Generation Tool] 生成角色图片: character_id={character_id}")
    
    from app.agent.tasks.image_tasks import agent_generate_character_image_task
    
    # 提交异步任务
    task = agent_generate_character_image_task.delay(
        creation_uuid=creation_uuid,
        character_id=character_id,
        prompt=prompt,
        style=style or {},
        model=model,
    )
    
    # 等待并返回结果
    result = await wait_for_task_with_progress(task)
    return result


@tool
async def generate_scene_image(
    creation_uuid: str,
    scene_id: int,
    prompt: str,
    style: Optional[Dict[str, Any]] = None,
    model: str = "doubao",
) -> Dict[str, Any]:
    """
    生成场景图片
    
    Args:
        creation_uuid: 创作项目 UUID
        scene_id: 场景 ID
        prompt: 图片生成提示词
        style: 风格参数（可选）
        model: 生成模型（默认 doubao）
        
    Returns:
        生成结果，包含 image_url
    """
    logger.info(f"[Generation Tool] 生成场景图片: scene_id={scene_id}")
    
    from app.agent.tasks.image_tasks import agent_generate_scene_image_task
    
    task = agent_generate_scene_image_task.delay(
        creation_uuid=creation_uuid,
        scene_id=scene_id,
        prompt=prompt,
        style=style or {},
        model=model,
    )
    
    result = await wait_for_task_with_progress(task)
    return result



# ==================== 视频生成 Tools ====================

@tool
async def generate_video(
    creation_uuid: str,
    shot_id: int,
    start_image_url: str,
    end_image_url: Optional[str] = None,
    prompt: Optional[str] = None,
    duration: float = 5.0,
    model: str = "kling",
) -> Dict[str, Any]:
    """
    生成分镜视频
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        start_image_url: 首帧图片 URL
        end_image_url: 尾帧图片 URL（可选，用于首尾帧模式）
        prompt: 视频运动提示词（可选）
        duration: 视频时长（秒）
        model: 生成模型（默认 kling）
        
    Returns:
        生成结果，包含 video_url
    """
    logger.info(f"[Generation Tool] 生成视频: shot_id={shot_id}")
    
    from app.agent.tasks.video_tasks import agent_generate_video_task
    
    task = agent_generate_video_task.delay(
        creation_uuid=creation_uuid,
        shot_id=shot_id,
        start_image_url=start_image_url,
        end_image_url=end_image_url,
        prompt=prompt,
        duration=duration,
        model=model,
    )
    
    # 视频生成时间较长，增加超时时间
    result = await wait_for_task_with_progress(task, timeout=600.0)
    return result


# ==================== 音频生成 Tools ====================

@tool
async def generate_audio(
    creation_uuid: str,
    shot_id: int,
    text: str,
    voice_id: str,
    audio_type: str = "dialogue",
    speed: float = 1.0,
    pitch: float = 1.0,
) -> Dict[str, Any]:
    """
    生成分镜音频
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        text: 要转换的文本
        voice_id: 语音模型 ID
        audio_type: 音频类型（dialogue=对话, narration=旁白）
        speed: 语速（0.5-2.0）
        pitch: 音调（0.5-2.0）
        
    Returns:
        生成结果，包含 audio_url
    """
    logger.info(f"[Generation Tool] 生成音频: shot_id={shot_id}, type={audio_type}")
    
    from app.agent.tasks.audio_tasks import agent_generate_audio_task
    
    task = agent_generate_audio_task.delay(
        creation_uuid=creation_uuid,
        shot_id=shot_id,
        text=text,
        voice_id=voice_id,
        audio_type=audio_type,
        speed=speed,
        pitch=pitch,
    )
    
    result = await wait_for_task_with_progress(task)
    return result


# ==================== 导出 ====================

# 所有可用的生成类 Tools
GENERATION_TOOLS = [
    generate_character_image,
    generate_scene_image,
    generate_video,
    generate_audio,
]



# ==================== 批量生成和任务管理工具 ====================
# 以下代码从 app/agent/tools/db_tools.py 迁移过来

from typing import List


@tool
async def create_asset_generation_tasks(
    creation_uuid: str,
    assets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    创建资产图片生成任务（角色和场景）
    
    Args:
        creation_uuid: 创作项目 UUID
        assets: 资产列表，每个资产包含 type (character/scene), id, prompt
        
    Returns:
        创建的任务列表
    """
    logger.info(f"[create_asset_generation_tasks] 创建资产生成任务: creation_uuid={creation_uuid}, assets={len(assets)}")
    
    from app.agent.tasks.image_tasks import (
        agent_generate_character_image_task,
        agent_generate_scene_image_task,
    )
    
    try:
        task_ids = []
        
        for asset in assets:
            asset_type = asset.get("type")
            asset_id = asset.get("id")
            prompt = asset.get("prompt", "")
            
            if asset_type == "character":
                task = agent_generate_character_image_task.delay(
                    creation_uuid=creation_uuid,
                    character_id=asset_id,
                    prompt=prompt,
                )
                task_ids.append({
                    "type": "character",
                    "id": asset_id,
                    "task_id": task.id,
                    "name": asset.get("name", ""),
                })
                
            elif asset_type == "scene":
                task = agent_generate_scene_image_task.delay(
                    creation_uuid=creation_uuid,
                    scene_id=asset_id,
                    prompt=prompt,
                )
                task_ids.append({
                    "type": "scene",
                    "id": asset_id,
                    "task_id": task.id,
                    "name": asset.get("name", ""),
                })
        
        return {
            "success": True,
            "task_ids": task_ids,
            "total": len(task_ids),
            "characters_count": len([t for t in task_ids if t["type"] == "character"]),
            "scenes_count": len([t for t in task_ids if t["type"] == "scene"]),
        }
        
    except Exception as e:
        logger.error(f"[create_asset_generation_tasks] 创建任务失败: {e}")
        return {"success": False, "error": str(e), "task_ids": []}


@tool
async def generate_shot_images(
    creation_uuid: str,
    force_regenerate: bool = False
) -> Dict[str, Any]:
    """
    触发创作项目的分镜图片批量生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        force_regenerate: 是否强制重新生成已有图片的分镜
    
    Returns:
        task_id, group_id, shot_task_ids, shot_count
    """
    from app.agent.tools.async_db import get_async_db_session
    from app.models import Creation, Scene, Shot
    from sqlalchemy import select
    
    try:
        async with get_async_db_session() as session:
            stmt = select(Creation).where(Creation.uuid == creation_uuid)
            result = await session.execute(stmt)
            creation = result.scalar_one_or_none()
            
            if not creation:
                return {"success": False, "error": f"创作不存在: {creation_uuid}"}
            
            # 查询分镜数量
            shot_stmt = (
                select(Shot)
                .join(Scene, Shot.scene_id == Scene.scene_id)
                .where(Scene.creation_id == creation.creation_id)
            )
            shot_result = await session.execute(shot_stmt)
            shots = shot_result.scalars().all()
            
            shots_to_generate = [
                s for s in shots 
                if force_regenerate or not s.image_url
            ]
            
            if not shots_to_generate:
                return {
                    "success": True,
                    "task_id": None,
                    "shot_count": 0,
                    "message": "所有分镜已有图片，无需生成",
                }
            
            # 使用新迁移的 task
            from app.agent.tasks.image_tasks import agent_generate_shot_images_task
            
            task = agent_generate_shot_images_task.delay(creation_uuid=creation_uuid)
            
            logger.info(f"[generate_shot_images] 启动分镜图片生成任务: task_id={task.id}, shot_count={len(shots_to_generate)}")
            
            try:
                loop = asyncio.get_event_loop()
                task_result = await loop.run_in_executor(None, lambda: task.get(timeout=10))
                
                return {
                    "success": True,
                    "task_id": task.id,
                    "group_id": task_result.get("group_id"),
                    "shot_task_ids": task_result.get("shot_task_ids", {}),
                    "shot_count": task_result.get("total", len(shots_to_generate)),
                    "message": task_result.get("message", "已启动分镜图片生成任务"),
                }
            except Exception as wait_err:
                logger.warning(f"[generate_shot_images] 等待任务结果失败: {wait_err}")
                return {
                    "success": True,
                    "task_id": task.id,
                    "shot_count": len(shots_to_generate),
                    "message": f"已启动分镜图片生成任务",
                }
            
    except Exception as e:
        logger.error(f"[generate_shot_images] 启动任务失败: {e}")
        return {"success": False, "error": str(e)}


@tool
async def generate_shot_videos(
    creation_uuid: str,
    force_regenerate: bool = False,
) -> Dict[str, Any]:
    """
    创建视频生成任务
    
    查询所有需要生成视频的分镜（有 video_prompt 但无 video_url），
    批量派发 Celery 任务。
    
    Args:
        creation_uuid: 创作 UUID
        force_regenerate: 是否强制重新生成已有视频的分镜
        
    Returns:
        task_id, group_id, shot_task_ids, shot_count
    """
    # 使用新迁移的 task
    from app.agent.tasks.video_tasks import agent_generate_shot_videos_task
    
    logger.info(f"[generate_shot_videos] 创建视频生成任务: creation_uuid={creation_uuid}")
    
    try:
        task = agent_generate_shot_videos_task.delay(creation_uuid=creation_uuid)
        
        try:
            loop = asyncio.get_event_loop()
            task_result = await loop.run_in_executor(None, lambda: task.get(timeout=10))
            
            if task_result.get("success"):
                return {
                    "success": True,
                    "task_id": task.id,
                    "group_id": task_result.get("group_id"),
                    "shot_task_ids": task_result.get("shot_task_ids", {}),
                    "shot_count": task_result.get("total", 0),
                    "message": task_result.get("message", "已启动视频生成任务"),
                }
            else:
                return {
                    "success": False,
                    "task_id": task.id,
                    "error": task_result.get("error", "未知错误"),
                }
                
        except Exception as wait_err:
            logger.warning(f"[generate_shot_videos] 等待任务结果失败: {wait_err}")
            return {
                "success": True,
                "task_id": task.id,
                "message": "已启动视频生成任务，请稍后查询状态",
            }
            
    except Exception as e:
        logger.error(f"[generate_shot_videos] 创建任务失败: {e}")
        return {"success": False, "error": str(e)}


@tool
async def check_task_status(task_id: str) -> Dict[str, Any]:
    """
    查询 Celery 任务状态
    
    Args:
        task_id: 任务 ID
        
    Returns:
        任务状态信息，包括 status、result、error 等
    """
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        response = {
            "task_id": task_id,
            "status": result.status,
            "ready": result.ready(),
        }
        
        if result.ready():
            if result.successful():
                response["result"] = result.result
            else:
                response["error"] = str(result.result) if result.result else "Unknown error"
        elif result.status == "PROGRESS":
            response["progress"] = result.info
            
        return response
        
    except Exception as e:
        logger.error(f"[check_task_status] 查询失败: {e}")
        return {"task_id": task_id, "status": "ERROR", "error": str(e)}


@tool
async def check_task_group_status(
    group_id: str,
    shot_task_ids: Dict[int, str],
) -> Dict[str, Any]:
    """
    查询任务组状态（用于批量分镜图片/视频生成）
    
    Args:
        group_id: Celery group 任务 ID
        shot_task_ids: shot_id -> task_id 映射
        
    Returns:
        任务组状态统计
    """
    from celery.result import AsyncResult
    from app.core.celery_app import celery_app
    
    try:
        total = len(shot_task_ids)
        completed = 0
        failed = 0
        pending = 0
        failed_shots = []
        completed_shots = []
        
        for shot_id, task_id in shot_task_ids.items():
            result = AsyncResult(task_id, app=celery_app)
            
            if result.successful():
                task_result = result.result or {}
                if isinstance(task_result, dict) and task_result.get("success") == False:
                    failed += 1
                    failed_shots.append({
                        "shot_id": shot_id,
                        "error": task_result.get("error", "Unknown error"),
                    })
                else:
                    completed += 1
                    completed_shots.append({"shot_id": shot_id, "result": task_result})
            elif result.failed():
                failed += 1
                failed_shots.append({
                    "shot_id": shot_id,
                    "error": str(result.result) if result.result else "Unknown error",
                })
            else:
                pending += 1
        
        all_done = (completed + failed) == total
        
        return {
            "group_id": group_id,
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "all_done": all_done,
            "success": all_done and failed == 0,
            "failed_shots": failed_shots if failed > 0 else None,
            "completed_shots": completed_shots[:3] if completed_shots else None,
        }
        
    except Exception as e:
        logger.error(f"[check_task_group_status] 查询失败: {e}")
        return {"group_id": group_id, "status": "ERROR", "error": str(e)}


# 更新导出列表
GENERATION_TOOLS.extend([
    create_asset_generation_tasks,
    generate_shot_images,
    generate_shot_videos,
    check_task_status,
    check_task_group_status,
])

