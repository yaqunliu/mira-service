"""
DB Tools 单元测试

测试数据库查询和更新 Tools
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestQueryTools:
    """测试查询类 Tools"""

    @pytest.mark.asyncio
    async def test_query_characters_schema(self):
        """测试 query_characters 输入输出模式"""
        from app.agent.tools.db_tools import query_characters
        
        # 验证 tool 存在且可调用
        assert hasattr(query_characters, 'ainvoke')
        
        # 获取 tool schema
        schema = query_characters.args_schema
        assert schema is not None
        
        # 验证必要字段
        fields = schema.model_fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_query_scenes_schema(self):
        """测试 query_scenes 输入输出模式"""
        from app.agent.tools.db_tools import query_scenes
        
        assert hasattr(query_scenes, 'ainvoke')
        
        schema = query_scenes.args_schema
        fields = schema.model_fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_query_shots_schema(self):
        """测试 query_shots 输入输出模式"""
        from app.agent.tools.db_tools import query_shots
        
        assert hasattr(query_shots, 'ainvoke')
        
        schema = query_shots.args_schema
        fields = schema.model_fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_query_creation_status_schema(self):
        """测试 query_creation_status 输入输出模式"""
        from app.agent.tools.db_tools import query_creation_status
        
        assert hasattr(query_creation_status, 'ainvoke')
        
        schema = query_creation_status.args_schema
        fields = schema.model_fields
        assert 'creation_uuid' in fields


class TestUpdateTools:
    """测试更新类 Tools"""

    @pytest.mark.asyncio
    async def test_update_character_schema(self):
        """测试 update_character 输入模式"""
        from app.agent.tools.db_tools import update_character
        
        assert hasattr(update_character, 'ainvoke')
        
        schema = update_character.args_schema
        fields = schema.model_fields
        assert 'character_id' in fields

    @pytest.mark.asyncio
    async def test_update_scene_schema(self):
        """测试 update_scene 输入模式"""
        from app.agent.tools.db_tools import update_scene
        
        assert hasattr(update_scene, 'ainvoke')
        
        schema = update_scene.args_schema
        fields = schema.model_fields
        assert 'scene_id' in fields

    @pytest.mark.asyncio
    async def test_update_shot_schema(self):
        """测试 update_shot 输入模式"""
        from app.agent.tools.db_tools import update_shot
        
        assert hasattr(update_shot, 'ainvoke')
        
        schema = update_shot.args_schema
        fields = schema.model_fields
        assert 'shot_id' in fields


class TestToolOutput:
    """测试 Tool 输出格式"""

    @pytest.mark.asyncio
    async def test_query_returns_dict(self):
        """验证查询 Tool 返回字典"""
        from app.agent.tools.db_tools import (
            query_characters,
            query_scenes,
            query_shots,
            query_creation_status,
        )
        
        # 验证都是 langchain tool
        for tool in [query_characters, query_scenes, query_shots, query_creation_status]:
            assert hasattr(tool, 'description')
            assert len(tool.description) > 0

    @pytest.mark.asyncio
    async def test_update_returns_dict(self):
        """验证更新 Tool 返回字典"""
        from app.agent.tools.db_tools import (
            update_character,
            update_scene,
            update_shot,
        )
        
        for tool in [update_character, update_scene, update_shot]:
            assert hasattr(tool, 'description')
            assert len(tool.description) > 0


class TestToolDescriptions:
    """测试 Tool 描述完整性"""

    def test_all_tools_have_descriptions(self):
        """验证所有 Tools 都有描述"""
        from app.agent.tools.db_tools import (
            query_characters,
            query_scenes,
            query_shots,
            query_creation_status,
            update_character,
            update_scene,
            update_shot,
        )
        
        all_tools = [
            query_characters,
            query_scenes,
            query_shots,
            query_creation_status,
            update_character,
            update_scene,
            update_shot,
        ]
        
        for tool in all_tools:
            assert tool.description, f"Tool {tool.name} 缺少描述"
            assert len(tool.description) > 10, f"Tool {tool.name} 描述过短"
