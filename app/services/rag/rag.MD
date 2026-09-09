# AI Coach — RAG & Agent

High-level overview of how the AI Coach chat works. See the source files for implementation details.

---

## What it does

The AI Coach answers fitness questions and can read/create the logged-in user's workouts.

It uses two mechanisms:

- **RAG** — retrieves relevant docs from Pinecone (exercise knowledge base) and injects them into the system prompt.
- **Tools** — lets the LLM call backend functions to query or update the user's workouts in Postgres.

---

## Key files

| File | Purpose |
|---|---|
| `app/router/chat.py` | Chat API, SSE streaming, saves messages |
| `app/services/rag/agent.py` | Agent loop (LLM + tools) |
| `app/services/rag/tools/workout_tools.py` | Tool definitions |
| `app/services/workout.py` | Workout DB logic (shared by API and tools) |
| `app/services/rag/retriever.py` | Pinecone search |
| `app/services/rag/memory.py` | Loads chat history |

---

## Request flow

1. User sends a message → `POST /chat`
2. Load conversation history, save the user message
3. Retrieve RAG context from Pinecone
4. Run the **agent loop**:
   - LLM decides whether to answer directly or call a tool
   - If tools are called, execute them and feed results back to the LLM
   - Repeat until the LLM produces a final text answer (max 5 rounds)
5. Stream the answer to the frontend as SSE tokens
6. Save the assistant message to the DB

---

## Tools (V1)

| Tool | What it does |
|---|---|
| `get_current_date` | Returns today's date and day of week (for "today" / relative questions) |
| `get_workouts_for_day` | Returns workouts for one weekday only (`has_workout: false` if rest day) |
| `list_workouts` | Returns the user's full workout schedule |
| `create_workout` | Creates a new workout day |

Set `APP_TIMEZONE` (e.g. `Asia/Manila`) so "today" resolves correctly. Defaults to `UTC`.

---

## Streaming

The backend sends Server-Sent Events: `start` → `token` (text chunks) → `done` (or `error`).

Tool execution happens silently on the server — the frontend only sees the final streamed reply.

---

## Config

Requires `OPENAI_API_KEY`, `MODEL`, and Pinecone vars (`PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_NAMESPACE`, `TOP_K`).

---

## Not yet implemented

- Edit/delete workout or exercise tools
- Tool progress events in the SSE stream
- Persisting tool calls in chat history
