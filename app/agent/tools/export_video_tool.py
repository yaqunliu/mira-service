"""
视频导出工具 - 合并多个分镜视频

使用 Celery 队列异步导出视频
"""

from typing import Dict, Any, List

from langchain_core.tools import tool

from app.core.logger import logger


@tool
async def export_final_video(
    creation_uuid: str,
    shot_ids: List[int],
    task_uuid: str = None,
) -> Dict[str, Any]:
    """
    导出最终视频 - 将多个分镜视频拼接成一个视频（异步提交）

    Args:
        creation_uuid: 创作项目UUID（支持完整UUID或数字ID）
        shot_ids: 分镜ID列表
        task_uuid: VocabTask UUID（用于更新任务状态）

    Returns:
        {
            "success": True,
            "message": "导出任务已提交"
        }
    """
    # 如果 creation_uuid 是数字，尝试从数据库查询
    if creation_uuid and not creation_uuid.startswith("-"):
        try:
            int_val = int(creation_uuid)
            from sqlalchemy import select
            from app.models.creation import Creation
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Creation).where(Creation.creation_id == int_val)
                )
                creation = result.scalar_one_or_none()
                if creation:
                    creation_uuid = creation.uuid
                    logger.info(f"[ExportVideo] 从ID获取到UUID: {creation_uuid}")
            finally:
                await db.close()
        except:
            pass
    
    logger.info(f"[ExportVideo] 开始导出流程: creation_uuid={creation_uuid}, shot_ids={shot_ids}")
    
    try:
        from app.agent.tools.async_db import get_async_session
        from app.models.shot import Shot
        from app.models.creation import Creation
        from sqlalchemy import select
        
        async with get_async_session() as db:
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result.scalar_one_or_none()
            if creation.video_url:
                logger.info(f"[ExportVideo] 创作已导出视频: {creation.video_url}")
                return {"success": True, "video_url": creation.video_url, "message": "创作已导出视频"}
            
            if not creation:
                logger.error(f"[ExportVideo] 未找到创作: {creation_uuid}")
                return {"success": False, "message": "未找到创作"}
            
            result = await db.execute(
                select(Shot).where(
                    Shot.shot_id.in_(shot_ids),
                    Shot.creation_id == creation.creation_id
                )
            )
            shots = result.scalars().all()
            
            video_count = sum(1 for shot in shots if shot.video_url)
            logger.info(f"[ExportVideo] 找到 {len(shots)} 个分镜, {video_count} 个有视频")
            
            if video_count == 0:
                logger.error(f"[ExportVideo] 没有可导出的视频")
                return {"success": False, "message": "没有可导出的视频"}
            
            if video_count == 1:
                first_video_url = next(shot.video_url for shot in shots if shot.video_url)
                logger.info(f"[ExportVideo] 只有一个视频，直接返回: {first_video_url}")
                return {"success": True, "video_url": first_video_url, "message": "只有一个视频，直接返回"}
            
            creation_id = creation.creation_id
            owner_id = creation.owner_id
        
        logger.info(f"[ExportVideo] 准备提交Celery任务: creation_id={creation_id}, creation_uuid={creation_uuid}")
        
        # 提交 celery 任务
        from app.tasks.vocab_export import export_vocab_video_task
        
        task = export_vocab_video_task.delay(
            creation_id, 
            owner_id, 
            shot_ids, 
            task_uuid
        )
        
        logger.info(f"[ExportVideo] Celery任务已提交: task_id={task.id}")
        
        # 等待任务完成并获取结果
        result = task.get(timeout=600)
        video_url = result.get("video_url") if isinstance(result, dict) else None
        
        return {
            "success": True,
            "video_url": video_url,
            "message": f"导出完成，共 {video_count} 个视频"
        }
        
    except Exception as e:
        logger.error(f"[ExportVideo] 导出失败: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


export_final_video_tool = export_final_video
