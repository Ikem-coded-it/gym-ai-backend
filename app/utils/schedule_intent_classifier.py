from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, field_validator
from typing import Literal
import os

MINI_MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

class AssistantIntentResult(BaseModel):
    intent: Literal[
        "ask_day",
        "ask_muscle_group",
        "ask_review",
        "ask_exercises",
        "confirm_save",
        "other"
    ]
    confidence: float  # 0.0 to 1.0

class UserIntentResult(BaseModel):
    intent: Literal[
        "schedule_workout",    # user wants to schedule a workout
        "confirm_yes",         # user is confirming/agreeing
        "confirm_no",          # user is declining a specific yes/no question
        "cancel_schedule",     # user aborts an in-progress scheduling flow
        "provide_day",         # user is providing a day of the week
        "provide_muscle_group", # user is providing a muscle group
        "provide_exercise",    # user is providing an exercise
        "edit_workout",        # user wants to change the proposed workout before saving
        "update_saved_exercise",  # user logged or changed a saved day's exercise
        "other"                # none of the above
    ]
    day: str | None = None  # lowercase weekday when the message names one
    muscle_groups: list[str] = Field(default_factory=list)
    confidence: float  # 0.0 to 1.0

    @field_validator("day", mode="before")
    @classmethod
    def _empty_day(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("muscle_groups", mode="before")
    @classmethod
    def _empty_muscle_groups(cls, value: object) -> object:
        if not value:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

CANCEL_SCHEDULE_CONFIDENCE_THRESHOLD = 0.65

USER_INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an intent classifier for a gym AI app.
    
    Classify the user's message into exactly one intent.
    Also extract every scheduling slot that is present. A single message can contain several slots.

    Slots:
    - day: lowercase weekday (monday–sunday) if the user names one, otherwise null
    - muscle_groups: every muscle group mentioned, using only these values:
      push, pull, legs, upper-body, lower-body, full-body, chest, back, shoulders, arms, core
      Map labels like "Upper body" to upper-body. Return [] when none are mentioned.

    Intents:
    - schedule_workout: user wants to schedule or plan a workout
    - confirm_yes: user is agreeing, confirming, or saying yes
    - confirm_no: user says no to a specific yes/no question (e.g. "Would you like to schedule?")
    - cancel_schedule: user aborts or opts out of an in-progress scheduling flow (changed their mind)
    - provide_day: user is providing or mentioning a day of the week
    - provide_muscle_group: user is mentioning a muscle group or body part
    - provide_exercise: user is listing one or more exercises (including multi-line workout details)
    - edit_workout: ONLY the chip/reply "edit" or a vague request to change a proposed
      (not yet saved) plan, e.g. "let me change something", "I want to tweak the exercises".
      Do NOT use this when they name an exercise and a field (sets/reps/weight) or a weekday.
    - update_saved_exercise: user logged performance or wants to change an already saved
      exercise. Use this for messages like:
      "Just hit 11 reps on my press", "I hit 12 on squats",
      "change bench on tuesday to 2 sets", "change Thursday bench to 80kg".
      Not for scheduling a new workout.
    - other: none of the above

    Use cancel_schedule (not confirm_no) when the user stops scheduling mid-flow, e.g.:
    - "I don't want to schedule anymore"
    - "never mind" / "forget it" / "cancel" / "stop scheduling"
    - "I changed my mind"

    Return JSON only. No explanation.
    Example: {{"intent": "schedule_workout", "day": "thursday", "muscle_groups": ["back"], "confidence": 0.95}}
    Example: {{"intent": "cancel_schedule", "day": null, "muscle_groups": [], "confidence": 0.95}}
    Example: {{"intent": "provide_day", "day": "monday", "muscle_groups": [], "confidence": 0.95}}
    Example: {{"intent": "edit_workout", "day": null, "muscle_groups": [], "confidence": 0.95}}
    Example: {{"intent": "update_saved_exercise", "day": null, "muscle_groups": [], "confidence": 0.95}}
    Example: {{"intent": "update_saved_exercise", "day": "thursday", "muscle_groups": [], "confidence": 0.9}}
    Example: {{"intent": "update_saved_exercise", "day": "tuesday", "muscle_groups": [], "confidence": 0.95}}
    """),
    ("human", "User message: {message}")
])

ASSISTANT_INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an intent classifier for a gym AI app.
    Classify the assistant's message into exactly one intent.
    
    Intents:
    - ask_day: asking for a day of the week
    - ask_muscle_group: asking for a muscle group  
    - ask_review: asking for review/confirmation
    - ask_exercises: asking about exercises
    - confirm_save: confirming the workout has been saved successfully
    - other: none of the above
    
    special case:
    - if the assistant is asking for review/confirmation, and the user has not explicitly confirmed the save, then the intent is "ask_review"
    - if the assistant is confirming the save, then the intent is "confirm_save"
    
    Return JSON only. No explanation.
    Example: {{"intent": "ask_day", "confidence": 0.95}}
    """),
    ("human", "Assistant message: {message}")
])

user_intent_classifier_llm = ChatOpenAI(
    model=MINI_MODEL,   # use mini — fast and cheap for classification
    temperature=0,
    api_key=OPENAI_API_KEY
).with_structured_output(UserIntentResult)

assistant_intent_classifier_llm = ChatOpenAI(
    model=MINI_MODEL,
    temperature=0,
    api_key=OPENAI_API_KEY
).with_structured_output(AssistantIntentResult)

async def classify_user_intent(message: str) -> UserIntentResult:
    """Classify the intent of a user message using LLM"""
    try:
        result = await user_intent_classifier_llm.ainvoke(
            USER_INTENT_PROMPT.format_messages(message=message)
        )
        return result
    except Exception:
        # fallback to "other" if classification fails
        return UserIntentResult(intent="other", confidence=0.0)
    
async def classify_assistant_message(message: str) -> AssistantIntentResult:
    """Classify the intent of an assistant message using LLM"""
    try:
        result = await assistant_intent_classifier_llm.ainvoke(
            ASSISTANT_INTENT_PROMPT.format_messages(message=message)
        )
        return result
    except Exception:
        # fallback to "other" if classification fails
        return AssistantIntentResult(intent="other", confidence=0.0)


def is_cancel_schedule_intent(
    user_intent: UserIntentResult,
    *,
    confidence_threshold: float = CANCEL_SCHEDULE_CONFIDENCE_THRESHOLD,
) -> bool:
    return (
        user_intent.intent == "cancel_schedule"
        and float(user_intent.confidence) >= confidence_threshold
    )