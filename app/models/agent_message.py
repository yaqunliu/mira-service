from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy.orm import relationship
import uuid
import enum
from app.db.base import Base


class MessageRole(str, enum.Enum):
    """消息角色枚举"""
    USER = "user"           # 用户消息
    ASSISTANT = "assistant" # Agent 回复
    SYSTEM = "system"       # 系统消息


class EventType(str, enum.Enum):
    """事件类型枚举"""
    MESSAGE = "message"               # 普通消息
    TOOL_CALL = "tool_call"           # 工具调用
    TOOL_OUTPUT = "tool_output"       # 工具输出
    PROGRESS = "progress"             # 进度更新
    BOARD_ACTION = "board_action"     # 看板联动指令
    ACTION_REQUEST = "action_request" # 请求用户操作
    THINKING = "thinking"             # Agent 思考过程
    ERROR = "error"                   # 错误消息
    SESSION_RESET = "session_reset"   # 会话重置
    INTERRUPT = "interrupt"           # 对话中断


class AgentMessage(Base):
    """Agent 消息模型 - 存储对话历史和事件流"""
    __tablename__ = "agent_messages"

    message_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text('gen_random_uuid()'),
        comment="消息唯一标识符"
    )

    # 关联的会话
    session_id = Column(
        Integer,
        ForeignKey("agent_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的 Agent 会话 ID"
    )

    # 消息角色
    role = Column(
        SQLEnum(MessageRole, name="message_role_enum", create_type=False),
        nullable=False,
        index=True,
        comment="消息角色：user/assistant/system"
    )

    # 消息内容
    content = Column(
        Text,
        nullable=True,
        comment="消息文本内容"
    )

    # 事件类型
    event_type = Column(
        SQLEnum(EventType, name="event_type_enum", create_type=False),
        default=EventType.MESSAGE,
        nullable=False,
        index=True,
        comment="事件类型，用于区分不同的 SSE 事件"
    )

    # 消息元数据（注意：metadata 是 SQLAlchemy 保留字段，使用 message_metadata）
    message_metadata = Column(
        JSONB,
        nullable=True,
        comment="消息元数据，如工具调用参数、进度详情、看板操作等"
    )

    # 时间戳
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )

    # 关系
    session = relationship("AgentSession", back_populates="messages")

    def __repr__(self):
        return f"<AgentMessage(uuid={self.uuid}, role={self.role}, event_type={self.event_type})>"

    def to_dict(self):
        """转换为字典（用于 API 响应）"""
        return {
            "id": str(self.uuid),
            "session_id": self.session_id,
            "role": self.role.value,
            "content": self.content,
            "event_type": self.event_type.value,
            "metadata": self.message_metadata,  # 对外仍使用 metadata
            "timestamp": self.created_at.isoformat() if self.created_at else None
        }
