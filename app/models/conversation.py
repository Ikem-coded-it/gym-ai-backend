from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Enum, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.message import Message

class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")