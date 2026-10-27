from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.workout_exercise import WorkoutExerciseUpdate


class ExerciseEditCandidate(BaseModel):
    id: str
    name: str


class NewExerciseSlots(BaseModel):
    """Slots collected for adding a new exercise to a saved workout."""

    exercise: str | None = None
    set_count: int | None = None
    rep_count: int | None = None
    kg_weight: float | None = None
    equipment_name: str | None = None


class PendingExerciseEdit(BaseModel):
    """Slot-filling record for a saved-workout change.

    mode "update": day, exercise, and patch. mode "add": day and new_exercise.
    """

    mode: Literal["update", "add"] = "update"
    new_exercise: NewExerciseSlots = Field(default_factory=NewExerciseSlots)
    day: str | None = None
    patch: WorkoutExerciseUpdate | None = None
    # Set once the exercise slot is filled (single match or chip pick).
    exercise_id: str | None = None
    exercise_name: str | None = None
    # Two or more rows matched; waiting for the user to pick one.
    candidates: list[ExerciseEditCandidate] = Field(default_factory=list)
    # User messages for this edit, so a later reply (e.g. the day) can re-parse the original request.
    request_text: str = ""


class MatchedExercise(BaseModel):
    id: str
    exercise: str | None = None


class ExerciseEditParse(BaseModel):
    matches: list[MatchedExercise] = Field(default_factory=list)
    confidence: float = 0.0
    set_count: int | None = None
    rep_count: int | None = None
    kg_weight: float | None = None
    equipment_name: str | None = None


class DayExerciseRow(BaseModel):
    id: str
    workout_id: str
    exercise: str
    set_count: int | None = None
    rep_count: int | None = None
    kg_weight: float | None = None
    equipment_name: str | None = None
