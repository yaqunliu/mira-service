"""
Agent 专用 Celery Tasks 模块

这些 Tasks 专门为 Agent 设计，与现有的 step3_*, step4_* 等任务隔离。
不要调用现有的任务，以避免参数结构和状态更新逻辑的冲突。
"""

from .image_tasks import (
    agent_generate_character_image_task,
    agent_generate_scene_image_task,
    agent_generate_shot_image_task,
)
from .video_tasks import agent_generate_video_task
from .audio_tasks import agent_generate_audio_task

__all__ = [
    # 图片生成
    "agent_generate_character_image_task",
    "agent_generate_scene_image_task",
    "agent_generate_shot_image_task",
    # 视频生成
    "agent_generate_video_task",
    # 音频生成
    "agent_generate_audio_task",
]
