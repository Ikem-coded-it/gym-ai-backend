# AI Coach chat stream

This document describes how a single chat turn works: the HTTP entry point, what runs in the middle, and how the response finishes. For the LLM agent, see [agent.md](./agent.md). For scheduling state and composers, see [scheduling.md](./scheduling.md).

## High-level overview

The AI Coach uses **Server-Sent Events (SSE)** over `POST /chat`. Each turn:

1. Persists the **user message** and loads **conversation history** plus **scheduling state**.
2. Runs **scheduling preparation** (`prepare_scheduling_turn`) to decide directives and draft updates before the coach speaks.
3. Streams the **coach reply** from the RAG agent (`stream_agent`).
4. Persists the **assistant message**, **advances scheduling state** (`advance_after_turn`), and sends a **composer** payload for the UI (day picker, exercise form, confirm chips, etc.).

Two systems cooperate on every turn:

| System | Role |
|--------|------|
| **Scheduling layer** ([scheduling.md](./scheduling.md)) | Tracks wizard step and draft in the DB; drives composers and optional coach directives. |
| **Agent** ([agent.md](./agent.md)) | LangChain LLM with tools (workouts, RAG, dates); produces natural-language replies and saves workouts on confirm. |

## Entry point

**Router:** [`app/router/chat.py`](../app/router/chat.py)

### `GET /chat/history`

Used when the AI Coach screen loads.

- Loads the user's conversation and messages via `conversation_service`.
- Loads `SchedulingState` from `conversation_scheduling_states`.
- Computes `active_composer` with `resolve_active_composer(state, last_assistant_content)`.
- Returns messages plus `active_composer` for the frontend to attach to the latest assistant bubble.

### `POST /chat`

Body: `ChatCreate` with `message` (user text).

**Phase A — before streaming** (same request DB session):

1. `get_or_create_conversation` for the authenticated user.
2. `load_chat_history` — DB messages converted to LangChain `HumanMessage` / `AIMessage` ([`app/services/rag/memory.py`](../app/services/rag/memory.py)).
3. `get_scheduling_state` for the conversation.
4. `save_message` (role `user`) and **commit**.

Note: history at this point is **before** the new user row in the DB, but the route passes `chat.message` separately into the agent, so the model still sees the latest user text.

**Phase B — SSE stream** (`StreamingResponse`, `text/event-stream`):

Returns immediately; work happens inside `event_stream()`.

## What happens in between

Events are JSON objects on `data: …` lines. Helper: `_sse()` in the chat router.

### 1. `start`

```json
{ "type": "start", "conversation_id": "<uuid>" }
```

### 2. Scheduling plan

`prepare_scheduling_turn(db, user_id, scheduling_state, chat.message, history)` returns a `SchedulingTurnPlan`:

- `state` — scheduling state for this turn (may already reflect edit, slots filled, etc.).
- `directive` — optional extra system message for the agent (see [scheduling.md](./scheduling.md)).
- `user_intent` — LLM classification reused in `advance_after_turn` and save detection.

### 3. Agent stream

`stream_agent` ([`app/services/rag/query_handlers.py`](../app/services/rag/query_handlers.py) → [`app/services/rag/agent.py`](../app/services/rag/agent.py)) yields text chunks.

For each chunk:

```json
{ "type": "token", "content": "<text>" }
```

The frontend appends tokens to the in-flight assistant message. The agent may run multiple tool rounds internally before yielding user-visible text; see [agent.md](./agent.md).

### 4. Persist and advance (new DB session)

After the full assistant text is assembled:

1. `save_message` (role `assistant`).
2. `advance_after_turn(session, user_id, plan.state, chat.message, full_response, history, user_intent=plan.user_intent)` — final step, draft exercises, idle on confirm, etc.
3. `save_scheduling_state` with the returned state.
4. `commit`.

### 5. Composer

`resolve_active_composer(new_state, full_response)` maps persisted step → UI composer.

If a composer exists:

```json
{
  "type": "composer",
  "message_id": "<assistant message uuid>",
  "composer": { "kind": "...", "options": [...], ... }
}
```

Otherwise:

```json
{ "type": "composer_clear", "message_id": "<uuid>" }
```

### 6. Errors

On failure inside the stream:

```json
{ "type": "error", "message": "<detail>" }
```

## Finish

### `done`

```json
{ "type": "done", "message_id": "<assistant message uuid>" }
```

The client replaces the temporary streaming message id with the server id and may refetch history so DB and UI stay aligned.

### Typical event order (happy path)

```
start → token (×N) → composer | composer_clear → done
```

## Frontend integration (reference)

**Service:** `frontend/src/services/chat.service.ts` — parses SSE, calls handlers for `token`, `composer`, `composer_clear`, `done`, `error`.

**UI:** `frontend/src/components/pages/dashboard/AiCoachChat.tsx` — optimistic user + assistant bubbles, clears composers on older messages, shows composer only on the latest assistant message (`shouldShowMessageComposer` in `chat-composer.ts`).

## Related files

| File | Purpose |
|------|---------|
| [`app/router/chat.py`](../app/router/chat.py) | Routes, SSE envelope |
| [`app/services/conversation.py`](../app/services/conversation.py) | Messages and scheduling row CRUD |
| [`app/services/chat_scheduling.py`](../app/services/chat_scheduling.py) | Prepare, advance, composers |
| [`app/services/rag/agent.py`](../app/services/rag/agent.py) | Coach LLM and tools |
| [`app/schemas/chat_composer.py`](../app/schemas/chat_composer.py) | Composer API shape |
