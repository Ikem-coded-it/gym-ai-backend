from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Enum, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.user import User

class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Enum("user", "assistant", name="message_role"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    user: Mapped["User"] = relationship(back_populates="messages")
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")