import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.logger import logger
from app.schemas.scheduling_state import ExerciseDraft

MINI_MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class ExtractedExercises(BaseModel):
    exercises: list[ExerciseDraft] = Field(default_factory=list)


EXTRACT_EXERCISES_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You extract workout exercises from a coach review summary or a user message.

Return every exercise that is clearly listed. Ignore prose that is not an exercise.

For each exercise:
- exercise: the movement name
- equipment_name: equipment if mentioned, otherwise null
- sets: one entry per set, in order. Each set has:
  - rep_count: integer reps (0 if missing)
  - kg_weight: kilograms as a number. Use 0 or null for bodyweight / no added load.
  - notes: a short note for that set if given, otherwise null
- When the text gives one plan for all sets, such as "3 sets x 10 reps @ 60kg" or "3x10", expand it
  into that many identical set entries.
- When sets differ ("Set 1: 10 reps @ 60kg, Set 2: 8 reps @ 70kg"), keep each set separate.
- When only the exercise name is given with no set details, return an empty sets list.

Return JSON only. No explanation.
Example: {{"exercises": [{{"exercise": "Squats", "equipment_name": "barbell", "sets": [{{"rep_count": 10, "kg_weight": 100, "notes": null}}, {{"rep_count": 8, "kg_weight": 110, "notes": null}}]}}]}}
""",
    ),
    ("human", "Text:\n{message}"),
])

_extractor_llm = ChatOpenAI(
    model=MINI_MODEL,
    temperature=0,
    api_key=OPENAI_API_KEY,
).with_structured_output(ExtractedExercises)


async def extract_exercises(text: str) -> list[ExerciseDraft]:
    """Parse structured exercises from a review summary or user exercise list."""
    if not text or not text.strip():
        return []
    try:
        result = await _extractor_llm.ainvoke(
            EXTRACT_EXERCISES_PROMPT.format_messages(message=text)
        )
        return [
            exercise
            for exercise in result.exercises
            if exercise.exercise and exercise.exercise.strip()
        ]
    except Exception:
        logger.exception("Failed to extract exercises from text")
        return []
