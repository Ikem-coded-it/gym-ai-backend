from datetime import UTC, datetime
from typing import Annotated
from app.schemas.onboarding import OnboardingCreate, OnboardingResponse
from app.schemas.workout import WorkoutResponse
from fastapi import APIRouter, Depends, HTTPException, status

from app.logger import logger
from app.models.workout import Workout as workout_model
from app.models.workout_exercise import WorkoutExercise as workout_exercise_model
from app.db import get_db

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from auth import CurrentUser

router = APIRouter()

@router.post(
    "/workouts",
    response_model=list[WorkoutResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create initial onboarding",
    description="Create initial onboarding workouts and exercises for the user",
)
async def create_onboarding_workouts(onboarding_data: OnboardingCreate, current_user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]):
    # Check if user is already onboarded
    if current_user.has_onboarded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already onboarded"
        )
        
    logger.info(f"New onboarding creation started")
    new_workouts = []
    new_workout_exercises = []

    for data in onboarding_data.workouts:
        new_workout = workout_model(
            **data.workout.model_dump(),
            user_id=current_user.id
        )
        db.add(new_workout)
        await db.flush()
        await db.refresh(new_workout)
        new_workouts.append(new_workout)

        for exercise in data.exercises:
            new_workout_exercise = workout_exercise_model(
                **exercise.model_dump(),
                workout_id=new_workout.id
            )
            new_workout_exercises.append(new_workout_exercise)

    db.add_all(new_workout_exercises)
    current_user.has_onboarded = True
    current_user.onboarding_completed_at = datetime.now(UTC)
    await db.commit()
    logger.info(f"New onboarding completed for user: {current_user.id}")
    return new_workouts