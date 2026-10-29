import asyncio
import os
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.logger import logger
from app.schemas.scheduling_state import ExerciseDraft, ExerciseSetDraft
from app.services.rag.retriever import create_retriever
from app.utils.exercise_match import normalize_exercise_name

MINI_MODEL = "gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SUGGESTED_SET_COUNT = 2
SUGGESTED_REP_COUNT = 10
MIN_EXERCISES_PER_GROUP = 2
MAX_DOC_CHARS = 1500

# Muscle group -> knowledge base topics to search (the KB is organised by
# chest / back / legs / shoulders / arms).
GROUP_TOPICS: dict[str, list[str]] = {
    "push": ["chest", "shoulders"],
    "pull": ["back", "arms biceps"],
    "legs": ["legs"],
    "upper-body": ["chest", "back", "shoulders", "arms"],
    "lower-body": ["legs"],
    "full-body": ["legs", "chest", "back", "shoulders"],
    "chest": ["chest"],
    "back": ["back"],
    "shoulders": ["shoulders"],
    "arms": ["arms biceps triceps"],
    "core": ["core abs"],
}


class SuggestedExercise(BaseModel):
    muscle_group: str = Field(description="One of the requested muscle groups, exactly as written")
    exercise: str = Field(max_length=50)
    equipment_name: str | None = None
    kg_weight: float | None = Field(
        default=None,
        ge=0,
        lt=1000,
        description="Reasonable working weight in kg for 10 reps. 0 for bodyweight.",
    )


class SuggestedPlan(BaseModel):
    exercises: list[SuggestedExercise] = Field(default_factory=list)


SUGGEST_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are a strength coach building a workout from a fitness knowledge base.

Requested muscle groups: {groups}

Knowledge base excerpts (prefer exercises that appear here):
{context}

Rules:
- Return AT LEAST {minimum} different exercises for EACH requested muscle group.
- For a combined group, cover its parts: push = chest and shoulders, pull = back and biceps,
  upper-body = chest, back, shoulders and arms, lower-body = legs, full-body = legs, chest, back and shoulders.
- Set muscle_group on every exercise to one of the requested groups, exactly as written.
- Do not repeat an exercise.
- Each exercise will be done for {sets} sets of {reps} reps. For each one give kg_weight:
  a reasonable working weight in kg for 10 reps for an intermediate lifter. For dumbbell
  exercises give the weight of ONE dumbbell. Bodyweight exercises (pull-up, plank, dip) use 0.
- equipment_name: the main equipment, e.g. barbell, dumbbell, cable, machine, bodyweight.

Return JSON only. No explanation.""",
    ),
    ("human", "Build the exercise list."),
])

_suggest_llm = ChatOpenAI(
    model=MINI_MODEL,
    temperature=0,
    api_key=OPENAI_API_KEY,
).with_structured_output(SuggestedPlan)


@lru_cache(maxsize=1)
def _retriever():
    return create_retriever()


def parse_muscle_groups(muscle_group: str | None) -> list[str]:
    """Split the draft's comma-separated muscle group value into unique groups."""
    groups: list[str] = []
    for part in (muscle_group or "").split(","):
        value = part.strip().lower()
        if value and value not in groups:
            groups.append(value)
    return groups


async def _retrieve_context(groups: list[str]) -> str:
    """Run the same knowledge base search the coach's search_fitness_knowledge tool does."""
    sections: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for topic in GROUP_TOPICS.get(group, [group]):
            try:
                docs = await asyncio.to_thread(
                    _retriever().invoke, f"{topic} exercises"
                )
            except Exception:
                logger.exception("Knowledge base search failed for %s", topic)
                continue
            for doc in docs:
                key = str(doc.metadata.get("id") or doc.page_content[:80])
                if key in seen:
                    continue
                seen.add(key)
                sections.append(f"[{group}] {doc.page_content[:MAX_DOC_CHARS]}")
    return "\n\n".join(sections) or "No knowledge base entries found."


async def _generate(groups: list[str], context: str) -> list[SuggestedExercise]:
    try:
        plan = await _suggest_llm.ainvoke(
            SUGGEST_PROMPT.format_messages(
                groups=", ".join(groups),
                context=context,
                minimum=MIN_EXERCISES_PER_GROUP,
                sets=SUGGESTED_SET_COUNT,
                reps=SUGGESTED_REP_COUNT,
            )
        )
        return plan.exercises
    except Exception:
        logger.exception("Failed to generate suggested exercises")
        return []


def _count_by_group(
    exercises: list[SuggestedExercise], groups: list[str]
) -> dict[str, int]:
    counts = {group: 0 for group in groups}
    for item in exercises:
        label = item.muscle_group.strip().lower()
        if label in counts:
            counts[label] += 1
    return counts


async def suggest_exercises(muscle_group: str | None) -> list[ExerciseDraft]:
    """Exercises from the knowledge base for the chosen muscle groups.

    At least two per group, each with exactly 2 sets of 10 reps at a reasonable weight.
    Returns [] when nothing could be generated, so the caller can fall back.
    """
    groups = parse_muscle_groups(muscle_group)
    if not groups:
        return []

    context = await _retrieve_context(groups)
    suggested = await _generate(groups, context)

    counts = _count_by_group(suggested, groups)
    short = [group for group, count in counts.items() if count < MIN_EXERCISES_PER_GROUP]
    if short:
        logger.info("Suggestion short for %s; asking again", short)
        suggested += await _generate(short, context)
        counts = _count_by_group(suggested, groups)
        still_short = [g for g, c in counts.items() if c < MIN_EXERCISES_PER_GROUP]
        if still_short:
            logger.warning("Suggestion still short for %s", still_short)

    drafts: list[ExerciseDraft] = []
    seen: set[str] = set()
    for item in suggested:
        name = item.exercise.strip()
        key = normalize_exercise_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        drafts.append(
            ExerciseDraft(
                exercise=name,
                equipment_name=(item.equipment_name or "").strip() or None,
                sets=[
                    ExerciseSetDraft(
                        rep_count=SUGGESTED_REP_COUNT,
                        kg_weight=item.kg_weight or 0,
                    )
                    for _ in range(SUGGESTED_SET_COUNT)
                ],
            )
        )
    logger.info("Suggested %s exercises for %s", len(drafts), groups)
    return drafts


def format_review_summary(
    day: str | None,
    muscle_group: str | None,
    exercises: list[ExerciseDraft],
) -> str:
    """The review text the coach shows, one line per set (parsed again on confirm)."""
    groups = ", ".join(
        part.strip().replace("-", " ").title()
        for part in (muscle_group or "").split(",")
        if part.strip()
    )
    title = f"{(day or '').capitalize()} — {groups}".strip(" —")
    lines = [title]
    for exercise in exercises:
        equipment = f" ({exercise.equipment_name})" if exercise.equipment_name else ""
        lines.append(f"• {exercise.exercise}{equipment}")
        for index, exercise_set in enumerate(exercise.sets, start=1):
            weight = exercise_set.kg_weight or 0
            lines.append(
                f"  Set {index}: {exercise_set.rep_count} reps @ {weight:g}kg"
            )
    return "\n".join(lines)
