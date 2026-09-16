import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.workout_exercise import WorkoutExerciseCreate
from app.schemas.workout_schedule import WorkoutScheduleCreate
from app.services.workout import (
    create_workout_with_exercises as create_workout_with_exercises_service,
    get_workout_for_day as get_workout_for_day_service,
    list_workouts as list_workouts_service,
)



class CreateWorkoutWithExercisesInput(BaseModel):
    day: str = Field(description="Lowercase weekday name, e.g. wednesday")
    muscle_group: str = Field(
        description="Training focus for the day, e.g. push, pull, legs, upper-body"
    )
    exercises: list[WorkoutExerciseCreate] = Field(
        min_length=1,
        description="At least one exercise with sets, reps, weight, and equipment",
    )


class GetWorkoutsForDayInput(BaseModel):
    day: str = Field(description="Lowercase weekday name, e.g. wednesday")


def make_workout_tools(db: AsyncSession, user_id: str):
    async def list_workouts() -> str:
        """Return all workouts and exercises for the current user."""
        workouts = await list_workouts_service(db, user_id)
        return json.dumps([w.model_dump(mode="json") for w in workouts])

    async def get_workouts_for_day(day: str) -> str:
        """Return workouts scheduled for a specific weekday only."""
        normalized_day = day.strip().lower()
        workouts = await get_workout_for_day_service(db, user_id, normalized_day)
        return json.dumps(
            {
                "day": normalized_day,
                "has_workout": len(workouts) > 0,
                "workouts": [w.model_dump(mode="json") for w in workouts],
            }
        )

    async def create_workout_with_exercises(
        day: str,
        muscle_group: str,
        exercises: list[WorkoutExerciseCreate],
    ) -> str:
        """Create a workout day with exercises in one transaction."""
        schedule = WorkoutScheduleCreate(
            day=day.strip().lower(),
            muscle_group=muscle_group.strip(),
            exercises=[
                WorkoutExerciseCreate.model_validate(exercise.model_dump())
                for exercise in exercises
            ],
        )
        workout = await create_workout_with_exercises_service(db, user_id, schedule)
        return workout.model_dump_json()

    return [
        StructuredTool.from_function(
            coroutine=get_workouts_for_day,
            name="get_workouts_for_day",
            description=(
                "Get workouts scheduled for one specific weekday only. "
                "Use after get_current_date when the user asks about today or a particular day."
            ),
            args_schema=GetWorkoutsForDayInput,
        ),
        StructuredTool.from_function(
            coroutine=list_workouts,
            name="list_workouts",
            description=(
                "Get the user's full workout schedule. "
                "Do not use this for 'today' questions — use get_workouts_for_day instead."
            ),
        ),
        StructuredTool.from_function(
            coroutine=create_workout_with_exercises,
            name="create_workout_with_exercises",
            description=(
                "Save a complete workout (day, muscle group, and exercises) after the user "
                "has reviewed and explicitly confirmed. Requires at least one exercise. "
                "Do not call until the user confirms the summary."
            ),
            args_schema=CreateWorkoutWithExercisesInput,
        ),
    ]
