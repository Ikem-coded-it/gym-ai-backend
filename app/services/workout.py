from app.models.workout import Workout as workout_model
from app.models.workout_exercise import WorkoutExercise as workout_exercise_model
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.schemas.workout import WorkoutCreate, WorkoutResponse, WorkoutWithExercisesResponse
from app.schemas.workout_schedule import WorkoutScheduleCreate

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


async def delete_workout(db: AsyncSession, workout_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(workout_model)
        .where(
            workout_model.id == workout_id,
            workout_model.user_id == user_id,
        )
        .options(selectinload(workout_model.exercises))
    )
    workout = result.scalar_one_or_none()
    if workout is None:
        return False

    await db.delete(workout)
    await db.commit()
    return True


async def create_workout_with_exercises(
    db: AsyncSession,
    user_id: str,
    schedule: WorkoutScheduleCreate,
) -> WorkoutWithExercisesResponse:
    normalized_day = schedule.day.strip().lower()
    existing = await get_workout_for_day(db, user_id, normalized_day)
    if existing:
        raise ValueError(
            f"A workout is already scheduled for {normalized_day}. "
            "Choose another day or edit the existing workout."
        )

    new_workout = workout_model(
        day=normalized_day,
        muscle_group=schedule.muscle_group.strip(),
        user_id=user_id,
    )
    db.add(new_workout)
    await db.flush()
    await db.refresh(new_workout)

    db.add_all(
        workout_exercise_model(
            **exercise.model_dump(),
            workout_id=new_workout.id,
        )
        for exercise in schedule.exercises
    )
    await db.commit()

    result = await db.execute(
        select(workout_model)
        .where(workout_model.id == new_workout.id)
        .options(selectinload(workout_model.exercises))
    )
    workout = result.scalar_one()
    return WorkoutWithExercisesResponse.model_validate(workout)