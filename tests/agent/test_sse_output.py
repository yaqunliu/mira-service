"""
SSE 格式化器单元测试

测试 LangGraph 到 SSE 的转换功能
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


class TestSSEFormatter:
    """测试 SSE 格式化器"""

    def test_format_sse_message(self):
        """测试 SSE 消息格式化"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        event = {
            "event": "message.delta",
            "data": {"id": "123", "content": "Hello"},
        }
        
        result = formatter._format_sse(event)
        
        assert "event: message.delta" in result
        assert "data:" in result
        assert "Hello" in result
        assert result.endswith("\n\n")

    def test_format_sse_with_chinese(self):
        """测试中文内容格式化"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        event = {
            "event": "message.delta",
            "data": {"id": "123", "content": "你好世界"},
        }
        
        result = formatter._format_sse(event)
        
        assert "你好世界" in result


class TestEventConversion:
    """测试事件转换"""

    def test_convert_message_event(self):
        """测试消息事件转换"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        event = {
            "type": "message",
            "data": {
                "id": "msg_123",
                "content": "test content",
                "is_start": True,
            },
            "node": "status_query",
        }
        
        sse_events = formatter._convert_event(event)
        
        assert len(sse_events) >= 1
        event_types = [e["event"] for e in sse_events]
        assert "message.start" in event_types

    def test_convert_tool_call_event(self):
        """测试工具调用事件转换"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        event = {
            "type": "tool_call",
            "data": {
                "id": "tool_123",
                "name": "generate_image",
                "status": "start",
            },
        }
        
        sse_events = formatter._convert_event(event)
        
        assert len(sse_events) >= 1
        assert sse_events[0]["event"] == "tool.start"

    def test_convert_progress_event(self):
        """测试进度事件转换"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        event = {
            "type": "progress",
            "data": {
                "stage": "generating",
                "current": 5,
                "total": 10,
            },
        }
        
        sse_events = formatter._convert_event(event)
        
        assert len(sse_events) == 1
        assert sse_events[0]["event"] == "progress"


class TestBatchPersistence:
    """测试批量持久化"""

    def test_batch_size_config(self):
        """测试批量大小配置"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        assert formatter.batch_size == 10

    def test_message_buffer_append(self):
        """测试消息缓冲区添加"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        event = {"event": "message.delta", "data": {"content": "test"}}
        formatter.message_buffer.append(event)
        
        assert len(formatter.message_buffer) == 1
        formatter.message_buffer.clear()
        assert len(formatter.message_buffer) == 0


class TestStreamFunction:
    """测试流式输出函数"""

    def test_stream_graph_output_exists(self):
        """验证流式输出函数存在"""
        from app.agent.handlers.sse_formatter import stream_graph_output
        
        assert callable(stream_graph_output)


class TestDoneEvent:
    """测试结束事件"""

    def test_build_done_event(self):
        """测试构建结束事件"""
        from app.agent.handlers.sse_formatter import SSEFormatter
        
        formatter = SSEFormatter()
        
        done_event = {"event": "done", "data": {}}
        result = formatter._format_sse(done_event)
        
        assert "event: done" in result
