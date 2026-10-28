# app/schemas/workout_exercise.py
from pydantic import BaseModel, Field, ConfigDict, computed_field, model_validator
from datetime import datetime
from uuid import UUID
from typing import Optional, Self

from app.schemas.exercise_set import ExerciseSetCreate, ExerciseSetResponse


class WorkoutExerciseCreate(BaseModel):
    """An exercise with its sets, each with its own reps and weight.
    Used by the agent, chat and onboarding."""

    exercise: str = Field(min_length=1, max_length=50)
    equipment_name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    sets: list[ExerciseSetCreate] = Field(min_length=1, max_length=50)


class WorkoutExerciseAdd(BaseModel):
    """REST body for adding an exercise: name and equipment, sets optional.
    Sets can be added now or one by one later."""

    exercise: str = Field(min_length=1, max_length=50)
    equipment_name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    sets: list[ExerciseSetCreate] = Field(default_factory=list, max_length=50)


class WorkoutExerciseUpdate(BaseModel):
    """Partial patch for a saved exercise. At least one field is required."""

    set_count: Optional[int] = Field(default=None, gt=0, lt=100)
    rep_count: Optional[int] = Field(default=None, gt=0, lt=100)
    kg_weight: Optional[float] = Field(default=None, ge=0, lt=1000)
    equipment_name: Optional[str] = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set or all(
            getattr(self, name) is None
            for name in ("set_count", "rep_count", "kg_weight", "equipment_name")
        ):
            raise ValueError("At least one exercise field must be provided")
        return self


class WorkoutExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workout_id: UUID
    exercise: str
    equipment_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    exercise_sets: list[ExerciseSetResponse] = Field(default_factory=list)

    # Summary of the sets, for the chat/agent paths that talk in "3 sets x 10 reps".
    @computed_field
    @property
    def set_count(self) -> int:
        return len(self.exercise_sets)

    @computed_field
    @property
    def rep_count(self) -> Optional[int]:
        return self.exercise_sets[0].rep_count if self.exercise_sets else None

    @computed_field
    @property
    def kg_weight(self) -> Optional[float]:
        return self.exercise_sets[0].kg_weight if self.exercise_sets else None
