from __future__ import annotations

from datetime import UTC, datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class ConversationSchedulingState(Base):
    """One row per conversation: tracks in-chat workout scheduling flow and draft fields."""

    __tablename__ = "conversation_scheduling_states"

    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    conversation_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    flow: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="idle",
    )
    step: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="idle",
    )
    draft_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    draft_muscle_group: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    conversation: Mapped["Conversation"] = relationship(
        back_populates="scheduling_state",
    )
