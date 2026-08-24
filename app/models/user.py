from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UUID, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
# from app.models.workout import Workout

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(120), unique=False, nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), unique=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(Enum("user", "admin", name="user_role"), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    workouts: Mapped[list["Workout"]] = relationship(back_populates="user")
    messages: Mapped[list["Message"]] = relationship(back_populates="user")