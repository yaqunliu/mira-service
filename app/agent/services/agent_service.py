"""
Agent 服务层 - Agent Service

提供 Agent 工作流的业务逻辑封装
"""

from typing import Dict, Any, Optional, AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from app.agent.checkpointer import AsyncPostgresCheckpointer
from app.agent.tools import (
    CharacterAnalysisTool,
    SceneAnalysisTool,
    ShotAnalysisTool,
    CharacterImageGenerationTool,
    SceneImageGenerationTool,
    SingleSceneImageGenerationTool,
    BatchShotImageGenerationTool,
    SingleShotImageGenerationTool,
    VideoPromptGenerationTool,
    SceneVideoGenerationTool,
    SingleShotVideoGenerationTool,
)
from app.agent.state.schemas import ComicDramaState
from app.models.creation import Creation
from app.models.agent_session import AgentSession, ProductionStage
from app.core.logger import logger
from datetime import datetime
import uuid


class AgentService:
    """
    Agent 服务类

    提供：
    1. 创建 Agent 会话
    2. 执行 Agent 工作流
    3. 处理用户反馈
    4. 查询会话状态
    """

    def __init__(self, async_session_factory):
        """
        初始化服务

        Args:
            async_session_factory: AsyncSession 工厂函数
        """
        self.async_session_factory = async_session_factory
        self.checkpointer = AsyncPostgresCheckpointer(async_session_factory)
        logger.info("AgentService 初始化完成")

    async def create_agent_session(
        self,
        creation_id: int,
        db: AsyncSession
    ) -> AgentSession:
        """
        创建 Agent 会话

        Args:
            creation_id: 创作 ID
            db: 数据库会话

        Returns:
            AgentSession 实例
        """
        # 查询创作项目
        from sqlalchemy import select
        stmt = select(Creation).where(Creation.creation_id == creation_id)
        result = await db.execute(stmt)
        creation = result.scalar_one_or_none()

        if not creation:
            raise ValueError(f"创作项目不存在: creation_id={creation_id}")

        # 生成 thread_id (使用 creation.uuid)
        thread_id = creation.uuid

        # 创建 Agent 会话
        agent_session = AgentSession(
            uuid=str(uuid.uuid4()),
            creation_id=creation_id,
            thread_id=thread_id,
            current_stage=ProductionStage.INIT,
            session_metadata={
                "created_by": "agent_service",
                "workflow_mode": "interactive"
            }
        )

        db.add(agent_session)
        await db.commit()
        await db.refresh(agent_session)

        logger.info(
            f"Agent 会话已创建: session_id={agent_session.session_id}, "
            f"thread_id={thread_id}"
        )

        return agent_session

    async def initialize_state(
        self,
        creation_id: int,
        db: AsyncSession
    ) -> ComicDramaState:
        """
        初始化 Agent 状态

        Args:
            creation_id: 创作 ID
            db: 数据库会话

        Returns:
            初始化的 ComicDramaState
        """
        from sqlalchemy import select

        # 查询创作项目
        stmt = select(Creation).where(Creation.creation_id == creation_id)
        result = await db.execute(stmt)
        creation = result.scalar_one_or_none()

        if not creation:
            raise ValueError(f"创作项目不存在: creation_id={creation_id}")

        # 构建初始状态
        initial_state: ComicDramaState = {
            "creation_uuid": creation.uuid,
            "thread_id": creation.uuid,
            "user_id": creation.owner_id,
            "script_text": None,
            "script_url": creation.text_content_url,
            "current_stage": "init",
            "script_summary": None,
            "script_theme": None,
            "script_style": None,
            "characters": [],
            "scenes": [],
            "props": [],
            "storyboards": [],
            "total_duration": None,
            "audio_segments": [],
            "final_audio_url": None,
            "subtitle_url": None,
            "video_segments": [],
            "final_video_url": None,
            "checkpoint_data": None,
            "user_feedback": None,
            "pending_approval": False,
            "tool_calls": [],
            "retry_count": {},
            "errors": [],
            "error_message": None,
            "config": {
                "visual_style": (creation.extra_data or {}).get("visual_style", "anime"),
                "llm_model": (creation.extra_data or {}).get("llm_model"),
                "text_to_image_model": (creation.extra_data or {}).get("text_to_image_model"),
                "storyboard_batch_size": 5
            },
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "extra_data": {}
        }

        logger.info(f"Agent 状态已初始化: creation_uuid={creation.uuid}")

        return initial_state

    async def execute_workflow(
        self,
        state: ComicDramaState,
        db: AsyncSession
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        执行 Agent 工作流（流式输出）

        Args:
            state: 初始状态
            db: 数据库会话

        Yields:
            工作流执行事件
        """
        from app.agent.graph import ComicDramaGraph

        # 准备工具字典
        tools = self._prepare_tools(db)

        # 创建工作流图
        graph = ComicDramaGraph(
            checkpointer=self.checkpointer,
            tools=tools
        )

        # 编译图
        compiled_graph = await graph.compile()

        # 流式执行
        async for event in compiled_graph.astream(state):
            # 解析事件
            yield self._parse_event(event)

    def _prepare_tools(self, db: AsyncSession) -> Dict[str, Any]:
        """
        准备工具字典

        Args:
            db: 数据库会话

        Returns:
            工具字典 {tool_name: tool_instance}
        """
        return {
            # 剧本分析工具
            "character_analysis": CharacterAnalysisTool(db),
            "scene_analysis": SceneAnalysisTool(db),
            "shot_analysis": ShotAnalysisTool(db),

            # 资产生成工具
            "generate_character_images": CharacterImageGenerationTool(db),
            "generate_scene_images": SceneImageGenerationTool(db),
            "generate_single_scene_image": SingleSceneImageGenerationTool(db),

            # 分镜工具
            "generate_shot_images_batch": BatchShotImageGenerationTool(db),
            "generate_single_shot_image": SingleShotImageGenerationTool(db),

            # 音视频工具
            "generate_video_prompt": VideoPromptGenerationTool(db),
            "generate_scene_videos": SceneVideoGenerationTool(db),
            "generate_single_shot_video": SingleShotVideoGenerationTool(db),
        }

    def _parse_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析工作流事件

        Args:
            event: LangGraph 事件

        Returns:
            格式化的事件数据
        """
        # 提取节点名称和状态更新
        node_name = list(event.keys())[0] if event else None
        state_update = event.get(node_name, {}) if node_name else {}

        return {
            "event_type": "node_execution",
            "node_name": node_name,
            "timestamp": datetime.utcnow().isoformat(),
            "state_update": state_update,
            "current_stage": state_update.get("current_stage"),
            "pending_approval": state_update.get("pending_approval", False),
            "checkpoint_data": state_update.get("checkpoint_data")
        }

    async def submit_user_feedback(
        self,
        thread_id: str,
        feedback: Dict[str, Any],
        db: AsyncSession
    ) -> ComicDramaState:
        """
        提交用户反馈

        Args:
            thread_id: 线程 ID
            feedback: 用户反馈数据
            db: 数据库会话

        Returns:
            更新后的状态
        """
        # 获取最新检查点
        state = await self.checkpointer.get(thread_id)

        if not state:
            raise ValueError(f"未找到检查点: thread_id={thread_id}")

        # 应用用户反馈
        from app.agent.state.utils import apply_user_feedback

        apply_user_feedback(
            state,
            action=feedback.get("action"),
            comments=feedback.get("comments"),
            modifications=feedback.get("modifications"),
            approved_items=feedback.get("approved_items"),
            rejected_items=feedback.get("rejected_items")
        )

        # 保存更新后的状态
        checkpoint_id = f"feedback-{datetime.utcnow().timestamp()}"
        await self.checkpointer.put(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            checkpoint_data=state,
            checkpoint_metadata={
                "type": "user_feedback",
                "action": feedback.get("action")
            }
        )

        logger.info(
            f"用户反馈已应用: thread_id={thread_id}, "
            f"action={feedback.get('action')}"
        )

        return state

    async def get_session_status(
        self,
        session_id: int,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        获取会话状态

        Args:
            session_id: 会话 ID
            db: 数据库会话

        Returns:
            会话状态信息
        """
        from sqlalchemy import select

        # 查询会话
        stmt = select(AgentSession).where(AgentSession.session_id == session_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            raise ValueError(f"会话不存在: session_id={session_id}")

        # 获取最新检查点
        state = await self.checkpointer.get(session.thread_id)

        return {
            "session_id": session.session_id,
            "thread_id": session.thread_id,
            "current_stage": session.current_stage.value,
            "checkpoint_status": session.checkpoint_status.value if session.checkpoint_status else None,
            "pending_approval": state.get("pending_approval", False) if state else False,
            "checkpoint_data": state.get("checkpoint_data") if state else None,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat() if session.updated_at else None
        }

    async def list_checkpoints(
        self,
        thread_id: str,
        limit: int = 10,
        offset: int = 0
    ) -> list:
        """
        列出检查点

        Args:
            thread_id: 线程 ID
            limit: 返回数量
            offset: 偏移量

        Returns:
            检查点列表
        """
        return await self.checkpointer.list(
            thread_id=thread_id,
            limit=limit,
            offset=offset
        )
