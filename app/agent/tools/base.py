"""
Tool 基类 - 定义所有 Agent 工具的基础接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logger import logger
from app.agent.state.schemas import ComicDramaState


class BaseTool(ABC):
    """
    Agent 工具基类

    所有工具必须实现：
    1. name: 工具名称
    2. description: 工具描述（用于 LLM 理解工具用途）
    3. execute(): 执行工具逻辑
    """

    def __init__(self, db_factory: Optional[Callable[[], AsyncSession]] = None):
        """
        初始化工具

        Args:
            db_factory: 异步数据库会话工厂函数（可选，如果不提供则需要子类自己管理）
        """
        self.db_factory = db_factory

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（用于 LLM 理解）"""
        pass

    @abstractmethod
    async def execute(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行工具

        Args:
            state: 当前 LangGraph 状态
            **kwargs: 工具特定参数

        Returns:
            工具执行结果字典，包含：
            - success: bool - 是否成功
            - message: str - 执行消息
            - data: Any - 返回数据
            - error: Optional[str] - 错误信息
        """
        pass

    def _create_success_result(
        self,
        message: str,
        data: Any = None
    ) -> Dict[str, Any]:
        """创建成功结果"""
        return {
            "success": True,
            "message": message,
            "data": data,
            "error": None
        }

    def _create_error_result(
        self,
        message: str,
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """创建错误结果"""
        logger.error(f"{self.name} 执行失败: {message}, error={error}")
        return {
            "success": False,
            "message": message,
            "data": None,
            "error": error or message
        }


class CeleryTaskTool(BaseTool):
    """
    Celery 任务工具基类

    用于封装 Celery 任务调用，提供统一的异步任务调度接口
    """

    @abstractmethod
    def get_celery_task(self):
        """获取对应的 Celery 任务"""
        pass

    async def execute(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行 Celery 任务

        默认实现：
        1. 调用 get_task_params() 获取任务参数
        2. 异步调度 Celery 任务（apply_async）
        3. 等待任务完成或返回任务 ID

        子类可以重写此方法以实现自定义逻辑
        """
        try:
            # 获取任务参数
            task_params = self.get_task_params(state, **kwargs)

            # 获取 Celery 任务
            celery_task = self.get_celery_task()

            # 调度任务
            task_result = celery_task.apply_async(
                args=task_params.get("args", []),
                kwargs=task_params.get("kwargs", {}),
                **task_params.get("options", {})
            )

            logger.info(
                f"{self.name} Celery 任务已调度: task_id={task_result.id}, "
                f"params={task_params}"
            )

            # 根据配置决定是否等待任务完成
            if task_params.get("wait_for_completion", False):
                # 等待任务完成（阻塞）
                result = task_result.get(
                    timeout=task_params.get("timeout", 600)
                )
                return self._create_success_result(
                    message=f"{self.name} 任务执行完成",
                    data={
                        "task_id": task_result.id,
                        "result": result
                    }
                )
            else:
                # 异步执行，返回任务 ID
                return self._create_success_result(
                    message=f"{self.name} 任务已调度",
                    data={
                        "task_id": task_result.id,
                        "status": "pending"
                    }
                )

        except Exception as e:
            logger.exception(f"{self.name} Celery 任务调度失败")
            return self._create_error_result(
                message=f"{self.name} 任务调度失败",
                error=str(e)
            )

    @abstractmethod
    def get_task_params(
        self,
        state: ComicDramaState,
        **kwargs
    ) -> Dict[str, Any]:
        """
        获取 Celery 任务参数

        Returns:
            包含以下字段的字典：
            - args: List - 位置参数
            - kwargs: Dict - 关键字参数
            - options: Dict - Celery 选项（如 countdown, eta 等）
            - wait_for_completion: bool - 是否等待完成
            - timeout: int - 超时时间（秒）
        """
        pass
