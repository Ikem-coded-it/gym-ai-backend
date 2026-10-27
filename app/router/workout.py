from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logger import logger
from app.schemas.workout import WorkoutCreate, WorkoutResponse, WorkoutWithExercisesResponse
from app.schemas.workout_exercise import WorkoutExerciseCreate, WorkoutExerciseResponse
from app.services.workout import (
    add_exercise_to_workout,
    create_workout as create_workout_service,
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
    exercise: WorkoutExerciseCreate,
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
