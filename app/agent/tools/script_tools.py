"""
剧本分析工具 - Script Analysis Tools
调用 LLM 解析剧本，提取角色、场景、分镜信息
"""

from typing import Dict, Any
from app.agent.tools.base import CeleryTaskTool
from app.agent.state.schemas import ComicDramaState
from app.tasks.creation_task import (
    character_analysis_task,
    scene_analysis_task,
    shot_analysis_task
)
from app.core.logger import logger


class CharacterAnalysisTool(CeleryTaskTool):
    """
    角色分析工具

    调用 character_analysis_task 解析剧本中的角色信息
    """

    @property
    def name(self) -> str:
        return "character_analysis"

    @property
    def description(self) -> str:
        return (
            "分析剧本文本，提取角色信息（姓名、外貌、性格、服装等）。"
            "支持历史角色库复用，自动识别出镜角色和声音角色。"
            "使用场景：剧本解析阶段，在场景分析之前执行。"
        )

    def get_celery_task(self):
        return character_analysis_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取角色分析任务参数

        从 state 中提取：
        - creation_uuid: 创作项目 UUID
        - script_url: 剧本文件 URL
        - user_id: 用户 ID
        """
        creation_uuid = state.get("creation_uuid")
        script_url = state.get("script_url")

        # 通过 creation_uuid 查询 creation 获取 novel_id, chapter_id, creation_id
        from app.models.creation import Creation
        creation = self.db.query(Creation).filter(
            Creation.uuid == creation_uuid
        ).first()

        if not creation:
            raise ValueError(f"创作项目不存在: {creation_uuid}")

        return {
            "args": [],
            "kwargs": {
                "novel_id": creation.novel_id,
                "chapter_id": creation.chapter_id,
                "creation_id": creation.creation_id,
                "chapter_content_url": script_url
            },
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 600)
        }


class SceneAnalysisTool(CeleryTaskTool):
    """
    场景分析工具

    调用 scene_analysis_task 解析剧本中的场景信息
    """

    @property
    def name(self) -> str:
        return "scene_analysis"

    @property
    def description(self) -> str:
        return (
            "分析剧本文本，提取场景信息（地点、时间、氛围、空间描述等）。"
            "支持历史场景库复用，自动识别场景环境设定。"
            "使用场景：剧本解析阶段，在角色分析之后、分镜拆解之前执行。"
        )

    def get_celery_task(self):
        return scene_analysis_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        creation_uuid = state.get("creation_uuid")
        script_url = state.get("script_url")

        from app.models.creation import Creation
        creation = self.db.query(Creation).filter(
            Creation.uuid == creation_uuid
        ).first()

        if not creation:
            raise ValueError(f"创作项目不存在: {creation_uuid}")

        return {
            "args": [],
            "kwargs": {
                "novel_id": creation.novel_id,
                "chapter_id": creation.chapter_id,
                "creation_id": creation.creation_id,
                "chapter_content_url": script_url
            },
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 600)
        }


class ShotAnalysisTool(CeleryTaskTool):
    """
    分镜分析工具

    调用 shot_analysis_task 将剧本拆解为分镜脚本
    """

    @property
    def name(self) -> str:
        return "shot_analysis"

    @property
    def description(self) -> str:
        return (
            "将剧本拆解为分镜脚本，生成详细的分镜列表（镜头类型、运镜、对话、画面描述等）。"
            "依赖于已完成的角色分析和场景分析结果。"
            "使用场景：剧本解析阶段，在角色和场景分析完成后执行。"
        )

    def get_celery_task(self):
        return shot_analysis_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        creation_uuid = state.get("creation_uuid")
        script_url = state.get("script_url")

        from app.models.creation import Creation
        creation = self.db.query(Creation).filter(
            Creation.uuid == creation_uuid
        ).first()

        if not creation:
            raise ValueError(f"创作项目不存在: {creation_uuid}")

        return {
            "args": [],
            "kwargs": {
                "novel_id": creation.novel_id,
                "chapter_id": creation.chapter_id,
                "creation_id": creation.creation_id,
                "chapter_content_url": script_url
            },
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 900)  # 分镜拆解可能需要更长时间
        }
