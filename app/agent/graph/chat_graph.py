"""
Chat Graph - 使用 LangGraph create_react_agent

架构（参考 comic_drama_subgraph）：
- supervisor: 使用 create_react_agent 的 Chat Supervisor，返回 next_node
- conditional_edges: 根据 next_node 路由到对应 Worker
- Worker 执行完成后回到 Supervisor
"""

from typing import Dict, Any
from langgraph.graph import StateGraph, END

from app.agent.state.chat_schemas import ChatState
from app.agent.graph.nodes.chat_supervisor_agent import get_chat_supervisor_agent
from app.agent.graph.nodes.teams.vocab_worker import VocabWorkerNode
from app.core.logger import logger


async def supervisor_node(state: ChatState) -> Dict[str, Any]:
    """
    Chat Supervisor Node
    
    使用 create_react_agent 处理用户消息
    返回包含 next_node 的结果，用于路由
    """
    logger.info("[ChatGraph] Supervisor 处理消息")
    
    # 检查是否应该结束 SSE（从 vocab_worker_node 传递过来的标记）
    should_end_sse = state.get("should_end_sse", False)
    if should_end_sse:
        logger.info("[ChatGraph] 检测到 should_end_sse=True，直接结束")
        # 保持 should_end_sse 标记，让 route_from_supervisor 正确处理
        return {
            "should_end_sse": True,
            "next_node": None,
        }
    
    # 如果有 worker_result，说明是 Worker 执行完成后回调，需要发送最终响应
    worker_result = state.get("worker_result")
    if worker_result:
        logger.info(f"[ChatGraph] Supervisor 发送最终响应: worker_result={worker_result}")
        # 返回最终响应，包含 worker_result
        video_url = worker_result.get("video_url", "")
        status = worker_result.get("status", "unknown")
        
        if status == "completed":
            response_text = f"🎬 视频生成完成！\n\n视频地址：{video_url}"
        else:
            response_text = f"⚠️ 视频生成状态：{status}"
        
        return {
            "response_text": response_text,
            "worker_result": worker_result,
            "next_node": None,  # 不再调度
            "should_end_sse": True,  # 标记应该结束 SSE
        }
    
    agent = get_chat_supervisor_agent()
    result = await agent.invoke(state)
    
    next_node = result.get("next_node")
    worker_result = result.get("worker_result")
    logger.info(f"[ChatGraph] Supervisor 返回: next_node={next_node}, worker_result={worker_result}")
    
    return result


async def vocab_worker_node(state: ChatState) -> Dict[str, Any]:
    """
    Vocab Worker Node - 生成单词视频
    
    1. 先查询状态
    2. 如果已完成/生成中 → 返回结果给 Supervisor
    3. 如果未开始 → 开始生成
    """
    logger.info("[ChatGraph] VocabWorker 处理视频生成")
    
    # 获取配置
    vocab_config = state.get("vocab_config", {})
    creation_uuid = state.get("creation_uuid", "")
    user_id = state.get("user_id", 0)
    
    from app.agent.triggers.vocab_trigger import _update_creation_status
    from uuid import uuid4
    from app.agent.state.schemas import ComicDramaState
    from app.agent.config.vocab_config import merge_vocab_config
    
    try:
        # 获取 creation_id 和当前状态
        from sqlalchemy import select
        from app.db.base import _get_async_session_factory
        from app.models.creation import Creation
        
        db = _get_async_session_factory()()
        try:
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result.scalar_one_or_none()
            if not creation:
                raise ValueError(f"未找到 Creation: {creation_uuid}")
            creation_id = creation.creation_id
            current_status = creation.status
            extra_data = creation.extra_data or {}
        finally:
            await db.close()
        
        logger.info(f"[ChatGraph] VocabWorker 当前状态: status={current_status} videour： {extra_data.get('video_url') or creation.video_url}")
        
        # 如果已完成，直接返回结果
        if current_status == "completed":
            video_url = extra_data.get("video_url") or creation.video_url
            return {
                "response_text": f"🎬 视频已生成完成！\n\n视频地址：{video_url}",
                "final_video_url": video_url,
                "worker_result": {
                    "status": "completed",
                    "video_url": video_url,
                },
                "should_end_sse": True,  # 标记结束
                "next_node": None,
            }
        
        # 如果正在生成中，返回进度（不调度到 Worker，避免循环）
        if current_status in ["processing", "generating", "exporting"]:
            progress = extra_data.get("progress", 0)
            current_step = extra_data.get("current_step", "处理中")
            return {
                "response_text": f"⏳ 视频正在生成中...\n\n进度：{progress}%\n当前步骤：{current_step}",
                "worker_result": {
                    "status": current_status,
                    "progress": progress,
                    "current_step": current_step,
                },
                "should_end_sse": True,  # 标记结束，不继续调度
                "next_node": None,
            }
        
        # 状态为 pending 或其他，开始生成
        logger.info(f"[ChatGraph] 开始生成视频，creation_id={creation_id}")
        
        # 合并配置
        merged_config = merge_vocab_config(vocab_config)
        
        # 构建初始状态
        initial_state: ComicDramaState = {
            "creation_uuid": creation_uuid,
            "thread_id": f"vocab_{creation_uuid}_{uuid4().hex[:8]}",
            "user_id": user_id,
            "task_id": creation_id,
            "user_message": "",
            "messages": [],
            "current_stage": "VOCAB_INIT",
            "creation_type": "vocab",
            "vocab_config": merged_config,
        }
        
        # 更新状态
        await _update_creation_status(
            creation_id=creation_id,
            status="processing",
            progress=10,
            current_step="开始生成单词视频",
        )
        
        # 执行 Worker
        vocab_worker = VocabWorkerNode()
        vocab_worker.creation_uuid = creation_uuid
        vocab_worker.creation_id = creation_id
        vocab_worker.user_id = user_id
        vocab_worker.task_id = creation_id
        
        # Worker 返回的结果已经包含 final_video_url
        result = await vocab_worker.run(initial_state)
        
        # 直接使用返回值获取 video_url
        video_url_from_result = result.get("final_video_url", "")
        
        # 从数据库获取 video_url 作为对比
        video_url_from_db = ""
        db = _get_async_session_factory()()
        try:
            result_db = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result_db.scalar_one_or_none()
            if creation:
                extra = creation.extra_data or {}
                video_url_from_db = extra.get("video_url", "")
                status = creation.status
            else:
                status = "unknown"
        finally:
            await db.close()
        
        # 优先使用 result 返回的 video_url
        video_url = video_url_from_result or video_url_from_db
        
        logger.info(f"[ChatGraph] VocabWorker 执行完成, status={status}, video_url_from_result={video_url_from_result}, video_url_from_db={video_url_from_db}")
        
        # 返回结果给 Supervisor
        return {
            "response_text": f"🎬 视频生成完成！\n\n视频地址：{video_url}",
            "final_video_url": video_url,
            "worker_result": {
                "status": "completed",
                "video_url": video_url,
            },
            "creation_id": creation_id,
            "should_end_sse": True,  # 标记结束 SSE
            "next_node": None,
        }
        
    except Exception as e:
        logger.error(f"[ChatGraph] VocabWorker 失败: {e}", exc_info=True)
        return {
            "response_text": f"❌ 视频生成失败：{str(e)}",
            "errors": [str(e)],
            "worker_result": {
                "status": "failed",
                "error": str(e),
            },
            "should_end_sse": True,  # 标记结束 SSE
            "next_node": None,
        }


def route_from_supervisor(state: ChatState) -> str:
    """
    Supervisor 决策后的路由
    
    根据 next_node 和 worker_result 决定下一步:
    - should_end_sse=True → Worker 已完成，发送最终响应并结束
    - worker_result 有值 → Worker 已返回结果，发送响应并结束
    - next_node 有值 → 调度到对应 Worker
    - 其他情况 → 结束
    """
    worker_result = state.get("worker_result")
    next_node = state.get("next_node")
    should_end_sse = state.get("should_end_sse", False)
    
    logger.info(f"[ChatGraph] route_from_supervisor: worker_result={worker_result}, next_node={next_node}, should_end_sse={should_end_sse}")
    
    # 如果标记了应该结束 SSE（Worker 已完成），直接结束
    if should_end_sse:
        logger.info("[ChatGraph] Worker 已完成，结束 SSE")
        return "done"
    
    # 如果 Worker 已返回结果，发送响应并结束
    if worker_result:
        logger.info("[ChatGraph] Worker 已返回结果，发送响应并结束")
        # 返回特殊标记，让 runner 发送最终响应
        return "done"
    
    # 如果需要调度到 Worker
    if next_node == "vocab_worker":
        logger.info("[ChatGraph] 调度到 vocab_worker")
        return "vocab_worker"
    
    # 没有下一个 Worker → 结束
    logger.info("[ChatGraph] 没有 Worker，结束")
    return "done"


def build_chat_graph() -> StateGraph:
    """
    构建 Chat Graph
    
    流程（参考 comic_drama_subgraph）：
    supervisor ⇄ vocab_worker → END
    supervisor → END
    
    Supervisor 使用 create_react_agent 自动处理用户请求
    根据 next_worker 路由到对应的 Worker
    """
    logger.info("[ChatGraph] 构建 Chat Graph")
    
    workflow = StateGraph(ChatState)
    
    # Supervisor 节点
    workflow.add_node("supervisor", supervisor_node)
    
    # Vocab Worker 节点
    workflow.add_node("vocab_worker", vocab_worker_node)
    
    # 设置入口
    workflow.set_entry_point("supervisor")
    
    # Supervisor 决策路由
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "vocab_worker": "vocab_worker",
            "done": END,
        }
    )
    
    # Worker 完成后回到 Supervisor，由 Supervisor 发送最终响应
    workflow.add_edge("vocab_worker", "supervisor")
    
    return workflow.compile()


# 全局实例
chat_graph = build_chat_graph()
