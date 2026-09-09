from app.models.workout import Workout as workout_model
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.schemas.workout import WorkoutCreate, WorkoutResponse, WorkoutWithExercisesResponse

async def list_workouts(db: AsyncSession, user_id: str):
    workouts = await db.execute(
        select(workout_model)
        .where(workout_model.user_id == user_id)
        .options(selectinload(workout_model.exercises))
    )

    return [
        WorkoutWithExercisesResponse.model_validate(workout)
        for workout in workouts.scalars().all()
    ]


async def get_workout_for_day(db: AsyncSession, user_id: str, day: str):
    normalized_day = day.strip().lower()
    workouts = await db.execute(
        select(workout_model)
        .where(workout_model.user_id == user_id)
        .where(workout_model.day == normalized_day)
        .options(selectinload(workout_model.exercises))
    )

    return [
        WorkoutWithExercisesResponse.model_validate(workout)
        for workout in workouts.scalars().all()
    ]


async def create_workout(db: AsyncSession, workout: WorkoutCreate, user_id: str):
    new_workout = workout_model(
        **workout.model_dump(),
        user_id=user_id,
    )
    db.add(new_workout)
    await db.commit()
    await db.refresh(new_workout)
    return WorkoutResponse.model_validate(new_workout)