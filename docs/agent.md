# Gym Bro AI agent

This document explains how the coach agent runs during a chat turn: prompts, tool loop, streaming behavior, and integration with scheduling. For the HTTP/SSE wrapper, see [stream_chat.md](./stream_chat.md). For step tracking and composers, see [scheduling.md](./scheduling.md).

## High-level overview

The agent is **Gym Bro AI**: a LangChain OpenAI chat model bound to **tools**. It receives:

- A fixed **system prompt** (persona, scheduling steps, tool rules).
- **Conversation history** (prior user/assistant turns).
- The **current user message**.
- Optional **scheduling directive** or **day availability** system notes from the scheduling layer.

It either:

- Calls **tools** (workouts, knowledge search, date) in a loop, then returns text, or
- Returns **text directly** when no tools are needed.

Entry point for chat: `stream_agent` in [`app/services/rag/agent.py`](../app/services/rag/agent.py), re-exported from [`app/services/rag/query_handlers.py`](../app/services/rag/query_handlers.py).

## Message stack (one turn)

Built in order inside `stream_agent`:

1. `SystemMessage(SYSTEM_PROMPT)` — long coach instructions (scheduling steps 1–5, tool usage, tone).
2. `*(history or [])` — LangChain messages from DB.
3. `HumanMessage(question)` — this turn's user text (same as saved user message).
4. **Either:**
   - `SystemMessage(scheduling_directive)` when `prepare_scheduling_turn` set a directive, **or**
   - If no directive: optional **day availability** block when `schedule_day_for_availability_check` returns a weekday — the route pre-calls `get_workouts_for_day` and injects JSON + rules into a system message.
5. During the loop: `AIMessage` with tool calls, `ToolMessage` results, and occasional extra system nudges (e.g. force save on confirm).

Scheduling directives always start with *"Authoritative scheduling decision"* and override the generic step list for that turn only.

## Tool loop

Constants: `MAX_AGENT_ITERATIONS = 8`.

1. `get_llm(streaming=False)` — non-streaming model for tool rounds.
2. Bind tools with `tool_choice="required"` when **`awaiting_workout_save`** is true (user confirmed a review summary); otherwise `tool_choice="auto"`.
3. `ainvoke(messages)` → if **no tool calls**:
   - If still awaiting save → append a system reminder and **retry** (must call create tool).
   - Else → **yield** `ai_message.content` once and **return**.
4. If tool calls → append AI message, run each tool via `execute_tool_call`, append `ToolMessage`s, repeat.
5. After max iterations → fallback: `get_llm(streaming=True).astream(messages)` and yield token chunks.

Most simple Q&A turns finish in one invocation with a single text yield. Scheduling **confirm** and **suggest** paths often need several tool iterations before any user-visible text.

### Save confirmation detection

[`app/utils/agent.py`](../app/utils/agent.py) — `awaiting_workout_save(question, history, user_intent)`:

- User intent `confirm_yes` (high confidence) **and**
- Last assistant message in history classified as `ask_review` (high confidence).

When true, the agent must call workout tools to persist; it must not claim success without `create_workout_with_exercises` succeeding.

## Tools

Tools are assembled per request with the current `db` session and `user_id`.

### Date — [`app/services/rag/tools/datetime_tools.py`](../app/services/rag/tools/datetime_tools.py)

| Tool | Description |
|------|-------------|
| `get_current_date` | Returns ISO date, lowercase weekday, and timezone (`APP_TIMEZONE`, default UTC). Use for "today", "tomorrow", relative scheduling. |

### Workouts — [`app/services/rag/tools/workout_tools.py`](../app/services/rag/tools/workout_tools.py)

| Tool | Description |
|------|-------------|
| `get_workouts_for_day` | JSON: `day`, `has_workout`, `workouts[]` for one lowercase weekday. Required when checking if a day is free during scheduling; also for "what's on Wednesday?". |
| `list_workouts` | Full schedule for the user. Not for single-day "today" questions. |
| `create_workout_with_exercises` | Creates day + muscle group + exercises in one transaction. **Only after explicit user confirm** on a reviewed plan. At least one exercise; uses `WorkoutExerciseCreate` / `WorkoutScheduleCreate`. |
| `delete_workout_for_day` | Removes the workout (and exercises) for one weekday. Returns JSON with deleted flag; coach must call tool before claiming deletion. |

The chat router may call `get_workouts_for_day` **before** the agent runs (via `schedule_day_for_availability_check`) when the user names a day while scheduling and no scheduling directive is present.

### Knowledge — [`app/services/rag/tools/rag_tool.py`](../app/services/rag/tools/rag_tool.py)

| Tool | Description |
|------|-------------|
| `search_fitness_knowledge` | RAG over the fitness knowledge base (`create_retriever()`). Used for technique, programming, and **Suggest a plan** exercise ideas. Not for the user's saved schedule or for saving workouts. |

## System prompt behavior (scheduling)

The system prompt describes a **five-step** scheduling conversation:

1. Day (and 1b — availability before muscle/exercises).
2. Muscle group(s).
3. Exercises (UI form + suggest; coach points to form, not long format examples).
4. Review summary — confirm or change; **no save tool**.
5. Save — **must** call `create_workout_with_exercises` after confirm.

Other rules: no inventing workout facts; no substituting another day's workout when a day is empty; deletion and empty-day wording; cancel mid-flow.

The **scheduling state machine** ([scheduling.md](./scheduling.md)) adds directives and composers so the backend and UI stay aligned even when the model drifts.

## Supporting utilities

| Module | Role |
|--------|------|
| [`app/utils/agent.py`](../app/utils/agent.py) | LLM factory, tool execution, weekday parsing, `awaiting_workout_save`, `schedule_day_for_availability_check` |
| [`app/services/rag/retriever.py`](../app/services/rag/retriever.py) | Vector retriever for RAG |
| [`app/services/rag/llm.py`](../app/services/rag/llm.py) | Model name and API key |
| [`app/utils/schedule_intent_classifier.py`](../app/utils/schedule_intent_classifier.py) | User/assistant intent for scheduling (used by scheduling layer and save detection) |

## Mental model

- **Scheduling** decides *what step we're on* and *what extra system message to add*.
- **Agent** decides *what to say* and *when to read/write the DB via tools*.
- **Confirm save** is the handoff: scheduling moves to idle after user confirm; agent is forced to run create tools; user sees confirmation text only after tools succeed.
