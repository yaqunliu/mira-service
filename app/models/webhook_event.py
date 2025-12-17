from sqlalchemy import Column, DateTime, Integer, String, Text, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, text as sa_text
import uuid
from app.db.base import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    event_id = Column(Integer, primary_key=True, index=True)
    uuid = Column(
        UUID(as_uuid=False),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
        server_default=sa_text("gen_random_uuid()"),
    )
    event_type = Column(String(50), nullable=False, index=True)
    creem_event_id = Column(String(100), unique=True, index=True)
    payload = Column(JSON, nullable=False)
    source = Column(String(20), nullable=True, default="webhook", index=True)  # webhook / polling
    processed = Column(Boolean, default=False, index=True)
    processed_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

