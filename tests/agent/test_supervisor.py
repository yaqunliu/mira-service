"""
Supervisor 架构测试

测试 Supervisor Node 和相关工具
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime


# ==================== 工具测试 ====================

class TestRegenerateTools:
    """regenerate_tools 测试"""
    
    @pytest.mark.asyncio
    async def test_clear_asset_character(self):
        """测试清空角色图片"""
        from app.agent.tools.regenerate_tools import clear_asset
        
        with patch('app.agent.tools.regenerate_tools.get_async_session') as mock_session:
            # Mock 数据库会话
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            
            # Mock 角色查询结果
            mock_character = MagicMock()
            mock_character.character_id = 1
            mock_character.image_url = "https://example.com/old.jpg"
            mock_character.status_details = {}
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_character
            mock_db.execute.return_value = mock_result
            
            result = await clear_asset.ainvoke({
                "target_type": "character",
                "target_id": 1,
                "save_version": True,
            })
            
            assert result["success"] == True
            assert result["target_type"] == "character"
    
    @pytest.mark.asyncio
    async def test_clear_asset_invalid_type(self):
        """测试无效的资源类型"""
        from app.agent.tools.regenerate_tools import clear_asset
        
        result = await clear_asset.ainvoke({
            "target_type": "invalid",
            "target_id": 1,
        })
        
        assert result["success"] == False
        assert "不支持" in result["error"]


class TestVersionTools:
    """version_tools 测试"""
    
    @pytest.mark.asyncio
    async def test_get_version_history(self):
        """测试获取版本历史"""
        from app.agent.tools.version_tools import get_version_history
        
        with patch('app.agent.tools.version_tools.get_async_session') as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            
            mock_character = MagicMock()
            mock_character.status_details = {
                "versions": [
                    {"version": 1, "field": "image_url", "value": "url1"},
                    {"version": 2, "field": "image_url", "value": "url2"},
                ]
            }
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_character
            mock_db.execute.return_value = mock_result
            
            result = await get_version_history.ainvoke({
                "target_type": "character",
                "target_id": 1,
            })
            
            assert result["success"] == True
            assert result["total_versions"] == 2
    
    @pytest.mark.asyncio
    async def test_get_version_history_not_found(self):
        """测试资源不存在"""
        from app.agent.tools.version_tools import get_version_history
        
        with patch('app.agent.tools.version_tools.get_async_session') as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result
            
            result = await get_version_history.ainvoke({
                "target_type": "character",
                "target_id": 999,
            })
            
            assert result["success"] == False
            assert "不存在" in result["error"]


class TestContextTools:
    """context_tools 测试"""
    
    @pytest.mark.asyncio
    async def test_check_constraints_allowed(self):
        """测试约束检查 - 允许操作"""
        from app.agent.tools.context_tools import check_constraints
        
        with patch('app.agent.tools.context_tools.get_async_session') as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            
            # Mock creation
            mock_creation = MagicMock()
            mock_creation.creation_id = 1
            
            # Mock scenes (no storyboard)
            mock_creation_result = MagicMock()
            mock_creation_result.scalar_one_or_none.return_value = mock_creation
            
            mock_scenes_result = MagicMock()
            mock_scenes_result.fetchall.return_value = []
            
            mock_db.execute.side_effect = [mock_creation_result, mock_scenes_result]
            
            result = await check_constraints.ainvoke({
                "creation_uuid": "test-uuid",
                "action": "modify",
                "target_type": "character",
            })
            
            assert result["allowed"] == True
    
    @pytest.mark.asyncio
    async def test_check_constraints_blocked(self):
        """测试约束检查 - 阻止操作（分镜已生成）"""
        from app.agent.tools.context_tools import check_constraints
        
        with patch('app.agent.tools.context_tools.get_async_session') as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__.return_value = mock_db
            
            # Mock creation
            mock_creation = MagicMock()
            mock_creation.creation_id = 1
            
            mock_creation_result = MagicMock()
            mock_creation_result.scalar_one_or_none.return_value = mock_creation
            
            # Mock scenes with IDs
            mock_scenes_result = MagicMock()
            mock_scenes_result.fetchall.return_value = [(1,), (2,)]
            
            # Mock shot count (has storyboard)
            mock_shot_count = MagicMock()
            mock_shot_count.scalar.return_value = 5
            
            mock_db.execute.side_effect = [mock_creation_result, mock_scenes_result, mock_shot_count]
            
            result = await check_constraints.ainvoke({
                "creation_uuid": "test-uuid",
                "action": "modify",
                "target_type": "character",
            })
            
            assert result["allowed"] == False
            assert "分镜已生成" in result["reason"]


# ==================== Supervisor Node 测试 ====================

class TestSupervisorNode:
    """Supervisor Node 测试"""
    
    @pytest.mark.asyncio
    async def test_supervisor_tools_available(self):
        """测试 Supervisor 工具可用"""
        from app.agent.graph.nodes.supervisor import _get_supervisor_tools
        
        tools = _get_supervisor_tools()
        
        tool_names = [t.name for t in tools]
        assert "query_production_status" in tool_names
        assert "check_constraints" in tool_names
        assert "route_to_worker" in tool_names
        assert "request_user_confirmation" in tool_names
    
    @pytest.mark.asyncio
    async def test_route_to_worker_valid(self):
        """测试 route_to_worker 有效 Worker"""
        from app.agent.graph.nodes.supervisor import route_to_worker
        
        result = await route_to_worker.ainvoke({
            "worker": "script_analyst",
            "task": "分析剧本",
        })
        
        assert result["success"] == True
        assert result["action"] == "route_to_worker"
        assert result["worker"] == "script_analyst"
    
    @pytest.mark.asyncio
    async def test_route_to_worker_invalid(self):
        """测试 route_to_worker 无效 Worker"""
        from app.agent.graph.nodes.supervisor import route_to_worker
        
        result = await route_to_worker.ainvoke({
            "worker": "invalid_worker",
            "task": "测试任务",
        })
        
        assert result["success"] == False
        assert "无效" in result["error"]
    
    @pytest.mark.asyncio
    async def test_request_user_confirmation(self):
        """测试请求用户确认"""
        from app.agent.graph.nodes.supervisor import request_user_confirmation
        
        result = await request_user_confirmation.ainvoke({
            "message": "是否继续？",
            "options": ["是", "否"],
        })
        
        assert result["success"] == True
        assert result["action"] == "request_confirmation"
        assert result["needs_input"] == True


# ==================== 路由测试 ====================

class TestSupervisorRouting:
    """Supervisor 路由测试"""
    
    def test_route_from_supervisor_to_worker(self):
        """测试路由到 Worker"""
        from app.agent.graph.nodes.supervisor import route_from_supervisor
        
        state = {
            "next_worker": "script_analyst",
            "needs_input": False,
        }
        
        result = route_from_supervisor(state)
        assert result == "script_analysis"
    
    def test_route_from_supervisor_needs_input(self):
        """测试需要用户输入时返回"""
        from app.agent.graph.nodes.supervisor import route_from_supervisor
        
        state = {
            "next_worker": "script_analyst",
            "needs_input": True,
        }
        
        result = route_from_supervisor(state)
        assert result == "return_to_main"
    
    def test_route_from_supervisor_no_worker(self):
        """测试无 Worker 时完成"""
        from app.agent.graph.nodes.supervisor import route_from_supervisor
        
        state = {
            "next_worker": None,
            "needs_input": False,
        }
        
        result = route_from_supervisor(state)
        assert result == "stage_complete"


# ==================== 子图构建测试 ====================

class TestSubgraphBuild:
    """子图构建测试"""
    
    def test_subgraph_build_legacy_mode(self):
        """测试 Legacy 模式构建"""
        with patch('app.agent.graph.comic_drama_subgraph.USE_SUPERVISOR_MODE', False):
            from importlib import reload
            import app.agent.graph.comic_drama_subgraph as subgraph_module
            reload(subgraph_module)
            
            subgraph = subgraph_module.build_comic_drama_subgraph()
            assert subgraph is not None
    
    def test_subgraph_build_supervisor_mode(self):
        """测试 Supervisor 模式构建"""
        with patch('app.agent.graph.comic_drama_subgraph.USE_SUPERVISOR_MODE', True):
            from importlib import reload
            import app.agent.graph.comic_drama_subgraph as subgraph_module
            reload(subgraph_module)
            
            subgraph = subgraph_module.build_comic_drama_subgraph()
            assert subgraph is not None
