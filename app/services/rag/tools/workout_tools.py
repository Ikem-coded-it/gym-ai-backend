import json

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.workout_exercise import WorkoutExerciseCreate, WorkoutExerciseUpdate
from app.schemas.workout_schedule import WorkoutScheduleCreate
from app.services.rag.tools.datetime_tools import current_weekday
from app.services.workout import (
    create_workout_with_exercises as create_workout_with_exercises_service,
    delete_workout_for_day as delete_workout_for_day_service,
    get_workout_for_day as get_workout_for_day_service,
    list_workouts as list_workouts_service,
    update_exercise_for_day as update_exercise_for_day_service,
)



class CreateWorkoutWithExercisesInput(BaseModel):
    day: str = Field(description="Lowercase weekday name, e.g. wednesday")
    muscle_group: str = Field(
        description="Training focus for the day, e.g. push, pull, legs, upper-body"
    )
    exercises: list[WorkoutExerciseCreate] = Field(
        min_length=1,
        description=(
            "At least one exercise: name, equipment, and its sets "
            "(one entry per set with rep_count, kg_weight, optional notes)"
        ),
    )


class GetWorkoutsForDayInput(BaseModel):
    day: str = Field(description="Lowercase weekday name, e.g. wednesday")


class DeleteWorkoutForDayInput(BaseModel):
    day: str = Field(
        description="Lowercase weekday name of the workout to delete, e.g. monday"
    )


class UpdateWorkoutExerciseInput(BaseModel):
    exercise_id: str = Field(
        description="UUID of the saved workout exercise row to update"
    )
    day: str | None = Field(
        default=None,
        description="Lowercase weekday. Omit to use today in the app timezone.",
    )
    set_count: int | None = Field(default=None, description="New set count, if changing")
    rep_count: int | None = Field(default=None, description="New rep count, if changing")
    kg_weight: float | None = Field(
        default=None,
        description="New weight in kg, if changing",
    )
    equipment_name: str | None = Field(
        default=None,
        description="New equipment name, if changing",
    )


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

    async def delete_workout_for_day(day: str) -> str:
        """Delete the user's scheduled workout for a specific weekday."""
        result = await delete_workout_for_day_service(
            db,
            user_id,
            day.strip().lower(),
        )
        return json.dumps(result)

    async def update_workout_exercise(
        exercise_id: str,
        day: str | None = None,
        set_count: int | None = None,
        rep_count: int | None = None,
        kg_weight: float | None = None,
        equipment_name: str | None = None,
    ) -> str:
        """Patch one already-saved exercise by id. Do not match by free-text name."""
        try:
            patch = WorkoutExerciseUpdate(
                set_count=set_count,
                rep_count=rep_count,
                kg_weight=kg_weight,
                equipment_name=equipment_name,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "updated": False,
                    "reason": "invalid_patch",
                    "message": str(exc),
                }
            )
        result = await update_exercise_for_day_service(
            db,
            user_id,
            exercise_id,
            patch,
            day=(day.strip().lower() if day else current_weekday()),
        )
        return json.dumps(result)

    return [
        StructuredTool.from_function(
            coroutine=get_workouts_for_day,
            name="get_workouts_for_day",
            description=(
                "Get workouts scheduled for one specific weekday only. "
                "REQUIRED after the user picks a day during workout scheduling (Step 1b) "
                "before asking for muscle group. "
                "Also use when the user asks about today or a particular day."
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
        StructuredTool.from_function(
            coroutine=delete_workout_for_day,
            name="delete_workout_for_day",
            description=(
                "Delete the user's scheduled workout for one weekday (and its exercises). "
                "Use when the user asks to remove, cancel, or delete a day's workout "
                "(e.g. 'delete Monday's workout'). Pass the weekday as lowercase "
                "(monday, tuesday, etc.). Do not use this to change sets, reps, or weight."
            ),
            args_schema=DeleteWorkoutForDayInput,
        ),
        StructuredTool.from_function(
            coroutine=update_workout_exercise,
            name="update_workout_exercise",
            description=(
                "Update one already-saved exercise by exercise_id (sets, reps, weight, "
                "or equipment). Use after you know the row id from get_workouts_for_day. "
                "Do not pass a free-text exercise name as the write key. "
                "Omit day to update today's workout."
            ),
            args_schema=UpdateWorkoutExerciseInput,
        ),
    ]
