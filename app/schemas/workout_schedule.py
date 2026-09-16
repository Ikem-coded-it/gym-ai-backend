from pydantic import BaseModel, Field

from app.schemas.workout_exercise import WorkoutExerciseCreate


class WorkoutScheduleCreate(BaseModel):
    day: str = Field(min_length=1, max_length=9, description="Lowercase weekday, e.g. wednesday")
    muscle_group: str = Field(min_length=1, max_length=50, description="e.g. push, legs, upper-body")
    exercises: list[WorkoutExerciseCreate] = Field(min_length=1)
