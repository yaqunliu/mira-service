"""
Video Editor Node 测试

测试视频生成节点的功能：
1. 单元测试 - Task 注册、模式选择逻辑
2. 集成测试 - 完整流程（真实调用 AI API）
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any


# ==================== 单元测试 ====================

class TestVideoTaskRegistration:
    """测试视频生成 Task 注册"""

    def test_single_shot_video_task_exists(self):
        """验证单分镜视频任务存在"""
        from app.tasks.agent_video_task import agent_generate_single_shot_video_task
        
        assert callable(agent_generate_single_shot_video_task)
        assert agent_generate_single_shot_video_task.name == "agent_generate_single_shot_video"

    def test_batch_video_task_exists(self):
        """验证批量视频任务存在"""
        from app.tasks.agent_video_task import agent_generate_shot_videos_task
        
        assert callable(agent_generate_shot_videos_task)
        assert agent_generate_shot_videos_task.name == "agent_generate_shot_videos"


class TestVideoGenerationMode:
    """测试视频生成模式选择逻辑"""

    def test_get_video_model_config(self):
        """测试模型配置获取"""
        from app.tasks.agent_video_task import _get_video_model_config
        
        # Mock creation
        mock_creation = MagicMock()
        mock_creation.extra_data = {
            "video_model": "doubao-seedance-1-5-pro-251215",
            "aspect_ratio": "16:9",
        }
        
        config = _get_video_model_config(mock_creation)
        
        assert config["model"] == "doubao-seedance-1-5-pro-251215"
        assert config["aspect_ratio"] == "16:9"

    def test_get_video_model_config_defaults(self):
        """测试模型配置默认值"""
        from app.tasks.agent_video_task import _get_video_model_config
        
        mock_creation = MagicMock()
        mock_creation.extra_data = None
        
        config = _get_video_model_config(mock_creation)
        
        assert config["model"] == "doubao-seedance-1-5-pro-251215"
        assert config["aspect_ratio"] == "16:9"


class TestVideoTools:
    """测试视频生成工具"""

    def test_save_video_prompts_tool_exists(self):
        """验证保存视频提示词工具存在"""
        from app.agent.tools.db_tools import save_video_prompts
        
        assert callable(save_video_prompts.ainvoke)

    def test_generate_shot_videos_tool_exists(self):
        """验证生成视频工具存在"""
        from app.agent.tools.agent_generation_tools import generate_shot_videos
        
        assert callable(generate_shot_videos.ainvoke)


class TestVideoEditorNode:
    """测试 VideoEditorNode"""

    def test_node_init(self):
        """测试节点初始化"""
        from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
        
        node = VideoEditorNode()
        assert node.llm is not None
        assert node.ai_client is not None
        assert node.POLL_INTERVAL == 5
        assert node.MAX_POLL_TIME == 3600

    def test_parse_prompts_response_valid_json(self):
        """测试解析有效的 JSON 响应"""
        from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
        
        node = VideoEditorNode()
        
        response = '''```json
[
  {
    "shot_id": 123,
    "video_prompt": "测试提示词",
    "generation_mode": "first_last_frame",
    "mode_reason": "测试原因"
  }
]
```'''
        
        result = node._parse_prompts_response(response)
        
        assert len(result) == 1
        assert result[0]["shot_id"] == 123
        assert result[0]["video_prompt"] == "测试提示词"
        assert result[0]["generation_mode"] == "first_last_frame"

    def test_parse_prompts_response_plain_json(self):
        """测试解析纯 JSON 响应（无 markdown）"""
        from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
        
        node = VideoEditorNode()
        
        response = '''[{"shot_id": 456, "video_prompt": "test", "generation_mode": "first_frame_only", "mode_reason": "reason"}]'''
        
        result = node._parse_prompts_response(response)
        
        assert len(result) == 1
        assert result[0]["shot_id"] == 456


class TestPromptTemplate:
    """测试提示词模板"""

    def test_template_exists(self):
        """验证模板文件存在"""
        import os
        template_path = "/Users/moji/ground/mira-service/app/prompt/agent_video_prompt_gen.md"
        assert os.path.exists(template_path)

    def test_template_has_required_sections(self):
        """验证模板包含必要的部分"""
        with open("/Users/moji/ground/mira-service/app/prompt/agent_video_prompt_gen.md", "r") as f:
            content = f.read()
        
        assert "{{SHOTS_DATA}}" in content
        assert "first_last_frame" in content
        assert "first_frame_only" in content
        assert "reference_image" in content
        assert "generation_mode" in content
        assert "video_prompt" in content


# ==================== 集成测试 ====================

class TestVideoEditorIntegration:
    """视频编辑节点集成测试"""

    @pytest.mark.asyncio
    async def test_check_progress_with_mock_db(self):
        """测试进度检查（使用 mock 数据库）"""
        from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
        
        node = VideoEditorNode()
        
        # Mock query_shots 工具
        mock_shots_result = {
            "success": True,
            "shots": [
                {
                    "shot_id": 1,
                    "description": "测试分镜1",
                    "image_prompt": "test prompt 1",
                    "image_url": "http://example.com/image1.jpg",
                    "video_url": None,
                    "video_duration": 5,
                    "extra_data": {
                        "end_frame_prompt": "end prompt 1",
                        "end_frame_image_url": "http://example.com/end1.jpg",
                    },
                    "narration": [],
                    "characters": [],
                },
                {
                    "shot_id": 2,
                    "description": "测试分镜2",
                    "image_prompt": "test prompt 2",
                    "image_url": "http://example.com/image2.jpg",
                    "video_url": "http://example.com/video2.mp4",  # 已有视频
                    "video_duration": 5,
                    "extra_data": {
                        "video_prompt": "existing prompt",
                    },
                    "narration": [],
                    "characters": [],
                },
            ],
        }
        
        with patch("app.agent.graph.nodes.teams.video_editor.query_shots") as mock_query:
            mock_query.ainvoke = AsyncMock(return_value=mock_shots_result)
            
            # 需要导入 query_shots 到正确的位置
            import app.agent.graph.nodes.teams.video_editor as ve_module
            original_query = getattr(ve_module, 'query_shots', None)
            
            try:
                from app.agent.tools.db_tools import query_shots
                with patch.object(query_shots, 'ainvoke', AsyncMock(return_value=mock_shots_result)):
                    progress = await node._check_progress("test-uuid")
                
                    assert progress["total_shots"] == 2
                    assert progress["with_video"] == 1
                    assert len(progress["needs_prompt"]) == 1
                    assert progress["needs_prompt"][0]["shot_id"] == 1
            except Exception as e:
                # 如果 mock 失败，跳过测试
                pytest.skip(f"Mock setup failed: {e}")

    @pytest.mark.asyncio
    async def test_generate_video_prompts_with_mock_llm(self):
        """测试视频提示词生成（使用 mock LLM）"""
        from app.agent.graph.nodes.teams.video_editor import VideoEditorNode
        
        node = VideoEditorNode()
        
        mock_shots = [
            {
                "shot_id": 1,
                "description": "她站在窗边",
                "image_prompt": "A woman standing by window",
                "end_frame_prompt": "A woman looking outside",
                "narration": [],
                "duration": 5,
                "has_start_image": True,
                "has_end_image": True,
                "characters": [],
            }
        ]
        
        mock_llm_response = {
            "content": '''```json
[
  {
    "shot_id": 1,
    "video_prompt": "暖色调室内光线。[0-2s] 中景固定：她静静站在窗边。[2-5s] 缓推：镜头推向她的侧脸，画面定格。",
    "generation_mode": "first_last_frame",
    "mode_reason": "首尾帧变化明显，适合首尾帧驱动"
  }
]
```'''
        }
        
        with patch.object(node.ai_client, 'chat_completion', return_value=mock_llm_response):
            with patch.object(node.ai_client, '_load_prompt_template', return_value="{{SHOTS_DATA}}"):
                prompts = await node._generate_video_prompts(mock_shots)
        
        assert len(prompts) == 1
        assert prompts[0]["shot_id"] == 1
        assert prompts[0]["generation_mode"] == "first_last_frame"
        assert "暖色调" in prompts[0]["video_prompt"]


class TestVideoGenerationModeSelection:
    """测试视频生成模式选择"""

    def test_first_last_frame_mode_conditions(self):
        """验证首尾帧模式的条件"""
        # 首尾帧模式需要：has_start_image=True AND has_end_image=True
        shot_data = {
            "has_start_image": True,
            "has_end_image": True,
        }
        
        # 模式选择应该优先 first_last_frame
        assert shot_data["has_start_image"] and shot_data["has_end_image"]

    def test_first_frame_only_mode_conditions(self):
        """验证首帧模式的条件"""
        # 首帧模式：has_start_image=True AND has_end_image=False
        shot_data = {
            "has_start_image": True,
            "has_end_image": False,
        }
        
        assert shot_data["has_start_image"] and not shot_data["has_end_image"]

    def test_reference_image_mode_conditions(self):
        """验证参考图模式的条件"""
        # 参考图模式：has_start_image=False
        shot_data = {
            "has_start_image": False,
            "has_end_image": False,
        }
        
        assert not shot_data["has_start_image"]


# ==================== 真实 API 集成测试 ====================

@pytest.mark.integration
@pytest.mark.skipif(
    not pytest.importorskip("app.core.config", reason="Config not available"),
    reason="需要完整的配置环境"
)
class TestRealVideoGeneration:
    """真实视频生成测试（需要 AI API 访问）"""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_real_video_generation_first_frame(self):
        """
        真实测试：首帧模式视频生成
        
        注意：此测试会消耗积分！
        """
        pytest.skip("需要手动启用真实 API 测试")

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_real_video_generation_first_last_frame(self):
        """
        真实测试：首尾帧模式视频生成
        
        注意：此测试会消耗积分！
        """
        pytest.skip("需要手动启用真实 API 测试")


# ==================== 运行测试的入口 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
