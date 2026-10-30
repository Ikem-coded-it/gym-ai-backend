from datetime import UTC, datetime
from typing import Annotated
from app.schemas.onboarding import (
    GenerateRoutineRequest,
    GenerateRoutineResponse,
    OnboardingCreate,
    OnboardingResponse,
)
from app.schemas.workout import WorkoutResponse
from fastapi import APIRouter, Depends, HTTPException, status

from app.logger import logger
from app.models.workout import Workout as workout_model
from app.schemas.exercise_set import ExerciseSetCreate
from app.schemas.workout_exercise import WorkoutExerciseCreate
from app.services.exercise_suggestion import suggest_exercises
from app.services.workout import build_workout_exercise
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
            day=data.workout.day.strip().lower(),
            muscle_group=data.workout.muscle_group.strip(),
            user_id=current_user.id
        )
        db.add(new_workout)
        await db.flush()
        await db.refresh(new_workout)
        new_workouts.append(new_workout)

        for exercise in data.exercises:
            new_workout_exercises.append(
                build_workout_exercise(new_workout.id, exercise)
            )

    db.add_all(new_workout_exercises)
    current_user.has_onboarded = True
    current_user.onboarding_completed_at = datetime.now(UTC)
    await db.commit()
    logger.info(f"New onboarding completed for user: {current_user.id}")
    return new_workouts


@router.post(
    "/generate-routine",
    response_model=GenerateRoutineResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a routine for the chosen muscle groups",
    description=(
        "Searches the fitness knowledge base for the selected focus areas and returns "
        "suggested exercises with sets, reps and weight. Nothing is saved; the user "
        "reviews and edits the result during onboarding."
    ),
)
async def generate_onboarding_routine(
    request: GenerateRoutineRequest,
    current_user: CurrentUser,
):
    logger.info(f"Generating routine for {current_user.id}: {request.focus_areas}")
    suggested = await suggest_exercises(",".join(request.focus_areas))
    exercises = [
        WorkoutExerciseCreate(
            exercise=draft.exercise,
            equipment_name=draft.equipment_name,
            sets=[
                ExerciseSetCreate(
                    rep_count=draft_set.rep_count,
                    kg_weight=draft_set.kg_weight,
                    notes=draft_set.notes,
                )
                for draft_set in draft.sets
            ],
        )
        for draft in suggested
        if draft.sets
    ]
    if not exercises:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not generate a routine right now. Please try again.",
        )
    return GenerateRoutineResponse(exercises=exercises)
