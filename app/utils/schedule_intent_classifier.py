from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from typing import Literal
import os

MINI_MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

class AssistantIntentResult(BaseModel):
    intent: Literal[
        "ask_day",
        "ask_muscle_group",
        "ask_confirmation",
        "ask_exercises",
        "other"
    ]
    confidence: float  # 0.0 to 1.0

class UserIntentResult(BaseModel):
    intent: Literal[
        "schedule_workout",    # user wants to schedule a workout
        "confirm_yes",         # user is confirming/agreeing
        "confirm_no",          # user is declining/cancelling
        "provide_day",         # user is providing a day of the week
        "provide_muscle_group", # user is providing a muscle group
        "provide_exercise",    # user is providing an exercise
        "other"                # none of the above
    ]
    extracted_value: str | None = None  # e.g. "monday" or "chest, back"
    confidence: float  # 0.0 to 1.0

USER_INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an intent classifier for a gym AI app.
    
    Classify the user's message into exactly one intent.
    Also extract any relevant value if present.

    Intents:
    - schedule_workout: user wants to schedule or plan a workout
    - confirm_yes: user is agreeing, confirming, or saying yes
    - confirm_no: user is declining, cancelling, or saying no  
    - provide_day: user is providing or mentioning a day of the week
    - provide_muscle_group: user is mentioning a muscle group or body part
    - provide_exercise: user is mentioning an exercise
    - other: none of the above

    Return JSON only. No explanation.
    Example: {{"intent": "provide_day", "extracted_value": "monday", "confidence": 0.95}}
    """),
    ("human", "User message: {message}")
])

ASSISTANT_INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an intent classifier for a gym AI app.
    Classify the assistant's message into exactly one intent.
    
    Intents:
    - ask_day: asking for a day of the week
    - ask_muscle_group: asking for a muscle group  
    - ask_confirmation: asking for confirmation/review
    - ask_exercises: asking about exercises
    - other: none of the above
    
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
    