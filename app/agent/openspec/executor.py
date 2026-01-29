"""
OpenSpec 工作流执行器

执行工作流步骤，管理状态，协调 Agent 和 Celery 任务
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.logger import logger
from app.agent.openspec.parser import (
    OpenSpecParser,
    StepInfo,
    StageInfo,
    get_openspec_parser
)
from app.agent.services.prompt_generator import get_prompt_generator


class OpenSpecExecutor:
    """OpenSpec 工作流执行器"""

    def __init__(self, parser: OpenSpecParser = None):
        """
        初始化执行器

        Args:
            parser: OpenSpec 解析器实例
        """
        self.parser = parser or get_openspec_parser()
        self.prompt_generator = None
        logger.info("OpenSpec 执行器初始化完成")

    def _get_prompt_generator(self):
        """延迟获取提示词生成器"""
        if self.prompt_generator is None:
            self.prompt_generator = get_prompt_generator()
        return self.prompt_generator

    async def get_creation_workflow_status(
        self,
        db: AsyncSession,
        creation_id: int
    ) -> Dict[str, Any]:
        """
        获取创作的工作流状态

        Args:
            db: 数据库会话
            creation_id: 创作 ID

        Returns:
            工作流状态信息
        """
        from app.models.creation import Creation

        try:
            stmt = select(Creation).where(Creation.creation_id == creation_id)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()

            if not creation:
                return {"error": f"创作不存在: {creation_id}"}

            # 从 extra_data 获取步骤状态
            extra_data = creation.extra_data or {}
            workflow_status = extra_data.get("workflow_status", {})
            step_statuses = workflow_status.get("steps", {})

            # 使用解析器计算进度
            progress = self.parser.get_workflow_progress(step_statuses)

            return {
                "creation_id": creation_id,
                "workflow": progress,
                "step_statuses": step_statuses,
                "last_updated": workflow_status.get("last_updated")
            }

        except Exception as e:
            logger.error(f"获取工作流状态失败: {e}")
            return {"error": str(e)}

    async def update_step_status(
        self,
        db: AsyncSession,
        creation_id: int,
        step_id: str,
        status: str,
        error: str = None,
        task_id: str = None
    ) -> Dict[str, Any]:
        """
        更新步骤状态

        Args:
            db: 数据库会话
            creation_id: 创作 ID
            step_id: 步骤 ID
            status: 新状态 (pending, in_progress, completed, failed)
            error: 错误信息（可选）
            task_id: Celery 任务 ID（可选）
        """
        from app.models.creation import Creation

        try:
            stmt = select(Creation).where(Creation.creation_id == creation_id)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()

            if not creation:
                return {"error": f"创作不存在: {creation_id}"}

            # 更新 extra_data 中的工作流状态
            if creation.extra_data is None:
                creation.extra_data = {}

            if "workflow_status" not in creation.extra_data:
                creation.extra_data["workflow_status"] = {"steps": {}}

            creation.extra_data["workflow_status"]["steps"][step_id] = {
                "status": status,
                "updated_at": datetime.utcnow().isoformat(),
                "error": error,
                "task_id": task_id
            }
            creation.extra_data["workflow_status"]["last_updated"] = datetime.utcnow().isoformat()

            flag_modified(creation, "extra_data")
            await db.commit()

            logger.info(f"更新步骤状态: creation={creation_id}, step={step_id}, status={status}")

            return {"success": True, "step_id": step_id, "status": status}

        except Exception as e:
            logger.error(f"更新步骤状态失败: {e}")
            return {"error": str(e)}

    async def check_step_prerequisites(
        self,
        db: AsyncSession,
        creation_id: int,
        step_id: str
    ) -> Dict[str, Any]:
        """
        检查步骤的前置条件是否满足

        Args:
            db: 数据库会话
            creation_id: 创作 ID
            step_id: 步骤 ID

        Returns:
            检查结果
        """
        step = self.parser.get_step(step_id)
        if not step:
            return {"can_execute": False, "error": f"步骤不存在: {step_id}"}

        # 获取当前工作流状态
        status_result = await self.get_creation_workflow_status(db, creation_id)
        if "error" in status_result:
            return {"can_execute": False, "error": status_result["error"]}

        step_statuses = status_result.get("step_statuses", {})

        # 检查所有依赖是否已完成
        missing_deps = []
        for dep_id in step.requires:
            dep_status = step_statuses.get(dep_id, {})
            if isinstance(dep_status, dict):
                dep_status = dep_status.get("status", "pending")
            if dep_status != "completed":
                missing_deps.append(dep_id)

        if missing_deps:
            return {
                "can_execute": False,
                "missing_dependencies": missing_deps,
                "message": f"需要先完成: {', '.join(missing_deps)}"
            }

        return {"can_execute": True, "step": step}

    async def execute_step(
        self,
        db: AsyncSession,
        creation_id: int,
        step_id: str,
        force: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行工作流步骤

        Args:
            db: 数据库会话
            creation_id: 创作 ID
            step_id: 步骤 ID
            force: 是否强制执行（忽略前置条件检查）
            **kwargs: 额外参数

        Returns:
            执行结果
        """
        step = self.parser.get_step(step_id)
        if not step:
            return {"success": False, "error": f"步骤不存在: {step_id}"}

        # 检查前置条件
        if not force:
            prereq_check = await self.check_step_prerequisites(db, creation_id, step_id)
            if not prereq_check.get("can_execute"):
                return {
                    "success": False,
                    "error": prereq_check.get("message", "前置条件不满足"),
                    "missing_dependencies": prereq_check.get("missing_dependencies", [])
                }

        # 更新状态为执行中
        await self.update_step_status(db, creation_id, step_id, "in_progress")

        try:
            if step.type == "agent":
                result = await self._execute_agent_step(db, creation_id, step, **kwargs)
            elif step.type == "celery":
                result = await self._execute_celery_step(db, creation_id, step, **kwargs)
            else:
                result = {"success": False, "error": f"未知步骤类型: {step.type}"}

            # 更新状态
            if result.get("success"):
                await self.update_step_status(
                    db, creation_id, step_id, "completed",
                    task_id=result.get("task_id")
                )
            else:
                await self.update_step_status(
                    db, creation_id, step_id, "failed",
                    error=result.get("error")
                )

            return result

        except Exception as e:
            logger.error(f"执行步骤失败: {e}")
            await self.update_step_status(db, creation_id, step_id, "failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def _execute_agent_step(
        self,
        db: AsyncSession,
        creation_id: int,
        step: StepInfo,
        **kwargs
    ) -> Dict[str, Any]:
        """执行 Agent 类型的步骤"""
        prompt_generator = self._get_prompt_generator()
        visual_style = kwargs.get("visual_style", "anime")
        force_regenerate = kwargs.get("force_regenerate", False)

        handler = step.handler
        if not handler:
            return {"success": False, "error": "Agent 步骤缺少 handler"}

        try:
            if handler == "generate_character_image_prompt":
                result = await prompt_generator.generate_all_prompts_for_creation(
                    db, creation_id,
                    prompt_types=["character"],
                    visual_style=visual_style,
                    force_regenerate=force_regenerate
                )
            elif handler == "generate_scene_image_prompt":
                result = await prompt_generator.generate_all_prompts_for_creation(
                    db, creation_id,
                    prompt_types=["scene"],
                    visual_style=visual_style,
                    force_regenerate=force_regenerate
                )
            elif handler == "generate_shot_image_prompt":
                result = await prompt_generator.generate_all_prompts_for_creation(
                    db, creation_id,
                    prompt_types=["shot_image"],
                    visual_style=visual_style,
                    force_regenerate=force_regenerate
                )
            elif handler == "generate_shot_video_prompt":
                result = await prompt_generator.generate_all_prompts_for_creation(
                    db, creation_id,
                    prompt_types=["shot_video"],
                    visual_style=visual_style,
                    force_regenerate=force_regenerate
                )
            else:
                return {"success": False, "error": f"未知的 handler: {handler}"}

            return result

        except Exception as e:
            logger.error(f"执行 Agent 步骤失败: {e}")
            return {"success": False, "error": str(e)}

    async def _execute_celery_step(
        self,
        db: AsyncSession,
        creation_id: int,
        step: StepInfo,
        **kwargs
    ) -> Dict[str, Any]:
        """执行 Celery 类型的步骤"""
        from app.models.creation import Creation

        task_name = step.task
        if not task_name:
            return {"success": False, "error": "Celery 步骤缺少 task"}

        try:
            # 获取创作信息
            stmt = select(Creation).where(Creation.creation_id == creation_id)
            result = await db.execute(stmt)
            creation = result.scalar_one_or_none()

            if not creation:
                return {"success": False, "error": f"创作不存在: {creation_id}"}

            # 根据任务名称调用对应的 Celery 任务
            task_result = None

            if task_name == "character_analysis_task":
                from app.tasks.creation_task import character_analysis_task
                task_result = character_analysis_task.delay(
                    novel_id=creation.novel_id or 0,
                    chapter_id=creation.chapter_id or 0,
                    creation_id=creation_id,
                    chapter_content_url=creation.text_content_url or ""
                )

            elif task_name == "scene_analysis_task":
                from app.tasks.creation_task import scene_analysis_task
                task_result = scene_analysis_task.delay(
                    novel_id=creation.novel_id or 0,
                    chapter_id=creation.chapter_id or 0,
                    creation_id=creation_id,
                    chapter_content_url=creation.text_content_url or ""
                )

            elif task_name == "shot_analysis_task":
                from app.tasks.creation_task import shot_analysis_task
                from app.models.chapter import Chapter

                # 获取章节 content_url
                chapter_stmt = select(Chapter).where(Chapter.chapter_id == creation.chapter_id)
                chapter_result = await db.execute(chapter_stmt)
                chapter = chapter_result.scalar_one_or_none()

                chapter_content_url = ""
                if chapter and chapter.content_url:
                    chapter_content_url = chapter.content_url
                    if not chapter_content_url.startswith(("http://", "https://")):
                        from app.utils.us3 import US3Client
                        us3_client = US3Client()
                        chapter_content_url = us3_client.get_file_url(chapter_content_url)

                task_result = shot_analysis_task.delay(
                    novel_id=creation.novel_id or 0,
                    chapter_id=creation.chapter_id or 0,
                    creation_id=creation_id,
                    chapter_content_url=chapter_content_url
                )

            elif task_name == "generate_character_image_task":
                from app.tasks.character_task import generate_character_image_task
                from app.models.character import Character

                char_stmt = select(Character).where(
                    Character.creation_id == creation_id,
                    Character.deleted_at.is_(None)
                )
                char_result = await db.execute(char_stmt)
                characters = char_result.scalars().all()

                character_ids = [c.character_id for c in characters if not c.image_url]
                visual_style = creation.extra_data.get("visual_style", "anime") if creation.extra_data else "anime"

                if character_ids:
                    task_result = generate_character_image_task.delay(
                        character_ids=character_ids,
                        visual_style=visual_style,
                        creation_uuid=creation.uuid,
                        creation_id=creation_id
                    )
                else:
                    return {"success": True, "message": "所有角色图片已生成"}

            elif task_name == "batch_generate_scene_images_task":
                from app.tasks.step4_scene_image_gen_task import batch_generate_scene_images_task
                task_result = batch_generate_scene_images_task.delay(creation_id=creation_id)

            elif task_name == "generate_creation_shots_task":
                from app.tasks.shot_task import generate_creation_shots_task
                task_result = generate_creation_shots_task.delay(
                    creation_id=creation_id,
                    force_regenerate=kwargs.get("force_regenerate", False)
                )

            elif task_name == "generate_all_videos_task":
                from app.tasks.step8_video_gen_task import generate_all_videos_task
                task_result = generate_all_videos_task.delay(
                    creation_id=creation_id,
                    user_id=creation.owner_id
                )

            else:
                return {"success": False, "error": f"未知的 Celery 任务: {task_name}"}

            if task_result:
                return {
                    "success": True,
                    "task_id": str(task_result.id),
                    "task_name": task_name
                }

            return {"success": False, "error": "任务提交失败"}

        except Exception as e:
            logger.error(f"执行 Celery 步骤失败: {e}")
            return {"success": False, "error": str(e)}

    async def get_next_executable_steps(
        self,
        db: AsyncSession,
        creation_id: int
    ) -> List[StepInfo]:
        """获取下一步可执行的步骤列表"""
        status_result = await self.get_creation_workflow_status(db, creation_id)
        if "error" in status_result:
            return []

        step_statuses = status_result.get("step_statuses", {})

        # 转换状态格式
        completed_steps = []
        for step_id, status_info in step_statuses.items():
            if isinstance(status_info, dict):
                if status_info.get("status") == "completed":
                    completed_steps.append(step_id)
            elif status_info == "completed":
                completed_steps.append(step_id)

        return self.parser.get_next_steps(completed_steps)


# 全局执行器实例
_executor: Optional[OpenSpecExecutor] = None


def get_openspec_executor() -> OpenSpecExecutor:
    """获取 OpenSpec 执行器实例"""
    global _executor
    if _executor is None:
        _executor = OpenSpecExecutor()
    return _executor
