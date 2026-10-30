# app/schemas/onboarding.py
from app.schemas.workout import WorkoutBase
from app.schemas.workout_exercise import WorkoutExerciseCreate
from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import datetime
from uuid import UUID

class OnboardingWorkout(BaseModel):
    workout: WorkoutBase
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

FOCUS_AREA_VALUES = frozenset(
    {
        "full-body",
        "upper-body",
        "lower-body",
        "chest",
        "back",
        "shoulders",
        "legs",
        "arms",
        "core",
    }
)


class GenerateRoutineRequest(BaseModel):
    """Focus areas (muscle groups) to build one day's routine for."""

    focus_areas: list[str] = Field(min_length=1, max_length=len(FOCUS_AREA_VALUES))

    @field_validator("focus_areas")
    @classmethod
    def _known_focus_areas(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for area in value:
            normalized = area.strip().lower()
            if normalized not in FOCUS_AREA_VALUES:
                raise ValueError(f"Unknown focus area: {area}")
            if normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned


class GenerateRoutineResponse(BaseModel):
    """Suggested exercises, each with its sets, for the user to review before saving."""

    exercises: list[WorkoutExerciseCreate]
