"""
Agent 角色定义 - 漫剧创作专业团队

定义不同职责的 Agent 角色：
- ScriptAnalysisAgent: 剧本分析师
- AssetDirector: 资产总监
- StoryboardDirector: 分镜导演
- ProductionManager: 制片经理
"""

from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class BaseAgent(ABC):
    """
    Agent 基类

    所有 Agent 角色必须实现：
    1. name: Agent 名称
    2. role: Agent 角色描述
    3. system_prompt: 系统提示词
    4. execute(): 执行 Agent 逻辑
    """

    def __init__(self):
        """初始化 Agent"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 名称"""
        pass

    @property
    @abstractmethod
    def role(self) -> str:
        """Agent 角色描述"""
        pass

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """系统提示词（用于 LLM）"""
        pass

    @abstractmethod
    async def execute(
        self,
        state: ComicDramaState,
        user_input: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        执行 Agent 逻辑

        Args:
            state: 当前 LangGraph 状态
            user_input: 用户输入（可选）
            **kwargs: 其他参数

        Returns:
            Agent 执行结果，包含对 state 的更新
        """
        pass

    def get_available_tools(self) -> List[str]:
        """
        获取 Agent 可用的工具列表

        Returns:
            工具名称列表
        """
        return []

    def format_tool_description(self, tools: Dict[str, Any]) -> str:
        """
        格式化工具描述（用于 system_prompt）

        Args:
            tools: 工具字典 {tool_name: tool_instance}

        Returns:
            格式化的工具描述文本
        """
        available_tools = self.get_available_tools()
        tool_descriptions = []

        for tool_name in available_tools:
            if tool_name in tools:
                tool = tools[tool_name]
                tool_descriptions.append(
                    f"- {tool.name}: {tool.description}"
                )

        if not tool_descriptions:
            return "无可用工具"

        return "\n".join(tool_descriptions)
