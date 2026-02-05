"""
Generation Trigger Tools - 图片/视频生成触发工具

提供触发异步生成任务的功能，供 AssetRegeneratorWorker 使用。
这些工具只负责任务触发，不处理具体的生成逻辑。
"""

from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.core.logger import logger


@tool
async def trigger_image_generation(
    resource_type: str,
    resource_id: int,
    frame_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    触发图片生成任务
    
    Args:
        resource_type: 资源类型 "character" / "scene" / "shot"
        resource_id: 资源ID
        frame_type: 帧类型（仅分镜需要）"start" / "end" / "both"
        
    Returns:
        {
            "success": bool,
            "task_id": str,
            "message": str
        }
    """
    logger.info(f"[Trigger Tool] 触发图片生成: {resource_type}={resource_id}, frame={frame_type}")
    
    try:
        # TODO: 调用 Celery 任务
        # from app.tasks.image_tasks import generate_image_task
        # task = generate_image_task.delay(resource_type, resource_id, frame_type)
        
        return {
            "success": True,
            "task_id": f"mock_task_{resource_type}_{resource_id}",
            "message": f"已触发{resource_type}图片生成任务"
        }
        
    except Exception as e:
        logger.error(f"[Trigger Tool] 触发图片生成失败: {e}")
        return {
            "success": False,
            "task_id": "",
            "message": f"触发失败: {str(e)}"
        }


@tool
async def trigger_video_generation(
    shot_id: int,
    generation_mode: str = "first_last_frame"
) -> Dict[str, Any]:
    """
    触发视频生成任务
    
    Args:
        shot_id: 分镜ID
        generation_mode: 生成模式 "first_frame_only" / "first_last_frame"
        
    Returns:
        {
            "success": bool,
            "task_id": str,
            "message": str
        }
    """
    logger.info(f"[Trigger Tool] 触发视频生成: shot_id={shot_id}, mode={generation_mode}")
    
    try:
        # TODO: 调用 Celery 任务
        # from app.tasks.video_tasks import generate_video_task
        # task = generate_video_task.delay(shot_id, generation_mode)
        
        return {
            "success": True,
            "task_id": f"mock_task_video_{shot_id}",
            "message": "已触发分镜视频生成任务"
        }
        
    except Exception as e:
        logger.error(f"[Trigger Tool] 触发视频生成失败: {e}")
        return {
            "success": False,
            "task_id": "",
            "message": f"触发失败: {str(e)}"
        }


# ==================== 工具列表导出 ====================

GENERATION_TRIGGER_TOOLS = [
    trigger_image_generation,
    trigger_video_generation,
]
