"""
Agent 专用视频生成 Tasks

⚠️ 核心原则：这些 Tasks 独立于现有的 step8_video_gen_task 等任务
"""

from typing import Dict, Any, Optional

from app.core.celery_app import celery_app
from app.core.logger import logger


@celery_app.task(bind=True, name="agent.generate_video")
def agent_generate_video_task(
    self,
    creation_uuid: str,
    shot_id: int,
    start_image_url: str,
    end_image_url: Optional[str] = None,
    prompt: Optional[str] = None,
    duration: float = 5.0,
    model: str = "kling",
) -> Dict[str, Any]:
    """
    Agent 专用视频生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        start_image_url: 首帧图片 URL
        end_image_url: 尾帧图片 URL（可选，用于首尾帧模式）
        prompt: 视频运动提示词（可选）
        duration: 视频时长（秒）
        model: 生成模型（默认 kling）
        
    Returns:
        {
            "status": "success" | "failed",
            "shot_id": int,
            "video_url": str,
            "duration": float,
            "error": str  # 仅失败时
        }
    """
    try:
        logger.info(f"[Agent Task] 开始生成视频: shot_id={shot_id}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '开始生成视频...',
            'shot_id': shot_id,
        })
        
        from app.services.video_generation import VideoGenerationService
        
        video_service = VideoGenerationService()
        
        self.update_state(state='PROGRESS', meta={
            'progress': 20,
            'status': '提交视频生成请求...',
            'shot_id': shot_id,
        })
        
        # 根据是否有尾帧选择生成模式
        if end_image_url:
            # 首尾帧模式
            result = video_service.generate_with_frames(
                start_image_url=start_image_url,
                end_image_url=end_image_url,
                prompt=prompt,
                duration=duration,
                model=model,
            )
        else:
            # 单图模式
            result = video_service.generate(
                image_url=start_image_url,
                prompt=prompt,
                duration=duration,
                model=model,
            )
        
        self.update_state(state='PROGRESS', meta={
            'progress': 90,
            'status': '保存结果到数据库...',
            'shot_id': shot_id,
        })
        
        # 更新数据库
        from app.db.session import get_sync_session
        from app.models.shot import Shot
        
        with get_sync_session() as db:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.video_url = result["url"]
                db.commit()
        
        logger.info(f"[Agent Task] 视频生成成功: shot_id={shot_id}")
        
        return {
            "status": "success",
            "shot_id": shot_id,
            "video_url": result["url"],
            "duration": duration,
            "generation_time": result.get("time", 0),
        }
        
    except Exception as e:
        logger.error(f"[Agent Task] 视频生成失败: {e}")
        return {
            "status": "failed",
            "shot_id": shot_id,
            "error": str(e),
            "recoverable": True,
        }
