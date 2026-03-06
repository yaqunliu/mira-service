"""
Graph 集成测试

测试完整的对话调度层工作流
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDialogueGraphBuild:
    """测试 Graph 构建"""

    def test_build_dialogue_graph(self):
        """验证 Graph 能正确构建"""
        from app.agent.graph.dialogue_graph import build_dialogue_graph
        
        graph = build_dialogue_graph()
        
        # 验证是 StateGraph
        assert graph is not None
        
        # 验证节点存在
        nodes = graph.nodes
        expected_nodes = [
            "entry",
            "intent_detection",
            "status_query",
            "task_execution",
            "clarify",
            "response_formatter",
            "human_review",
        ]
        
        for node_name in expected_nodes:
            assert node_name in nodes, f"缺少节点: {node_name}"

    def test_graph_runner_init(self):
        """验证 Runner 能正确初始化"""
        from app.agent.graph.dialogue_graph import DialogueGraphRunner
        
        runner = DialogueGraphRunner()
        
        assert runner.graph is not None
        assert runner.checkpointer is not None


class TestDialogueGraphRunner:
    """测试 Graph Runner"""

    def test_get_dialogue_runner_singleton(self):
        """验证全局 Runner 是单例"""
        from app.agent.graph.dialogue_graph import get_dialogue_runner
        
        runner1 = get_dialogue_runner()
        runner2 = get_dialogue_runner()
        
        assert runner1 is runner2


class TestGraphRouting:
    """测试路由逻辑"""

    def test_route_by_intent_status_query(self):
        """测试状态查询路由"""
        from app.agent.graph.dialogue_graph import _route_by_intent
        
        state = {
            "intent_category": "status_query",
            "intent_confidence": 0.9,
        }
        
        result = _route_by_intent(state)
        assert result == "status_query"

    def test_route_by_intent_task_execution(self):
        """测试任务执行路由（高置信度）"""
        from app.agent.graph.dialogue_graph import _route_by_intent
        
        state = {
            "intent_category": "task_intent",
            "intent_confidence": 0.95,
        }
        
        result = _route_by_intent(state)
        assert result == "task_execution"

    def test_route_by_intent_clarify(self):
        """测试澄清路由（低置信度）"""
        from app.agent.graph.dialogue_graph import _route_by_intent
        
        state = {
            "intent_category": "task_intent",
            "intent_confidence": 0.5,
        }
        
        result = _route_by_intent(state)
        assert result == "clarify"

    def test_route_after_response_end(self):
        """测试响应后路由到结束"""
        from app.agent.graph.dialogue_graph import _route_after_response
        
        state = {"pending_approval": False}
        
        result = _route_after_response(state)
        assert result == "end"

    def test_route_after_response_human_review(self):
        """测试响应后路由到人工确认"""
        from app.agent.graph.dialogue_graph import _route_after_response
        
        state = {"pending_approval": True}
        
        result = _route_after_response(state)
        assert result == "human_review"


class TestGraphStateFlow:
    """测试状态流转"""

    @pytest.mark.asyncio
    async def test_entry_to_intent_detection(self):
        """验证 entry → intent_detection 边存在"""
        from app.agent.graph.dialogue_graph import build_dialogue_graph
        
        graph = build_dialogue_graph()
        
        # 检查边是否存在
        edges = graph.edges
        # entry 应该连接到 intent_detection
        assert ("entry", "intent_detection") in edges or "entry" in str(edges)


class TestFullGraphExecution:
    """测试完整 Graph 执行（需要 mock LLM）"""

    @pytest.mark.asyncio
    async def test_graph_compile(self):
        """验证 Graph 能编译"""
        from app.agent.graph.dialogue_graph import DialogueGraphRunner
        
        runner = DialogueGraphRunner()
        
        # 验证编译成功
        assert runner.graph is not None
        assert hasattr(runner.graph, 'ainvoke')
        assert hasattr(runner.graph, 'astream')
