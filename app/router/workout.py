from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logger import logger
from app.schemas.workout import WorkoutCreate, WorkoutResponse, WorkoutWithExercisesResponse
from app.schemas.exercise_set import (
    ExerciseSetCreate,
    ExerciseSetResponse,
    ExerciseSetUpdate,
)
from app.schemas.workout_exercise import WorkoutExerciseAdd, WorkoutExerciseResponse
from app.services.workout import (
    add_exercise_to_workout,
    add_set_to_exercise,
    create_workout as create_workout_service,
    delete_exercise_from_workout,
    delete_exercise_set,
    update_exercise_set,
    delete_workout as delete_workout_service,
    list_workouts as list_workouts_service,
)
from auth import CurrentUser

router = APIRouter()


@router.post(
    "/",
    response_model=WorkoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workout",
    description="Create a new workout with the given information",
)
async def create_workout(
    workout: WorkoutCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # TODO: Check the user has a routine for the day
    logger.info(f"New workout creation started: {workout}")
    return await create_workout_service(db, workout, str(current_user.id))


@router.get(
    "/",
    response_model=list[WorkoutWithExercisesResponse],
    status_code=status.HTTP_200_OK,
    summary="Get all workouts",
    description="Get all workouts for the current user",
)
async def get_workouts(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info(f"Getting all workouts for user: {current_user.id}")
    return await list_workouts_service(db, str(current_user.id))


@router.post(
    "/{workout_id}/exercises",
    response_model=WorkoutExerciseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an exercise to a workout",
    description="Append an exercise to a workout owned by the current user",
)
async def add_workout_exercise(
    workout_id: str,
    exercise: WorkoutExerciseAdd,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info(f"Adding exercise to workout {workout_id} for user: {current_user.id}")
    created = await add_exercise_to_workout(
        db,
        str(current_user.id),
        workout_id,
        exercise,
    )
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workout not found",
        )
    return created


@router.delete(
    "/{workout_id}/exercises/{exercise_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an exercise from a workout",
    description="Delete one exercise from a workout owned by the current user",
)
async def delete_workout_exercise(
    workout_id: str,
    exercise_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info(
        f"Deleting exercise {exercise_id} from workout {workout_id} for user: {current_user.id}"
    )
    deleted = await delete_exercise_from_workout(
        db,
        str(current_user.id),
        workout_id,
        exercise_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exercise not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workout_id}/exercises/{exercise_id}/sets",
    response_model=ExerciseSetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a set to an exercise",
    description="Append a set (reps, weight, optional notes) to an exercise owned by the current user",
)
async def add_exercise_set(
    workout_id: str,
    exercise_id: str,
    new_set: ExerciseSetCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    created = await add_set_to_exercise(
        db, str(current_user.id), workout_id, exercise_id, new_set
    )
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exercise not found",
        )
    return created


@router.patch(
    "/{workout_id}/exercises/{exercise_id}/sets/{set_id}",
    response_model=ExerciseSetResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a set",
    description="Change the reps, weight or notes of one set",
)
async def update_set(
    workout_id: str,
    exercise_id: str,
    set_id: str,
    patch: ExerciseSetUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    updated = await update_exercise_set(
        db, str(current_user.id), workout_id, exercise_id, set_id, patch
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Set not found",
        )
    return updated


@router.delete(
    "/{workout_id}/exercises/{exercise_id}/sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a set",
    description="Delete one set from an exercise owned by the current user",
)
async def delete_set(
    workout_id: str,
    exercise_id: str,
    set_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    deleted = await delete_exercise_set(
        db, str(current_user.id), workout_id, exercise_id, set_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Set not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{workout_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workout",
    description="Delete a workout owned by the current user",
)
async def delete_workout(
    workout_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    logger.info(f"Deleting workout {workout_id} for user: {current_user.id}")
    deleted = await delete_workout_service(
        db,
        workout_id,
        str(current_user.id),
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workout not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
