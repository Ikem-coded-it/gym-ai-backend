from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Enum, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"
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