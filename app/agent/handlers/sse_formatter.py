"""
SSE 格式化处理器

将 LangGraph 输出转换为 SSE 事件流
"""

import json
import asyncio
from typing import Dict, Any, AsyncIterator, Optional, List
from datetime import datetime

from app.core.logger import logger


class SSEFormatter:
    """SSE 格式化器"""
    
    def __init__(self):
        self.message_buffer: List[Dict[str, Any]] = []
        self.batch_size = 10  # 批量持久化阈值
        
    async def langgraph_to_sse(
        self,
        graph_stream: AsyncIterator,
        creation_uuid: str,
        thread_id: str,
    ) -> AsyncIterator[str]:
        """
        将 LangGraph 流输出转换为 SSE 事件
        
        Args:
            graph_stream: LangGraph stream_mode="messages" 的输出
            creation_uuid: 创作项目 UUID
            thread_id: 对话线程 ID
            
        Yields:
            SSE 格式的字符串
        """
        try:
            async for event in graph_stream:
                sse_events = self._convert_event(event)
                
                for sse_event in sse_events:
                    # 添加到缓冲区
                    self.message_buffer.append(sse_event)
                    
                    # 批量持久化
                    if len(self.message_buffer) >= self.batch_size:
                        await self._persist_batch(creation_uuid, thread_id)
                    
                    # 生成 SSE 字符串
                    yield self._format_sse(sse_event)
            
            # 持久化剩余消息
            if self.message_buffer:
                await self._persist_batch(creation_uuid, thread_id)
            
            # 发送结束事件
            yield self._format_sse({"event": "done", "data": {}})
            
        except Exception as e:
            logger.error(f"[SSE] 转换错误: {e}")
            yield self._format_sse({
                "event": "error",
                "data": {
                    "error": str(e),
                    "code": "STREAM_ERROR",
                    "recoverable": False,
                }
            })
    
    def _convert_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """转换单个 LangGraph 事件"""
        sse_events = []
        
        # 获取事件类型和数据
        event_type = event.get("type", "")
        data = event.get("data", {})
        node = event.get("node", "")
        
        if event_type == "message":
            # 消息事件
            content = data.get("content", "")
            message_id = data.get("id", str(id(event)))
            
            if data.get("is_start"):
                sse_events.append({
                    "event": "message.start",
                    "data": {"id": message_id},
                })
            
            if content:
                sse_events.append({
                    "event": "message.delta",
                    "data": {
                        "id": message_id,
                        "content": content,
                        "node": node,
                    },
                })
            
            if data.get("is_end"):
                sse_events.append({
                    "event": "message.end",
                    "data": {
                        "id": message_id,
                        "finish_reason": data.get("finish_reason", "stop"),
                    },
                })
                
        elif event_type == "tool_call":
            # 工具调用事件
            tool_id = data.get("id", "")
            tool_name = data.get("name", "")
            status = data.get("status", "")
            
            if status == "start":
                sse_events.append({
                    "event": "tool.start",
                    "data": {
                        "id": tool_id,
                        "tool_name": tool_name,
                        "arguments": data.get("arguments", {}),
                    },
                })
            elif status == "progress":
                sse_events.append({
                    "event": "tool.progress",
                    "data": {
                        "id": tool_id,
                        "status": "processing",
                        "progress": data.get("progress", 0),
                    },
                })
            elif status == "end":
                sse_events.append({
                    "event": "tool.end",
                    "data": {
                        "id": tool_id,
                        "status": "completed" if data.get("success") else "failed",
                        "result_summary": data.get("result_summary", ""),
                    },
                })
                
        elif event_type == "thinking":
            # 思考事件
            thinking_id = data.get("id", str(id(event)))
            content = data.get("content", "")
            
            sse_events.append({
                "event": "thinking.delta",
                "data": {
                    "id": thinking_id,
                    "content": content,
                    "node": node,
                },
            })
            
        elif event_type == "board_action":
            # 看板操作
            sse_events.append({
                "event": "board.action",
                "data": data,
            })
            
        elif event_type == "progress":
            # 进度更新
            sse_events.append({
                "event": "progress",
                "data": data,
            })
        
        return sse_events
    
    def _format_sse(self, event: Dict[str, Any]) -> str:
        """格式化为 SSE 字符串"""
        event_type = event.get("event", "message")
        data = event.get("data", {})
        
        return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    
    async def _persist_batch(self, creation_uuid: str, thread_id: str):
        """批量持久化消息"""
        if not self.message_buffer:
            return
        
        try:
            # 提取需要持久化的消息
            messages_to_persist = [
                e for e in self.message_buffer
                if e.get("event") in ["message.delta", "thinking.delta"]
            ]
            
            if messages_to_persist:
                # 这里应该调用实际的持久化服务
                # await message_service.batch_save(creation_uuid, thread_id, messages_to_persist)
                logger.debug(f"[SSE] 持久化 {len(messages_to_persist)} 条消息")
            
            self.message_buffer.clear()
            
        except Exception as e:
            logger.error(f"[SSE] 持久化失败: {e}")
            # 不抛出异常，避免中断流


async def stream_graph_output(
    graph,
    initial_state: Dict[str, Any],
    thread_id: str,
    creation_uuid: str,
) -> AsyncIterator[str]:
    """
    流式输出 Graph 执行结果
    
    Args:
        graph: ComicDramaGraph 实例
        initial_state: 初始状态
        thread_id: 对话线程 ID
        creation_uuid: 创作项目 UUID
        
    Yields:
        SSE 格式的字符串
    """
    formatter = SSEFormatter()
    
    try:
        # 使用 stream_mode="messages" 获取流式输出
        graph_stream = graph.astream(
            initial_state,
            config={"configurable": {"thread_id": thread_id}},
        )
        
        async for sse_string in formatter.langgraph_to_sse(
            graph_stream,
            creation_uuid,
            thread_id,
        ):
            yield sse_string
            
    except Exception as e:
        logger.error(f"[SSE] 流式输出错误: {e}")
        yield formatter._format_sse({
            "event": "error",
            "data": {
                "error": str(e),
                "code": "GRAPH_ERROR",
                "recoverable": False,
            }
        })
        yield formatter._format_sse({"event": "done", "data": {}})
