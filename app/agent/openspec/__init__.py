"""
OpenSpec 工作流控制模块

使用 YAML 定义创作工作流，支持：
- 阶段（Stage）管理
- 步骤（Step）依赖
- 状态跟踪
"""

from app.agent.openspec.parser import OpenSpecParser, WorkflowSpec, StageInfo, StepInfo
from app.agent.openspec.executor import OpenSpecExecutor

__all__ = [
    "OpenSpecParser",
    "OpenSpecExecutor",
    "WorkflowSpec",
    "StageInfo",
    "StepInfo",
]
