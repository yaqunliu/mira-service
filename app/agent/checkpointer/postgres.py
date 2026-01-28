"""
PostgreSQL Checkpointer - 异步状态持久化

实现 LangGraph 的 AsyncCheckpointer 接口，使用 PostgreSQL 存储状态
"""

from typing import Dict, Any, Optional, AsyncIterator, Sequence, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert
from app.models.agent_checkpoint import AgentCheckpoint
from app.agent.state.schemas import ComicDramaState
from app.agent.state.utils import serialize_state, deserialize_state
from app.core.logger import logger
import json


class AsyncPostgresCheckpointer:
    """
    异步 PostgreSQL Checkpointer

    实现 LangGraph 状态持久化，支持：
    1. 保存检查点（put）
    2. 获取检查点（get）
    3. 列出检查点（list）
    4. 删除检查点（delete）
    5. 获取检查点链（get_checkpoint_chain）
    """

    def __init__(self, async_session_factory):
        """
        初始化 Checkpointer

        Args:
            async_session_factory: AsyncSession 工厂函数
        """
        self.async_session_factory = async_session_factory
        logger.info("AsyncPostgresCheckpointer 初始化完成")

    async def put(
        self,
        thread_id: str,
        checkpoint_id: str,
        checkpoint_data: ComicDramaState,
        checkpoint_metadata: Optional[Dict[str, Any]] = None,
        parent_checkpoint_id: Optional[str] = None
    ) -> None:
        """
        保存检查点

        Args:
            thread_id: 线程 ID（对应 creation.uuid）
            checkpoint_id: 检查点 ID（唯一标识）
            checkpoint_data: 检查点数据（ComicDramaState）
            checkpoint_metadata: 检查点元数据（节点名称、步数等）
            parent_checkpoint_id: 父检查点 ID（用于追踪检查点链）
        """
        async with self.async_session_factory() as session:
            try:
                # 序列化状态数据
                serialized_data = serialize_state(checkpoint_data)

                # 准备元数据
                metadata = checkpoint_metadata or {}
                metadata["saved_at"] = datetime.utcnow().isoformat()

                # 使用 PostgreSQL 的 INSERT ... ON CONFLICT DO UPDATE
                stmt = insert(AgentCheckpoint).values(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    parent_checkpoint_id=parent_checkpoint_id,
                    checkpoint_data=serialized_data,
                    checkpoint_metadata=metadata,
                    created_at=datetime.utcnow()
                )

                # 如果已存在则更新
                stmt = stmt.on_conflict_do_update(
                    constraint='agent_checkpoints_pkey',
                    set_={
                        'checkpoint_data': serialized_data,
                        'checkpoint_metadata': metadata,
                        'parent_checkpoint_id': parent_checkpoint_id,
                        'created_at': datetime.utcnow()
                    }
                )

                await session.execute(stmt)
                await session.commit()

                logger.info(
                    f"检查点已保存: thread_id={thread_id}, "
                    f"checkpoint_id={checkpoint_id}"
                )

            except Exception as e:
                await session.rollback()
                logger.error(f"保存检查点失败: {e}")
                raise

    async def get(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> Optional[ComicDramaState]:
        """
        获取检查点

        Args:
            thread_id: 线程 ID
            checkpoint_id: 检查点 ID（如果为 None，返回最新的检查点）

        Returns:
            检查点数据（ComicDramaState）或 None
        """
        async with self.async_session_factory() as session:
            try:
                if checkpoint_id:
                    # 获取指定检查点
                    stmt = select(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id,
                        AgentCheckpoint.checkpoint_id == checkpoint_id
                    )
                else:
                    # 获取最新检查点
                    stmt = select(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id
                    ).order_by(
                        AgentCheckpoint.created_at.desc()
                    ).limit(1)

                result = await session.execute(stmt)
                checkpoint = result.scalar_one_or_none()

                if not checkpoint:
                    logger.info(
                        f"未找到检查点: thread_id={thread_id}, "
                        f"checkpoint_id={checkpoint_id}"
                    )
                    return None

                # 反序列化状态数据
                state = deserialize_state(checkpoint.checkpoint_data)

                logger.info(
                    f"检查点已加载: thread_id={thread_id}, "
                    f"checkpoint_id={checkpoint.checkpoint_id}"
                )

                return state

            except Exception as e:
                logger.error(f"获取检查点失败: {e}")
                raise

    async def get_with_metadata(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取检查点及其元数据

        Args:
            thread_id: 线程 ID
            checkpoint_id: 检查点 ID

        Returns:
            包含检查点数据和元数据的字典
        """
        async with self.async_session_factory() as session:
            try:
                if checkpoint_id:
                    stmt = select(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id,
                        AgentCheckpoint.checkpoint_id == checkpoint_id
                    )
                else:
                    stmt = select(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id
                    ).order_by(
                        AgentCheckpoint.created_at.desc()
                    ).limit(1)

                result = await session.execute(stmt)
                checkpoint = result.scalar_one_or_none()

                if not checkpoint:
                    return None

                return {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
                    "checkpoint_data": deserialize_state(checkpoint.checkpoint_data),
                    "checkpoint_metadata": checkpoint.checkpoint_metadata,
                    "created_at": checkpoint.created_at.isoformat()
                }

            except Exception as e:
                logger.error(f"获取检查点（含元数据）失败: {e}")
                raise

    async def list(
        self,
        thread_id: str,
        limit: int = 10,
        offset: int = 0
    ) -> Sequence[Dict[str, Any]]:
        """
        列出检查点

        Args:
            thread_id: 线程 ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            检查点列表（包含元数据）
        """
        async with self.async_session_factory() as session:
            try:
                stmt = select(AgentCheckpoint).where(
                    AgentCheckpoint.thread_id == thread_id
                ).order_by(
                    AgentCheckpoint.created_at.desc()
                ).limit(limit).offset(offset)

                result = await session.execute(stmt)
                checkpoints = result.scalars().all()

                checkpoint_list = []
                for checkpoint in checkpoints:
                    checkpoint_list.append({
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
                        "checkpoint_metadata": checkpoint.checkpoint_metadata,
                        "created_at": checkpoint.created_at.isoformat()
                    })

                logger.info(
                    f"列出检查点: thread_id={thread_id}, "
                    f"count={len(checkpoint_list)}"
                )

                return checkpoint_list

            except Exception as e:
                logger.error(f"列出检查点失败: {e}")
                raise

    async def delete(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> int:
        """
        删除检查点

        Args:
            thread_id: 线程 ID
            checkpoint_id: 检查点 ID（如果为 None，删除该线程的所有检查点）

        Returns:
            删除的检查点数量
        """
        async with self.async_session_factory() as session:
            try:
                if checkpoint_id:
                    stmt = delete(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id,
                        AgentCheckpoint.checkpoint_id == checkpoint_id
                    )
                else:
                    stmt = delete(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id
                    )

                result = await session.execute(stmt)
                await session.commit()

                deleted_count = result.rowcount

                logger.info(
                    f"检查点已删除: thread_id={thread_id}, "
                    f"checkpoint_id={checkpoint_id}, "
                    f"deleted_count={deleted_count}"
                )

                return deleted_count

            except Exception as e:
                await session.rollback()
                logger.error(f"删除检查点失败: {e}")
                raise

    async def get_checkpoint_chain(
        self,
        thread_id: str,
        checkpoint_id: str
    ) -> List[Dict[str, Any]]:
        """
        获取检查点链（从指定检查点回溯到最早的检查点）

        Args:
            thread_id: 线程 ID
            checkpoint_id: 起始检查点 ID

        Returns:
            检查点链列表（从最新到最早）
        """
        chain = []
        current_id = checkpoint_id
        visited = set()

        async with self.async_session_factory() as session:
            try:
                while current_id and current_id not in visited:
                    visited.add(current_id)

                    stmt = select(AgentCheckpoint).where(
                        AgentCheckpoint.thread_id == thread_id,
                        AgentCheckpoint.checkpoint_id == current_id
                    )

                    result = await session.execute(stmt)
                    checkpoint = result.scalar_one_or_none()

                    if not checkpoint:
                        break

                    chain.append({
                        "checkpoint_id": checkpoint.checkpoint_id,
                        "parent_checkpoint_id": checkpoint.parent_checkpoint_id,
                        "checkpoint_metadata": checkpoint.checkpoint_metadata,
                        "created_at": checkpoint.created_at.isoformat()
                    })

                    current_id = checkpoint.parent_checkpoint_id

                logger.info(
                    f"获取检查点链: thread_id={thread_id}, "
                    f"chain_length={len(chain)}"
                )

                return chain

            except Exception as e:
                logger.error(f"获取检查点链失败: {e}")
                raise

    async def get_latest_checkpoint_id(self, thread_id: str) -> Optional[str]:
        """
        获取最新的检查点 ID

        Args:
            thread_id: 线程 ID

        Returns:
            最新的检查点 ID 或 None
        """
        async with self.async_session_factory() as session:
            try:
                stmt = select(AgentCheckpoint.checkpoint_id).where(
                    AgentCheckpoint.thread_id == thread_id
                ).order_by(
                    AgentCheckpoint.created_at.desc()
                ).limit(1)

                result = await session.execute(stmt)
                checkpoint_id = result.scalar_one_or_none()

                return checkpoint_id

            except Exception as e:
                logger.error(f"获取最新检查点 ID 失败: {e}")
                raise
