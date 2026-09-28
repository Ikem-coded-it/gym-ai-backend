from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.rag.llm import format_docs


class SearchFitnessKnowledgeInput(BaseModel):
    query: str = Field(
        min_length=1,
        description=(
            "Search query for the fitness knowledge base, e.g. "
            "'barbell row form', 'shoulder hypertrophy exercises', 'leg day warm-up'"
        ),
    )


def make_rag_tool(retriever):
    async def search_fitness_knowledge(query: str) -> str:
        docs = retriever.invoke(query.strip())
        if not docs:
            return "No matching knowledge base entries found."
        return format_docs(docs)

    return [
        StructuredTool.from_function(
            coroutine=search_fitness_knowledge,
            name="search_fitness_knowledge",
            description=(
                "Search the fitness knowledge base for exercise technique, equipment, "
                "muscle groups, programming, and general training information. "
                "Use when the user asks how to perform an exercise, wants exercise "
                "suggestions (e.g. Step 3 'suggest'), or needs factual fitness guidance. "
                "Do NOT use for the user's saved schedule (use workout tools), dates "
                "(use get_current_date), or saving a confirmed plan "
                "(use create_workout_with_exercises)."
            ),
            args_schema=SearchFitnessKnowledgeInput,
        ),
    ]
