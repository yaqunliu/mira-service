"""
分镜工具 - Storyboard Tools
调用分镜图片生成和相关任务
"""

from typing import Dict, Any, List
from app.agent.tools.base import CeleryTaskTool
from app.agent.state.schemas import ComicDramaState
from app.tasks.shot_task import (
    batch_generate_shot_images_task,
    generate_single_shot_image_task
)
from app.core.logger import logger


class BatchShotImageGenerationTool(CeleryTaskTool):
    """
    批量分镜图片生成工具

    调用 batch_generate_shot_images_task 并发生成多个分镜的图片
    """

    @property
    def name(self) -> str:
        return "generate_shot_images_batch"

    @property
    def description(self) -> str:
        return (
            "批量生成分镜图片（首帧/尾帧），使用图生图技术结合角色图和场景图。"
            "支持并发生成，自动处理角色定位和场景融合。"
            "使用场景：分镜创建阶段，在角色图和场景图生成完成后执行。"
        )

    def get_celery_task(self):
        return batch_generate_shot_images_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取批量分镜图片生成任务参数

        从 state 中提取：
        - creation_uuid: 创作 UUID
        - storyboards: 分镜列表
        """
        creation_uuid = state.get("creation_uuid")

        from app.models.creation import Creation
        creation = self.db.query(Creation).filter(
            Creation.uuid == creation_uuid
        ).first()

        if not creation:
            raise ValueError(f"创作项目不存在: {creation_uuid}")

        # 提取分镜 ID 列表（如果有指定）
        shot_ids = kwargs.get("shot_ids")
        force_regen_prompt = kwargs.get("force_regen_prompt", False)
        frame_type = kwargs.get("frame_type", "both")  # "start", "end", "both"

        logger.info(
            f"准备批量生成分镜图片, creation_id={creation.creation_id}, "
            f"shot_ids={shot_ids}, frame_type={frame_type}"
        )

        task_kwargs = {
            "creation_id": creation.creation_id,
            "force_regen_prompt": force_regen_prompt,
            "frame_type": frame_type
        }

        if shot_ids:
            task_kwargs["shot_ids"] = shot_ids

        return {
            "args": [],
            "kwargs": task_kwargs,
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 3600)  # 1小时，分镜生成耗时较长
        }


class SingleShotImageGenerationTool(CeleryTaskTool):
    """
    单个分镜图片生成工具

    调用 generate_single_shot_image_task 生成单个分镜的图片
    """

    @property
    def name(self) -> str:
        return "generate_single_shot_image"

    @property
    def description(self) -> str:
        return (
            "生成单个分镜的图片，用于重新生成或修复失败的分镜图。"
            "支持首帧/尾帧选择。"
            "使用场景：分镜创建阶段，用于单独处理某个分镜。"
        )

    def get_celery_task(self):
        return generate_single_shot_image_task

    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取单个分镜图片生成任务参数

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

        frame_type = kwargs.get("frame_type", "both")

        return {
            "args": [],
            "kwargs": {
                "shot_id": shot_id,
                "creation_id": creation.creation_id,
                "frame_type": frame_type
            },
            "options": {},
            "wait_for_completion": kwargs.get("wait", True),
            "timeout": kwargs.get("timeout", 300)  # 5分钟
        }
