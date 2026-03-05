"""
API Trigger - 通过API触发Agent执行单词视频生成

当用户通过API调用 /vocab/create 时，使用这个触发器
"""

from typing import Dict, Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.models.creation import Creation, WorkflowMode


async def trigger_vocab_creation(
    db: AsyncSession,
    user_id: int,
    config: Dict[str, Any],
) -> Creation:
    """
    创建 Vocab 创作任务（供 Standalone Agent 使用）
    
    Args:
        db: 数据库会话
        user_id: 用户ID
        config: 单词视频配置
        
    Returns:
        Creation: 创建的 Creation 对象
    """
    import asyncio
    from uuid import uuid4
    
    task_uuid = str(uuid4())
    words = config.get("words", [])
    
    # 优化视频命名
    if len(words) == 0:
        title = "单词视频"
    elif len(words) <= 3:
        title = f"单词视频: {', '.join(words)}"
    else:
        title = f"单词视频: {', '.join(words[:3])} 等{len(words)}个单词"
    
    creation = Creation(
        uuid=task_uuid,
        title=title,
        creation_type="chat",
        status="processing",
        owner_id=user_id,
        workflow_mode=WorkflowMode.AGENT,
        extra_data={
            "config": config,
            "progress": 0,
            "current_step": "等待处理",
        }
    )
    
    db.add(creation)
    await db.commit()
    await db.refresh(creation)
    
    # 异步触发 Agent
    asyncio.create_task(
        trigger_agent_for_vocab(
            user_id=user_id,
            task_uuid=creation.uuid,
            creation_id=creation.creation_id,
            config=config,
        )
    )
    
    logger.info(f"[trigger_vocab_creation] 创建成功: creation_id={creation.creation_id}, uuid={creation.uuid}")
    
    return creation


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
        
        # 执行 Worker（内部已完成视频生成和导出）
        result = await vocab_worker.run(initial_state)
        
        # Worker 返回的结果已经包含 final_video_url
        video_url = result.get("final_video_url", "")
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
