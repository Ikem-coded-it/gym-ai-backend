# app/schemas/workout_exercise.py
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import datetime
from uuid import UUID
from typing import Optional, Self

class WorkoutExerciseBase(BaseModel):
    exercise: str = Field(min_length=1, max_length=50)
    set_count: int = Field(gt=0, lt=100)
    rep_count: int = Field(gt=0, lt=100)
    equipment_name: Optional[str] = Field(min_length=1, max_length=50)
    kg_weight: Optional[float] = Field(default=None, ge=0, lt=1000)

class WorkoutExerciseCreate(WorkoutExerciseBase):
    pass


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

class WorkoutExerciseResponse(WorkoutExerciseBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workout_id: UUID
    created_at: datetime
    updated_at: datetime