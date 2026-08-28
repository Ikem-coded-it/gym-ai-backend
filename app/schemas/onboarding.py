# app/schemas/onboarding.py
from app.schemas.workout import WorkoutCreate
from app.schemas.workout_exercise import WorkoutExerciseCreate
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID

class OnboardingWorkout(BaseModel):
    workout: WorkoutCreate
    exercises: list[WorkoutExerciseCreate]

class OnboardingBase(BaseModel):
    workouts: list[OnboardingWorkout]
    
class OnboardingCreate(OnboardingBase):
    pass

class OnboardingResponse(OnboardingBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime