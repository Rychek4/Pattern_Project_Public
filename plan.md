# Plan: Fix Tool Use Calls Missing from Web Process Panel

## Context

The web UI's process panel doesn't show tool invocations because of gaps between
two parallel event systems (EngineEventType and ProcessEventType). Since the
desktop GUI is being deprecated, this plan focuses exclusively on the web path.

---

## Architecture Decision: Which Event System to Use?

There are two options for getting tool calls to the web UI:

**Option A — Forward ProcessEventType.TOOL_INVOKED from ProcessEventBus**
- Add `TOOL_INVOKED` to `_FORWARDED_PROCESS_EVENTS` in web_server.py
- Add a conversion case in `_process_event_to_ws()`
- Pros: Single line change fixes ALL sources (user, pulse, reminder, telegram)
  because `response_helper.py` already emits `ProcessEventType.TOOL_INVOKED` for
  every tool call regardless of origin
- Cons: Relies on the ProcessEventBus (a GUI-era artifact) surviving long-term

**Option B — Emit EngineEventType.TOOL_INVOKED from the engine**
- Add `self._emit(EngineEventType.TOOL_INVOKED, ...)` in chat_engine.py wherever
  tools are processed
- Pros: Uses the "proper" engine event system; web_server.py already has a handler
  for it (line 195)
- Cons: Must add emission in multiple places (process_message, process_pulse,
  process_reminder); risk of double-display with existing SERVER_TOOL_INVOKED
  emission for server tools

**Recommendation: Option A** — It's the minimal, correct fix. ProcessEventBus is
the single source of truth for tool invocations (response_helper.py emits there
for ALL code paths). Forwarding it is one change that fixes everything. We can
deprecate ProcessEventBus later as a separate effort if desired.

---

## Changes

### Step 1: Forward TOOL_INVOKED to web clients

**File: `interface/web_server.py`**

1a. Add `ProcessEventType.TOOL_INVOKED` to `_FORWARDED_PROCESS_EVENTS` (~line 265):

```python
_FORWARDED_PROCESS_EVENTS = frozenset({
    ProcessEventType.DELEGATION_START,
    ProcessEventType.DELEGATION_TOOL,
    ProcessEventType.DELEGATION_COMPLETE,
    ProcessEventType.CURIOSITY_SELECTED,
    ProcessEventType.MEMORY_EXTRACTION,
    ProcessEventType.TOOL_INVOKED,        # ← ADD
})
```

1b. Add a conversion case in `_process_event_to_ws()` (~line 273-296):

```python
if event.event_type == ProcessEventType.TOOL_INVOKED:
    detail = event.data.get("detail", "")
    tool_name = detail.split(":")[0].strip() if ":" in detail else detail
    return {
        "type": "tool_invoked",
        "tool_name": tool_name,
        "detail": detail,
    }
```

This single change makes ALL tool calls visible in the web UI — user messages,
pulses, reminders, and telegrams — because they all flow through
`response_helper.process_response()` which emits `ProcessEventType.TOOL_INVOKED`.

### Step 2: Remove phantom EngineEventType.TOOL_INVOKED handler

**File: `interface/web_server.py`**

Remove the `EngineEventType.TOOL_INVOKED` case from `_engine_event_to_ws()`
(~lines 195-200).

**Why:** No code in the entire codebase ever emits `EngineEventType.TOOL_INVOKED`.
It's dead code that creates confusion. Tool display now comes exclusively through
the ProcessEventBus forwarding (Step 1).

### Step 3: Deduplicate server tool display

After Steps 1-2, server tools called during `process_message()` would show twice:
once via `EngineEventType.SERVER_TOOL_INVOKED` (emitted at chat_engine.py:422-427)
and once via `ProcessEventType.TOOL_INVOKED` (emitted at response_helper.py:453-462).

**Fix — Remove SERVER_TOOL_INVOKED emission from chat_engine.py:**
- Delete lines ~421-427 in `chat_engine.py` (the `if final_state.server_tool_details`
  block inside `process_message()`)
- Remove the `EngineEventType.SERVER_TOOL_INVOKED` handler from
  `_engine_event_to_ws()` in web_server.py (~lines 202-207)
- ProcessEventBus becomes the single path for ALL tool display — clean, no duplication

### Step 4: Add STREAM_START to pulse and reminder paths

**File: `engine/chat_engine.py`**

Without STREAM_START, the web process panel never creates a "round group" for
pulse/reminder responses. The process.js client uses `stream_start` to open a new
round context (the container that holds tool nodes).

4a. In `process_pulse()` (~line 578, before the LLM call):
```python
self._emit(EngineEventType.STREAM_START)
```

4b. In `process_reminder()` (~line 700, before the LLM call):
```python
self._emit(EngineEventType.STREAM_START)
```

This ensures tool nodes have proper round context in the process panel.

### Step 5: Clean up dead code in gui.py

**File: `interface/gui.py`**

Remove the unused `_process_typed_pulse()` method (~line 2813+). It's dead code
from before the engine refactor — never called, emits to the wrong event system,
and creates confusion during maintenance.

Since GUI is being deprecated, this is low priority. Alternatively, mark it with a
`# DEPRECATED` comment if full removal feels risky.

---

## Summary of Changes

| File | Change | Fixes |
|------|--------|-------|
| `web_server.py` | Add TOOL_INVOKED to forwarded set + conversion | All tools invisible in web |
| `web_server.py` | Remove phantom TOOL_INVOKED engine handler | Dead code cleanup |
| `web_server.py` | Remove SERVER_TOOL_INVOKED engine handler | Dedup with Step 1 |
| `chat_engine.py` | Remove SERVER_TOOL_INVOKED emission in process_message() | Dedup with Step 1 |
| `chat_engine.py` | Add STREAM_START to process_pulse() | Missing round context |
| `chat_engine.py` | Add STREAM_START to process_reminder() | Missing round context |
| `gui.py` | Remove/deprecate dead _process_typed_pulse() | Dead code cleanup |

## What This Does NOT Change

- **response_helper.py** — Untouched. It already correctly emits TOOL_INVOKED for
  all tool types and all sources. It's the single source of truth.
- **process.js** — Untouched. It already handles `tool_invoked` messages correctly.
- **process_panel.py** — Untouched. Desktop GUI continues working as-is during
  deprecation period.

## Risk Assessment

- **Low risk**: Step 1 (forwarding) is additive — worst case is tools show when
  they didn't before (which is the goal)
- **Medium risk**: Step 3 (dedup) removes emission paths — needs testing to confirm
  no other consumers depend on SERVER_TOOL_INVOKED engine events
- **Low risk**: Step 4 (STREAM_START) is additive — adds context that was missing
- **No risk**: Step 5 (dead code) removes unreachable code

## Testing Strategy

1. Send a user message that triggers tool calls (e.g., "search for X") → verify
   tools appear in web process panel
2. Trigger a reflective pulse → verify pulse tool calls appear
3. Trigger a reminder → verify reminder tool calls appear
4. Send a message that triggers server tools (web_search/web_fetch) → verify they
   appear exactly once (not duplicated)
5. Verify desktop GUI still shows tools correctly (regression check during
   deprecation period)
