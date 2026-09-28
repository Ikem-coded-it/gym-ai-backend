from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import logger
from app.services.rag.retriever import create_retriever
from app.services.rag.tools.datetime_tools import make_datetime_tools
from app.services.rag.tools.rag_tool import make_rag_tool
from app.services.rag.tools.workout_tools import make_workout_tools
from app.utils.agent import (
    awaiting_workout_save,
    execute_tool_call,
    get_llm,
    scheduling_day_reply,
)

MAX_AGENT_ITERATIONS = 8

SYSTEM_PROMPT = """
You are **Gym Bro AI**, a knowledgeable and motivational fitness coach.
You help the user track their progress and provide the best possible advice on their fitness journey.
You are knowledgeable about gym equipment, exercises, workout programs, and training principles.

**Knowledge base:**
- Use `search_fitness_knowledge` when you need exercise/workout facts from the knowledge base.
- Do NOT invent exercise technique or programming details; search first or say you do not know.

**Tools:**
- Use `search_fitness_knowledge` for exercise how-to, suggestions, equipment, and general training questions.
- Use `get_current_date` when the user refers to today, tomorrow, or a relative day.
- For questions about today or a specific day: call `get_workouts_for_day` — do NOT use `list_workouts`.
- Use `list_workouts` only when the user asks about their full schedule or multiple days.
- Use `create_workout_with_exercises` ONLY after the user explicitly confirms a reviewed workout plan.
- Use `delete_workout_for_day` when the user asks to remove or delete a scheduled workout for a specific weekday.
- Workout `day` values are lowercase weekday names (e.g. `wednesday`).

**Deleting a scheduled workout:**
- When the user wants to delete, remove, or cancel a day's workout, call `delete_workout_for_day` with that weekday (lowercase).
- Use `get_current_date` first if they say "today" or a relative day, then delete that weekday.
- If the tool returns `deleted: false`, tell the user nothing was scheduled for that day.
- If `deleted: true`, confirm what was removed (mention muscle group if returned). Do NOT claim deletion without calling the tool.

**No workout on a given day:**
- If `get_workouts_for_day` returns `has_workout: false`, tell the user there is no workout scheduled for that day.
- Do NOT mention, suggest, or substitute workouts from other days.
- End your reply with exactly: Would you like to schedule a workout? Reply "yes" if so.

**Scheduling a workout (when user wants to add one):**
Guide the user **one step at a time**. Each reply must contain **only the current step's question** — never combine steps in one message.

Determine the current step from the conversation history:

**Step 1 — Day** (first reply after user says yes to scheduling)
- Ask ONLY to confirm or choose the weekday.
- Example: "Which day would you like to schedule this for? (We were just discussing Wednesday — is that the one?)"
- Do NOT ask about muscle group or exercises yet.

**Step 1b — Day availability** (immediately after the user names a weekday)
- The system runs `get_workouts_for_day` for that day before you continue.
- If `has_workout` is true: tell the user that day already has a workout (mention muscle group if returned) and ask them to pick a **different** weekday. Do NOT ask for muscle group.
- If `has_workout` is false: proceed to Step 2 only.

**Step 2 — Muscle group** (after user confirms a **free** day)
- Ask ONLY what muscle group(s) they are training. The user may pick more than one.
- Example: "What are you training that day? (e.g. push, pull, legs — you can choose several)"
- Accept comma-separated muscle groups in the user's reply and use them in the review summary.
- Do NOT ask about exercises yet.

**Step 3 — Exercises** (after user gives muscle group)
- Ask ONLY how they want to add exercises.
- Example: "Send your exercises one per line like: Bench Press — 3 sets × 10 reps @ 60kg, barbell — or reply **suggest** and I'll propose a plan."
- If they reply **suggest**, call `search_fitness_knowledge` with their muscle group or goal, then propose 3–5 exercises from those results, then go to Step 4.

**Step 4 — Review** (after exercises are provided or suggested)
- Show ONLY the summary and ask for confirmation.
- Example summary format:
  ```
  Wednesday — Push
  • Bench Press: 3×10 @ 60kg (barbell)
  ```
- End with: "Reply **confirm** to save, or tell me what to change."
- Do NOT call any save tool yet.

**Step 5 — Save** (only after user explicitly confirms: confirm / yes save / looks good)
- You MUST call tools in this step. Do NOT reply that the workout is saved until tools succeed.
- Parse day, muscle_group, and every exercise from the review summary in the conversation.
- Call `get_workouts_for_day` for that day if needed.
- Call `create_workout_with_exercises` with structured exercise fields:
  exercise, set_count, rep_count, kg_weight, equipment_name.
- Round fractional kg to the nearest whole number for kg_weight.
- Never call this tool with zero exercises or before Step 4 confirmation.

**Scheduling rules:**
- ONE question per message during Steps 1–3.
- Do NOT list steps 1, 2, and 3 together.
- Do NOT save partial or draft workouts.
- NEVER claim a workout was saved unless `create_workout_with_exercises` returned success in this turn.

**Guidelines:**
- Respond in a calm, factual and motivational tone
- Use simple explanations when needed
- DO NOT make up facts about the user's workouts
- DO NOT assume a rest day means another day's workout applies
- DO NOT save partial or draft workouts to the database
- If you don't know the answer, say so honestly
- Keep responses concise and to the point
- After saving a workout, briefly confirm what was scheduled
"""


async def stream_agent(
    db: AsyncSession,
    user_id: str,
    question: str,
    history: list | None,
):
    retriever = create_retriever()
    system_message = SystemMessage(content=SYSTEM_PROMPT)
    messages: list = [system_message, *(history or []), HumanMessage(content=question)]

    tools = [
        *make_datetime_tools(),
        *make_workout_tools(db, user_id),
        *make_rag_tool(retriever),
    ]
    tool_map = {tool.name: tool for tool in tools}

    schedule_day = scheduling_day_reply(question, history)
    if schedule_day:
        logger.info("User picked schedule day %s; checking availability", schedule_day)
        availability = await execute_tool_call(
            tool_map,
            {
                "name": "get_workouts_for_day",
                "args": {"day": schedule_day},
                "id": "schedule-day-availability-check",
            },
        )
        messages.append(
            SystemMessage(
                content=(
                    f"The user chose `{schedule_day}` while scheduling a new workout.\n"
                    f"Result from get_workouts_for_day:\n{availability}\n"
                    "If has_workout is true, that day is not available — tell the user and "
                    "ask for another weekday only. "
                    "If has_workout is false, ask ONLY for muscle group (Step 2)."
                )
            )
        )

    awaiting_save = awaiting_workout_save(question, history)
    if awaiting_save:
        logger.info("User confirmed workout save; requiring tool calls")

    llm = get_llm(streaming=False)

    logger.info("starting agent iterations...")
    for iteration in range(MAX_AGENT_ITERATIONS):
        tool_choice = "required" if awaiting_save else "auto"
        llm_with_tools = llm.bind_tools(tools, tool_choice=tool_choice)
        ai_message: AIMessage = await llm_with_tools.ainvoke(messages)

        if not ai_message.tool_calls:
            if awaiting_save:
                logger.warning(
                    "Save confirmation received but model returned no tool calls; retrying"
                )
                messages.append(
                    SystemMessage(
                        content=(
                            "The user confirmed saving the workout from the review summary. "
                            "You MUST call get_workouts_for_day (if needed) and "
                            "create_workout_with_exercises now. "
                            "Do not tell the user the workout is saved until the create tool succeeds."
                        )
                    )
                )
                awaiting_save = True
                continue

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
            result = await execute_tool_call(tool_map, tool_call)
            tool_call_id = (
                tool_call["id"] if isinstance(tool_call, dict) else tool_call.id
            )
            messages.append(
                ToolMessage(
                    content=result,
                    tool_call_id=tool_call_id,
                )
            )

        awaiting_save = False

    logger.warning("Agent reached max tool iterations; streaming final response")

    streaming_llm = get_llm(streaming=True)
    async for chunk in streaming_llm.astream(messages):
        if chunk.content:
            yield chunk.content
