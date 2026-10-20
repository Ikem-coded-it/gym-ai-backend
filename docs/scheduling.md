# Workout scheduling state and composers

This document explains how in-chat workout scheduling is tracked in the database, how each chat turn updates that state, and how the API tells the frontend which **composer** to show. For the HTTP flow, see [stream_chat.md](./stream_chat.md). For the coach LLM and tools, see [agent.md](./agent.md).

## High-level overview

Scheduling is a **wizard state machine** stored per conversation. It does not replace the agent: the coach still speaks and saves workouts via tools. Scheduling:

- Stores **flow**, **step**, and a **draft** (day, muscle group, exercises).
- Injects **directives** into the agent when the coach must ask exactly one thing.
- Emits **composer** payloads so the UI can show day chips, muscle multi-select, exercise form, or Confirm/Edit.

Implementation: [`app/services/chat_scheduling.py`](../app/services/chat_scheduling.py).

Schemas: [`app/schemas/scheduling_state.py`](../app/schemas/scheduling_state.py), [`app/schemas/chat_composer.py`](../app/schemas/chat_composer.py).

Persistence: [`app/models/conversation_scheduling_state.py`](../app/models/conversation_scheduling_state.py) — table `conversation_scheduling_states` (one row per conversation).

## State shape

### `SchedulingState`

| Field | Meaning |
|-------|---------|
| `flow` | `idle` or `schedule_workout` |
| `step` | See steps below |
| `draft.day` | Lowercase weekday when chosen |
| `draft.muscle_group` | Composer muscle value(s), often comma-separated |
| `draft.exercises` | List of `ExerciseDraft` for prefill on edit and composer payload |

`is_scheduling()` is true when `flow == schedule_workout` and `step != idle`.

### Steps

```
idle
  → pick_day
  → pick_muscle_group
  → pick_exercises
  → review
  → edit_exercises  (branch from review when user chooses Edit)
  → idle            (after confirm, or cancel)
```

`next_schedule_step(draft)` only returns `pick_day`, `pick_muscle_group`, or `pick_exercises` based on empty draft fields. Steps **`review`** and **`edit_exercises`** are set explicitly in prepare/advance logic (exercise submit, suggest + summary, edit chip, etc.).

### Database columns

| Column | Maps to |
|--------|---------|
| `flow`, `step` | State machine position |
| `draft_day`, `draft_muscle_group` | Draft slots |
| `draft_exercises` (JSONB) | Serialized `ExerciseDraft[]` |

Load/save: `scheduling_state_from_row`, `apply_scheduling_state`, via `conversation_service`.

## Two functions per chat turn

Every `POST /chat` turn runs **prepare** then **advance**, with the agent in between.

```
DB state at start
       ↓
prepare_scheduling_turn(user message, history)  →  plan.state, plan.directive, plan.user_intent
       ↓
stream_agent(..., scheduling_directive=plan.directive)
       ↓
advance_after_turn(plan.state, user message, assistant text)  →  new_state
       ↓
save_scheduling_state(new_state)
resolve_active_composer(new_state, assistant text)  →  SSE composer
```

**Important:** `plan.state` from prepare is the input to advance. The **composer** uses **`new_state` after advance**, not prepare alone. Example: user submits the exercise form — prepare may still leave `step=pick_exercises` while sending `EXERCISES_SUBMITTED_DIRECTIVE`; advance then sets `step=review` and persists exercises.

## `prepare_scheduling_turn`

Runs **before** the coach replies. Always classifies the user message (`classify_user_intent` in [`app/utils/schedule_intent_classifier.py`](../app/utils/schedule_intent_classifier.py)).

Decision order (first match wins):

1. **Cancel** while scheduling → reset to `SchedulingState.idle()`, `CANCEL_SCHEDULING_DIRECTIVE`.
2. **On `review`:**
   - **Edit** (`edit` chip or `edit_workout` intent) → `step=edit_exercises`, backfill `draft.exercises` from last assistant review in history if needed, `EDIT_EXERCISES_DIRECTIVE`.
   - **Confirm** (`confirm_yes`, high confidence) → stay on review, **no directive** (agent handles save via `awaiting_workout_save`).
   - Else → `REVIEW_SCHEDULING_DIRECTIVE`.
3. **On `pick_exercises` or `edit_exercises`:**
   - User sent exercises (form or typed lines) → `EXERCISES_SUBMITTED_DIRECTIVE` (step unchanged here).
   - User sent `suggest` → `SUGGEST_EXERCISES_DIRECTIVE`.
   - On `edit_exercises` otherwise → `EDIT_EXERCISES_DIRECTIVE`.
   - Else → `scheduling_directive(state)` for pick exercises.
4. **Not entering scheduling** (`_should_enter_scheduling` false) → no directive, state unchanged.
5. **Enter/continue scheduling** → set `flow=schedule_workout`, `_apply_user_slots` (day/muscle + blocked-day check), `step=next_schedule_step(...)`, directive from `scheduling_directive` (blocked day vs current step).

Returns `SchedulingTurnPlan`: `state`, `directive`, `user_intent`.

### Slot filling (`_apply_user_slots`)

- **Day:** `canonical_day` from intent slot or message parsing; if day already has a workout, day is **not** stored and a **blocked day** directive asks for another weekday.
- **Muscle:** `canonical_muscle_group` from intent + regex patterns on message text.
- **Merge:** `merge_schedule_slots` only writes fields provided this turn.

### Directives

All scheduling directives include:

> Authoritative scheduling decision (follow this over the generic step list):

| Constant | When |
|----------|------|
| `CANCEL_SCHEDULING_DIRECTIVE` | User aborted flow |
| Blocked-day variant in `scheduling_directive` | Chosen day taken |
| Step-specific (`pick_day`, `pick_muscle_group`, `pick_exercises`) | Normal wizard |
| `EXERCISES_SUBMITTED_DIRECTIVE` | User submitted exercise lines |
| `SUGGEST_EXERCISES_DIRECTIVE` | User tapped Suggest |
| `REVIEW_SCHEDULING_DIRECTIVE` | On review, re-show summary |
| `EDIT_EXERCISES_DIRECTIVE` | User editing before save |

## `advance_after_turn`

Runs **after** the assistant message is saved. Reuses `user_intent` from prepare when provided; classifies **assistant** message too.

- **Cancel** → idle.
- **Idle + assistant opened scheduling** (`ask_day` / `ask_muscle_group` / `ask_exercises`, confident) → enter `schedule_workout`, apply slots, set step via `next_schedule_step`.
- **`pick_exercises` / `edit_exercises`:**
  - Edit request → stay on step; backfill exercises if needed.
  - User listed exercises → `step=review`, `_persist_extracted_exercises`.
  - Assistant `ask_review` + confident + message looks like a summary (`assistant_message_is_review_summary`) → `step=review`, persist exercises (covers suggest flow).
  - `suggest` → stay on pick exercises.
- **`review`:**
  - User `confirm_yes` (confident) → **idle** (scheduling UI done; agent still saves via tools).
  - Assistant `ask_review` → refresh `draft.exercises` from new summary text.
- **Other steps** → `_skip_filled_slots` jumps forward if draft already has day/muscle (never rewinds).

### Exercise draft extraction

- [`app/utils/exercise_extractor.py`](../app/utils/exercise_extractor.py) — LLM structured extract from review or user lines.
- `_persist_extracted_exercises` — prefer assistant text, else user message.
- `_backfill_draft_exercises_from_history` — on Edit, scan prior `AIMessage`s in LangChain history if draft is empty.

### Heuristics (with LLM intents)

| Helper | Purpose |
|--------|---------|
| `EDIT_PATTERN` / `is_edit_request` | Edit chip or `edit_workout` intent |
| `SUGGEST_PATTERN` | Suggest chip |
| `EXERCISE_DETAIL_PATTERN` | Detect sets/reps/`@ kg` in text |
| `user_message_lists_exercises` | Form submit; excludes edit/suggest |
| `assistant_message_is_review_summary` | Avoid treating short edit acks as review |
| `is_cancel_schedule_intent` | Abort flow |

Confidence threshold `SLOT_CONFIDENCE_THRESHOLD = 0.8` for many transitions; exercise provide uses `0.6`.

## Composers

Composers describe **UI shortcuts below the latest assistant message**, not replacements for the text input.

### `composer_for_state`

Pure mapping from persisted state:

| Step | `kind` | UI |
|------|--------|-----|
| `pick_day` | `day_select` | Weekday options + optional `suggested_value` |
| `pick_muscle_group` | `muscle_group_multi_select` | Muscle options + suggested |
| `pick_exercises`, `edit_exercises` | `exercise_form` | Suggest option + optional `exercises` prefill |
| `review` | `confirm` | Confirm / Edit chips |

If not scheduling (`idle` flow/step), returns `None`.

### `resolve_active_composer`

1. Use `composer_for_state(state)` if non-null.
2. Else, if still scheduling and `last_assistant_message` provided, classify assistant intent and **infer** a composer (fallback when step lags behind coach wording).
3. `confirm_save` on assistant → treat as idle (no composer).

Used in:

- `POST /chat` — SSE `composer` event after advance.
- `GET /chat/history` — `active_composer` on the response.

Frontend attaches `active_composer` to the last assistant message only; see `attachActiveComposerToMessages` and `shouldShowMessageComposer` in the frontend chat-composer utils.

## Intent classification

[`app/utils/schedule_intent_classifier.py`](../app/utils/schedule_intent_classifier.py) — gpt-4o-mini structured output:

**User intents:** `schedule_workout`, `confirm_yes`, `confirm_no`, `cancel_schedule`, `provide_day`, `provide_muscle_group`, `provide_exercise`, `edit_workout`, `other` — plus optional `day` and `muscle_groups` slots.

**Assistant intents:** `ask_day`, `ask_muscle_group`, `ask_exercises`, `ask_review`, `confirm_save`, `other`.

Used by prepare, advance, composer fallback, and `awaiting_workout_save` in the agent.

## Example turn sequence

| User action | Prepare (summary) | Advance → step | Composer |
|-------------|-------------------|----------------|----------|
| "Schedule workout" | Enter flow, maybe pick_day | May sync from assistant ask | day / muscle / form |
| Tap Saturday | Draft day, pick_muscle_group | skip slots if needed | muscle |
| Tap Legs | Draft muscle, pick_exercises | — | exercise_form |
| Send form | EXERCISES_SUBMITTED, step still pick_* | → review | confirm |
| Edit | → edit_exercises, backfill | stay edit_exercises | exercise_form |
| Update form | EXERCISES_SUBMITTED | → review | confirm |
| Confirm | directive None | → idle | none |

## What scheduling does not do

- Does **not** call `create_workout_with_exercises` — the agent does on confirm.
- Does **not** guarantee the coach's words match the step; directives and advance reduce drift.
- Does **not** store partial workouts in the workout tables — only draft fields on the scheduling row until save.

## Related files

| File | Role |
|------|------|
| [`app/services/chat_scheduling.py`](../app/services/chat_scheduling.py) | Prepare, advance, composers, directives |
| [`app/schemas/scheduling_state.py`](../app/schemas/scheduling_state.py) | State and draft models |
| [`app/schemas/chat_composer.py`](../app/schemas/chat_composer.py) | Composer API model |
| [`app/models/conversation_scheduling_state.py`](../app/models/conversation_scheduling_state.py) | DB row |
| [`app/router/chat.py`](../app/router/chat.py) | Wires prepare → agent → advance → composer |
