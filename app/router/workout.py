from typing import Annotated
from app.schemas.workout import WorkoutResponse, WorkoutCreate
from fastapi import APIRouter, Depends, HTTPException, status

from app.logger import logger
from app.models.workout import Workout as workout_model
from app.db import get_db

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.logger import logger
from auth import CurrentUser

router = APIRouter()

@router.post(
    "/", 
    response_model=WorkoutResponse, 
    status_code=status.HTTP_201_CREATED, 
    summary="Create a new workout", 
    description="Create a new workout with the given information",
)
async def create_workout(workout: WorkoutCreate, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    logger.info(f"New workout creation started: {workout}")
    new_workout = workout_model(
        **workout.model_dump(),
        user_id=current_user.id,
    )
    db.add(new_workout)
    await db.commit()
    await db.refresh(new_workout)
    return WorkoutResponse.model_validate(new_workout)

@router.get(
    "/",
    response_model=list[WorkoutResponse],
    status_code=status.HTTP_200_OK,
    summary="Get all workouts",
    description="Get all workouts for the current user",
)
async def get_workouts(current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    logger.info(f"Getting all workouts for user: {current_user.id}")
    workouts = await db.execute(select(workout_model).where(workout_model.user_id == current_user.id))
    return [WorkoutResponse.model_validate(workout) for workout in workouts.scalars().all()]