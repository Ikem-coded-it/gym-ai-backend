# app/schemas/workout_exercise.py
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
from uuid import UUID
from typing import Optional

class WorkoutExerciseBase(BaseModel):
    exercise: str = Field(min_length=1, max_length=50)
    set_count: int = Field(gt=0, lt=100)
    rep_count: int = Field(gt=0, lt=100)
    equipment_name: str = Field(min_length=1, max_length=50)
    kg_weight: float = Field(gt=0, lt=1000)

class WorkoutExerciseCreate(WorkoutExerciseBase):
    pass

class WorkoutExerciseResponse(WorkoutExerciseBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workout_id: UUID
    created_at: datetime
    updated_at: datetime