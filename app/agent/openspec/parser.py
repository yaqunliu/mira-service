"""
OpenSpec 工作流解析器

解析 YAML 工作流定义，提供工作流状态查询和管理
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logger import logger


@dataclass
class StepInfo:
    """步骤信息"""
    id: str
    name: str
    type: str  # "agent" 或 "celery"
    handler: Optional[str] = None  # agent handler 名称
    task: Optional[str] = None  # celery task 名称
    description: str = ""
    requires: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    status: str = "pending"
    error: Optional[str] = None


@dataclass
class StageInfo:
    """阶段信息"""
    id: str
    name: str
    description: str = ""
    requires: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    status: str = "pending"


@dataclass
class WorkflowSpec:
    """工作流规范"""
    version: str
    title: str
    description: str
    stages: List[StageInfo]
    steps: Dict[str, StepInfo]
    statuses: Dict[str, str]


class OpenSpecParser:
    """OpenSpec 工作流解析器"""

    def __init__(self, spec_path: str = None):
        """
        初始化解析器

        Args:
            spec_path: YAML 工作流定义文件路径，默认使用内置的 creation_workflow.yaml
        """
        if spec_path is None:
            # 使用默认的工作流定义
            current_dir = Path(__file__).parent
            spec_path = current_dir / "creation_workflow.yaml"

        self.spec_path = str(spec_path)
        self._workflow: Optional[WorkflowSpec] = None
        logger.info(f"OpenSpec 解析器初始化: {self.spec_path}")

    def load_workflow(self) -> WorkflowSpec:
        """加载工作流定义"""
        if self._workflow is not None:
            return self._workflow

        try:
            with open(self.spec_path, 'r', encoding='utf-8') as f:
                spec_data = yaml.safe_load(f)

            # 解析阶段
            stages = []
            for stage_data in spec_data.get("workflow", {}).get("stages", []):
                stage = StageInfo(
                    id=stage_data["id"],
                    name=stage_data["name"],
                    description=stage_data.get("description", ""),
                    requires=stage_data.get("requires", []),
                    steps=stage_data.get("steps", [])
                )
                stages.append(stage)

            # 解析步骤
            steps = {}
            for step_id, step_data in spec_data.get("steps", {}).items():
                step = StepInfo(
                    id=step_id,
                    name=step_data.get("name", step_id),
                    type=step_data.get("type", "celery"),
                    handler=step_data.get("handler"),
                    task=step_data.get("task"),
                    description=step_data.get("description", ""),
                    requires=step_data.get("requires", []),
                    outputs=step_data.get("outputs", [])
                )
                steps[step_id] = step

            # 解析状态
            statuses = spec_data.get("statuses", {
                "pending": "等待执行",
                "in_progress": "执行中",
                "completed": "已完成",
                "failed": "失败",
                "skipped": "已跳过"
            })

            # 构建工作流规范
            info = spec_data.get("info", {})
            self._workflow = WorkflowSpec(
                version=spec_data.get("openspec", "1.0"),
                title=info.get("title", "未命名工作流"),
                description=info.get("description", ""),
                stages=stages,
                steps=steps,
                statuses=statuses
            )

            logger.info(f"工作流加载成功: {self._workflow.title}, {len(stages)} 个阶段, {len(steps)} 个步骤")
            return self._workflow

        except Exception as e:
            logger.error(f"加载工作流定义失败: {e}")
            raise

    def get_stage(self, stage_id: str) -> Optional[StageInfo]:
        """获取阶段信息"""
        workflow = self.load_workflow()
        for stage in workflow.stages:
            if stage.id == stage_id:
                return stage
        return None

    def get_step(self, step_id: str) -> Optional[StepInfo]:
        """获取步骤信息"""
        workflow = self.load_workflow()
        return workflow.steps.get(step_id)

    def get_stage_for_step(self, step_id: str) -> Optional[StageInfo]:
        """获取步骤所属的阶段"""
        workflow = self.load_workflow()
        for stage in workflow.stages:
            if step_id in stage.steps:
                return stage
        return None

    def get_step_dependencies(self, step_id: str) -> List[StepInfo]:
        """获取步骤的依赖"""
        workflow = self.load_workflow()
        step = workflow.steps.get(step_id)
        if not step:
            return []

        dependencies = []
        for dep_id in step.requires:
            if dep_id in workflow.steps:
                dependencies.append(workflow.steps[dep_id])
        return dependencies

    def get_next_steps(self, completed_steps: List[str]) -> List[StepInfo]:
        """
        获取下一步可执行的步骤

        Args:
            completed_steps: 已完成的步骤 ID 列表

        Returns:
            可以执行的步骤列表（所有依赖都已完成）
        """
        workflow = self.load_workflow()
        next_steps = []

        for step_id, step in workflow.steps.items():
            # 跳过已完成的步骤
            if step_id in completed_steps:
                continue

            # 检查所有依赖是否已完成
            all_deps_completed = all(
                dep_id in completed_steps
                for dep_id in step.requires
            )

            if all_deps_completed:
                next_steps.append(step)

        return next_steps

    def get_stage_progress(self, stage_id: str, step_statuses: Dict[str, str]) -> Dict[str, Any]:
        """
        获取阶段进度

        Args:
            stage_id: 阶段 ID
            step_statuses: 步骤状态字典 {step_id: status}

        Returns:
            阶段进度信息
        """
        stage = self.get_stage(stage_id)
        if not stage:
            return {"error": f"阶段不存在: {stage_id}"}

        total = len(stage.steps)
        completed = 0
        in_progress = 0
        failed = 0

        for step_id in stage.steps:
            status = step_statuses.get(step_id, "pending")
            if status == "completed":
                completed += 1
            elif status == "in_progress":
                in_progress += 1
            elif status == "failed":
                failed += 1

        return {
            "stage_id": stage_id,
            "stage_name": stage.name,
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "failed": failed,
            "pending": total - completed - in_progress - failed,
            "progress_percent": round(completed / total * 100, 1) if total > 0 else 0
        }

    def get_workflow_progress(self, step_statuses: Dict[str, str]) -> Dict[str, Any]:
        """
        获取整体工作流进度

        Args:
            step_statuses: 步骤状态字典 {step_id: status}

        Returns:
            整体进度信息
        """
        workflow = self.load_workflow()

        total_steps = len(workflow.steps)
        completed = sum(1 for s in step_statuses.values() if s == "completed")
        in_progress = sum(1 for s in step_statuses.values() if s == "in_progress")
        failed = sum(1 for s in step_statuses.values() if s == "failed")

        # 计算当前阶段
        current_stage = None
        for stage in workflow.stages:
            stage_progress = self.get_stage_progress(stage.id, step_statuses)
            if stage_progress["in_progress"] > 0:
                current_stage = stage
                break
            elif stage_progress["completed"] < stage_progress["total"]:
                current_stage = stage
                break

        return {
            "title": workflow.title,
            "total_steps": total_steps,
            "completed": completed,
            "in_progress": in_progress,
            "failed": failed,
            "pending": total_steps - completed - in_progress - failed,
            "progress_percent": round(completed / total_steps * 100, 1) if total_steps > 0 else 0,
            "current_stage": {
                "id": current_stage.id,
                "name": current_stage.name
            } if current_stage else None,
            "stages": [
                self.get_stage_progress(stage.id, step_statuses)
                for stage in workflow.stages
            ]
        }


# 全局解析器实例
_parser: Optional[OpenSpecParser] = None


def get_openspec_parser() -> OpenSpecParser:
    """获取 OpenSpec 解析器实例"""
    global _parser
    if _parser is None:
        _parser = OpenSpecParser()
    return _parser
