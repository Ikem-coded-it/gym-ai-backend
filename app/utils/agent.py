import re

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from app.logger import logger
from app.services.rag.llm import MODEL, OPENAI_API_KEY
from app.utils.schedule_intent_classifier import classify_user_intent, classify_assistant_message


WEEKDAY_ALIASES: dict[str, str] = {
    "monday": "monday",
    "mon": "monday",
    "tuesday": "tuesday",
    "tue": "tuesday",
    "tues": "tuesday",
    "wednesday": "wednesday",
    "wed": "wednesday",
    "thursday": "thursday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "friday": "friday",
    "fri": "friday",
    "saturday": "saturday",
    "sat": "saturday",
    "sunday": "sunday",
    "sun": "sunday",
}

def message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return " ".join(parts)
    return str(content or "")


def get_last_assistant_message(history: list | None) -> str | None:
    if not history:
        return None
    for message in reversed(history):
        if not isinstance(message, AIMessage):
            continue
        else:
            return message_text(message)
    return None


# This function is used to check if the user has a pending workout review
#  by checking if the user has explicitly confirmed the save and if the chat history has a pending workout review
async def awaiting_workout_save(
    question: str,
    history: list | None,
    user_intent=None,
) -> bool:
    if user_intent is None:
        user_intent = await classify_user_intent(question)
    assistant_intent = await classify_assistant_message(get_last_assistant_message(history))
    return user_intent.intent == "confirm_yes" and float(user_intent.confidence) > 0.8 and assistant_intent.intent == "ask_review" and float(assistant_intent.confidence) > 0.8


def parse_weekday_from_message(text: str) -> str | None:
    normalized = text.strip().lower().rstrip(".")
    if not normalized:
        return None

    if normalized in WEEKDAY_ALIASES:
        return WEEKDAY_ALIASES[normalized]

    for token in re.findall(r"[a-z]+", normalized):
        if token in WEEKDAY_ALIASES:
            return WEEKDAY_ALIASES[token]

    return None


SCHEDULE_KEYWORDS_PATTERN = re.compile(
    r"\b(schedule|scheduled|plan|add|book|set up|create|want to|workout for|training on)\b",
    re.IGNORECASE,
)


def message_suggests_scheduling(text: str) -> bool:
    return bool(SCHEDULE_KEYWORDS_PATTERN.search(text))


def _resolve_day_from_question(question: str, day_slot: str | None) -> str | None:
    if day_slot:
        parsed = parse_weekday_from_message(day_slot)
        if parsed:
            return parsed
    return parse_weekday_from_message(question)


async def schedule_day_for_availability_check(
    question: str,
    history: list | None,
    user_intent=None,
) -> str | None:
    """
    Return a weekday when the user is picking or naming a day for a new workout
    and we must verify the day is free before muscle group / exercises.
    """
    if user_intent is None:
        user_intent = await classify_user_intent(question)
    day = _resolve_day_from_question(question, user_intent.day)
    if not day:
        return None

    user_confident = float(user_intent.confidence) >= 0.6
    last_assistant = get_last_assistant_message(history)
    assistant_intent = await classify_assistant_message(last_assistant or "")

    if user_intent.intent in (
        "confirm_yes",
        "confirm_no",
        "cancel_schedule",
        "provide_exercise",
    ):
        return None

    if assistant_intent.intent == "ask_day" and user_intent.intent in (
        "provide_day",
        "schedule_workout",
        "confirm_yes",
    ):
        return day

    if user_intent.intent == "schedule_workout" and user_confident:
        return day

    if user_intent.intent == "provide_day" and user_confident:
        if assistant_intent.intent in ("ask_day", "other") or not history:
            return day

    if message_suggests_scheduling(question):
        return day

    return None


async def scheduling_day_reply(question: str, history: list | None) -> str | None:
    """Backward-compatible alias for schedule day availability pre-check."""
    return await schedule_day_for_availability_check(question, history)


def get_llm(*, streaming: bool) -> ChatOpenAI:
    return ChatOpenAI(
        model=MODEL,
        temperature=0,
        api_key=OPENAI_API_KEY,
        streaming=streaming,
    )


async def execute_tool_call(
    tool_map: dict[str, BaseTool],
    tool_call,
) -> str:
    tool_name = tool_call["name"] if isinstance(tool_call, dict) else tool_call.name
    tool_args = tool_call["args"] if isinstance(tool_call, dict) else tool_call.args
    tool = tool_map.get(tool_name)
    if tool is None:
        return f"Error: unknown tool '{tool_name}'"

    try:
        result = await tool.ainvoke(tool_args)
        return str(result)
    except Exception as e:
        logger.exception(f"Tool '{tool_name}' failed: {e}")
        return f"Error running {tool_name}: {e}"
