"""
Knowledge Tools 单元测试

测试 RAG 知识库查询 Tools
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestKnowledgeToolsSchema:
    """测试 Knowledge Tools 输入模式"""

    @pytest.mark.asyncio
    async def test_query_knowledge_base_schema(self):
        """测试知识库查询 Tool 模式"""
        from app.agent.tools.knowledge_tools import query_knowledge_base
        
        assert hasattr(query_knowledge_base, 'ainvoke')
        
        schema = query_knowledge_base.args_schema
        fields = schema.model_fields
        assert 'query' in fields
        assert 'knowledge_type' in fields

    @pytest.mark.asyncio
    async def test_prompt_enhancement_schema(self):
        """测试提示词增强 Tool 模式"""
        from app.agent.tools.knowledge_tools import get_prompt_enhancement_suggestions
        
        assert hasattr(get_prompt_enhancement_suggestions, 'ainvoke')
        
        schema = get_prompt_enhancement_suggestions.args_schema
        fields = schema.model_fields
        assert 'original_prompt' in fields

    @pytest.mark.asyncio
    async def test_camera_angle_schema(self):
        """测试镜头角度建议 Tool 模式"""
        from app.agent.tools.knowledge_tools import get_camera_angle_suggestions
        
        assert hasattr(get_camera_angle_suggestions, 'ainvoke')
        
        schema = get_camera_angle_suggestions.args_schema
        fields = schema.model_fields
        assert 'scene_description' in fields


class TestKnowledgeBaseTypes:
    """测试知识库类型配置"""

    def test_knowledge_base_types_defined(self):
        """验证知识库类型定义完整"""
        from app.agent.tools.knowledge_tools import KNOWLEDGE_BASE_TYPES
        
        expected_types = [
            'prompt_examples',
            'prompt_techniques',
            'storyboard_techniques',
            'camera_angles',
            'composition_rules',
        ]
        
        for kb_type in expected_types:
            assert kb_type in KNOWLEDGE_BASE_TYPES, f"缺少知识库类型: {kb_type}"

    def test_knowledge_base_types_have_descriptions(self):
        """验证知识库类型都有描述"""
        from app.agent.tools.knowledge_tools import KNOWLEDGE_BASE_TYPES
        
        for kb_type, description in KNOWLEDGE_BASE_TYPES.items():
            assert description, f"知识库类型 {kb_type} 缺少描述"
            assert len(description) > 5, f"知识库类型 {kb_type} 描述过短"


class TestMockKnowledge:
    """测试模拟知识库数据"""

    @pytest.mark.asyncio
    async def test_mock_knowledge_returns_data(self):
        """验证模拟知识库能返回数据"""
        from app.agent.tools.knowledge_tools import query_knowledge_base
        
        # 调用查询（会使用模拟数据）
        result = await query_knowledge_base.ainvoke({
            'query': 'character design',
            'knowledge_type': 'prompt_examples',
            'top_k': 3,
        })
        
        assert result['status'] == 'success'
        assert 'results' in result
        assert isinstance(result['results'], list)


class TestKnowledgeToolsExport:
    """测试 Knowledge Tools 导出"""

    def test_all_tools_exported(self):
        """验证所有 Tools 正确导出"""
        from app.agent.tools.knowledge_tools import KNOWLEDGE_TOOLS
        
        assert len(KNOWLEDGE_TOOLS) >= 3
        
        tool_names = [tool.name for tool in KNOWLEDGE_TOOLS]
        assert 'query_knowledge_base' in tool_names
        assert 'get_prompt_enhancement_suggestions' in tool_names
        assert 'get_camera_angle_suggestions' in tool_names
