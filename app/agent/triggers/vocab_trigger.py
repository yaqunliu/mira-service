"""
API Trigger - 通过API触发Agent执行单词视频生成

当用户通过API调用 /vocab/create 时，使用这个触发器
"""

from typing import Dict, Any
import uuid

from sqlalchemy import select

from app.core.logger import logger


async def trigger_agent_for_vocab(
    user_id: int,
    task_uuid: str,
    creation_id: int,
    config: Dict[str, Any],
) -> str:
    """
    通过API触发Agent执行单词视频生成
    
    Args:
        user_id: 用户ID
        task_uuid: 任务UUID（用于外部查询）
        creation_id: Creation ID（用于内部更新状态）
    config: 单词视频配置
        
    Returns:
        thread_id
    """
    from app.agent.config.vocab_config import merge_vocab_config
    from app.agent.graph.nodes.teams.vocab_worker import VocabWorkerNode
    from app.agent.state.schemas import ComicDramaState, ProductionStage
    
    merged_config = merge_vocab_config(config)
    
    creation_uuid = task_uuid  # 使用 task_uuid 作为 creation_uuid
    
    logger.info(f"[Vocab Trigger] 触发单词视频生成: task_uuid={task_uuid}, creation_id={creation_id}, config={merged_config}")
    
    vocab_worker = VocabWorkerNode()
    
    try:
        await _update_creation_status(
            creation_id=creation_id,
            status="processing",
            progress=10,
            current_step="初始化",
        )
        
        initial_state: ComicDramaState = {
            "creation_uuid": creation_uuid,
            "thread_id": f"vocab_{task_uuid}_{uuid.uuid4().hex[:8]}",
            "user_id": user_id,
            "task_id": creation_id,
            "user_message": "",
            "messages": [],
            "current_stage": "VOCAB_INIT",
            "creation_type": "vocab",
            "vocab_config": merged_config,
            "task_id": creation_id,
        }
        
        await _update_creation_status(
            creation_id=creation_id,
            progress=5,
            current_step="开始生成单词视频",
        )
        
        vocab_worker.creation_uuid = creation_uuid
        vocab_worker.creation_id = creation_id
        vocab_worker.user_id = user_id
        vocab_worker.task_id = creation_id
        
        result = await vocab_worker.run(initial_state)
        
        await _update_creation_status(
            creation_id=creation_id,
            status="exporting",
            progress=80,
            current_step="导出视频",
        )
        
        from app.agent.tools.export_video_tool import export_final_video
        shot_ids = [s.get("shot_id") for s in result.get("shots", []) if s.get("shot_id")]
        
        export_result = await export_final_video.ainvoke({
            "creation_uuid": creation_uuid,
            "shot_ids": shot_ids,
        })
        
        logger.info(f"[Vocab Trigger] 导出结果: {export_result}")
        
        # 更新最终状态
        video_url = export_result.get("video_url")
        logger.info(f"[Vocab Trigger] 视频URL: {video_url}")
        
        await _update_creation_status(
            creation_id=creation_id,
            status="completed",
            progress=100,
            current_step="导出完成",
            video_url=video_url,
        )
        
        return initial_state["thread_id"]
        
    except Exception as e:
        logger.error(f"[Vocab Trigger] 执行失败: {e}")
        
        await _update_creation_status(
            creation_id=creation_id,
            status="failed",
            progress=0,
            current_step="执行失败",
            error_message=str(e)[:500],
        )
        
        raise


async def _update_creation_status(
    creation_id: int,
    status: str = None,
    progress: int = None,
    current_step: str = None,
    step_status: str = None,
    video_url: str = None,
    error_message: str = None,
):
    """更新 Creation 状态"""
    from sqlalchemy import update
    from sqlalchemy.orm.attributes import flag_modified
    from app.db.base import AsyncSessionLocal
    from app.models.creation import Creation
    
    db = AsyncSessionLocal()()
    try:
        result = await db.execute(
            select(Creation).where(Creation.creation_id == creation_id)
        )
        creation = result.scalar_one_or_none()
        
        if not creation:
            logger.error(f"[_update_creation_status] Creation not found: {creation_id}")
            return
        
        if status:
            creation.status = status
        
        extra = creation.extra_data or {}
        
        if progress is not None:
            extra["progress"] = progress
        if current_step:
            # 截断到100字符
            extra["current_step"] = current_step[:100]
        if step_status:
            if "step_status" in extra and extra["step_status"]:
                extra["step_status"] = extra["step_status"] + "\n" + step_status
            else:
                extra["step_status"] = step_status
        if video_url:
            extra["video_url"] = video_url
        if error_message:
            extra["error_message"] = error_message
        
        creation.extra_data = extra
        flag_modified(creation, "extra_data")
        
        await db.commit()
        logger.info(f"[_update_creation_status] 更新成功: creation_id={creation_id}, status={status}, progress={progress}, current_step={current_step}")
    except Exception as e:
        logger.error(f"[_update_creation_status] 更新失败: {e}")
    finally:
        await db.close()
