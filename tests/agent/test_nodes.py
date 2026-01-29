"""
Agent 节点单元测试
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestEntryNode:
    """入口节点测试"""
    
    @pytest.mark.asyncio
    async def test_entry_node_basic_message(self):
        """测试基本消息处理"""
        from app.agent.graph.nodes.entry import entry_node
        
        state = {
            "user_message": "帮我生成角色图片",
            "messages": [],
        }
        
        result = await entry_node(state)
        
        assert "messages" in result
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "帮我生成角色图片"
        assert "updated_at" in result
    
    @pytest.mark.asyncio
    async def test_entry_node_with_action(self):
        """测试带 action 的消息处理"""
        from app.agent.graph.nodes.entry import entry_node
        
        state = {
            "user_message": "确认",
            "user_action": "approve",
            "user_action_data": {"target_id": 1},
            "messages": [],
        }
        
        result = await entry_node(state)
        
        assert result["messages"][0]["action"] == "approve"
        assert result["pending_action"] == "approve"
    
    @pytest.mark.asyncio
    async def test_entry_node_append_to_history(self):
        """测试追加到历史记录"""
        from app.agent.graph.nodes.entry import entry_node
        
        state = {
            "user_message": "新消息",
            "messages": [
                {"role": "user", "content": "旧消息"}
            ],
        }
        
        result = await entry_node(state)
        
        assert len(result["messages"]) == 2
        assert result["messages"][0]["content"] == "旧消息"
        assert result["messages"][1]["content"] == "新消息"


class TestRouterNode:
    """路由节点测试"""
    
    def test_router_status_query(self):
        """测试状态查询路由"""
        from app.agent.graph.nodes.router import router_node
        
        state = {
            "intent_category": "status_query",
            "detected_intent": "overall_status",
            "intent_confidence": 0.9,
        }
        
        result = router_node(state)
        assert result == "status_query"
    
    def test_router_task_intent_high_confidence(self):
        """测试高置信度任务意图路由"""
        from app.agent.graph.nodes.router import router_node
        
        state = {
            "intent_category": "task_intent",
            "detected_intent": "generate_character_images",
            "intent_confidence": 0.95,
        }
        
        result = router_node(state)
        assert result == "task_execution"
    
    def test_router_task_intent_low_confidence(self):
        """测试低置信度任务意图路由"""
        from app.agent.graph.nodes.router import router_node
        
        state = {
            "intent_category": "task_intent",
            "detected_intent": "generate_character_images",
            "intent_confidence": 0.6,
        }
        
        result = router_node(state)
        assert result == "clarify"
    
    def test_router_asset_action(self):
        """测试资产操作路由"""
        from app.agent.graph.nodes.router import router_node
        
        state = {
            "intent_category": "asset_action",
            "detected_intent": "modify_prompt",
            "intent_confidence": 0.9,
        }
        
        result = router_node(state)
        assert result == "task_execution"
    
    def test_router_confirm_action(self):
        """测试确认操作路由"""
        from app.agent.graph.nodes.router import router_node
        
        state = {
            "intent_category": "confirm",
            "detected_intent": "confirm",
            "intent_confidence": 1.0,
        }
        
        result = router_node(state)
        assert result == "task_execution"
    
    def test_router_unknown_intent(self):
        """测试未知意图路由"""
        from app.agent.graph.nodes.router import router_node
        
        state = {
            "intent_category": "other",
            "detected_intent": "unknown",
            "intent_confidence": 0.3,
        }
        
        result = router_node(state)
        assert result == "clarify"
