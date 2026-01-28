from sqlalchemy import Column, DateTime, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class AgentCheckpoint(Base):
    """
    Agent Checkpoint 模型 - LangGraph 状态持久化

    用于存储 LangGraph 执行图的状态快照，支持断点恢复。
    基于 PostgreSQL 实现，替代默认的 SQLite Checkpointer。
    """
    __tablename__ = "agent_checkpoints"

    # LangGraph thread_id（主键）
    thread_id = Column(
        String(255),
        primary_key=True,
        index=True,
        comment="LangGraph 执行图的 thread_id，对应 creation.uuid"
    )

    # 检查点 ID
    checkpoint_id = Column(
        String(255),
        nullable=False,
        index=True,
        comment="检查点唯一标识符"
    )

    # 父检查点 ID（用于构建检查点树）
    parent_checkpoint_id = Column(
        String(255),
        nullable=True,
        comment="父检查点 ID，用于追踪检查点链"
    )

    # 检查点数据（完整的 State 快照）
    checkpoint_data = Column(
        JSONB,
        nullable=False,
        comment="完整的 ComicDramaState 数据，包含 characters, scenes, storyboards 等"
    )

    # 检查点元数据（注意：metadata 是 SQLAlchemy 保留字段，使用 checkpoint_metadata）
    checkpoint_metadata = Column(
        JSONB,
        nullable=True,
        comment="检查点元数据，如节点名称、执行步数、时间戳等"
    )

    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="检查点创建时间"
    )

    # 复合索引：提升查询性能
    __table_args__ = (
        Index('idx_checkpoint_thread_id', 'thread_id'),
        Index('idx_checkpoint_id', 'checkpoint_id'),
        Index('idx_checkpoint_created_at', 'created_at'),
        Index('idx_checkpoint_thread_created', 'thread_id', 'created_at'),
    )

    def __repr__(self):
        return f"<AgentCheckpoint(thread_id={self.thread_id}, checkpoint_id={self.checkpoint_id})>"
