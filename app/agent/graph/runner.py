"""
Graph Runner 模块

封装 LangGraph 的执行逻辑，提供统一的入口
"""

from typing import Dict, Any, Optional, AsyncIterator
from datetime import datetime

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
            
            # 只有这些节点的 LLM 输出需要流式发送给用户
            USER_VISIBLE_NODES = {"clarify", "status_query", "task_execution"}
            
            config = {"configurable": {"thread_id": self.thread_id}}
            
            async for event in runner.graph.astream_events(initial_state, config, version="v2"):
                event_kind = event.get("event", "")
                
                # 节点开始事件 - 追踪当前节点
                if event_kind == "on_chain_start":
                    node_name = event.get("name", "")
                    if node_name and node_name != last_node_reported and not node_name.startswith("_"):
                        last_node_reported = node_name
                        # 记录当前处理的节点（用于过滤 LLM 输出）
                        if node_name in USER_VISIBLE_NODES:
                            streaming_node = node_name
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
                        # 如果节点输出有 response_text 且之前没流式输出，补充发送
                        output = event.get("data", {}).get("output", {})
                        if isinstance(output, dict) and "response_text" in output:
                            resp_text = output["response_text"]
                            if resp_text and not full_response:
                                # 没有流式输出过，一次性发送
                                yield formatter._format_sse({
                                    "event": "message.delta",
                                    "data": {
                                        "id": message_id,
                                        "content": resp_text,
                                        "node": node_name,
                                    },
                                })
                                full_response = resp_text
            
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
    
    async def _generate_simple_response(
        self,
        user_message: str,
        state: Dict[str, Any],
    ) -> str:
        """
        生成简单响应（用于初始集成测试）
        
        TODO: 替换为完整的 Graph 执行流程
        """
        # 简单的关键词匹配响应
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ["进度", "状态", "怎么样"]):
            return "📊 正在查询创作进度...\n\n当前阶段：初始化\n整体进度：待开始\n\n如需了解详情，请告诉我您想查看哪个部分。"
        
        elif any(word in message_lower for word in ["生成", "创建", "开始"]):
            return "🎨 收到！我将为您执行生成任务。\n\n请确认您要生成的内容，我会为您处理。"
        
        elif any(word in message_lower for word in ["修改", "改一下", "调整"]):
            return "✏️ 好的，请告诉我您想修改的具体内容和目标。"
        
        elif any(word in message_lower for word in ["帮助", "怎么用", "功能"]):
            return """🤖 我是漫剧创作助手，可以帮您：

1. **查询进度** - 了解当前创作状态
2. **生成资产** - 包括角色图、场景图、分镜
3. **修改内容** - 调整提示词、重新生成
4. **一键创作** - 自动完成整个流程

请告诉我您需要什么帮助？"""
        
        else:
            return f"收到您的消息：「{user_message[:50]}...」\n\n请问您是想查询进度、生成内容，还是有其他需求呢？"
    
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
