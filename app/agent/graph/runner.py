"""
Graph Runner 模块

封装 LangGraph 的执行逻辑，提供统一的入口
"""

from typing import Dict, Any, Optional, AsyncIterator
from datetime import datetime
import asyncio

from app.core.logger import logger


class GraphRunner:
    """
    Graph 执行器
    
    封装 ComicDramaGraph 的执行，提供：
    - 状态初始化
    - SSE 流式输出
    - 检查点管理
    - 错误处理
    """
    
    def __init__(
        self,
        creation_uuid: str,
        thread_id: str,
        user_id: int,
    ):
        self.creation_uuid = creation_uuid
        self.thread_id = thread_id
        self.user_id = user_id
        
        # 状态管理
        from app.agent.state.persistence import StatePersistence
        from app.agent.state.messages import MessageHistory
        
        self.persistence = StatePersistence(creation_uuid, thread_id)
        self.message_history = MessageHistory(creation_uuid, thread_id)
    
    async def handle_chat_message(
        self,
        user_message: str,
        user_action: Optional[str] = None,
        user_action_data: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """
        处理用户聊天消息
        
        Args:
            user_message: 用户消息
            user_action: 用户操作（approve/reject/modify）
            user_action_data: 操作附加数据
            
        Yields:
            SSE 格式的字符串
        """
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        try:
            # 1. 加载历史消息
            history_messages = await self.message_history.load()
            logger.info(f"[GraphRunner] 加载历史消息: {len(history_messages)} 条")
            
            # 2. 尝试加载上一个检查点
            last_state = await self.persistence.load_checkpoint()
            logger.info(f"[GraphRunner] checkpoint 内容: {last_state}")
            
            # 尝试从 LangGraph 内存获取状态
            from app.agent.graph.dialogue_graph import get_dialogue_runner
            runner = get_dialogue_runner()
            langgraph_state = runner.get_state(self.thread_id)
            if langgraph_state and hasattr(langgraph_state, 'values'):
                langgraph_values = dict(langgraph_state.values)
                logger.info(f"[GraphRunner] LangGraph 状态: {langgraph_values}")
                # 合并 LangGraph 状态到 last_state
                if last_state:
                    last_state.update(langgraph_values)
                else:
                    last_state = langgraph_values
            
            # 3. 加载 creation_type
            creation_type = await self._load_creation_type()
            logger.info(f"[GraphRunner] 加载 creation_type: {creation_type}, creation_uuid: {self.creation_uuid}")
            
            # 4. 构建初始状态
            initial_state = self._build_initial_state(
                user_message=user_message,
                user_action=user_action,
                user_action_data=user_action_data,
                history_messages=history_messages,
                last_state=last_state,
            )
            initial_state["creation_type"] = creation_type
            logger.info(f"[GraphRunner] 初始状态: creation_type={initial_state.get('creation_type')}")
            
            # 4. 添加用户消息到历史
            await self.message_history.append({
                "role": "user",
                "content": user_message,
                "timestamp": datetime.now().isoformat(),
            })
            
            # 5. 执行 Graph
            async for sse_event in self._run_graph(initial_state, formatter):
                yield sse_event
            
            # 6. 发送完成事件
            yield formatter._format_sse({"event": "done", "data": {}})
            
        except Exception as e:
            logger.error(f"[GraphRunner] 执行错误: {e}")
            
            # 保存错误检查点
            await self.persistence.save_checkpoint(
                {"error": str(e), "timestamp": datetime.now().isoformat()},
                checkpoint_type="error",
            )
            
            yield formatter._format_sse({
                "event": "error",
                "data": {
                    "error": str(e),
                    "code": "EXECUTION_ERROR",
                    "recoverable": True,
                }
            })
            yield formatter._format_sse({"event": "done", "data": {}})
    
    def _build_initial_state(
        self,
        user_message: str,
        user_action: Optional[str],
        user_action_data: Optional[Dict[str, Any]],
        history_messages: list,
        last_state: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """构建初始状态
        
        重要：user_message 和 creation_uuid 始终使用当前请求的值，不从 checkpoint 恢复
        """
        state = {
            "creation_uuid": self.creation_uuid,  # 始终使用当前请求的 creation_uuid
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "user_message": user_message,  # 始终使用当前请求的 user_message
            "messages": history_messages,
            "updated_at": datetime.now().isoformat(),
            "video_type": None,
            "should_generate": False,
        }
        
        # 如果有上一个检查点状态，恢复部分字段（但不覆盖关键字段）
        if last_state:
            # 恢复生产阶段状态
            state["production_stage"] = last_state.get("production_stage")
            state["production_cache"] = last_state.get("production_cache", {})
            # 恢复检查点状态
            state["checkpoint_status"] = last_state.get("checkpoint_status")
            state["checkpoint_data"] = last_state.get("checkpoint_data")
            # 恢复 Chat 模式的状态
            state["video_type"] = last_state.get("video_type")
            state["vocab_config"] = last_state.get("vocab_config", {})
            state["should_generate"] = last_state.get("should_generate", False)
            # 恢复其他状态
            state["current_stage"] = last_state.get("current_stage", "init")
            state["pending_approval"] = last_state.get("pending_approval", False)
            # 恢复角色、场景、分镜数据
            state["characters"] = last_state.get("characters", [])
            state["scenes"] = last_state.get("scenes", [])
            state["shots"] = last_state.get("shots", [])
            # 恢复视频生成配置
            state["video_generation_type"] = last_state.get("video_generation_type")
            state["video_model"] = last_state.get("video_model")
            # 恢复剧本数据
            state["script_text"] = last_state.get("script_text")
            state["script_url"] = last_state.get("script_url")
        
        # 如果有用户操作
        if user_action:
            state["user_action"] = user_action
            state["user_action_data"] = user_action_data or {}
            
            # 如果用户确认生成
            if user_action == "confirm_generation":
                state["should_generate"] = True
                state["user_action"] = user_action  # 重新设置
                logger.info(f"[GraphRunner] 用户确认生成视频, user_action={user_action}, should_generate={state.get('should_generate')}")
        
        return state
    
    async def _load_creation_type(self) -> str:
        """从数据库加载 creation_type"""
        from app.db.base import _get_async_session_factory
        from app.models.creation import Creation
        from sqlalchemy import select
        
        db = _get_async_session_factory()()
        try:
            result = await db.execute(
                select(Creation).where(Creation.uuid == self.creation_uuid)
            )
            creation = result.scalar_one_or_none()
            if creation:
                return creation.creation_type or "chapter"
            return "chapter"
        finally:
            await db.close()
    
    async def _monitor_task(
        self,
        task_id: Optional[str],
        creation_id: Optional[int],
        formatter,
        message_id: str,
    ) -> AsyncIterator[str]:
        """
        监控任务状态，推送进度到前端
        
        当 graph 执行完成后，如果有任务在运行，继续保持 SSE 连接推送进度
        """
        from app.db.base import _get_async_session_factory
        from app.models.creation import Creation
        from sqlalchemy import select
        
        logger.info(f"[GraphRunner] 开始监控任务: task_id={task_id}, creation_id={creation_id}")
        
        # 任务状态映射
        STATUS_MAP = {
            "pending": "等待中",
            "processing": "处理中",
            "generating": "生成中",
            "completed": "已完成",
            "failed": "失败",
        }
        
        check_interval = 3  # 每 3 秒检查一次
        max_wait_time = 3600  # 最多等待 1 小时
        elapsed = 0
        
        while elapsed < max_wait_time:
            await asyncio.sleep(check_interval)
            elapsed += check_interval
            
            # 查询任务状态
            db = _get_async_session_factory()()
            try:
                creation = None
                if creation_id:
                    result = await db.execute(
                        select(Creation).where(Creation.creation_id == creation_id)
                    )
                    creation = result.scalar_one_or_none()
                elif task_id:
                    result = await db.execute(
                        select(Creation).where(Creation.uuid == task_id)
                    )
                    creation = result.scalar_one_or_none()
                
                if not creation:
                    logger.warning(f"[GraphRunner] 任务不存在: {task_id}/{creation_id}")
                    break
                
                status = creation.status or "unknown"
                logger.info(f"[GraphRunner] 任务状态: {status}")
                
                # 发送进度更新
                status_text = STATUS_MAP.get(status, status)
                
                if status == "completed":
                    # 任务完成
                    video_url = getattr(creation, 'video_url', None) or getattr(creation, 'output_url', None)
                    yield formatter._format_sse({
                        "event": "message.delta",
                        "data": {
                            "id": message_id,
                            "content": f"\n\n✅ 视频生成完成！\n",
                            "node": "task_monitor",
                        },
                    })
                    if video_url:
                        yield formatter._format_sse({
                            "event": "message.delta",
                            "data": {
                                "id": message_id,
                                "content": f"视频地址：{video_url}\n",
                                "node": "task_monitor",
                            },
                        })
                    yield formatter._format_sse({
                        "event": "progress",
                        "data": {
                            "node": "task_monitor",
                            "status": "completed",
                        },
                    })
                    logger.info(f"[GraphRunner] 任务完成: {task_id}")
                    break
                    
                elif status == "failed":
                    # 任务失败
                    error_msg = getattr(creation, 'error_message', None) or "未知错误"
                    yield formatter._format_sse({
                        "event": "message.delta",
                        "data": {
                            "id": message_id,
                            "content": f"\n\n❌ 视频生成失败：{error_msg}\n",
                            "node": "task_monitor",
                        },
                    })
                    yield formatter._format_sse({
                        "event": "progress",
                        "data": {
                            "node": "task_monitor",
                            "status": "failed",
                        },
                    })
                    logger.info(f"[GraphRunner] 任务失败: {task_id}")
                    break
                else:
                    # 仍在处理中，发送进度
                    yield formatter._format_sse({
                        "event": "progress",
                        "data": {
                            "node": "task_monitor",
                            "status": status,
                            "progress": f"正在{status_text}...",
                        },
                    })
                    
            finally:
                await db.close()
        
        # 超时
        if elapsed >= max_wait_time:
            logger.warning(f"[GraphRunner] 任务监控超时: {task_id}")
            yield formatter._format_sse({
                "event": "message.delta",
                "data": {
                    "id": message_id,
                    "content": "\n\n⏰ 任务等待超时，请稍后查询状态\n",
                    "node": "task_monitor",
                },
            })
    
    async def _run_graph(
        self,
        initial_state: Dict[str, Any],
        formatter,
    ) -> AsyncIterator[str]:
        """
        执行 Graph 并转换为 SSE
        
        使用 astream_events 实现 LLM 流式输出
        """
        from app.agent.graph.dialogue_graph import get_dialogue_runner
        import uuid
        
        runner = get_dialogue_runner()
        message_id = str(uuid.uuid4())
        
        # 1. 发送消息开始
        yield formatter._format_sse({
            "event": "message.start",
            "data": {"id": message_id},
        })
        
        try:
            # 2. 使用 astream_events 流式执行 Graph（实时输出 LLM tokens）
            full_response = ""
            current_node = ""
            last_node_reported = ""
            streaming_node = ""  # 当前正在流式输出的节点
            
            # 去重集合：防止同一节点的消息重复发送
            sent_start_nodes = set()     # 已发送开始消息的节点
            sent_complete_nodes = set()  # 已发送完成消息的节点
            sent_response_nodes = set()  # 已发送 response_text 的节点
            
            # 收集所有 board_actions，用于保存到消息历史
            all_board_actions = []
            
            # 用户可见节点（会流式输出 LLM tokens）
            # - clarify: 澄清对话
            # - task_execution: 任务执行（保持 SSE 连接活跃）
            # - human_review: 人机交互确认请求
            # - supervisor: 重新生成等操作需要展示给用户
            # 注意：status_query 改为 ReAct Agent 后，不应流式输出中间思考过程
            # 注意：asset_generation 不在此列表，因为它的 LLM 输出是内部提示词，不应显示给用户
            USER_VISIBLE_NODES = {"query_status", "clarify", "human_review", "supervisor", "chat_supervisor"}
            
            # 不应发送 response_text 的节点（分析/内部过程）
            INTERNAL_NODES = {"storyboard_creation", "audio_processing", "video_generation", "editing", "entry", "intent_detection", "router", "response_formatter", "stage_complete"}
            
            # 需要发送开始消息的节点（用户可见的阶段）
            START_MESSAGE_NODES = {
                # "script_analysis": "📖 好的，正在分析剧本内容，识别角色和场景信息，请稍候...",
                # "asset_generation": "🎨 好的，开始为您生成角色和场景图片，请稍候...",
                # "storyboard_creation": "🎬 好的，正在生成分镜脚本，请稍候...",
                # "audio_processing": "🎤 好的，正在处理音频内容，请稍候...",
                # "video_generation": "🎥 好的，正在生成视频内容，请稍候...",
            }
            
            # 需要发送完成消息的节点（只有这些节点发送自动完成消息）
            # script_analysis 不在此列表，因为它的 response_text 已包含结果
            COMPLETE_MESSAGE_NODES = {
                "vocab_worker": "✅ 视频生成完成！",
            }
            
            # 需要发送 response_text 的节点
            # 统一由 supervisor 发送消息，其他节点只返回结果不直接发送
            # supervisor: 统一管理和发送所有消息给用户
            # chat_supervisor: ChatGraph 的 supervisor 节点
            RESPONSE_TEXT_NODES = {"supervisor", "chat_supervisor"}
            
            # 配置递归深度限制
            from app.core.config import settings
            recursion_limit = getattr(settings, 'LANGGRAPH_RECURSION_LIMIT', 25)
            config = {
                "configurable": {"thread_id": self.thread_id},
                "recursion_limit": recursion_limit,
            }
            
            # 使用 asyncio.Queue 来合并事件和心跳
            import time
            HEARTBEAT_INTERVAL = 10  # 每 10 秒发送一次心跳
            event_queue = asyncio.Queue()
            graph_done = asyncio.Event()
            
            async def heartbeat_producer():
                """后台任务：定期发送心跳事件"""
                while not graph_done.is_set():
                    try:
                        await asyncio.sleep(HEARTBEAT_INTERVAL)
                        if not graph_done.is_set():
                            await event_queue.put({
                                "_type": "heartbeat",
                                "node": last_node_reported or "processing",
                            })
                    except asyncio.CancelledError:
                        break
            
            async def event_producer():
                """后台任务：收集 graph 事件"""
                try:
                    async for event in runner.graph.astream_events(initial_state, config, version="v2"):
                        await event_queue.put({"_type": "graph_event", "event": event})
                finally:
                    graph_done.set()
                    await event_queue.put({"_type": "done"})
            
            # 启动后台任务
            heartbeat_task = asyncio.create_task(heartbeat_producer())
            event_task = asyncio.create_task(event_producer())
            
            try:
                while True:
                    item = await event_queue.get()
                    
                    if item["_type"] == "done":
                        break
                    elif item["_type"] == "heartbeat":
                        # 发送进度心跳
                        yield formatter._format_sse({
                            "event": "progress",
                            "data": {
                                "node": item["node"],
                                "status": "processing",
                            },
                        })
                        logger.debug(f"[GraphRunner] 发送进度心跳 node={item['node']}")
                        continue
                    
                    # 处理 graph 事件
                    event = item["event"]
                    
                    event_kind = event.get("event", "")
                    
                    # 节点开始事件 - 追踪当前节点
                    if event_kind == "on_chain_start":
                        node_name = event.get("name", "")
                        if node_name and node_name != last_node_reported and not node_name.startswith("_"):
                            last_node_reported = node_name
                            # 记录当前处理的节点（用于过滤 LLM 输出）
                            if node_name in USER_VISIBLE_NODES:
                                streaming_node = node_name
                            else:
                                streaming_node = ""  # 非可见节点，停止流式输出
                            
                            # 为特定阶段发送开始消息（只发送一次）
                            if node_name in START_MESSAGE_NODES and node_name not in sent_start_nodes:
                                sent_start_nodes.add(node_name)
                                start_msg = START_MESSAGE_NODES[node_name]
                                yield formatter._format_sse({
                                    "event": "message.delta",
                                    "data": {
                                        "id": message_id,
                                        "content": start_msg + "\n\n",
                                        "node": node_name,
                                    },
                                })
                                full_response += start_msg + "\n\n"
                            
                            yield formatter._format_sse({
                                "event": "progress",
                                "data": {
                                    "node": node_name,
                                    "status": "processing",
                                },
                            })
                    
                    # LLM 流式 token 事件 - 只输出用户可见节点的内容！
                    elif event_kind == "on_chat_model_stream":
                        # 只有当前节点是用户可见节点时才输出
                        if streaming_node in USER_VISIBLE_NODES:
                            chunk = event.get("data", {}).get("chunk")
                            if chunk and hasattr(chunk, "content") and chunk.content:
                                content = chunk.content
                                full_response += content
                                yield formatter._format_sse({
                                    "event": "message.delta",
                                    "data": {
                                        "id": message_id,
                                        "content": content,
                                        "node": streaming_node,
                                    },
                                })
                    
                    # 节点完成事件
                    elif event_kind == "on_chain_end":
                        node_name = event.get("name", "")
                        if node_name:
                            current_node = node_name
                            output = event.get("data", {}).get("output", {})
                            
                            # 处理 Command 对象
                            if hasattr(output, 'update') and isinstance(getattr(output, 'update', None), dict):
                                output = output.update
                            
                            # 调试日志
                            if node_name in RESPONSE_TEXT_NODES and isinstance(output, dict) and "response_text" in output:
                                logger.info(f"[GraphRunner] on_chain_end: node={node_name}, has_response_text=True, already_sent={node_name in sent_response_nodes}")
                            
                            # 检查是否有错误
                            has_error = isinstance(output, dict) and output.get("errors")
                            
                            # 为特定阶段发送完成/错误消息（只发送一次）
                            # 只对 COMPLETE_MESSAGE_NODES 中的节点发送完成消息
                            if node_name in COMPLETE_MESSAGE_NODES:
                                if has_error:
                                    error_msg = output.get("errors", [{}])[0].get("message", "未知错误")
                                    complete_msg = f"❌ {node_name} 执行失败：{error_msg}"
                                else:
                                    complete_msg = COMPLETE_MESSAGE_NODES[node_name]
                                
                                yield formatter._format_sse({
                                    "event": "message.delta",
                                    "data": {
                                        "id": message_id,
                                        "content": complete_msg + "\n\n",
                                        "node": node_name,
                                    },
                                })
                                full_response += complete_msg + "\n\n"
                            
                            # 如果节点输出有 response_text，根据白名单决定是否发送
                            if isinstance(output, dict) and "response_text" in output:
                                # 只有在 RESPONSE_TEXT_NODES 白名单中的节点才发送 response_text
                                # 同时检查是否已经发送过（防止重复）
                                if node_name in RESPONSE_TEXT_NODES:
                                    resp_text = output["response_text"]
                                    if resp_text:
                                        # 检查是否已经发送过这个节点的 response_text
                                        if node_name not in sent_response_nodes:
                                            sent_response_nodes.add(node_name)
                                            logger.info(f"[GraphRunner] 发送 response_text from {node_name}, 长度={len(resp_text)}")
                                            # 发送响应内容
                                            yield formatter._format_sse({
                                                "event": "message.delta",
                                                "data": {
                                                    "id": message_id,
                                                    "content": resp_text,
                                                    "node": node_name,
                                                },
                                            })
                                            full_response += resp_text
                                        else:
                                            logger.warning(f"[GraphRunner] 跳过重复 response_text from {node_name}")
                            
                            # 处理 board_actions - 发送给前端控制看板
                            # 只有特定节点才发送 board_actions（避免状态累积导致重复发送）
                            BOARD_ACTION_NODES = {"supervisor", "chat_supervisor"}
                            
                            # 处理 Command 对象或 dict
                            output_data = output
                            # Command 对象的 update 属性是字典
                            if hasattr(output, 'update') and isinstance(getattr(output, 'update', None), dict):
                                output_data = output.update
                            
                            if node_name in BOARD_ACTION_NODES and isinstance(output_data, dict) and "board_actions" in output_data:
                                board_actions = output_data.get("board_actions", [])
                                logger.info(f"[GraphRunner] 发现 board_actions: {board_actions}")
                                if board_actions:
                                    for action in board_actions:
                                        if action:  # 确保 action 不为 None
                                            yield formatter._format_sse({
                                                "event": "board_action",
                                                "data": {
                                                    "action": action,
                                                    "node": node_name,
                                                },
                                            })
                                            # 收集 board_action 用于保存
                                            all_board_actions.append(action)
                                            logger.info(f"[GraphRunner] 发送 board_action: {action}")
            
            finally:
                # 清理后台任务
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            
            # 3. 发送消息结束
            yield formatter._format_sse({
                "event": "message.end",
                "data": {
                    "id": message_id,
                    "finish_reason": "stop",
                },
            })
            
            # 4. 保存助手消息（包含 board_actions，用于刷新后恢复卡片）
            if full_response:
                message_data = {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.now().isoformat(),
                }
                # 如果有 board_actions，保存到消息中
                if all_board_actions:
                    message_data["board_actions"] = all_board_actions
                    logger.info(f"[GraphRunner] 保存消息时包含 {len(all_board_actions)} 个 board_actions")
                await self.message_history.append(message_data)
            
            # 5. 保存检查点
            final_state = runner.get_state(self.thread_id)
            logger.info(f"[GraphRunner] 保存检查点: final_state={final_state}")
            if final_state:
                state_values = dict(final_state.values) if hasattr(final_state, 'values') else {}
                logger.info(f"[GraphRunner] 保存 checkpoint 前的 state_values: creation_uuid in state_values={'creation_uuid' in state_values}, value={state_values.get('creation_uuid')}")
                logger.info(f"[GraphRunner] self.creation_uuid = {self.creation_uuid}")
                # 确保 creation_uuid 被保存
                if self.creation_uuid and "creation_uuid" not in state_values:
                    state_values["creation_uuid"] = self.creation_uuid
                await self.persistence.save_checkpoint(state_values, checkpoint_type="auto")
                
                # 6. 检查是否应该结束 SSE（Worker 已完成）
                should_end_sse = state_values.get("should_end_sse", False)
                
                if should_end_sse:
                    logger.info("[GraphRunner] Worker 已完成，标记 should_end_sse=True，不进入监控模式")
                    # Worker 已完成，直接发送完成消息
                    worker_result = state_values.get("worker_result", {})
                    video_url = worker_result.get("video_url", "")
                    if video_url:
                        yield formatter._format_sse({
                            "event": "message.delta",
                            "data": {
                                "id": message_id,
                                "content": f"\n\n🎬 视频生成完成！\n\n视频地址：{video_url}\n",
                                "node": "vocab_worker",
                            },
                        })
                else:
                    # 检查是否有任务在运行，如果有则继续监控
                    task_id = state_values.get("task_id")
                    creation_id = state_values.get("creation_id")
                    
                    if task_id or creation_id:
                        logger.info(f"[GraphRunner] 检测到任务运行中: task_id={task_id}, creation_id={creation_id}")
                        # 进入任务监控模式
                        async for task_event in self._monitor_task(task_id, creation_id, formatter, message_id):
                            yield task_event
                
        except Exception as e:
            logger.error(f"[GraphRunner] Graph 执行错误: {e}")
            
            # 发送错误消息
            error_msg = f"执行过程中出现错误：{str(e)}"
            yield formatter._format_sse({
                "event": "message.delta",
                "data": {
                    "id": message_id,
                    "content": error_msg,
                    "node": "error",
                },
            })
            
            yield formatter._format_sse({
                "event": "message.end",
                "data": {
                    "id": message_id,
                    "finish_reason": "error",
                },
            })
            
            # 保存错误检查点
            await self.persistence.save_checkpoint(
                {"error": str(e), "node": current_node},
                checkpoint_type="error",
            )

    async def get_status(self) -> Dict[str, Any]:
        """获取当前状态摘要"""
        last_state = await self.persistence.load_checkpoint()
        messages = await self.message_history.get_recent(5)
        
        return {
            "creation_uuid": self.creation_uuid,
            "thread_id": self.thread_id,
            "current_stage": last_state.get("current_stage", "init") if last_state else "init",
            "pending_approval": last_state.get("pending_approval", False) if last_state else False,
            "message_count": len(messages),
            "last_updated": last_state.get("updated_at") if last_state else None,
        }
