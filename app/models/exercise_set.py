from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Enum, UUID, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.workout_exercise import WorkoutExercise
# from app.models.workout import Workout

class ExerciseSet(Base):
    __tablename__ = "exercise_sets"
    id: Mapped[str] = mapped_column(
        UUID,
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4())
    )
    workout_exercise_id: Mapped[str] = mapped_column(
        UUID,
        ForeignKey("workout_exercises.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    rep_count: Mapped[float] = mapped_column(Float, nullable=True)
    kg_weight: Mapped[float] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC)
    )
    workout_exercise: Mapped["WorkoutExercise"] = relationship(back_populates="exercise_sets")