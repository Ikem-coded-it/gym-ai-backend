import json
import os
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.logger import logger
from app.schemas.exercise_edit import DayExerciseRow, ExerciseEditParse
from app.schemas.workout_exercise import WorkoutExerciseUpdate

MINI_MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

EXERCISE_EDIT_PARSE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You match a gym user's message to exercises already scheduled for one day.

You are given:
- the user message
- a JSON list of that day's exercises: id, exercise (stored name), sets, reps, weight, equipment

Return:
- matches: every row the user could mean. Use only ids from the list. Never invent an exercise.
- Include synonyms and family names. If several listed rows share that family, return ALL of them — never pick a single closest guess.
  Examples: "press" → bench press AND overhead press; "squats" → back squat AND goblet squat; "curls" → barbell curl AND hammer curl.
- If none of the listed rows fit, return an empty matches list.
- Also extract the fields they want to change: set_count, rep_count, kg_weight, equipment_name.
  Only fill a field when the user stated it. Leave others null.
- confidence: 0 to 1 for the match list.

Return JSON only.
Example: {{"matches": [{{"id": "uuid-here", "exercise": "Bench Press"}}], "confidence": 0.9, "set_count": null, "rep_count": 11, "kg_weight": null, "equipment_name": null}}
""",
    ),
    (
        "human",
        "User message: {message}\n\nDay's exercises:\n{exercises}",
    ),
])

_parse_llm = ChatOpenAI(
    model=MINI_MODEL,
    temperature=0,
    api_key=OPENAI_API_KEY,
).with_structured_output(ExerciseEditParse)


def normalize_exercise_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_MESSAGE_STOPWORDS = frozenset(
    {
        "change",
        "changed",
        "update",
        "updated",
        "just",
        "hit",
        "did",
        "logged",
        "make",
        "sets",
        "set",
        "reps",
        "rep",
        "the",
        "my",
        "on",
        "to",
        "for",
        "and",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "today",
        "tomorrow",
        "workout",
        "exercise",
    }
)


def _message_tokens(message: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z]+", message.lower())
        if len(token) >= 4 and token not in _MESSAGE_STOPWORDS
    ]


def _token_stems(token: str) -> list[str]:
    stems = [token]
    if token.endswith("es") and len(token) > 5:
        stems.append(token[:-2])
    elif token.endswith("s") and len(token) > 4:
        stems.append(token[:-1])
    return stems


def _rows_with_full_name_in_message(
    message: str,
    exercises: list[DayExerciseRow],
) -> list[DayExerciseRow]:
    msg_norm = normalize_exercise_name(message)
    if not msg_norm:
        return []
    return [
        row
        for row in exercises
        if (name := normalize_exercise_name(row.exercise)) and name in msg_norm
    ]


def family_matches(
    message: str,
    exercises: list[DayExerciseRow],
) -> list[DayExerciseRow]:
    """Every row whose stored name contains a user exercise token (curl/curls, squat/squats)."""
    stems = [
        stem
        for token in _message_tokens(message)
        for stem in _token_stems(token)
        if len(stem) >= 4
    ]
    if not stems:
        return []
    hits: list[DayExerciseRow] = []
    seen: set[str] = set()
    for row in exercises:
        name_norm = normalize_exercise_name(row.exercise)
        if not name_norm or row.id in seen:
            continue
        if any(stem in name_norm for stem in stems):
            seen.add(row.id)
            hits.append(row)
    return hits


def exact_unique_matches(
    message: str,
    exercises: list[DayExerciseRow],
) -> list[DayExerciseRow]:
    """Unique full-name or unique family-token match. Empty when the family is ambiguous."""
    full_hits = _rows_with_full_name_in_message(message, exercises)
    if len(full_hits) == 1:
        return full_hits
    if len(full_hits) > 1:
        return full_hits
    token_hits = family_matches(message, exercises)
    if len(token_hits) == 1:
        return token_hits
    return []


def resolve_edit_matches(
    llm_matched: list[DayExerciseRow],
    message: str,
    exercises: list[DayExerciseRow],
) -> list[DayExerciseRow]:
    """Prefer a unique full name; if a family token hits several rows, ask — do not keep the LLM's closest pick."""
    full_hits = _rows_with_full_name_in_message(message, exercises)
    if full_hits:
        return full_hits

    family_hits = family_matches(message, exercises)
    if len(family_hits) >= 2:
        return family_hits
    if llm_matched:
        return llm_matched
    if len(family_hits) == 1:
        return family_hits
    return exact_unique_matches(message, exercises)


def _patch_from_parse(parsed: ExerciseEditParse) -> WorkoutExerciseUpdate | None:
    payload = {
        "set_count": parsed.set_count,
        "rep_count": parsed.rep_count,
        "kg_weight": parsed.kg_weight,
        "equipment_name": parsed.equipment_name,
    }
    filled = {key: value for key, value in payload.items() if value is not None}
    if not filled:
        return None
    try:
        return WorkoutExerciseUpdate.model_validate(filled)
    except Exception:
        return None


def fallback_patch_from_message(message: str) -> WorkoutExerciseUpdate | None:
    """Numeric field fallback only — not used for exercise names."""
    filled: dict[str, int | float] = {}
    reps = re.search(r"\b(\d+)\s*reps?\b", message, re.IGNORECASE)
    sets = re.search(r"\b(\d+)\s*sets?\b", message, re.IGNORECASE)
    kg = re.search(r"\b(\d+(?:\.\d+)?)\s*kg\b", message, re.IGNORECASE)
    if reps:
        filled["rep_count"] = int(reps.group(1))
    if sets:
        filled["set_count"] = int(sets.group(1))
    if kg:
        filled["kg_weight"] = float(kg.group(1))
    if not filled:
        return None
    try:
        return WorkoutExerciseUpdate.model_validate(filled)
    except Exception:
        return None


async def parse_exercise_edit(
    message: str,
    exercises: list[DayExerciseRow],
) -> tuple[list[DayExerciseRow], WorkoutExerciseUpdate | None, float]:
    """Return matching rows, a partial patch, and matcher confidence."""
    if not exercises:
        return [], None, 0.0

    allowed = {row.id: row for row in exercises}
    by_name = {normalize_exercise_name(row.exercise): row for row in exercises}
    parsed = ExerciseEditParse()
    try:
        parsed = await _parse_llm.ainvoke(
            EXERCISE_EDIT_PARSE_PROMPT.format_messages(
                message=message,
                exercises=json.dumps(
                    [row.model_dump(mode="json") for row in exercises],
                    ensure_ascii=False,
                ),
            )
        )
    except Exception:
        logger.exception("Failed to parse exercise edit from user message")

    matched: list[DayExerciseRow] = []
    seen: set[str] = set()
    for item in parsed.matches:
        row = allowed.get(str(item.id))
        if row is None and item.exercise:
            row = by_name.get(normalize_exercise_name(item.exercise))
        if row is None or row.id in seen:
            continue
        seen.add(row.id)
        matched.append(row)

    matched = resolve_edit_matches(matched, message, exercises)

    patch = _patch_from_parse(parsed) or fallback_patch_from_message(message)
    return matched, patch, float(parsed.confidence)
