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
            
            # 2. 尝试加载上一个检查点
            last_state = await self.persistence.load_checkpoint()
            
            # 3. 构建初始状态
            initial_state = self._build_initial_state(
                user_message=user_message,
                user_action=user_action,
                user_action_data=user_action_data,
                history_messages=history_messages,
                last_state=last_state,
            )
            
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
        """构建初始状态"""
        state = {
            "creation_uuid": self.creation_uuid,
            "thread_id": self.thread_id,
            "user_id": self.user_id,
            "user_message": user_message,
            "messages": history_messages,
            "updated_at": datetime.now().isoformat(),
        }
        
        # 如果有上一个检查点状态，恢复部分字段
        if last_state:
            state["current_stage"] = last_state.get("current_stage", "init")
            state["pending_approval"] = last_state.get("pending_approval", False)
        
        # 如果有用户操作
        if user_action:
            state["user_action"] = user_action
            state["user_action_data"] = user_action_data or {}
        
        return state
    
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
            
            # 用户可见节点（会流式输出 LLM tokens）
            # - clarify: 澄清对话
            # - task_execution: 任务执行（保持 SSE 连接活跃）
            # - human_review: 人机交互确认请求
            # - supervisor: 重新生成等操作需要展示给用户
            # 注意：status_query 改为 ReAct Agent 后，不应流式输出中间思考过程
            # 注意：asset_generation 不在此列表，因为它的 LLM 输出是内部提示词，不应显示给用户
            USER_VISIBLE_NODES = {"clarify", "task_execution", "human_review", "supervisor"}
            
            # 不应发送 response_text 的节点（分析/内部过程）
            INTERNAL_NODES = {"storyboard_generation", "audio_processing", "video_generation", "editing", "entry", "intent_detection", "router", "response_formatter", "stage_complete"}
            
            # 需要发送开始消息的节点（用户可见的阶段）
            START_MESSAGE_NODES = {
                "script_analysis": "📖 好的，正在分析剧本内容，识别角色和场景信息，请稍候...",
                "asset_generation": "🎨 好的，开始为您生成角色和场景图片，请稍候...",
                "storyboard_generation": "🎬 好的，正在生成分镜脚本，请稍候...",
                "audio_processing": "🎤 好的，正在处理音频内容，请稍候...",
                "video_generation": "🎥 好的，正在生成视频内容，请稍候...",
            }
            
            # 需要发送完成消息的节点（只有这些节点发送自动完成消息）
            # script_analysis 不在此列表，因为它的 response_text 已包含结果
            COMPLETE_MESSAGE_NODES = {
                "script_analysis": "✅ 剧本分析完成！",
                "asset_generation": "✅ 图片生成任务已提交！",
                "storyboard_generation": "✅ 分镜脚本生成完成！",
                "audio_processing": "✅ 音频处理完成！",
                "video_generation": "✅ 视频生成完成！",
            }
            
            # 需要发送 response_text 的节点
            # 只有外层包装节点发送，内部子图节点（如 script_analysis）不在此列表
            # storyboard_creation 需要发送完成消息到 SSE
            # supervisor: 重新生成等操作需要展示结果给用户
            RESPONSE_TEXT_NODES = {"human_review", "clarify", "status_query", "task_execution", "supervisor"}
            
            # 配置递归深度限制
            from app.core.config import settings
            recursion_limit = getattr(settings, 'LANGGRAPH_RECURSION_LIMIT', 15)
            config = {
                "configurable": {"thread_id": self.thread_id},
                "recursion_limit": recursion_limit,
            }
            
            # 使用 asyncio.Queue 来合并事件和心跳
            import time
            HEARTBEAT_INTERVAL = 5  # 每 5 秒发送一次心跳
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
                            
                            # 调试日志
                            if node_name in RESPONSE_TEXT_NODES and isinstance(output, dict) and "response_text" in output:
                                logger.info(f"[GraphRunner] on_chain_end: node={node_name}, has_response_text=True, already_sent={node_name in sent_response_nodes}")
                            
                            # 检查是否有错误
                            has_error = isinstance(output, dict) and output.get("errors")
                            
                            # 为特定阶段发送完成/错误消息（只发送一次）
                            # 只对 COMPLETE_MESSAGE_NODES 中的节点发送完成消息
                            if node_name in COMPLETE_MESSAGE_NODES and node_name not in sent_complete_nodes:
                                sent_complete_nodes.add(node_name)
                                
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
                                if node_name in RESPONSE_TEXT_NODES and node_name not in sent_response_nodes:
                                    resp_text = output["response_text"]
                                    if resp_text:
                                        sent_response_nodes.add(node_name)
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
            
            # 4. 保存助手消息
            if full_response:
                await self.message_history.append({
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": datetime.now().isoformat(),
                })
            
            # 5. 保存检查点
            final_state = runner.get_state(self.thread_id)
            if final_state:
                await self.persistence.save_checkpoint(
                    dict(final_state.values) if hasattr(final_state, 'values') else {},
                    checkpoint_type="auto",
                )
                
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
