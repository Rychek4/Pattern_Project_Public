# Plan: Fix Tool Use Display in Web Process Panel

## Context

The process panel does not show tool invocations during reminder, reflective,
or action pulses. With the GUI being deprecated and the web UI becoming the
standard, this plan targets the web event pipeline exclusively. Desktop-only
code paths (`gui.py`'s `_process_typed_pulse`, `_on_engine_event` bridge) are
treated as legacy and left untouched.

---

## Root Cause Summary

Three gaps prevent tool calls from reaching the web process panel:

| # | Gap | Location | Impact |
|---|-----|----------|--------|
| 1 | `ProcessEventType.TOOL_INVOKED` not in `_FORWARDED_PROCESS_EVENTS` | `web_server.py:264-270` | Tool calls from ALL sources (user, pulse, reminder, telegram) are silently dropped before reaching WebSocket clients |
| 2 | `EngineEventType.TOOL_INVOKED` is consumed but never produced | `web_server.py:195` handler exists; no emitter anywhere | Phantom handler — dead code |
| 3 | `process_pulse()` and `process_reminder()` skip `STREAM_START` and `SERVER_TOOL_INVOKED` | `chat_engine.py` | No round group created for non-user sources; server-side tools invisible |

---

## Proposed Changes

### Step 1 — Forward `TOOL_INVOKED` from ProcessEventBus to WebSocket clients

**File:** `interface/web_server.py`

- Add `ProcessEventType.TOOL_INVOKED` to `_FORWARDED_PROCESS_EVENTS` (line ~264)
- Add a mapping case in `_process_event_to_ws()` (after line ~294):
  ```
  ProcessEventType.TOOL_INVOKED →
      {"type": "tool_invoked", "tool_name": <parsed>, "detail": <parsed>}
  ```
  The `ProcessEvent.detail` field contains the formatted string from
  `response_helper._build_tool_detail()` (e.g. `"search_memories: query='weather'"`).
  We split on the first `:` to extract `tool_name` and `detail` separately,
  matching the shape `process.js:_onToolInvoked()` already expects.

**Why this is the highest-impact change:** It unblocks tool display for
*every* source (user, pulse, reminder, telegram) in one shot, because
`response_helper.py` emits `ProcessEventType.TOOL_INVOKED` uniformly for
all code paths through `process_with_tools()`.

**Risk:** Low. `process.js` already has `_onToolInvoked()` wired up at
line 516 and renders them with the purple tool dot. No JS changes needed.

---

### Step 2 — Emit `STREAM_START` in `process_pulse()` and `process_reminder()`

**File:** `engine/chat_engine.py`

- In `process_pulse()` (~line 572, before the `self._llm_router.chat()` call):
  add `self._emit(EngineEventType.STREAM_START)`
- In `process_reminder()` (~line 707, before the `self._llm_router.chat()` call):
  add `self._emit(EngineEventType.STREAM_START)`

**Why:** Without `STREAM_START`, the web process panel never creates a
round group for pulses/reminders. Tool nodes still render (Step 1 fixes
that), but the "Thinking..." streaming node and round structure are
missing, making the timeline feel incomplete compared to user messages.

**Risk:** Low. The web server already maps `EngineEventType.STREAM_START` →
`{"type": "stream_start"}` (line 164), and `process.js` already handles it
via `_onStreamStart`. No new JS code needed.

---

### Step 3 — Add missing `STREAM_COMPLETE` in `process_reminder()`

**File:** `engine/chat_engine.py`

- In `process_reminder()`, after the successful LLM call (~line 715, before
  `process_with_tools()`), emit:
  ```python
  self._emit(EngineEventType.STREAM_COMPLETE,
             text=response.text,
             tokens_in=getattr(response, 'tokens_in', 0),
             tokens_out=getattr(response, 'tokens_out', 0),
             stop_reason=getattr(response, 'stop_reason', ''))
  ```
  (`process_pulse()` already emits this at line ~595 — only `process_reminder()`
  is missing it.)

**Why:** Without `STREAM_COMPLETE`, the streaming node created by Step 2
would stay in the "active" amber state forever. This pairs with Step 2
to give reminders a complete lifecycle: `STREAM_START` → `STREAM_COMPLETE`.

**Risk:** Low. Same existing event mapping and handler.

---

### Step 4 — Remove phantom `EngineEventType.TOOL_INVOKED` handler

**File:** `interface/web_server.py`

- Remove the `EngineEventType.TOOL_INVOKED` handler block at lines 195-200.

**Why:** Nothing in the engine emits `EngineEventType.TOOL_INVOKED` — it's
dead code. With Step 1 routing tool calls through the ProcessEventBus
bridge instead, keeping this handler is misleading. Removing it makes the
event flow clear: tool invocations arrive via ProcessEventBus, not engine
events.

**Risk:** None. Dead code removal.

---

## Files Modified (Summary)

| File | Changes | Lines |
|------|---------|-------|
| `interface/web_server.py` | Add TOOL_INVOKED to forwarded set + mapping; remove phantom handler | ~15 |
| `engine/chat_engine.py` | Add STREAM_START to pulse + reminder; add STREAM_COMPLETE to reminder | ~6 |

**Total: 2 files, ~20 lines of changes.**

No changes to `process.js`, `process_panel.py`, `response_helper.py`, or
`gui.py`. The web frontend already has the rendering code ready — it just
isn't receiving the messages.

---

## What This Does NOT Change

- **Desktop GUI (`gui.py`, `process_panel.py`):** Left as-is. The desktop
  panel already receives tool events via its unfiltered ProcessEventBus
  subscription. Since the GUI is being deprecated, no investment here.
- **`response_helper.py`:** The emission source is correct and uniform
  across all code paths. No changes needed.
- **`_process_typed_pulse()` in `gui.py`:** Dead code (unused — actual
  callbacks delegate to `self._engine.process_pulse()`). Not cleaning up
  since GUI is being deprecated.
- **`process.js`:** Already has `_onToolInvoked()` wired up. No changes.

---

## Verification

After the changes, the web process panel should show this structure for a
reminder pulse that uses tools:

```
● Remembered something he promised
  └─ Round 1
       ● Thinking...  →  ● Responded (142 tokens)
       ● Tool: search_memories   query='...'
       ● Tool: read_file         path='...'
  ● Settled
```

This matches the existing structure for user messages.
