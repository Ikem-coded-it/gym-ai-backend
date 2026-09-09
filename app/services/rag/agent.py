from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.services.rag.llm import MODEL, OPENAI_API_KEY, format_docs
from app.services.rag.tools.datetime_tools import make_datetime_tools
from app.services.rag.tools.workout_tools import make_workout_tools

MAX_AGENT_ITERATIONS = 5

SYSTEM_PROMPT = """
You are **Gym Bro AI**, a knowledgeable and motivational fitness coach.
You help the user track their progress and provide the best possible advice on their fitness journey.
You are knowledgeable about gym equipment, exercises, workout programs, and training principles.

Use the following context from the fitness knowledge base to answer the user's question.

**Context:**
{context}

**Tools:**
- Use `get_current_date` when the user refers to today, tomorrow, or a relative day.
- For questions about today or a specific day: call `get_workouts_for_day` with that weekday — do NOT use `list_workouts`.
- Use `list_workouts` only when the user asks about their full schedule or multiple days.
- Use `create_workout` when the user asks to add a new workout day.
- Workout `day` values are lowercase weekday names (e.g. `wednesday`).

**No workout on a given day:**
- If `get_workouts_for_day` returns `has_workout: false`, tell the user there is no workout scheduled for that day.
- Do NOT mention, suggest, or substitute workouts from other days.
- End your reply with exactly: Would you like to schedule a workout? Reply "yes" if so.

**Guidelines:**
- Respond in a calm, factual and motivational tone
- Use simple explanations when needed
- DO NOT make up facts about the user's workouts
- DO NOT assume a rest day means another day's workout applies
- If you don't know the answer, say so honestly
- Keep responses concise and to the point
- After changing workouts, briefly confirm what you did
"""


def _get_llm(*, streaming: bool) -> ChatOpenAI:
    return ChatOpenAI(
        model=MODEL,
        temperature=0,
        api_key=OPENAI_API_KEY,
        streaming=streaming,
    )


async def _execute_tool_call(
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


async def stream_agent(
    db: AsyncSession,
    user_id: str,
    question: str,
    history: list | None,
    retriever,
):
    context = format_docs(retriever.invoke(question))
    system_message = SystemMessage(content=SYSTEM_PROMPT.format(context=context))
    messages: list = [system_message, *(history or []), HumanMessage(content=question)]

    tools = [*make_datetime_tools(), *make_workout_tools(db, user_id)]
    tool_map = {tool.name: tool for tool in tools}

    llm = _get_llm(streaming=False)
    llm_with_tools = llm.bind_tools(tools)

    for iteration in range(MAX_AGENT_ITERATIONS):
        ai_message: AIMessage = await llm_with_tools.ainvoke(messages)

        if not ai_message.tool_calls:
            if ai_message.content:
                yield ai_message.content
            return

        messages.append(ai_message)
        logger.info(
            "Agent tool calls (iteration %s): %s",
            iteration + 1,
            [call["name"] for call in ai_message.tool_calls],
        )

        for tool_call in ai_message.tool_calls:
            result = await _execute_tool_call(tool_map, tool_call)
            tool_call_id = (
                tool_call["id"] if isinstance(tool_call, dict) else tool_call.id
            )
            messages.append(
                ToolMessage(
                    content=result,
                    tool_call_id=tool_call_id,
                )
            )

    logger.warning("Agent reached max tool iterations; streaming final response")

    streaming_llm = _get_llm(streaming=True)
    async for chunk in streaming_llm.astream(messages):
        if chunk.content:
            yield chunk.content
