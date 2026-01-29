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
            # 2. 流式执行 Graph
            full_response = ""
            current_node = ""
            
            async for event in runner.stream(initial_state, self.thread_id):
                # event 格式: {node_name: {state_updates}}
                for node_name, updates in event.items():
                    current_node = node_name
                    
                    # 发送节点进度
                    yield formatter._format_sse({
                        "event": "progress",
                        "data": {
                            "node": node_name,
                            "status": "processing",
                        },
                    })
                    
                    # 如果有响应文本，流式发送
                    if "response_text" in updates:
                        content = updates["response_text"]
                        if content and content != full_response:
                            # 发送增量内容
                            delta = content[len(full_response):]
                            if delta:
                                yield formatter._format_sse({
                                    "event": "message.delta",
                                    "data": {
                                        "id": message_id,
                                        "content": delta,
                                        "node": node_name,
                                    },
                                })
                                full_response = content
                    
                    # 如果有看板操作
                    if "board_actions" in updates:
                        for action in updates.get("board_actions", []):
                            yield formatter._format_sse({
                                "event": "board.action",
                                "data": action,
                            })
            
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
