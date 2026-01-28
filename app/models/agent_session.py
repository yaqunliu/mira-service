from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
import enum
from app.db.base import Base


class ProductionStage(str, enum.Enum):
    """创作阶段枚举"""
    INIT = "init"
    SCRIPT_ANALYSIS = "script_analysis"
    ASSET_GENERATION = "asset_generation"
    STORYBOARD_CREATION = "storyboard_creation"
    AUDIO_PROCESSING = "audio_processing"
    EDITING = "editing"
    COMPLETED = "completed"


class CheckpointStatus(str, enum.Enum):
    """检查点状态枚举"""
    PENDING = "pending"     # 等待用户审核
    APPROVED = "approved"   # 用户通过
    REJECTED = "rejected"   # 用户驳回
    PARTIAL = "partial"     # 部分通过


class AgentSession(Base):
    """Agent 会话模型 - 管理 Agent 工作流的会话状态"""
    __tablename__ = "agent_sessions"

    session_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text('gen_random_uuid()'),
        comment="会话唯一标识符"
    )

    # 关联的创作项目
    creation_id = Column(
        Integer,
        ForeignKey("creations.creation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的创作项目 ID"
    )

    # 创作的 UUID（冗余字段，便于查询）
    creation_uuid = Column(
        UUID(as_uuid=False),
        nullable=False,
        index=True,
        comment="关联的创作项目 UUID"
    )

    # 用户 ID
    user_id = Column(
        Integer,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话所属用户 ID"
    )

    # LangGraph thread_id（用于 Checkpointer）
    thread_id = Column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="LangGraph 执行图的 thread_id，用于断点恢复"
    )

    # 当前执行阶段
    current_stage = Column(
        SQLEnum(ProductionStage, name="production_stage_enum", create_type=False),
        default=ProductionStage.INIT,
        nullable=False,
        index=True,
        comment="当前创作阶段"
    )

    # 会话状态
    status = Column(
        String(20),
        default="active",
        nullable=False,
        index=True,
        comment="会话状态: active, reset, completed"
    )

    # 检查点数据（待用户审核的数据）
    checkpoint_data = Column(
        JSONB,
        nullable=True,
        comment="当前检查点的数据，如解析结果、生成的资产等"
    )

    # 用户反馈
    user_feedback = Column(
        JSONB,
        nullable=True,
        comment="用户在检查点的反馈数据"
    )

    # 检查点状态
    checkpoint_status = Column(
        SQLEnum(CheckpointStatus, name="checkpoint_status_enum", create_type=False),
        nullable=True,
        comment="当前检查点的状态"
    )

    # 会话元数据（注意：metadata 是 SQLAlchemy 保留字段，使用 session_metadata）
    session_metadata = Column(
        JSONB,
        nullable=True,
        comment="会话元数据，如使用的模型、配置等"
    )

    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True, comment="会话完成时间")

    # 关系
    creation = relationship("Creation", back_populates="agent_session")
    messages = relationship(
        "AgentMessage",
        back_populates="session",
        order_by="AgentMessage.created_at",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<AgentSession(uuid={self.uuid}, creation_id={self.creation_id}, stage={self.current_stage})>"
