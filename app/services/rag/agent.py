from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sqlalchemy.ext.asyncio import AsyncSession



from app.logger import logger

from app.services.rag.llm import format_docs

from app.services.rag.tools.datetime_tools import make_datetime_tools

from app.services.rag.tools.workout_tools import make_workout_tools

from app.utils.agent import (

    awaiting_workout_save,

    execute_tool_call,

    get_llm,

)



MAX_AGENT_ITERATIONS = 8



SYSTEM_PROMPT = """

You are **Gym Bro AI**, a knowledgeable and motivational fitness coach.

You help the user track their progress and provide the best possible advice on their fitness journey.

You are knowledgeable about gym equipment, exercises, workout programs, and training principles.



Use the following context from the fitness knowledge base to answer the user's question.



**Context:**

{context}



**Tools:**

- Use `get_current_date` when the user refers to today, tomorrow, or a relative day.

- For questions about today or a specific day: call `get_workouts_for_day` — do NOT use `list_workouts`.

- Use `list_workouts` only when the user asks about their full schedule or multiple days.

- Use `create_workout_with_exercises` ONLY after the user explicitly confirms a reviewed workout plan.

- Workout `day` values are lowercase weekday names (e.g. `wednesday`).



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



**Step 2 — Muscle group** (after user confirms the day)

- Ask ONLY what muscle group they are training.

- Example: "What are you training that day? (e.g. push, pull, legs, upper-body)"

- Do NOT ask about exercises yet.



**Step 3 — Exercises** (after user gives muscle group)

- Ask ONLY how they want to add exercises.

- Example: "Send your exercises one per line like: Bench Press — 3 sets × 10 reps @ 60kg, barbell — or reply **suggest** and I'll propose a plan."

- If they reply **suggest**, propose 3–5 exercises from RAG context, then go to Step 4.



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

    retriever,

):

    context = format_docs(retriever.invoke(question))

    system_message = SystemMessage(content=SYSTEM_PROMPT.format(context=context))

    messages: list = [system_message, *(history or []), HumanMessage(content=question)]



    tools = [*make_datetime_tools(), *make_workout_tools(db, user_id)]

    tool_map = {tool.name: tool for tool in tools}



    awaiting_save = awaiting_workout_save(question, history)

    if awaiting_save:

        logger.info("User confirmed workout save; requiring tool calls")



    llm = get_llm(streaming=False)



    logger.info("starting agent iterations...")

    for iteration in range(MAX_AGENT_ITERATIONS):

        tool_choice = "required" if awaiting_save else "auto"

        llm_with_tools = llm.bind_tools(tools, tool_choice=tool_choice)

        ai_message: AIMessage = await llm_with_tools.ainvoke(messages)
        logger.info(f"AI message: {ai_message.model_dump_json(indent=2)}")


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


