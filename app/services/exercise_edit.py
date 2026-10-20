import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.schemas.exercise_edit import (
    DayExerciseRow,
    ExerciseEditCandidate,
    PendingExerciseEdit,
)
from app.schemas.scheduling_state import SchedulingState
from app.schemas.workout_exercise import WorkoutExerciseUpdate
from app.services.rag.tools.datetime_tools import current_weekday
from app.services.workout import list_exercises_for_day, update_exercise_for_day
from app.utils.agent import message_suggests_scheduling, parse_weekday_from_message
from app.utils.exercise_match import fallback_patch_from_message, parse_exercise_edit
from app.utils.schedule_intent_classifier import (
    UserIntentResult,
    classify_user_intent,
    is_cancel_schedule_intent,
)

UPDATE_SAVED_EXERCISE_THRESHOLD = 0.65
PERFORMANCE_PATTERN = re.compile(
    r"\b(just hit|hit|did|logged|changed?|update[d]?|bumped|make)\b",
    re.IGNORECASE,
)
DETAIL_PATTERN = re.compile(
    r"\b(sets?|reps?)\b|\d+\s*[x×]\s*\d+|@\s*\d+\s*kg",
    re.IGNORECASE,
)

DIRECTIVE_HEADER = (
    "Authoritative scheduling decision (follow this over the generic step list):"
)


@dataclass
class ExerciseEditTurnPlan:
    handled: bool
    state: SchedulingState
    directive: str | None
    user_intent: UserIntentResult


def is_update_saved_exercise_intent(user_intent: UserIntentResult) -> bool:
    return (
        user_intent.intent == "update_saved_exercise"
        and float(user_intent.confidence) >= UPDATE_SAVED_EXERCISE_THRESHOLD
    )


def looks_like_saved_exercise_update(
    message: str,
    user_intent: UserIntentResult,
) -> bool:
    if is_update_saved_exercise_intent(user_intent):
        return True
    if user_intent.intent == "schedule_workout":
        return False
    # Idle "edit"/"change X to 2 sets" is a saved-row patch, not the pre-save form.
    if user_intent.intent == "edit_workout":
        return True
    if user_intent.intent == "provide_exercise" and (
        PERFORMANCE_PATTERN.search(message) or DETAIL_PATTERN.search(message)
    ):
        return True
    if PERFORMANCE_PATTERN.search(message) and DETAIL_PATTERN.search(message):
        return True
    return False


def resolve_edit_day(user_intent: UserIntentResult, message: str) -> str | None:
    """Weekday the user named (or "today"). None means the day slot is still empty."""
    if user_intent.day:
        parsed = parse_weekday_from_message(user_intent.day)
        if parsed:
            return parsed
    parsed = parse_weekday_from_message(message)
    if parsed:
        return parsed
    if re.search(r"\btoday\b", message, re.IGNORECASE):
        return current_weekday()
    return None


# Find the correct exercise that the user picked from the list of similar exercise matches
def _candidate_from_message(
    message: str,
    pending: PendingExerciseEdit,
) -> ExerciseEditCandidate | None:
    stripped = message.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for candidate in pending.candidates:
        if stripped == candidate.id or lowered == candidate.name.lower():
            return candidate
    return None


def _success_directive(result: dict) -> str:
    exercise = result.get("exercise") or {}
    name = exercise.get("exercise", "the exercise")
    day = result.get("day", "that day")
    details = []
    if exercise.get("set_count") is not None:
        details.append(f"{exercise['set_count']} sets")
    if exercise.get("rep_count") is not None:
        details.append(f"{exercise['rep_count']} reps")
    if exercise.get("kg_weight") is not None:
        details.append(f"{exercise['kg_weight']}kg")
    summary = ", ".join(details)
    changed = ", ".join(result.get("changed_fields") or [])
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"A saved exercise was already updated. Do NOT call update tools. "
        f"Do NOT start scheduling. Do NOT ask the user to confirm.\n"
        f"Tell them the edit succeeded: {name} on {day}"
        + (f" is now {summary}" if summary else "")
        + (f" (changed: {changed})." if changed else ".")
        + " Keep the reply to 1–2 short sentences."
    )


def _ask_which_directive(day: str, names: list[str]) -> str:
    listed = ", ".join(names)
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"The user wants to update a saved exercise on {day}, but more than one "
        f"exercise matches: {listed}.\n"
        "Ask which one they mean. The chat UI shows chips for those names. "
        "Do NOT call update tools. Do NOT start scheduling. Do NOT guess."
    )


def _none_found_directive(day: str, names: list[str]) -> str:
    listed = ", ".join(names) if names else "none listed"
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"No scheduled exercise on {day} matched the user's message. "
        f"Exercises that day: {listed}.\n"
        "Tell them you could not match it and ask which of those they meant. "
        "Do NOT call update tools. Do NOT offer to schedule a new workout."
    )


def _no_workout_directive(day: str) -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"There is no workout scheduled for {day}. Tell the user that. "
        "Do NOT invent exercises. Do NOT start the new-workout scheduling flow "
        "unless they ask to schedule one."
    )


def _no_patch_directive(day: str, name: str) -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"Matched {name} on {day}, but the user did not say what to change "
        "(sets, reps, weight, or equipment). Ask what to update. "
        "Do NOT call update tools yet. Do NOT start scheduling."
    )


def _failed_update_directive(result: dict) -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        f"The exercise update did not apply ({result.get('reason', 'unknown')}). "
        f"{result.get('message', '')}\n"
        "Tell the user it was not saved. Do NOT claim success. "
        "Do NOT offer to schedule a new workout."
    )


async def _apply_patch(
    db: AsyncSession,
    user_id: str,
    exercise_id: str,
    patch: WorkoutExerciseUpdate,
    day: str,
) -> tuple[bool, str, dict]:
    result = await update_exercise_for_day(
        db,
        user_id,
        exercise_id,
        patch,
        day=day,
    )
    if result.get("updated"):
        logger.info(
            "Updated exercise %s on %s fields=%s",
            exercise_id,
            day,
            result.get("changed_fields"),
        )
        return True, _success_directive(result), result
    return False, _failed_update_directive(result), result


def _ask_day_directive() -> str:
    return (
        f"{DIRECTIVE_HEADER}\n"
        "The user wants to update a saved exercise but did not say which day. "
        "Ask ONLY which weekday the exercise is on. The chat UI shows a day picker. "
        "Do NOT call update tools. Do NOT start scheduling. Do NOT assume today."
    )


def _merge_patch(
    old: WorkoutExerciseUpdate | None,
    new: WorkoutExerciseUpdate | None,
) -> WorkoutExerciseUpdate | None:
    """Newer fields win; fields only the older patch had are kept."""
    fields: dict = {}
    for patch in (old, new):
        if patch is not None:
            fields.update(patch.model_dump(exclude_none=True))
    return WorkoutExerciseUpdate.model_validate(fields) if fields else None


def _slots_snapshot(pending: PendingExerciseEdit) -> dict:
    return pending.model_dump(exclude={"request_text"})


async def _fill_slots(
    db: AsyncSession,
    user_id: str,
    pending: PendingExerciseEdit,
    message: str,
    user_intent: UserIntentResult,
) -> list[DayExerciseRow]:
    """Fill every slot this message provides (day, exercise, fields). Returns the day's rows."""
    if pending.candidates:
        picked = _candidate_from_message(message, pending)
        if picked is not None:
            pending.exercise_id = picked.id
            pending.exercise_name = picked.name
            pending.candidates = []

    if pending.day is None:
        pending.day = resolve_edit_day(user_intent, message)

    pending.request_text = f"{pending.request_text}\n{message}".strip()
    pending.patch = _merge_patch(pending.patch, fallback_patch_from_message(message))

    if pending.day is None:
        return []
    rows = await list_exercises_for_day(db, user_id, pending.day)
    if not rows or pending.exercise_id is not None:
        return rows

    matched, patch, confidence = await parse_exercise_edit(pending.request_text, rows)
    logger.info(
        "Saved-exercise match day=%s matches=%s confidence=%s patch=%s",
        pending.day,
        [row.exercise for row in matched],
        confidence,
        patch.model_dump() if patch else None,
    )
    pending.patch = _merge_patch(pending.patch, patch)
    if len(matched) == 1:
        pending.exercise_id = matched[0].id
        pending.exercise_name = matched[0].exercise
        pending.candidates = []
    elif len(matched) > 1:
        pending.candidates = [
            ExerciseEditCandidate(id=row.id, name=row.exercise) for row in matched
        ]
    return rows


async def _decide(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    pending: PendingExerciseEdit,
    rows: list[DayExerciseRow],
    user_intent: UserIntentResult,
) -> ExerciseEditTurnPlan:
    """Ask for the first empty slot, or apply the edit once all are filled."""

    def waiting(directive: str) -> ExerciseEditTurnPlan:
        state.pending_exercise_edit = pending
        return ExerciseEditTurnPlan(
            handled=True, state=state, directive=directive, user_intent=user_intent
        )

    if pending.day is None:
        return waiting(_ask_day_directive())

    day = pending.day
    if not rows:
        logger.info("No workout on %s for saved-exercise edit", day)
        pending.day = None
        return waiting(_no_workout_directive(day) + " Ask if they meant a different day.")

    if pending.exercise_id is None:
        if len(pending.candidates) >= 2:
            names = [candidate.name for candidate in pending.candidates]
            directive = _ask_which_directive(day, names)
            if pending.patch is None:
                directive += " Also ask what to change (sets, reps, weight, or equipment)."
            return waiting(directive)
        return waiting(_none_found_directive(day, [row.exercise for row in rows]))

    if pending.patch is None:
        return waiting(_no_patch_directive(day, pending.exercise_name or "the exercise"))

    _ok, directive, _result = await _apply_patch(
        db, user_id, pending.exercise_id, pending.patch, day
    )
    state.pending_exercise_edit = None
    return ExerciseEditTurnPlan(
        handled=True, state=state, directive=directive, user_intent=user_intent
    )


async def prepare_exercise_edit_turn(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    user_message: str,
    user_intent: UserIntentResult | None = None,
) -> ExerciseEditTurnPlan:
    """Slot-fill a saved-exercise edit (day, exercise, fields) before scheduling.

    Slots persist on state.pending_exercise_edit across turns. The DB write happens
    only once every slot is filled. Idle scheduling stays idle.
    """
    state = state.model_copy(deep=True)
    if user_intent is None:
        user_intent = await classify_user_intent(user_message)

    def not_handled() -> ExerciseEditTurnPlan:
        return ExerciseEditTurnPlan(
            handled=False, state=state, directive=None, user_intent=user_intent
        )

    pending = state.pending_exercise_edit
    if pending is not None:
        if is_cancel_schedule_intent(user_intent):
            logger.info("Clearing pending exercise edit after cancel")
            state.pending_exercise_edit = None
            return ExerciseEditTurnPlan(
                handled=True,
                state=state,
                directive=(
                    f"{DIRECTIVE_HEADER}\n"
                    "The user cancelled the exercise update. Acknowledge briefly. "
                    "Do NOT edit. Do NOT start scheduling."
                ),
                user_intent=user_intent,
            )
        if user_intent.intent == "schedule_workout" or message_suggests_scheduling(user_message):
            logger.info("Clearing pending exercise edit; user switched to scheduling")
            state.pending_exercise_edit = None
            return not_handled()

    if state.is_scheduling():
        return not_handled()

    is_new_update = looks_like_saved_exercise_update(user_message, user_intent)
    had_pending = pending is not None
    if pending is None:
        if not is_new_update:
            return not_handled()
        pending = PendingExerciseEdit()

    before = _slots_snapshot(pending)
    rows = await _fill_slots(db, user_id, pending, user_message, user_intent)
    if had_pending and is_new_update and _slots_snapshot(pending) == before:
        # Nothing new filled and it reads like a fresh request: drop the stale edit and restart.
        logger.info("Restarting pending exercise edit from new message")
        pending = PendingExerciseEdit()
        rows = await _fill_slots(db, user_id, pending, user_message, user_intent)

    return await _decide(db, user_id, state, pending, rows, user_intent)
