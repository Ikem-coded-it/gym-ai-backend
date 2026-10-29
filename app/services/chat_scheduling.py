import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.schemas.chat_composer import ChatComposer, ComposerOption
from app.models.conversation_scheduling_state import ConversationSchedulingState
from app.schemas.exercise_edit import PendingExerciseEdit
from app.schemas.scheduling_state import (
    ExerciseDraft,
    ExerciseSetDraft,
    ScheduleStep,
    SchedulingDraft,
    SchedulingState,
)
from app.services.exercise_suggestion import format_review_summary, suggest_exercises
from app.services.workout import get_workout_for_day
from langchain_core.messages import AIMessage

from app.utils.agent import (
    message_suggests_scheduling,
    message_text,
    parse_weekday_from_message,
)
from app.utils.exercise_extractor import extract_exercises
from app.utils.schedule_intent_classifier import (
    UserIntentResult,
    classify_assistant_message,
    classify_user_intent,
    is_cancel_schedule_intent,
)

SUGGEST_PATTERN = re.compile(r"^\s*suggest\s*\.?\s*$", re.IGNORECASE)
EDIT_PATTERN = re.compile(r"^\s*edit\s*\.?\s*$", re.IGNORECASE)
EDIT_REQUEST_CONFIDENCE_THRESHOLD = 0.65
EXERCISE_DETAIL_PATTERN = re.compile(
    r"\b(sets?|reps?)\b|\d+\s*[x×]\s*\d+|@\s*\d+\s*kg",
    re.IGNORECASE,
)
PROVIDE_EXERCISE_CONFIDENCE_THRESHOLD = 0.6

WEEKDAY_OPTIONS: list[ComposerOption] = [
    ComposerOption(label="Monday", value="monday"),
    ComposerOption(label="Tuesday", value="tuesday"),
    ComposerOption(label="Wednesday", value="wednesday"),
    ComposerOption(label="Thursday", value="thursday"),
    ComposerOption(label="Friday", value="friday"),
    ComposerOption(label="Saturday", value="saturday"),
    ComposerOption(label="Sunday", value="sunday"),
]

MUSCLE_GROUP_VALUES: frozenset[str] = frozenset(
    {
        "push",
        "pull",
        "legs",
        "upper-body",
        "lower-body",
        "full-body",
        "chest",
        "back",
        "shoulders",
        "arms",
        "core",
    }
)

MUSCLE_GROUP_OPTIONS: list[ComposerOption] = [
    ComposerOption(label="Push", value="push"),
    ComposerOption(label="Pull", value="pull"),
    ComposerOption(label="Legs", value="legs"),
    ComposerOption(label="Upper body", value="upper-body"),
    ComposerOption(label="Lower body", value="lower-body"),
    ComposerOption(label="Full body", value="full-body"),
    ComposerOption(label="Chest", value="chest"),
    ComposerOption(label="Back", value="back"),
    ComposerOption(label="Shoulders", value="shoulders"),
    ComposerOption(label="Arms", value="arms"),
    ComposerOption(label="Core", value="core"),
]

EXERCISE_SUGGEST_OPTION = ComposerOption(label="Suggest a plan", value="suggest")

CONFIRM_OPTIONS: list[ComposerOption] = [
    ComposerOption(label="Confirm", value="confirm"),
    ComposerOption(label="Edit", value="edit"),
]


def _pending_from_row(raw: dict | None) -> PendingExerciseEdit | None:
    if not raw:
        return None
    try:
        return PendingExerciseEdit.model_validate(raw)
    except Exception:
        logger.warning("Skipping malformed pending exercise edit: %s", raw)
        return None


def _exercises_from_row(raw: list | None) -> list[ExerciseDraft]:
    if not raw:
        return []
    exercises: list[ExerciseDraft] = []
    for item in raw:
        try:
            exercises.append(ExerciseDraft.model_validate(item))
        except Exception:
            logger.warning("Skipping malformed draft exercise: %s", item)
    return exercises


def scheduling_state_from_row(
    row: ConversationSchedulingState | None,
) -> SchedulingState:
    if row is None:
        return SchedulingState.idle()
    return SchedulingState(
        flow=row.flow,  # type: ignore[arg-type]
        step=row.step,  # type: ignore[arg-type]
        draft=SchedulingDraft(
            day=row.draft_day,
            muscle_group=row.draft_muscle_group,
            exercises=_exercises_from_row(row.draft_exercises),
        ),
        pending_exercise_edit=_pending_from_row(row.pending_exercise_edit),
    )


def apply_scheduling_state(
    row: ConversationSchedulingState,
    state: SchedulingState,
) -> None:
    row.flow = state.flow
    row.step = state.step
    row.draft_day = state.draft.day
    row.draft_muscle_group = state.draft.muscle_group
    row.draft_exercises = (
        [exercise.model_dump(mode="json") for exercise in state.draft.exercises]
        if state.draft.exercises
        else None
    )
    row.pending_exercise_edit = (
        state.pending_exercise_edit.model_dump(mode="json")
        if state.pending_exercise_edit
        else None
    )

# This sets and returns the chat composer for the current scheduling state.
# The chat composer is used to tell the UI what type of input to show the user.
def composer_for_pending_edit(state: SchedulingState) -> ChatComposer | None:
    pending = state.pending_exercise_edit
    if pending is None:
        return None
    if pending.day is None:
        return ChatComposer(kind="day_select", options=WEEKDAY_OPTIONS)
    if pending.mode == "add":
        # Form pre-filled with whatever the user already gave; no "Suggest" option here.
        slots = pending.new_exercise
        return ChatComposer(
            kind="exercise_form",
            options=[],
            exercises=[
                ExerciseDraft(
                    exercise=slots.exercise or "",
                    equipment_name=slots.equipment_name,
                    sets=[
                        ExerciseSetDraft(
                            rep_count=new_set.rep_count,
                            kg_weight=new_set.kg_weight,
                            notes=new_set.notes,
                        )
                        for new_set in slots.sets
                    ],
                )
            ],
        )
    if len(pending.candidates) < 2:
        return None
    return ChatComposer(
        kind="chips",
        options=[
            ComposerOption(label=candidate.name, value=candidate.name)
            for candidate in pending.candidates
        ],
    )


def composer_for_state(state: SchedulingState) -> ChatComposer | None:
    pending_composer = composer_for_pending_edit(state)
    if pending_composer is not None:
        return pending_composer
    if not state.is_scheduling():
        return None

    # if scheduling state is in pick_day, return the day_select composer
    if state.step == "pick_day":
        return ChatComposer(
            kind="day_select",
            options=WEEKDAY_OPTIONS,
            suggested_value=state.draft.day,
        )

    # if scheduling state is in pick_muscle_group, return the muscle_group_select composer
    if state.step == "pick_muscle_group":
        return ChatComposer(
            kind="muscle_group_multi_select",
            options=MUSCLE_GROUP_OPTIONS,
            suggested_value=state.draft.muscle_group,
        )
    if state.step in ("pick_exercises", "edit_exercises"):
        return ChatComposer(
            kind="exercise_form",
            options=[EXERCISE_SUGGEST_OPTION],
            exercises=state.draft.exercises or None,
        )
    if state.step == "review":
        return ChatComposer(
            kind="confirm",
            options=CONFIRM_OPTIONS,
        )
    return None


async def resolve_active_composer(
    state: SchedulingState,
    last_assistant_message: str | None = None,
) -> ChatComposer | None:
    """Return composer from persisted state, or infer from the latest assistant prompt."""
    composer = composer_for_state(state)
    if composer is not None:
        return composer
    if not last_assistant_message:
        return None

    # Do not infer scheduling composers when flow is idle (e.g. user cancelled).
    if not state.is_scheduling() or state.pending_exercise_edit is not None:
        return None
    
    assistant_intent = await classify_assistant_message(last_assistant_message)
    logger.info(f"Assistant intent: {assistant_intent.intent} (confidence: {assistant_intent.confidence})")

    if assistant_intent.intent == "ask_day" and float(assistant_intent.confidence) > 0.8:
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="pick_day")
        )
    if assistant_intent.intent == "ask_muscle_group" and float(assistant_intent.confidence) > 0.8:
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="pick_muscle_group")
        )
    if assistant_intent.intent == "ask_exercises" and float(assistant_intent.confidence) > 0.8:
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="pick_exercises")
        )
    if assistant_intent.intent == "ask_review" and float(assistant_intent.confidence) > 0.8:
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="review")
        )

    if assistant_intent.intent == "confirm_save" and float(assistant_intent.confidence) > 0.8:
        return composer_for_state(
            SchedulingState(flow="idle", step="idle")
        )
    return None


DIRECTIVE_HEADER = (
    "Authoritative scheduling decision (follow this over the generic step list):"
)
CANCEL_SCHEDULING_DIRECTIVE = (
    f"{DIRECTIVE_HEADER}\n"
    "The user cancelled scheduling. Acknowledge briefly and stop. "
    "Do NOT ask for a day, muscle group, exercises, or confirmation."
)
REVIEW_SCHEDULING_DIRECTIVE = (
    f"{DIRECTIVE_HEADER}\n"
    "The workout is ready for review. Show the summary and ask them to confirm. "
    "Do NOT re-ask for the day or muscle group."
)
EDIT_EXERCISES_DIRECTIVE = (
    f"{DIRECTIVE_HEADER}\n"
    "The user wants to change the workout before saving. Acknowledge in one short sentence. "
    "The chat UI shows the exercise form below your message, pre-filled with the current exercises; "
    "tell them to adjust it and resubmit. Do NOT repeat the summary, do NOT ask for day or muscle group, "
    "do NOT save."
)
EXERCISES_SUBMITTED_DIRECTIVE = (
    f"{DIRECTIVE_HEADER}\n"
    "The user submitted exercises in this message (exercise form or typed lines).\n"
    "Show Step 4 review ONLY: a clear summary listing every exercise with each set's "
    "reps and weight (e.g. Set 1: 10 reps @ 60kg) and the equipment, from their message.\n"
    "End with: Reply **confirm** to save, or tell me what to change.\n"
    "Do NOT ask them to use the exercise form again or add exercises again."
)
SUGGEST_EXERCISES_DIRECTIVE = (
    f"{DIRECTIVE_HEADER}\n"
    "The user asked for exercise suggestions (Suggest a plan).\n"
    "Call `search_fitness_knowledge` for their muscle group, propose 3–5 exercises, "
    "then show a review summary and ask for confirmation. Do NOT ask them to fill the form."
)
SLOT_CONFIDENCE_THRESHOLD = 0.8


def suggested_plan_directive(state: SchedulingState) -> str:
    summary = format_review_summary(
        state.draft.day, state.draft.muscle_group, state.draft.exercises
    )
    return (
        f"{DIRECTIVE_HEADER}\n"
        "The user chose Suggest a plan. The knowledge base was already searched for their "
        "muscle groups and this plan was built: at least two exercises per muscle group, "
        "2 sets of 10 reps each. Do NOT call tools. Do NOT change, add or remove anything.\n"
        "Reply with one short intro sentence, then the plan below EXACTLY as written, "
        "then: Reply **confirm** to save, or **edit** to change it.\n\n"
        f"{summary}"
    )


@dataclass
class SchedulingTurnPlan:
    state: SchedulingState
    directive: str | None
    user_intent: UserIntentResult


def _label_to_muscle_value(token: str) -> str | None:
    cleaned = token.strip().lower()
    if cleaned in MUSCLE_GROUP_VALUES:
        return cleaned
    for option in MUSCLE_GROUP_OPTIONS:
        if cleaned == option.label.lower():
            return option.value
    return None


def _muscle_group_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    seen_labels: set[str] = set()
    for option in MUSCLE_GROUP_OPTIONS:
        for label in (option.value, option.label.lower()):
            if label in seen_labels:
                continue
            seen_labels.add(label)
            parts = [part for part in re.split(r"[\s-]+", label) if part]
            body = r"[\s-]+".join(re.escape(part) for part in parts)
            patterns.append((re.compile(rf"\b{body}\b", re.IGNORECASE), option.value))
    patterns.sort(key=lambda item: len(item[0].pattern), reverse=True)
    return patterns


_MUSCLE_GROUP_PATTERNS = _muscle_group_patterns()


def assistant_message_is_review_summary(text: str) -> bool:
    """True when assistant text looks like a workout summary, not a short edit ack."""
    stripped = text.strip()
    if not stripped:
        return False
    return EXERCISE_DETAIL_PATTERN.search(stripped) is not None


def user_message_lists_exercises(message: str, user_intent: UserIntentResult) -> bool:
    """True when the user sent one or more exercises (chat lines or form payload)."""
    stripped = message.strip()
    if not stripped or SUGGEST_PATTERN.match(stripped):
        return False
    if is_edit_request(message, user_intent):
        return False
    if (
        user_intent.intent == "provide_exercise"
        and float(user_intent.confidence) >= PROVIDE_EXERCISE_CONFIDENCE_THRESHOLD
    ):
        return True
    return EXERCISE_DETAIL_PATTERN.search(message) is not None


def is_edit_request(message: str, user_intent: UserIntentResult) -> bool:
    """True when the user chose Edit (chip) or asked to change the proposed workout."""
    if EDIT_PATTERN.match(message.strip()):
        return True
    return (
        user_intent.intent == "edit_workout"
        and float(user_intent.confidence) >= EDIT_REQUEST_CONFIDENCE_THRESHOLD
    )


def muscle_groups_mentioned(text: str) -> list[str]:
    """Find composer muscle-group values that appear literally in text."""
    if not text.strip() or SUGGEST_PATTERN.match(text.strip()):
        return []
    selected: list[str] = []
    for pattern, value in _MUSCLE_GROUP_PATTERNS:
        if pattern.search(text) and value not in selected:
            selected.append(value)
    return selected


def canonical_day(user_intent: UserIntentResult, message: str) -> str | None:
    if user_intent.day:
        parsed = parse_weekday_from_message(user_intent.day)
        if parsed:
            return parsed
    return parse_weekday_from_message(message)


def canonical_muscle_group(user_intent: UserIntentResult, message: str) -> str | None:
    """Normalize model slots, then fill any group the model omitted but the text names."""
    if SUGGEST_PATTERN.match(message.strip()):
        return None

    selected: list[str] = []
    for item in user_intent.muscle_groups:
        parts = re.split(r"[,/&]+|\band\b", item.lower())
        for part in parts:
            value = _label_to_muscle_value(part)
            if value and value not in selected:
                selected.append(value)
    if not user_message_lists_exercises(message, user_intent):
        for value in muscle_groups_mentioned(message):
            if value not in selected:
                selected.append(value)
    if not selected:
        return None
    return ", ".join(selected)


def merge_schedule_slots(
    draft: SchedulingDraft,
    *,
    day: str | None,
    muscle_group: str | None,
) -> SchedulingDraft:
    """Write a slot only when this turn provided it."""
    updates: dict[str, str] = {}
    if day:
        updates["day"] = day
    if muscle_group:
        updates["muscle_group"] = muscle_group
    if not updates:
        return draft
    return draft.model_copy(update=updates)


def next_schedule_step(draft: SchedulingDraft, *, day_is_free: bool) -> ScheduleStep:
    """First required slot that is still empty. A taken day counts as empty."""
    if not draft.day or not day_is_free:
        return "pick_day"
    if not draft.muscle_group:
        return "pick_muscle_group"
    return "pick_exercises"


def _should_enter_scheduling(
    state: SchedulingState,
    user_intent: UserIntentResult,
    message: str,
) -> bool:
    if state.flow == "schedule_workout" and state.step != "idle":
        return True
    if user_intent.intent in ("update_saved_exercise", "add_saved_exercise"):
        return False
    confident = float(user_intent.confidence) > SLOT_CONFIDENCE_THRESHOLD
    if user_intent.intent == "confirm_yes" and confident:
        return True
    if user_intent.intent == "schedule_workout" and confident:
        return True
    # One message can be labeled provide_day or provide_muscle_group even when
    # it is clearly a request to schedule ("book a back workout for thursday").
    if (
        confident
        and user_intent.intent in ("provide_day", "provide_muscle_group")
        and message_suggests_scheduling(message)
    ):
        return True
    return False


def scheduling_directive(
    state: SchedulingState,
    *,
    blocked_day: str | None,
    existing_muscle_group: str | None,
) -> str | None:
    if blocked_day:
        existing = (
            f" Existing workout muscle group: {existing_muscle_group}."
            if existing_muscle_group
            else ""
        )
        kept = (
            f" The user already chose muscle group `{state.draft.muscle_group}`; "
            "keep it and do not ask for it again after they pick a free day."
            if state.draft.muscle_group
            else ""
        )
        return (
            f"{DIRECTIVE_HEADER}\n"
            f"`{blocked_day}` already has a workout.{existing}\n"
            f"Ask ONLY for a different weekday.{kept}\n"
            "Do NOT ask for muscle group or exercises."
        )

    if state.step == "pick_day":
        return (
            f"{DIRECTIVE_HEADER}\n"
            "Ask ONLY which weekday to schedule. "
            "Do NOT ask for muscle group or exercises."
        )

    if state.step == "pick_muscle_group":
        return (
            f"{DIRECTIVE_HEADER}\n"
            f"Day `{state.draft.day}` is free and saved. "
            "Ask ONLY which muscle group(s) they are training. "
            "Do NOT ask for the day again or for exercises."
        )

    if state.step == "pick_exercises":
        return (
            f"{DIRECTIVE_HEADER}\n"
            f"Filled slots: day=`{state.draft.day}`, muscle_group=`{state.draft.muscle_group}`. "
            "The day is free.\n"
            "The chat UI shows an exercise form directly below your message (fields + "
            '"Suggest a plan"). Do NOT ask how to add exercises. Do NOT give one-per-line '
            "format examples or tell them to reply suggest in chat.\n"
            "Reply in 1–2 short sentences: confirm day and muscle group, and tell them to "
            "use the form below (or Suggest a plan there). Do NOT ask for the day or muscle group."
        )

    if state.step == "review":
        return REVIEW_SCHEDULING_DIRECTIVE

    if state.step == "edit_exercises":
        return EDIT_EXERCISES_DIRECTIVE

    return None


async def _apply_user_slots(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    user_message: str,
    user_intent: UserIntentResult,
) -> tuple[str | None, str | None]:
    """Merge this turn's slots. A taken day is not stored. Returns (blocked day, existing muscle)."""
    requested_day = canonical_day(user_intent, user_message)
    muscle_group = canonical_muscle_group(user_intent, user_message)
    blocked_day: str | None = None
    existing_muscle_group: str | None = None
    day_to_store: str | None = None

    if requested_day:
        workouts = await get_workout_for_day(db, user_id, requested_day)
        if workouts:
            blocked_day = requested_day
            existing_muscle_group = workouts[0].muscle_group
            logger.info("Schedule day %s taken; staying on pick_day", requested_day)
        else:
            day_to_store = requested_day
            logger.info("Schedule day %s free", requested_day)

    state.draft = merge_schedule_slots(
        state.draft,
        day=day_to_store,
        muscle_group=muscle_group,
    )
    if blocked_day:
        state.draft.day = None
    return blocked_day, existing_muscle_group


# Classifies user intent (schedule_intent_classifier — e.g. provide_day, confirm_yes, edit_workout).
# Updates draft (day/muscle) when the user supplies slots; checks if the day is already taken.
# Sets directive: extra system messages like “ask ONLY for weekday” or “user submitted exercises — show review”.
# Returns SchedulingTurnPlan: { state, directive, user_intent }.
async def prepare_scheduling_turn(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    user_message: str,
    history: list | None,
    user_intent: UserIntentResult | None = None,
) -> SchedulingTurnPlan:
    """Fill slots from the user message and choose the next step before the coach replies."""
    state = state.model_copy(deep=True)
    if user_intent is None:
        user_intent = await classify_user_intent(user_message)
    logger.info(
        "Scheduling slots: intent=%s confidence=%s day=%s muscle_groups=%s",
        user_intent.intent,
        user_intent.confidence,
        user_intent.day,
        user_intent.muscle_groups,
    )

    if state.is_scheduling() and is_cancel_schedule_intent(user_intent):
        logger.info("User cancelled scheduling; resetting flow to idle")
        return SchedulingTurnPlan(
            state=SchedulingState.idle(),
            directive=CANCEL_SCHEDULING_DIRECTIVE,
            user_intent=user_intent,
        )

    if state.step == "review" and state.flow == "schedule_workout":
        if is_edit_request(user_message, user_intent):
            state.step = "edit_exercises"
            await _backfill_draft_exercises_from_history(state, history)
            logger.info("User requested edit; step=edit_exercises")
            return SchedulingTurnPlan(
                state=state,
                directive=EDIT_EXERCISES_DIRECTIVE,
                user_intent=user_intent,
            )
        directive = (
            None
            if user_intent.intent == "confirm_yes"
            and float(user_intent.confidence) > SLOT_CONFIDENCE_THRESHOLD
            else REVIEW_SCHEDULING_DIRECTIVE
        )
        return SchedulingTurnPlan(
            state=state,
            directive=directive,
            user_intent=user_intent,
        )

    if state.flow == "schedule_workout" and state.step in (
        "pick_exercises",
        "edit_exercises",
    ):
        if user_message_lists_exercises(user_message, user_intent):
            logger.info("Exercises submitted in chat; directing coach to review")
            return SchedulingTurnPlan(
                state=state,
                directive=EXERCISES_SUBMITTED_DIRECTIVE,
                user_intent=user_intent,
            )
        if SUGGEST_PATTERN.match(user_message.strip()):
            logger.info("User requested exercise suggestions via composer")
            suggested = await suggest_exercises(state.draft.muscle_group)
            if suggested:
                # Plan comes straight from the knowledge base; go to review so the
                # Confirm / Edit composer shows (Edit opens the form prefilled).
                state.draft.exercises = suggested
                state.step = "review"
                return SchedulingTurnPlan(
                    state=state,
                    directive=suggested_plan_directive(state),
                    user_intent=user_intent,
                )
            return SchedulingTurnPlan(
                state=state,
                directive=SUGGEST_EXERCISES_DIRECTIVE,
                user_intent=user_intent,
            )
        if state.step == "edit_exercises":
            return SchedulingTurnPlan(
                state=state,
                directive=EDIT_EXERCISES_DIRECTIVE,
                user_intent=user_intent,
            )
        return SchedulingTurnPlan(
            state=state,
            directive=scheduling_directive(
                state,
                blocked_day=None,
                existing_muscle_group=None,
            ),
            user_intent=user_intent,
        )

    if not _should_enter_scheduling(state, user_intent, user_message):
        return SchedulingTurnPlan(state=state, directive=None, user_intent=user_intent)

    if not state.is_scheduling():
        state.draft = SchedulingDraft()
        state.pending_exercise_edit = None
    state.flow = "schedule_workout"

    blocked_day, existing_muscle_group = await _apply_user_slots(
        db,
        user_id,
        state,
        user_message,
        user_intent,
    )
    state.step = next_schedule_step(state.draft, day_is_free=blocked_day is None)
    logger.info(
        "Scheduling plan: step=%s day=%s muscle_group=%s",
        state.step,
        state.draft.day,
        state.draft.muscle_group,
    )
    return SchedulingTurnPlan(
        state=state,
        directive=scheduling_directive(
            state,
            blocked_day=blocked_day,
            existing_muscle_group=existing_muscle_group,
        ),
        user_intent=user_intent,
    )


async def _backfill_draft_exercises_from_history(
    state: SchedulingState,
    history: list | None,
) -> None:
    """Seed draft.exercises from the latest assistant review when user opens edit."""
    if state.draft.exercises or not history:
        return
    for message in reversed(history):
        if not isinstance(message, AIMessage):
            continue
        extracted = await extract_exercises(message_text(message))
        if extracted:
            state.draft.exercises = extracted
            logger.info(
                "Backfilled %s exercises from history for edit",
                len(extracted),
            )
            return


async def _persist_extracted_exercises(
    state: SchedulingState,
    assistant_message: str,
    user_message: str,
) -> None:
    extracted = await extract_exercises(assistant_message)
    if not extracted:
        extracted = await extract_exercises(user_message)
    if extracted:
        state.draft.exercises = extracted
        logger.info("Persisted %s extracted exercises on draft", len(extracted))


_STEP_ORDER: tuple[ScheduleStep, ...] = (
    "pick_day",
    "pick_muscle_group",
    "pick_exercises",
)


def _skip_filled_slots(state: SchedulingState) -> None:
    """Move forward to the first empty slot. Never rewind a filled one."""
    if state.flow != "schedule_workout" or state.step not in _STEP_ORDER:
        return
    target = next_schedule_step(state.draft, day_is_free=True)
    if _STEP_ORDER.index(state.step) < _STEP_ORDER.index(target):
        logger.info("Skipping filled slots; step=%s", target)
        state.step = target


# Classifies user + assistant intents again.
# Moves step forward (e.g. exercises submitted → review, confirm → idle after save intent).
# Extracts exercises from review text into draft.exercises when entering review.
# Does not replace the agent saving workouts — it mainly drives UI step and draft data.
async def advance_after_turn(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    user_message: str,
    assistant_message: str,
    history: list | None,
    user_intent: UserIntentResult | None = None,
) -> SchedulingState:
    """Apply assistant outcomes without rewinding slots already filled this turn."""
    state = state.model_copy(deep=True)
    if user_intent is None:
        user_intent = await classify_user_intent(user_message)
    assistant_intent = await classify_assistant_message(assistant_message)
    logger.info(
        "Intent classified: %s (confidence: %s), %s (confidence: %s)",
        user_intent.intent,
        user_intent.confidence,
        assistant_intent.intent,
        assistant_intent.confidence,
    )

    if is_cancel_schedule_intent(user_intent):
        logger.info("User cancelled scheduling; resetting flow to idle")
        return SchedulingState.idle()

    if state.pending_exercise_edit is not None:
        return state

    # Mid-wizard, an exercise form submit can be labeled as a saved-exercise change;
    # it still has to advance the wizard.
    if not state.is_scheduling() and user_intent.intent in (
        "update_saved_exercise",
        "add_saved_exercise",
    ):
        return state

    assistant_confident = float(assistant_intent.confidence) > SLOT_CONFIDENCE_THRESHOLD
    if state.flow == "idle" and state.step == "idle":
        if assistant_confident and assistant_intent.intent in (
            "ask_day",
            "ask_muscle_group",
            "ask_exercises",
        ):
            state.flow = "schedule_workout"
            blocked_day, _existing = await _apply_user_slots(
                db,
                user_id,
                state,
                user_message,
                user_intent,
            )
            state.step = next_schedule_step(
                state.draft,
                day_is_free=blocked_day is None,
            )
            logger.info(
                "Assistant opened scheduling; step=%s",
                state.step,
            )
        return state

    if state.flow != "schedule_workout":
        return state

    if state.step in ("pick_exercises", "edit_exercises"):
        if is_edit_request(user_message, user_intent):
            if state.step == "edit_exercises":
                await _backfill_draft_exercises_from_history(state, history)
            logger.info("Edit request; staying on %s", state.step)
            return state
        if user_message_lists_exercises(user_message, user_intent):
            state.step = "review"
            await _persist_extracted_exercises(state, assistant_message, user_message)
            logger.info("Exercises provided; step=review")
        elif (
            assistant_intent.intent == "ask_review"
            and assistant_confident
            and assistant_message_is_review_summary(assistant_message)
        ):
            state.step = "review"
            await _persist_extracted_exercises(state, assistant_message, user_message)
            logger.info("Review summary detected; step=review")
        elif SUGGEST_PATTERN.match(user_message.strip()):
            logger.info("User requested exercise suggestions; staying on pick_exercises")
        return state

    if state.step == "review":
        if (
            user_intent.intent == "confirm_yes"
            and float(user_intent.confidence) > SLOT_CONFIDENCE_THRESHOLD
        ):
            logger.info("Save confirmed; scheduling flow cleared")
            return SchedulingState.idle()
        if assistant_intent.intent == "ask_review" and assistant_confident:
            await _persist_extracted_exercises(state, assistant_message, user_message)
        return state

    _skip_filled_slots(state)
    return state
