"""
Agent Tasks 单元测试

测试 Agent 专用 Celery Tasks 的功能
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAgentImageTasks:
    """测试图片生成 Tasks"""

    def test_task_registration(self):
        """验证 Tasks 正确注册到 Celery"""
        from app.agent.tasks import (
            agent_generate_character_image_task,
            agent_generate_scene_image_task,
            agent_generate_shot_image_task,
        )
        
        assert agent_generate_character_image_task.name == "agent_generate_character_image_task"
        assert agent_generate_scene_image_task.name == "agent_generate_scene_image_task"
        assert agent_generate_shot_image_task.name == "agent_generate_shot_image_task"

    @pytest.mark.asyncio
    async def test_character_image_task_params(self):
        """测试角色图片任务参数要求"""
        from app.agent.tasks.image_tasks import agent_generate_character_image_task
        
        # 验证任务存在
        assert callable(agent_generate_character_image_task)

    @pytest.mark.asyncio
    async def test_scene_image_task_params(self):
        """测试场景图片任务参数要求"""
        from app.agent.tasks.image_tasks import agent_generate_scene_image_task
        
        assert callable(agent_generate_scene_image_task)

    @pytest.mark.asyncio
    async def test_shot_image_task_params(self):
        """测试分镜图片任务参数要求"""
        from app.agent.tasks.image_tasks import agent_generate_shot_image_task
        
        assert callable(agent_generate_shot_image_task)


class TestAgentVideoTasks:
    """测试视频生成 Tasks"""

    def test_video_task_registration(self):
        """验证视频任务正确注册"""
        from app.agent.tasks import agent_generate_video_task
        
        assert agent_generate_video_task.name == "agent_generate_video_task"

    @pytest.mark.asyncio
    async def test_video_task_exists(self):
        """测试视频任务存在"""
        from app.agent.tasks.video_tasks import agent_generate_video_task
        
        assert callable(agent_generate_video_task)


class TestAgentAudioTasks:
    """测试音频生成 Tasks"""

    def test_audio_task_registration(self):
        """验证音频任务正确注册"""
        from app.agent.tasks import (
            agent_generate_audio_task,
            agent_generate_batch_audio_task,
        )
        
        assert agent_generate_audio_task.name == "agent_generate_audio_task"
        assert agent_generate_batch_audio_task.name == "agent_generate_batch_audio_task"

    @pytest.mark.asyncio
    async def test_single_audio_task_exists(self):
        """测试单个音频任务存在"""
        from app.agent.tasks.audio_tasks import agent_generate_audio_task
        
        assert callable(agent_generate_audio_task)

    @pytest.mark.asyncio
    async def test_batch_audio_task_exists(self):
        """测试批量音频任务存在"""
        from app.agent.tasks.audio_tasks import agent_generate_batch_audio_task
        
        assert callable(agent_generate_batch_audio_task)


class TestTaskIsolation:
    """测试任务隔离性"""

    def test_tasks_have_agent_prefix(self):
        """确保所有 Agent Tasks 都有 agent_ 前缀"""
        from app.agent.tasks import (
            agent_generate_character_image_task,
            agent_generate_scene_image_task,
            agent_generate_shot_image_task,
            agent_generate_video_task,
            agent_generate_audio_task,
            agent_generate_batch_audio_task,
        )
        
        all_tasks = [
            agent_generate_character_image_task,
            agent_generate_scene_image_task,
            agent_generate_shot_image_task,
            agent_generate_video_task,
            agent_generate_audio_task,
            agent_generate_batch_audio_task,
        ]
        
        for task in all_tasks:
            assert task.name.startswith("agent_"), f"Task {task.name} 缺少 agent_ 前缀"

    def test_tasks_in_agent_module(self):
        """确保任务在正确的模块路径下"""
        import app.agent.tasks as tasks_module
        
        # 验证模块存在
        assert hasattr(tasks_module, "agent_generate_character_image_task")
        assert hasattr(tasks_module, "agent_generate_video_task")
        assert hasattr(tasks_module, "agent_generate_audio_task")
