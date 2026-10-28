import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.schemas.exercise_edit import NewExerciseSlots, PendingExerciseEdit
from app.schemas.exercise_set import ExerciseSetCreate
from app.schemas.scheduling_state import SchedulingState
from app.schemas.workout_exercise import WorkoutExerciseCreate
from app.services.exercise_edit import (
    DIRECTIVE_HEADER,
    ExerciseEditTurnPlan,
    resolve_edit_day,
)
from app.services.workout import (
    add_exercise_to_day,
    get_workout_for_day,
    list_exercises_for_day,
)
from app.utils.agent import parse_weekday_from_message
from app.utils.exercise_extractor import extract_exercises
from app.utils.exercise_match import fallback_patch_from_message, normalize_exercise_name
from app.utils.schedule_intent_classifier import (
    UserIntentResult,
    classify_user_intent,
    is_cancel_schedule_intent,
)

ADD_SAVED_EXERCISE_THRESHOLD = 0.65
SETS_X_REPS_PATTERN = re.compile(r"\b(\d+)\s*[x×]\s*(\d+)\b", re.IGNORECASE)


def is_add_saved_exercise_intent(user_intent: UserIntentResult) -> bool:
    return (
        user_intent.intent == "add_saved_exercise"
        and float(user_intent.confidence) >= ADD_SAVED_EXERCISE_THRESHOLD
    )


def _is_bare_day_reply(message: str) -> bool:
    """A short reply like "thursday" or the day chip, which names no exercise."""
    return parse_weekday_from_message(message) is not None and len(message.split()) <= 3


def _uniform_sets(message: str) -> list[ExerciseSetCreate]:
    """Sets from a one-line plan like "3x10", or "3 sets of 10 reps @ 40kg"."""
    grid = SETS_X_REPS_PATTERN.search(message)
    patch = fallback_patch_from_message(message)
    if grid:
        count, reps = int(grid.group(1)), int(grid.group(2))
    elif patch is not None and patch.rep_count:
        count, reps = patch.set_count or 1, patch.rep_count
    else:
        return []
    kg = patch.kg_weight if patch is not None else None
    return [
        ExerciseSetCreate(rep_count=reps, kg_weight=kg) for _ in range(min(count, 50))
    ]


async def _extract_slots(message: str) -> NewExerciseSlots:
    """Exercise name, equipment and sets this single message provides."""
    slots = NewExerciseSlots()
    if not _is_bare_day_reply(message):
        drafts = await extract_exercises(message)
        if drafts:
            draft = drafts[0]
            slots.exercise = draft.exercise.strip() or None
            slots.equipment_name = (draft.equipment_name or "").strip() or None
            slots.sets = [
                ExerciseSetCreate(
                    rep_count=draft_set.rep_count,
                    kg_weight=draft_set.kg_weight,
                    notes=draft_set.notes,
                )
                for draft_set in draft.sets
                if draft_set.rep_count > 0
            ]
    if not slots.sets:
        slots.sets = _uniform_sets(message)
    return slots


def _merge_slots(old: NewExerciseSlots, new: NewExerciseSlots) -> NewExerciseSlots:
    """Newer sets and equipment win. The name is kept once set unless the new message
    is a full form submit (it has sets), so a loose reply can't overwrite it."""
    merged = old.model_copy()
    if new.sets:
        merged.sets = new.sets
    if new.equipment_name:
        merged.equipment_name = new.equipment_name
    if new.exercise and (merged.exercise is None or new.sets):
        merged.exercise = new.exercise
    return merged


def _ask_day_directive(slots: NewExerciseSlots) -> str:
    known = f" (exercise: {slots.exercise})" if slots.exercise else ""
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"The user wants to add an exercise to a saved workout{known} but did not say "
        "which day. Ask ONLY which weekday's workout to add it to. The chat UI shows a "
        "day picker. Do NOT call tools. Do NOT start scheduling. Do NOT assume today."
    )


def _no_workout_directive(day: str) -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"There is no saved workout on {day}, so nothing to add the exercise to. "
        "Tell the user that and ask which other day's workout to add it to. "
        "Do NOT call tools. Do NOT start the new-workout scheduling flow unless they ask."
    )


def _missing_directive(day: str, missing: list[str]) -> str:
    listed = ", ".join(missing)
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"Adding an exercise to {day}. Still missing: {listed}.\n"
        "The chat UI shows an exercise form directly below your message, pre-filled with "
        "what the user already gave. In 1-2 short sentences, tell them to fill in the "
        "remaining fields in the form: the sets, each with its own reps and weight "
        "(equipment is optional). "
        "Do NOT list the fields as questions. Do NOT call tools. "
        "Do NOT start scheduling. Do NOT claim it was added."
    )


def _duplicate_directive(day: str, name: str) -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"{name} is already on the {day} workout, so nothing was added. Tell the user, "
        "and say they can change its sets, reps or weight instead. "
        "Do NOT call tools. Do NOT start scheduling."
    )


def _added_directive(result: dict) -> str:
    exercise = result.get("exercise") or {}
    parts = []
    for saved_set in exercise.get("exercise_sets") or []:
        piece = f"{saved_set.get('rep_count')} reps"
        if saved_set.get("kg_weight"):
            piece += f" @ {saved_set['kg_weight']}kg"
        parts.append(piece)
    summary = f" ({len(parts)} sets: {'; '.join(parts)})" if parts else ""
    return (
        f"{DIRECTIVE_HEADER}\n"
        "An exercise was already added to the saved workout. Do NOT call tools. "
        "Do NOT start scheduling. Do NOT ask the user to confirm.\n"
        f"Tell them {exercise.get('exercise', 'the exercise')}{summary} was added to "
        f"{result.get('day', 'that day')}'s workout. Keep it to 1-2 short sentences."
    )


def _failed_directive(message: str) -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"The exercise could not be added ({message}). Tell the user it was not saved. "
        "Do NOT claim success. Do NOT start scheduling."
    )


async def _decide(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    pending: PendingExerciseEdit,
    user_intent: UserIntentResult,
) -> ExerciseEditTurnPlan:
    """Ask for the first empty slot, or add the exercise once all are filled."""
    slots = pending.new_exercise

    def waiting(directive: str) -> ExerciseEditTurnPlan:
        state.pending_exercise_edit = pending
        return ExerciseEditTurnPlan(
            handled=True, state=state, directive=directive, user_intent=user_intent
        )

    def finished(directive: str) -> ExerciseEditTurnPlan:
        state.pending_exercise_edit = None
        return ExerciseEditTurnPlan(
            handled=True, state=state, directive=directive, user_intent=user_intent
        )

    if pending.day is None:
        return waiting(_ask_day_directive(slots))

    day = pending.day
    if not await get_workout_for_day(db, user_id, day):
        logger.info("No workout on %s to add an exercise to", day)
        pending.day = None
        return waiting(_no_workout_directive(day))

    missing = [
        label
        for label, filled in (
            ("exercise name", bool(slots.exercise)),
            ("at least one set (reps and weight)", bool(slots.sets)),
        )
        if not filled
    ]
    if missing:
        return waiting(_missing_directive(day, missing))

    name = slots.exercise or ""
    existing = await list_exercises_for_day(db, user_id, day)
    if any(
        normalize_exercise_name(row.exercise) == normalize_exercise_name(name)
        for row in existing
    ):
        return finished(_duplicate_directive(day, name))

    try:
        exercise = WorkoutExerciseCreate(
            exercise=name,
            equipment_name=slots.equipment_name,
            sets=slots.sets,
        )
    except Exception as exc:
        logger.warning("Invalid new exercise %s: %s", slots, exc)
        slots.sets = []
        return waiting(_missing_directive(day, ["valid sets (reps and weight)"]))

    result = await add_exercise_to_day(db, user_id, day, exercise)
    if not result.get("added"):
        return finished(_failed_directive(result.get("message", "unknown error")))
    logger.info("Added exercise %s to %s", name, day)
    return finished(_added_directive(result))


async def prepare_exercise_add_turn(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    user_message: str,
    user_intent: UserIntentResult | None = None,
) -> ExerciseEditTurnPlan:
    """Slot-fill adding an exercise to a saved workout (day, name, sets).

    Slots persist on state.pending_exercise_edit (mode "add") across turns. The DB
    write happens only once every required slot is filled.
    """
    state = state.model_copy(deep=True)
    if user_intent is None:
        user_intent = await classify_user_intent(user_message)

    def not_handled() -> ExerciseEditTurnPlan:
        return ExerciseEditTurnPlan(
            handled=False, state=state, directive=None, user_intent=user_intent
        )

    pending = state.pending_exercise_edit
    adding = pending is not None and pending.mode == "add"
    starting = is_add_saved_exercise_intent(user_intent)

    if adding:
        if is_cancel_schedule_intent(user_intent):
            state.pending_exercise_edit = None
            return ExerciseEditTurnPlan(
                handled=True,
                state=state,
                directive=(
                    f"{DIRECTIVE_HEADER}\n"
                    "The user cancelled adding the exercise. Acknowledge briefly. "
                    "Do NOT add anything. Do NOT start scheduling."
                ),
                user_intent=user_intent,
            )
        # The exercise form submit reads like an update_saved_exercise, so only an
        # explicit scheduling request abandons the add.
        if not starting and user_intent.intent == "schedule_workout":
            logger.info("Dropping pending add; user switched to scheduling")
            state.pending_exercise_edit = None
            return not_handled()
    elif not starting or state.is_scheduling():
        return not_handled()

    if not adding:
        # A fresh add request replaces any pending update.
        pending = PendingExerciseEdit(mode="add")

    assert pending is not None
    if pending.day is None:
        pending.day = resolve_edit_day(user_intent, user_message)
    pending.new_exercise = _merge_slots(
        pending.new_exercise, await _extract_slots(user_message)
    )
    logger.info("Add-exercise slots day=%s %s", pending.day, pending.new_exercise)

    return await _decide(db, user_id, state, pending, user_intent)
