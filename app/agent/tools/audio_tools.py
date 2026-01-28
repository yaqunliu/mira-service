"""
音频工具 - Audio Tools
调用 TTS 和音频处理任务
"""

from typing import Dict, Any
from app.agent.tools.base import CeleryTaskTool, BaseTool
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class VideoPromptGenerationTool(CeleryTaskTool):
    """
    视频提示词生成工具

    为分镜生成视频提示词（用于视频生成）
    """

    @property
    def name(self) -> str:
        return "generate_video_prompt"

    @property
    def description(self) -> str:
        return (
            "为分镜生成视频提示词，结合首尾帧图片提示词、分镜描述和对话。"
            "生成的提示词用于后续的视频生成任务。"
            "使用场景：视频生成阶段，在分镜图片生成完成后执行。"
        )

    def get_celery_task(self):
        from app.tasks.step7_video_prompt_gen_task import generate_video_prompt_task
        return generate_video_prompt_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取视频提示词生成任务参数

        需要传入：
        - shot_id: 分镜 ID (通过 kwargs)
        """
        creation_uuid = state.get("creation_uuid")
        shot_id = kwargs.get("shot_id")

        if not shot_id:
            raise ValueError("必须提供 shot_id 参数")

        from app.models.creation import Creation
        creation = self.db.query(Creation).filter(
            Creation.uuid == creation_uuid
        ).first()

        if not creation:
            raise ValueError(f"创作项目不存在: {creation_uuid}")

        return {
            "args": [],
            "kwargs": {
                "shot_id": shot_id,
                "creation_id": creation.creation_id
            },
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 300)  # 5分钟
        }


class AudioGenerationTool(BaseTool):
    """
    音频生成工具（占位符）

    TODO: 实现 TTS 和音频合成功能
    目前系统的音频处理尚未完全模块化为独立的 Celery 任务
    """

    @property
    def name(self) -> str:
        return "generate_audio"

    @property
    def description(self) -> str:
        return (
            "生成分镜音频，包括对话 TTS、旁白和背景音乐。"
            "使用场景：音频处理阶段。"
            "注意：此工具为占位符，待音频任务模块化后实现。"
        )

    async def execute(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        音频生成执行逻辑（待实现）
        """
        logger.warning(f"{self.name} 工具尚未实现，返回占位符结果")
        return self._create_success_result(
            message="音频生成功能待实现",
            data={"status": "not_implemented"}
        )
