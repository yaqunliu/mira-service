"""
视频工具 - Video Tools
调用视频生成和剪辑任务
"""

from typing import Dict, Any, Optional
from app.agent.tools.base import CeleryTaskTool, BaseTool
from app.agent.state.schemas import ComicDramaState, StoryboardState
from app.core.logger import logger


class VideoPromptGenerationTool(BaseTool):
    """
    视频提示词生成工具

    根据分镜信息生成用于图生视频的提示词
    """

    @property
    def name(self) -> str:
        return "generate_video_prompt"

    @property
    def description(self) -> str:
        return (
            "根据分镜信息和场景描述生成视频生成提示词。"
            "用于 AI 图生视频模型的输入。"
            "使用场景：视频生成阶段，在生成视频之前执行。"
        )

    async def execute(
        self,
        state: ComicDramaState,
        shot_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成分镜的视频提示词

        Args:
            state: 当前状态
            shot_id: 分镜 ID

        Returns:
            视频提示词信息
        """
        try:
            from app.models.shot import Shot
            from app.agent.tools.async_db import get_async_db_session

            async with get_async_db_session() as db:
                shot = await db.get(Shot, shot_id)
                if not shot:
                    return self._create_error_result(
                        message=f"分镜不存在: {shot_id}",
                        error="shot_not_found"
                    )

                shot_data = shot.to_dict() if hasattr(shot, 'to_dict') else {
                    "shot_id": shot.shot_id,
                    "title": shot.title,
                    "description": shot.description,
                    "shot_type": shot.shot_type,
                    "camera_movement": shot.camera_movement,
                }

                video_prompt = self._generate_video_prompt(shot_data)

                return self._create_success_result(
                    message=f"视频提示词生成成功",
                    data={
                        "shot_id": shot_id,
                        "video_prompt": video_prompt,
                        "prompt_style": self._get_prompt_style(shot_data)
                    }
                )

        except Exception as e:
            logger.exception(f"生成视频提示词失败: {e}")
            return self._create_error_result(
                message="视频提示词生成失败",
                error=str(e)
            )

    def _generate_video_prompt(self, shot_data: Dict[str, Any]) -> str:
        """生成视频提示词"""
        parts = []

        shot_type = shot_data.get("shot_type", "")
        camera_movement = shot_data.get("camera_movement", "")

        if shot_type:
            shot_descriptions = {
                "远景": "wide shot, establishing shot",
                "全景": "full shot showing entire figure",
                "中景": "medium shot",
                "中近景": "medium close-up",
                "特写": "close-up",
                "大特写": "extreme close-up",
            }
            for cn, en in shot_descriptions.items():
                if cn in shot_type or shot_type in cn:
                    parts.append(en)
                    break

        if camera_movement:
            movement_descriptions = {
                "推": "slow push in, approaching",
                "拉": "slow pull back, revealing",
                "摇": "pan shot",
                "移": "tracking shot",
                "跟": "following shot",
                "升降": "boom shot, crane shot",
                "旋转": "spinning rotation",
                "固定": "static shot, stationary",
            }
            for cn, en in movement_descriptions.items():
                if cn in camera_movement or camera_movement in cn:
                    parts.append(en)
                    break

        if not parts:
            parts = ["cinematic shot"]

        prompt = ", ".join(parts)
        prompt += ", smooth motion, high quality, professional cinematography"

        return prompt

    def _get_prompt_style(self, shot_data: Dict[str, Any]) -> str:
        """获取提示词风格"""
        description = shot_data.get("description", "")
        mood = shot_data.get("mood", "")

        if "紧张" in description or "紧张" in mood:
            return "tense, fast-paced"
        elif "浪漫" in description or "浪漫" in mood:
            return "romantic, soft lighting"
        elif "动作" in description or "动作" in mood:
            return "dynamic, action-packed"
        elif "恐怖" in description or "恐怖" in mood:
            return "dark, suspenseful"
        else:
            return "neutral, balanced"


class SceneVideoGenerationTool(CeleryTaskTool):
    """
    场景视频生成工具

    为场景下的所有分镜生成视频
    """

    @property
    def name(self) -> str:
        return "generate_scene_videos"

    @property
    def description(self) -> str:
        return (
            "为场景下的所有分镜生成视频，使用 AI 图生视频技术。"
            "根据视频提示词和分镜图片生成动态视频片段。"
            "使用场景：视频生成阶段，在视频提示词生成完成后执行。"
        )

    def get_celery_task(self):
        from app.tasks.step8_video_gen_task import generate_scene_videos_task
        return generate_scene_videos_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取场景视频生成任务参数

        需要传入：
        - scene_id: 场景 ID (通过 kwargs)
        """
        creation_uuid = state.get("creation_uuid")
        scene_id = kwargs.get("scene_id")

        if not scene_id:
            raise ValueError("必须提供 scene_id 参数")

        from app.models.creation import Creation
        creation = self.db.query(Creation).filter(
            Creation.uuid == creation_uuid
        ).first()

        if not creation:
            raise ValueError(f"创作项目不存在: {creation_uuid}")

        return {
            "args": [],
            "kwargs": {
                "scene_id": scene_id,
                "creation_id": creation.creation_id
            },
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 3600)  # 1小时，视频生成耗时很长
        }


class SingleShotVideoGenerationTool(CeleryTaskTool):
    """
    单个分镜视频生成工具

    生成单个分镜的视频
    """

    @property
    def name(self) -> str:
        return "generate_single_shot_video"

    @property
    def description(self) -> str:
        return (
            "生成单个分镜的视频，用于重新生成或修复失败的视频片段。"
            "使用场景：视频生成阶段，用于单独处理某个分镜。"
        )

    def get_celery_task(self):
        from app.tasks.step8_video_gen_task import generate_single_shot_video_task
        return generate_single_shot_video_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取单个分镜视频生成任务参数

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
            "timeout": kwargs.get("timeout", 600)  # 10分钟
        }


class VideoEditingTool(BaseTool):
    """
    视频剪辑工具（占位符）

    TODO: 实现视频剪辑和合成功能
    目前系统的视频剪辑尚未完全模块化为独立的 Celery 任务
    """

    @property
    def name(self) -> str:
        return "edit_and_merge_videos"

    @property
    def description(self) -> str:
        return (
            "合并分镜视频、添加音频、生成字幕，输出最终视频。"
            "使用场景：剪辑合成阶段。"
            "注意：此工具为占位符，待剪辑任务模块化后实现。"
        )

    async def execute(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        视频剪辑执行逻辑（待实现）
        """
        logger.warning(f"{self.name} 工具尚未实现，返回占位符结果")
        return self._create_success_result(
            message="视频剪辑功能待实现",
            data={"status": "not_implemented"}
        )
