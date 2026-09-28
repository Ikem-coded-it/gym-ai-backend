import re

from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.schemas.chat_composer import ChatComposer, ComposerOption
from app.models.conversation_scheduling_state import ConversationSchedulingState
from app.schemas.scheduling_state import SchedulingDraft, SchedulingState
from app.services.workout import get_workout_for_day
from app.utils.agent import (
    SCHEDULE_DAY_PROMPT_MARKERS,
    history_has_pending_workout_review,
    is_explicit_save_confirmation,
    message_text,
    parse_weekday_from_message,
)

SCHEDULE_OFFER_MARKERS = (
    "would you like to schedule a workout",
    "schedule a workout",
)

SCHEDULE_YES_PATTERN = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|please|go ahead|let'?s do it)\s*\.?\s*$",
    re.IGNORECASE,
)

SCHEDULE_INTENT_PATTERN = re.compile(
    r"\b(schedule|book|plan|add|create)\b.*\b(workout|training|session)\b"
    r"|\b(wanna|want to)\s+schedule\b",
    re.IGNORECASE,
)

MUSCLE_GROUP_PROMPT_MARKERS = (
    "muscle group",
    "what are you training",
    "what are you training that day",
)

SUGGEST_PATTERN = re.compile(r"^\s*suggest\s*\.?\s*$", re.IGNORECASE)

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

EXERCISE_STEP_OPTIONS: list[ComposerOption] = [
    ComposerOption(label="Suggest a plan", value="suggest"),
]

CONFIRM_OPTIONS: list[ComposerOption] = [
    ComposerOption(label="Confirm", value="confirm"),
    ComposerOption(label="Edit", value="edit"),
]


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
        ),
    )


def apply_scheduling_state(
    row: ConversationSchedulingState,
    state: SchedulingState,
) -> None:
    row.flow = state.flow
    row.step = state.step
    row.draft_day = state.draft.day
    row.draft_muscle_group = state.draft.muscle_group

# This specifies the chat composer for the current scheduling state.
# The chat composer is used to tell the UI what type of input to show the user.
def composer_for_state(state: SchedulingState) -> ChatComposer | None:
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
    if state.step == "pick_exercises":
        return ChatComposer(
            kind="chips",
            options=EXERCISE_STEP_OPTIONS,
        )
    if state.step == "review":
        return ChatComposer(
            kind="confirm",
            options=CONFIRM_OPTIONS,
        )
    return None


def resolve_active_composer(
    state: SchedulingState,
    last_assistant_message: str | None = None,
) -> ChatComposer | None:
    """Return composer from persisted state, or infer from the latest assistant prompt."""
    composer = composer_for_state(state)
    if composer is not None:
        return composer
    if not last_assistant_message:
        return None

    if _assistant_asks_for_schedule_day(last_assistant_message):
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="pick_day")
        )
    if _assistant_asks_for_muscle_group(last_assistant_message):
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="pick_muscle_group")
        )
    if _assistant_has_review(last_assistant_message):
        return composer_for_state(
            SchedulingState(flow="schedule_workout", step="review")
        )
    return None


def _history_offered_schedule(history: list | None) -> bool:
    if not history:
        return False
    for message in reversed(history):
        if not isinstance(message, AIMessage):
            continue
        text = message_text(message).lower()
        return any(marker in text for marker in SCHEDULE_OFFER_MARKERS)
    return False


def _assistant_has_review(assistant_message: str) -> bool:
    fake = AIMessage(content=assistant_message)
    return history_has_pending_workout_review([fake])


def _assistant_asks_for_schedule_day(assistant_message: str) -> bool:
    lower = assistant_message.lower()
    return any(marker in lower for marker in SCHEDULE_DAY_PROMPT_MARKERS)


def _assistant_asks_for_muscle_group(assistant_message: str) -> bool:
    lower = assistant_message.lower()
    return any(marker in lower for marker in MUSCLE_GROUP_PROMPT_MARKERS)


def _user_expressed_schedule_intent(user_message: str) -> bool:
    return bool(SCHEDULE_INTENT_PATTERN.search(user_message.strip()))


def _user_wants_to_schedule(user_message: str, history: list | None) -> bool:
    if not SCHEDULE_YES_PATTERN.match(user_message.strip()):
        return False
    return _history_offered_schedule(history)


def _normalize_muscle_group(text: str) -> str | None:
    normalized = text.strip().lower()
    if not normalized or parse_weekday_from_message(normalized):
        return None
    if is_explicit_save_confirmation(normalized):
        return None
    if SUGGEST_PATTERN.match(normalized):
        return None
    return normalized


def _label_to_muscle_value(token: str) -> str | None:
    cleaned = token.strip().lower()
    if cleaned in MUSCLE_GROUP_VALUES:
        return cleaned
    for option in MUSCLE_GROUP_OPTIONS:
        if cleaned == option.label.lower():
            return option.value
    return None


def _parse_muscle_groups_from_message(text: str) -> str | None:
    """Parse one or more muscle groups (comma / and separated) into a stored string."""
    normalized = text.strip()
    if not normalized:
        return None
    if parse_weekday_from_message(normalized):
        return None
    if is_explicit_save_confirmation(normalized):
        return None
    if SUGGEST_PATTERN.match(normalized):
        return None

    parts = re.split(r"[,/&]+|\band\b", normalized.lower())
    selected: list[str] = []
    for part in parts:
        value = _label_to_muscle_value(part)
        if value and value not in selected:
            selected.append(value)

    if selected:
        return ", ".join(selected)

    return _normalize_muscle_group(normalized)


async def advance_after_turn(
    db: AsyncSession,
    user_id: str,
    state: SchedulingState,
    user_message: str,
    assistant_message: str,
    history: list | None,
) -> SchedulingState:
    """Update scheduling state after one chat turn (user message + assistant reply)."""
    state = state.model_copy(deep=True)

    if state.flow == "idle" and state.step == "idle":
        if _user_wants_to_schedule(user_message, history):
            state.flow = "schedule_workout"
            state.step = "pick_day"
            state.draft = state.draft.model_copy(
                update={"day": None, "muscle_group": None}
            )
            logger.info("Scheduling flow started (yes); step=pick_day")
        elif _user_expressed_schedule_intent(user_message):
            state.flow = "schedule_workout"
            state.step = "pick_day"
            state.draft = state.draft.model_copy(
                update={"day": None, "muscle_group": None}
            )
            logger.info("Scheduling flow started (intent); step=pick_day")
        elif _assistant_asks_for_schedule_day(assistant_message):
            state.flow = "schedule_workout"
            state.step = "pick_day"
            logger.info("Assistant asked for schedule day; step=pick_day")
        elif _assistant_asks_for_muscle_group(assistant_message):
            state.flow = "schedule_workout"
            state.step = "pick_muscle_group"
            day = parse_weekday_from_message(user_message)
            if day:
                state.draft.day = day
            logger.info("Assistant asked for muscle group; step=pick_muscle_group")

    if state.flow != "schedule_workout":
        return state

    if state.step == "pick_day":
        day = parse_weekday_from_message(user_message)
        if day:
            workouts = await get_workout_for_day(db, user_id, day)
            if workouts:
                logger.info("Schedule day %s taken; staying on pick_day", day)
                state.draft.day = None
            else:
                state.draft.day = day
                state.step = "pick_muscle_group"
                logger.info("Schedule day %s free; step=pick_muscle_group", day)

    elif state.step == "pick_muscle_group":
        muscle = _parse_muscle_groups_from_message(user_message)
        if muscle:
            state.draft.muscle_group = muscle
            state.step = "pick_exercises"
            logger.info("Muscle group set; step=pick_exercises")

    elif state.step == "pick_exercises":
        if _assistant_has_review(assistant_message):
            state.step = "review"
            logger.info("Review summary detected; step=review")

    elif state.step == "review":
        if is_explicit_save_confirmation(user_message):
            state.flow = "idle"
            state.step = "idle"
            state.draft = state.draft.model_copy(update={"day": None, "muscle_group": None})
            logger.info("Save confirmed; scheduling flow cleared")

    if state.step == "pick_exercises" and _assistant_has_review(assistant_message):
        state.step = "review"

    if (
        state.step == "pick_day"
        and state.draft.day
        and _assistant_asks_for_muscle_group(assistant_message)
    ):
        state.step = "pick_muscle_group"
        logger.info("Assistant asked for muscle group; step=pick_muscle_group")

    return state
