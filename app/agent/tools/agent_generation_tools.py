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


@tool
async def generate_shot_image(
    creation_uuid: str,
    shot_id: int,
    prompt: str,
    frame_type: str = "both",
    style: Optional[Dict[str, Any]] = None,
    model: str = "doubao",
) -> Dict[str, Any]:
    """
    生成分镜图片
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        prompt: 图片生成提示词
        frame_type: 帧类型（start=首帧, end=尾帧, both=双帧）
        style: 风格参数（可选）
        model: 生成模型（默认 doubao）
        
    Returns:
        生成结果
    """
    logger.info(f"[Generation Tool] 生成分镜图片: shot_id={shot_id}, frame_type={frame_type}")
    
    from app.agent.tasks.image_tasks import agent_generate_shot_image_task
    
    task = agent_generate_shot_image_task.delay(
        creation_uuid=creation_uuid,
        shot_id=shot_id,
        prompt=prompt,
        frame_type=frame_type,
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
    generate_shot_image,
    generate_video,
    generate_audio,
]
