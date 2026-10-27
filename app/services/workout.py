from datetime import UTC, datetime
from uuid import UUID

from app.models.workout import Workout as workout_model
from app.models.workout_exercise import WorkoutExercise as workout_exercise_model
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.schemas.exercise_edit import DayExerciseRow
from app.schemas.workout import WorkoutCreate, WorkoutResponse, WorkoutWithExercisesResponse
from app.schemas.workout_exercise import (
    WorkoutExerciseCreate,
    WorkoutExerciseResponse,
    WorkoutExerciseUpdate,
)
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


async def delete_workout_for_day(
    db: AsyncSession,
    user_id: str,
    day: str,
) -> dict:
    normalized_day = day.strip().lower()
    result = await db.execute(
        select(workout_model)
        .where(workout_model.user_id == user_id)
        .where(workout_model.day == normalized_day)
        .options(selectinload(workout_model.exercises))
    )
    workouts = result.scalars().all()
    if not workouts:
        return {
            "deleted": False,
            "day": normalized_day,
            "message": f"No workout scheduled for {normalized_day}.",
        }

    muscle_groups = [workout.muscle_group for workout in workouts]
    for workout in workouts:
        await db.delete(workout)
    await db.commit()

    return {
        "deleted": True,
        "day": normalized_day,
        "count": len(workouts),
        "muscle_groups": muscle_groups,
        "message": f"Deleted {len(workouts)} workout(s) for {normalized_day}.",
    }


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


def _compact_exercise(exercise, workout_id: str) -> DayExerciseRow:
    return DayExerciseRow(
        id=str(exercise.id),
        workout_id=str(workout_id),
        exercise=exercise.exercise,
        set_count=exercise.set_count,
        rep_count=exercise.rep_count,
        kg_weight=exercise.kg_weight,
        equipment_name=exercise.equipment_name,
    )


async def list_exercises_for_day(
    db: AsyncSession,
    user_id: str,
    day: str,
) -> list[DayExerciseRow]:
    workouts = await get_workout_for_day(db, user_id, day)
    rows: list[DayExerciseRow] = []
    for workout in workouts:
        for exercise in workout.exercises:
            rows.append(_compact_exercise(exercise, str(workout.id)))
    return rows


async def _insert_exercise(
    db: AsyncSession,
    workout: workout_model,
    exercise: WorkoutExerciseCreate,
) -> workout_exercise_model:
    values = exercise.model_dump()
    if values.get("kg_weight") is not None:
        values["kg_weight"] = int(round(float(values["kg_weight"])))
    new_exercise = workout_exercise_model(**values, workout_id=workout.id)
    db.add(new_exercise)
    await db.commit()
    await db.refresh(new_exercise)
    return new_exercise


async def add_exercise_to_workout(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise: WorkoutExerciseCreate,
) -> WorkoutExerciseResponse | None:
    """Append one exercise to an owned workout. None when the workout isn't the user's."""
    result = await db.execute(
        select(workout_model)
        .where(workout_model.id == workout_id)
        .where(workout_model.user_id == user_id)
    )
    workout = result.scalar_one_or_none()
    if workout is None:
        return None
    new_exercise = await _insert_exercise(db, workout, exercise)
    return WorkoutExerciseResponse.model_validate(new_exercise)


async def delete_exercise_from_workout(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise_id: str,
) -> bool:
    """Delete one exercise from an owned workout. False when it isn't found."""
    result = await db.execute(
        select(workout_exercise_model)
        .join(workout_model)
        .where(workout_exercise_model.id == exercise_id)
        .where(workout_exercise_model.workout_id == workout_id)
        .where(workout_model.user_id == user_id)
    )
    exercise = result.scalar_one_or_none()
    if exercise is None:
        return False
    await db.delete(exercise)
    await db.commit()
    return True


async def add_exercise_to_day(
    db: AsyncSession,
    user_id: str,
    day: str,
    exercise: WorkoutExerciseCreate,
) -> dict:
    """Append one exercise to the user's existing workout for `day`."""
    normalized_day = day.strip().lower()
    result = await db.execute(
        select(workout_model)
        .where(workout_model.user_id == user_id)
        .where(workout_model.day == normalized_day)
    )
    workout = result.scalars().first()
    if workout is None:
        return {
            "added": False,
            "reason": "no_workout",
            "day": normalized_day,
            "message": f"No workout scheduled for {normalized_day}.",
        }

    new_exercise = await _insert_exercise(db, workout, exercise)

    return {
        "added": True,
        "day": normalized_day,
        "workout_id": str(workout.id),
        "muscle_group": workout.muscle_group,
        "exercise": WorkoutExerciseResponse.model_validate(new_exercise).model_dump(
            mode="json"
        ),
        "message": f"Added {new_exercise.exercise} to {normalized_day}.",
    }


async def update_exercise_for_day(
    db: AsyncSession,
    user_id: str,
    exercise_id: str,
    patch: WorkoutExerciseUpdate,
    day: str | None = None,
) -> dict:
    """Patch one owned exercise. Optionally require it to belong to `day`."""
    normalized_day = day.strip().lower() if day else None
    try:
        exercise_uuid = str(UUID(str(exercise_id)))
    except (TypeError, ValueError):
        exercise_uuid = str(exercise_id)
    result = await db.execute(
        select(workout_exercise_model)
        .join(workout_model)
        .where(workout_exercise_model.id == exercise_uuid)
        .where(workout_model.user_id == user_id)
        .options(selectinload(workout_exercise_model.workout))
    )
    exercise = result.scalar_one_or_none()
    if exercise is None:
        day_exercises = (
            await list_exercises_for_day(db, user_id, normalized_day)
            if normalized_day
            else []
        )
        return {
            "updated": False,
            "reason": "not_found",
            "day": normalized_day,
            "exercises": [row.model_dump(mode="json") for row in day_exercises],
            "message": "No matching exercise found for this user.",
        }

    workout_day = str(exercise.workout.day).strip().lower()
    if normalized_day and workout_day != normalized_day:
        day_exercises = await list_exercises_for_day(db, user_id, normalized_day)
        return {
            "updated": False,
            "reason": "not_found",
            "day": normalized_day,
            "exercises": [row.model_dump(mode="json") for row in day_exercises],
            "message": f"That exercise is not on {normalized_day}.",
        }

    changed_fields: list[str] = []
    updates = patch.model_dump(exclude_unset=True)
    if "kg_weight" in updates and updates["kg_weight"] is not None:
        updates["kg_weight"] = int(round(float(updates["kg_weight"])))

    for field, value in updates.items():
        if value is None:
            continue
        setattr(exercise, field, value)
        changed_fields.append(field)

    exercise.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(exercise)

    return {
        "updated": True,
        "day": workout_day,
        "workout_id": str(exercise.workout_id),
        "exercise": WorkoutExerciseResponse.model_validate(exercise).model_dump(
            mode="json"
        ),
        "changed_fields": changed_fields,
        "message": f"Updated {exercise.exercise} for {workout_day}.",
    }