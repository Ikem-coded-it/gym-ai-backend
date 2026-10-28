# app/schemas/exercise_set.py
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Self


class ExerciseSetBase(BaseModel):
    rep_count: Optional[int] = Field(default=None, ge=0, lt=1000)
    kg_weight: Optional[float] = Field(default=None, ge=0, lt=1000)
    notes: Optional[str] = Field(default=None, max_length=500)


# Create — a single set of an exercise
class ExerciseSetCreate(ExerciseSetBase):
    rep_count: int = Field(ge=0, lt=1000)


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
