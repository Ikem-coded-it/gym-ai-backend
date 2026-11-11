from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Enum, UUID, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
    __table_args__ = (
        Index("ix_workout_exercises_workout_id_position", "workout_id", "position"),
    )
    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )
    workout_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("workouts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    exercise: Mapped[str] = mapped_column(String(120), unique=False, nullable=False)
    equipment_name: Mapped[str] = mapped_column(String(120), unique=False, nullable=True)
    # 0-based place of this exercise within its workout. Not unique: gaps are fine
    # (e.g. after a delete) and rows with equal values fall back to created_at.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    workout: Mapped["Workout"] = relationship(back_populates="exercises")
    exercise_sets: Mapped[list["ExerciseSet"]] = relationship(
        back_populates="workout_exercise",
        cascade="all, delete-orphan",
        order_by="ExerciseSet.created_at",
    )