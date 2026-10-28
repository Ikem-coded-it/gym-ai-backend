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
    WorkoutExerciseAdd,
    WorkoutExerciseCreate,
    WorkoutExerciseResponse,
    WorkoutExerciseUpdate,
)
from app.schemas.workout_schedule import WorkoutScheduleCreate
from app.models.exercise_set import ExerciseSet as exercise_set_model
from app.schemas.exercise_set import (
    ExerciseSetCreate,
    ExerciseSetResponse,
    ExerciseSetUpdate,
)


def _exercises_loader():
    """Eager-load a workout's exercises together with their sets (async can't lazy-load)."""
    return selectinload(workout_model.exercises).selectinload(
        workout_exercise_model.exercise_sets
    )


def build_workout_exercise(
    workout_id: str,
    exercise: WorkoutExerciseCreate | WorkoutExerciseAdd,
) -> workout_exercise_model:
    """Exercise row with one ExerciseSet per entry in `exercise.sets`."""
    return workout_exercise_model(
        workout_id=workout_id,
        exercise=exercise.exercise.strip(),
        equipment_name=exercise.equipment_name,
        exercise_sets=[
            exercise_set_model(
                rep_count=new_set.rep_count,
                kg_weight=new_set.kg_weight,
                notes=new_set.notes,
            )
            for new_set in exercise.sets
        ],
    )


async def list_workouts(db: AsyncSession, user_id: str):
    workouts = await db.execute(
        select(workout_model)
        .where(workout_model.user_id == user_id)
        .options(_exercises_loader())
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
        .options(_exercises_loader())
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
        .options(_exercises_loader())
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
        .options(_exercises_loader())
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
        build_workout_exercise(new_workout.id, exercise)
        for exercise in schedule.exercises
    )
    await db.commit()

    result = await db.execute(
        select(workout_model)
        .where(workout_model.id == new_workout.id)
        .options(_exercises_loader())
    )
    workout = result.scalar_one()
    return WorkoutWithExercisesResponse.model_validate(workout)


def _compact_exercise(exercise, workout_id: str) -> DayExerciseRow:
    """Chat/agent view of an exercise: set count plus the first set's reps and weight."""
    sets = exercise.exercise_sets
    first = sets[0] if sets else None
    return DayExerciseRow(
        id=str(exercise.id),
        workout_id=str(workout_id),
        exercise=exercise.exercise,
        set_count=len(sets),
        rep_count=first.rep_count if first else None,
        kg_weight=first.kg_weight if first else None,
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


async def _load_exercise(
    db: AsyncSession,
    exercise_id: str,
    *,
    user_id: str | None = None,
    workout_id: str | None = None,
) -> workout_exercise_model | None:
    """One exercise with its sets (and workout), optionally scoped to its owner/workout."""
    query = (
        select(workout_exercise_model)
        .join(workout_model)
        .where(workout_exercise_model.id == exercise_id)
        .options(
            selectinload(workout_exercise_model.exercise_sets),
            selectinload(workout_exercise_model.workout),
        )
        .execution_options(populate_existing=True)
    )
    if user_id is not None:
        query = query.where(workout_model.user_id == user_id)
    if workout_id is not None:
        query = query.where(workout_exercise_model.workout_id == workout_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _insert_exercise(
    db: AsyncSession,
    workout: workout_model,
    exercise: WorkoutExerciseCreate,
) -> workout_exercise_model:
    new_exercise = build_workout_exercise(workout.id, exercise)
    db.add(new_exercise)
    await db.commit()
    loaded = await _load_exercise(db, new_exercise.id)
    assert loaded is not None
    return loaded


async def add_exercise_to_workout(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise: WorkoutExerciseAdd,
) -> WorkoutExerciseResponse | None:
    """Append one exercise (with optional sets) to an owned workout. None if not the user's."""
    result = await db.execute(
        select(workout_model)
        .where(workout_model.id == workout_id)
        .where(workout_model.user_id == user_id)
    )
    workout = result.scalar_one_or_none()
    if workout is None:
        return None

    new_exercise = build_workout_exercise(workout.id, exercise)
    db.add(new_exercise)
    await db.commit()
    loaded = await _load_exercise(db, new_exercise.id)
    assert loaded is not None
    return WorkoutExerciseResponse.model_validate(loaded)


async def delete_exercise_from_workout(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise_id: str,
) -> bool:
    """Delete one exercise from an owned workout. False when it isn't found."""
    exercise = await _load_exercise(
        db, exercise_id, user_id=user_id, workout_id=workout_id
    )
    if exercise is None:
        return False
    await db.delete(exercise)
    await db.commit()
    return True


async def add_set_to_exercise(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise_id: str,
    new_set: ExerciseSetCreate,
) -> ExerciseSetResponse | None:
    """Append a set to an owned exercise. None when the exercise isn't found."""
    exercise = await _load_exercise(
        db, exercise_id, user_id=user_id, workout_id=workout_id
    )
    if exercise is None:
        return None
    row = exercise_set_model(
        workout_exercise_id=exercise.id,
        rep_count=new_set.rep_count,
        kg_weight=new_set.kg_weight,
        notes=new_set.notes,
    )
    db.add(row)
    exercise.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return ExerciseSetResponse.model_validate(row)


async def _get_owned_set(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise_id: str,
    set_id: str,
) -> exercise_set_model | None:
    result = await db.execute(
        select(exercise_set_model)
        .join(workout_exercise_model)
        .join(workout_model)
        .where(exercise_set_model.id == set_id)
        .where(exercise_set_model.workout_exercise_id == exercise_id)
        .where(workout_exercise_model.workout_id == workout_id)
        .where(workout_model.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def update_exercise_set(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise_id: str,
    set_id: str,
    patch: ExerciseSetUpdate,
) -> ExerciseSetResponse | None:
    """Patch one set's reps, weight or notes. None when it isn't found."""
    row = await _get_owned_set(db, user_id, workout_id, exercise_id, set_id)
    if row is None:
        return None
    for field, value in patch.model_dump(exclude_unset=True).items():
        if field == "rep_count" and value is None:
            continue  # reps can be cleared only by deleting the set
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return ExerciseSetResponse.model_validate(row)


async def delete_exercise_set(
    db: AsyncSession,
    user_id: str,
    workout_id: str,
    exercise_id: str,
    set_id: str,
) -> bool:
    row = await _get_owned_set(db, user_id, workout_id, exercise_id, set_id)
    if row is None:
        return False
    await db.delete(row)
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
    """Patch one owned exercise. Optionally require it to belong to `day`.

    set_count adds or removes sets at the end; rep_count and kg_weight apply to every set.
    """
    normalized_day = day.strip().lower() if day else None
    try:
        exercise_uuid = str(UUID(str(exercise_id)))
    except (TypeError, ValueError):
        exercise_uuid = str(exercise_id)
    exercise = await _load_exercise(db, exercise_uuid, user_id=user_id)
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
    now = datetime.now(UTC)

    if updates.get("equipment_name") is not None:
        exercise.equipment_name = updates["equipment_name"]
        changed_fields.append("equipment_name")

    sets = list(exercise.exercise_sets)
    for field in ("rep_count", "kg_weight"):
        value = updates.get(field)
        if value is None:
            continue
        for row in sets:
            setattr(row, field, value)
            row.updated_at = now
        changed_fields.append(field)

    target_sets = updates.get("set_count")
    if target_sets is not None:
        template = sets[-1] if sets else None
        while len(sets) > target_sets:
            await db.delete(sets.pop())
        while len(sets) < target_sets:
            new_row = exercise_set_model(
                workout_exercise_id=exercise.id,
                rep_count=template.rep_count if template else None,
                kg_weight=template.kg_weight if template else None,
            )
            db.add(new_row)
            sets.append(new_row)
        changed_fields.append("set_count")

    exercise.updated_at = now
    await db.commit()
    refreshed = await _load_exercise(db, exercise_uuid)
    assert refreshed is not None

    return {
        "updated": True,
        "day": workout_day,
        "workout_id": str(refreshed.workout_id),
        "exercise": WorkoutExerciseResponse.model_validate(refreshed).model_dump(
            mode="json"
        ),
        "changed_fields": changed_fields,
        "message": f"Updated {refreshed.exercise} for {workout_day}.",
    }
