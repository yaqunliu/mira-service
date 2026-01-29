"""
Generation Tools 单元测试

测试图片/视频/音频生成 Tools
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGenerationToolsSchema:
    """测试 Generation Tools 输入模式"""

    @pytest.mark.asyncio
    async def test_generate_character_image_schema(self):
        """测试角色图片生成 Tool 模式"""
        from app.agent.tools.agent_generation_tools import generate_character_image
        
        assert hasattr(generate_character_image, 'ainvoke')
        
        schema = generate_character_image.args_schema
        fields = schema.model_fields
        assert 'character_id' in fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_generate_scene_image_schema(self):
        """测试场景图片生成 Tool 模式"""
        from app.agent.tools.agent_generation_tools import generate_scene_image
        
        assert hasattr(generate_scene_image, 'ainvoke')
        
        schema = generate_scene_image.args_schema
        fields = schema.model_fields
        assert 'scene_id' in fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_generate_shot_image_schema(self):
        """测试分镜图片生成 Tool 模式"""
        from app.agent.tools.agent_generation_tools import generate_shot_image
        
        assert hasattr(generate_shot_image, 'ainvoke')
        
        schema = generate_shot_image.args_schema
        fields = schema.model_fields
        assert 'shot_id' in fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_generate_video_schema(self):
        """测试视频生成 Tool 模式"""
        from app.agent.tools.agent_generation_tools import generate_video
        
        assert hasattr(generate_video, 'ainvoke')
        
        schema = generate_video.args_schema
        fields = schema.model_fields
        assert 'shot_id' in fields
        assert 'creation_uuid' in fields

    @pytest.mark.asyncio
    async def test_generate_audio_schema(self):
        """测试音频生成 Tool 模式"""
        from app.agent.tools.agent_generation_tools import generate_audio
        
        assert hasattr(generate_audio, 'ainvoke')
        
        schema = generate_audio.args_schema
        fields = schema.model_fields
        assert 'shot_id' in fields
        assert 'creation_uuid' in fields


class TestGenerationToolsExport:
    """测试 Generation Tools 导出"""

    def test_all_tools_exported(self):
        """验证所有 Tools 正确导出"""
        from app.agent.tools.agent_generation_tools import GENERATION_TOOLS
        
        assert len(GENERATION_TOOLS) >= 5
        
        tool_names = [tool.name for tool in GENERATION_TOOLS]
        assert 'generate_character_image' in tool_names
        assert 'generate_scene_image' in tool_names
        assert 'generate_shot_image' in tool_names
        assert 'generate_video' in tool_names
        assert 'generate_audio' in tool_names


class TestGenerationToolsDescription:
    """测试 Generation Tools 描述"""

    def test_all_tools_have_descriptions(self):
        """验证所有 Tools 都有描述"""
        from app.agent.tools.agent_generation_tools import GENERATION_TOOLS
        
        for tool in GENERATION_TOOLS:
            assert tool.description, f"Tool {tool.name} 缺少描述"
            assert len(tool.description) > 20, f"Tool {tool.name} 描述过短"
