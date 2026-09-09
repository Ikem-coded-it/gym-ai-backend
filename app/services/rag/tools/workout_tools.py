# app/services/rag/tools/workout_tools.py
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from app.services.workout import (
    create_workout as create_workout_service,
    get_workout_for_day as get_workout_for_day_service,
    list_workouts as list_workouts_service,
)
from app.schemas.workout import WorkoutCreate
import json
from sqlalchemy.ext.asyncio import AsyncSession

class CreateWorkoutInput(BaseModel):
    day: str = Field(description="Lowercase weekday name, e.g. wednesday")
    muscle_group: str = Field(description="e.g. Push, Pull, Legs")


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

    async def create_workout(day: str, muscle_group: str) -> str:
        """Create a new workout day for the current user."""
        workout = await create_workout_service(
            db,
            WorkoutCreate(day=day.strip().lower(), muscle_group=muscle_group),
            user_id,
        )
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
            coroutine=create_workout,
            name="create_workout",
            description="Create a new workout day.",
            args_schema=CreateWorkoutInput,
        ),
    ]
