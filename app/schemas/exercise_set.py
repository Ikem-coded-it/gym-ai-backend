# app/schemas/exercise_set.py
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Self


class ExerciseSetBase(BaseModel):
    rep_count: Optional[int] = Field(default=None, ge=0, lt=1000)
    kg_weight: Optional[float] = Field(default=None, ge=0, lt=1000)
    # Seconds held, for timed exercises like a plank (under 24 hours).
    duration_seconds: Optional[int] = Field(default=None, ge=0, lt=86400)
    notes: Optional[str] = Field(default=None, max_length=500)


def has_reps_or_duration(rep_count: Optional[int], duration_seconds: Optional[int]) -> bool:
    return bool(rep_count) or bool(duration_seconds)


# Create — a single set: counted in reps, held for a time, or both
class ExerciseSetCreate(ExerciseSetBase):
    @model_validator(mode="after")
    def reps_or_duration(self) -> Self:
        if not has_reps_or_duration(self.rep_count, self.duration_seconds):
            raise ValueError("A set needs reps or a duration")
        return self


# Update — partial patch; at least one field is required
class ExerciseSetUpdate(ExerciseSetBase):
    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one set field must be provided")
        return self


# Response — what the API returns to the client
class ExerciseSetResponse(ExerciseSetBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workout_exercise_id: UUID
    created_at: datetime
    updated_at: datetime
