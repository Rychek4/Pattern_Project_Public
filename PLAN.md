# Plan: Migrate Dev Tools to Web UI

## Context

The PyQt5 GUI is permanently deprecated. The dev tools (debug window showing
internal AI operations) currently only work via the PyQt5 `DevWindow` class.
This plan wires those same dev tools into the existing web UI as standalone
pages served on separate routes — one route per tool — so each opens in its
own browser tab.

## Architecture Overview

```
Current:
  engine/agency code  →  emit_*() functions  →  PyQt5 DevWindow (signals)

Target:
  engine/agency code  →  emit_*() functions  →  DevEventBus (callbacks)
                                                   ↓
                                              WebServer subscribes
                                                   ↓
                                              WebSocket /ws/dev
                                                   ↓
                                          Browser pages (7 routes)
```

The key insight: the `emit_*()` functions in `dev_window.py` are already called
from the right places in the engine and agency layers. We just need to decouple
them from PyQt5 and route them through WebSocket instead.

---

## Step 1: Create DevEventBus (backend event infrastructure)

**File**: `interface/dev_events.py` (new)

Create a lightweight, PyQt5-free event bus for dev data. This replaces the
`DevWindowSignals` (pyqtSignal) system with plain callbacks:

- Move the 7 dataclass definitions (`PromptAssemblyData`, `CommandExecutionData`,
  `ResponsePassData`, `MemoryRecallData`, `ActiveThoughtsData`, `CuriosityData`,
  `IntentionData`, and `WebSearchCitationData`) out of `dev_window.py` into
  this new file.
- Define a `DevEventBus` class with:
  - `add_callback(event_type: str, callback)` — register a listener
  - `emit(event_type: str, data)` — notify all listeners for that type
  - Event types: `"prompt_assembly"`, `"command_executed"`, `"response_pass"`,
    `"memory_recall"`, `"active_thoughts"`, `"curiosity"`, `"intentions"`
- Define module-level `get_dev_event_bus()` singleton.
- Rewrite the 7 `emit_*()` functions to dispatch through `DevEventBus`
  instead of checking for `_dev_window`. Keep the same function signatures so
  callers don't change. The guard changes from
  `if _dev_window and config.DEV_MODE_ENABLED` to
  `if config.DEV_MODE_ENABLED`.
- Rewrite the 3 `load_initial_*()` functions similarly (they load initial
  state for active_thoughts, curiosity, and intentions on startup).

**Why a new file instead of editing dev_window.py**: `dev_window.py` imports
PyQt5 at module level. Any file that imports from it (and there are 8 callers
across engine/agency) would fail without PyQt5 installed. A clean new file
with zero PyQt5 dependency is the right call.

## Step 2: Update all callers to import from dev_events

**Files to change** (8 files, mechanical import path changes):

| File | Current import | New import |
|------|---------------|------------|
| `interface/gui.py` (×4 sites) | `from interface.dev_window import emit_prompt_assembly` | `from interface.dev_events import emit_prompt_assembly` |
| `interface/gui.py` (×4 sites) | `from interface.dev_window import emit_response_pass, emit_command_executed` | `from interface.dev_events import emit_response_pass, emit_command_executed` |
| `prompt_builder/sources/semantic_memory.py` | `from interface.dev_window import emit_memory_recall` | `from interface.dev_events import emit_memory_recall` |
| `agency/commands/handlers/active_thoughts_handler.py` | `from interface.dev_window import emit_active_thoughts_update` | `from interface.dev_events import emit_active_thoughts_update` |
| `agency/curiosity/engine.py` | `from interface.dev_window import emit_curiosity_update, get_dev_window` | `from interface.dev_events import emit_curiosity_update` |
| `agency/curiosity/source.py` | `from interface.dev_window import emit_curiosity_update` | `from interface.dev_events import emit_curiosity_update` |
| `agency/intentions/manager.py` | `from interface.dev_window import emit_intentions_update` | `from interface.dev_events import emit_intentions_update` |
| `agency/tools/executor.py` | `from interface.dev_window import emit_curiosity_update` | `from interface.dev_events import emit_curiosity_update` |

**Critical**: The `emit_prompt_assembly` and `emit_response_pass` /
`emit_command_executed` calls currently live inside `gui.py`'s engine event
handler — meaning they ONLY fire in GUI mode. These need to be relocated so
they fire in all modes:

- `emit_prompt_assembly`: The engine already emits `PROMPT_ASSEMBLED` with
  `blocks` and `token_estimate` data (gui.py line 917-921 reads these from
  `data`). Move this call into `web_server.py`'s `_on_engine_event` handler
  for the `PROMPT_ASSEMBLED` event type (and keep it in gui.py for backward
  compat).
- `emit_response_pass` / `emit_command_executed`: These are passed as
  `dev_callbacks` into `process_with_tools()` (gui.py line 2117-2134). The
  web server's message processing path needs to pass the same callbacks.
  Add `dev_callbacks` to the web server's `_handle_chat` flow.

## Step 3: Add dev WebSocket endpoint and wire DevEventBus into WebServer

**File**: `interface/web_server.py`

### WebSocket endpoint

Add a `/ws/dev` WebSocket endpoint dedicated to dev events. This keeps the
main `/ws` lean (no debug traffic on the chat page). Use a separate
`DevConnectionManager` instance.

### Wiring

In `WebServer.set_backend()`, if `config.DEV_MODE_ENABLED`:

- Import `get_dev_event_bus` from `interface.dev_events`
- Register 7 callbacks on the DevEventBus, one per event type
- Each callback serializes its dataclass to a JSON dict and broadcasts via
  the `DevConnectionManager`
- Message format: `{"type": "dev_prompt_assembly", ...fields}`,
  `{"type": "dev_command_executed", ...fields}`, etc.

### Serialization

Each dataclass needs a `to_dict()` method or a simple serialization function.
The data is already mostly plain dicts/lists/strings inside the dataclasses,
so this is straightforward. Handle `WebSearchCitationData` objects inside
`ResponsePassData.citations` by converting them to dicts too.

## Step 4: Add dev page routes to FastAPI

**File**: `interface/web_server.py`

Add 8 GET routes serving standalone HTML pages:

```
/dev             → Index page with links to all 7 tools
/dev/prompt      → Prompt Assembly viewer
/dev/tools       → Tool Execution viewer
/dev/pipeline    → Response Pipeline viewer
/dev/memory      → Memory Recall viewer
/dev/thoughts    → Active Thoughts viewer
/dev/curiosity   → Curiosity Engine viewer
/dev/intentions  → Intentions/Reminders viewer
```

Each route serves an HTML file from `interface/web/dev/`. Mount
`interface/web/dev/` as a second static files directory at `/static/dev`.

Guard these routes behind `config.DEV_MODE_ENABLED` — return 404 if dev mode
is off.

## Step 5: Create the frontend pages

**Directory**: `interface/web/dev/` (new)

### Shared infrastructure (2 files)

**`dev-common.js`** — Shared JavaScript module:
- WebSocket connection to `/ws/dev` with auto-reconnect (same pattern as
  `connection.js` but connecting to the dev endpoint)
- Event subscription: `DevConnection.on(type, callback)`
- Shared color constants matching existing dark theme
- Timestamp formatting helpers
- Auto-scroll management

**`dev-common.css`** — Shared styles:
- Dark theme matching existing web UI (`#1a1a2e` background family)
- Card/panel layouts for data display
- Color-coded badges for priorities, scores, statuses
- Collapsible sections with toggle
- Scrollable containers with auto-scroll toggle
- Responsive layout basics

### Per-tool pages (7 HTML files)

Each page is self-contained: includes `dev-common.css`, `dev-common.js`,
and its own inline `<script>` block. Each connects to `/ws/dev`, subscribes
to its specific event type, and renders incoming data into the DOM.

#### 1. `prompt.html` — Prompt Assembly
- Subscribes to `dev_prompt_assembly`
- Renders: header with total token estimate, list of context block cards
- Each card shows: source name (color badge), priority, token estimate,
  collapsible content preview (first 200 chars)
- Replaces on each update (shows latest assembly only)
- Color-code by source name (same COLORS dict from dev_window.py)

#### 2. `tools.html` — Tool Execution
- Subscribes to `dev_command_executed`
- Renders: appending log of tool executions
- Each entry: tool name header, query text, collapsible JSON result in `<pre>`,
  error indicator (red), continuation flag
- Auto-scroll with toggle button

#### 3. `pipeline.html` — Response Pipeline
- Subscribes to `dev_response_pass`
- Renders: appending list of response pass cards
- Each card: pass number badge, provider name, tokens in/out, duration (ms),
  commands detected (pill badges), web search count, citation list
  (title as link, excerpt)
- Summary stats accumulated across passes

#### 4. `memory.html` — Memory Recall
- Subscribes to `dev_memory_recall`
- Renders: query text header, result cards
- Each card: content preview, score bars or numbers for semantic/importance/
  freshness, warmth boost breakdown (retrieval vs topic warmth), adjusted
  score with color gradient
- Shows warmth cache stats if present in the data

#### 5. `thoughts.html` — Active Thoughts
- Subscribes to `dev_active_thoughts`
- Renders: ranked list of thought cards
- Each card: rank badge (color-coded: 1-3 green, 4-6 amber, 7+ dim),
  slug, topic, elaboration preview
- Replaces on each update (always shows current state)
- Count in header

#### 6. `curiosity.html` — Curiosity Engine
- Subscribes to `dev_curiosity`
- Renders: current goal section (id, content, category, context, activated_at),
  history section (last 5 goals with status badges and timestamps),
  cooldowns section
- Event type indicator badge
- Replaces on each update

#### 7. `intentions.html` — Intentions/Reminders
- Subscribes to `dev_intentions`
- Renders: status groups (triggered → pending → completed → dismissed)
- Each intention card: id, type badge, content, context, trigger info,
  timestamps, priority level
- Status count summary bar in header
- Replaces on each update

### Index page

**`index.html`** (in `interface/web/dev/`):
- Grid of 7 cards, one per tool, each linking to its page
- Each card: tool name, brief description, opens in new tab (`target="_blank"`)
- Same dark theme styling

## Step 6: Enable dev mode for web in main.py

**File**: `main.py`

In `run_web_mode()`, after `web_server.set_backend(...)`:

- If `config.DEV_MODE_ENABLED`, call the initial-load functions from
  `dev_events.py`: `load_initial_active_thoughts()`,
  `load_initial_curiosity()`, `load_initial_intentions()` — so dev pages
  connecting later get populated with current state.
- The `--dev` flag already sets `config.DEV_MODE_ENABLED = True` (line 449-450),
  so no argparse changes needed.
- Update the `--dev` help text to mention web mode support.

### Web server message processing path

Currently `web_server.py`'s `_handle_chat` dispatches to
`self._engine.process_message()` which does NOT pass dev callbacks. The GUI's
`_process_message_sync` does. Fix this by:

- Having the web server's engine event listener (`_on_engine_event`) forward
  `PROMPT_ASSEMBLED` data to `emit_prompt_assembly()` (same as gui.py does).
- Passing `dev_callbacks` when the engine calls `process_with_tools()`. This
  likely means the engine itself should accept dev callbacks (or always call
  emit functions when dev mode is on), rather than requiring each UI to
  inject them. Check `engine/chat_engine.py` → `process_message()` to see
  if dev callbacks can be wired at the engine level rather than the UI level.

## Step 7: Cleanup and backward compatibility

- **Do NOT delete `dev_window.py`** — it still works for anyone running the
  PyQt5 GUI locally. The web path bypasses it entirely via `dev_events.py`.
- Optionally update `dev_window.py` to subscribe to the `DevEventBus` so it
  doesn't duplicate logic — the PyQt5 signals can be driven by DevEventBus
  callbacks instead of direct `_dev_window.signals.*.emit()` calls.
- Remove the `get_dev_window` import from `agency/curiosity/engine.py` (it
  was checking `if get_dev_window()` which is no longer needed since
  `emit_curiosity_update` handles the guard internally).

---

## What does NOT change

- **The main chat web UI** (`/`, `/ws`) — unchanged, no dev traffic added
- **CLI mode** — unchanged (but could benefit from dev events later)
- **ProcessEventBus** — unchanged, continues handling delegation/curiosity/
  memory extraction events for the process panel sidebar
- **Engine core** — minimal changes (just ensuring dev data is emitted in
  all modes, not just GUI mode)

## File Change Summary

| File | Action | Size |
|------|--------|------|
| `interface/dev_events.py` | **Create** | ~200 lines |
| `interface/web_server.py` | **Edit** | ~100 lines added |
| `main.py` | **Edit** | ~10 lines |
| `interface/gui.py` | **Edit** | Import path changes (8 spots) |
| `prompt_builder/sources/semantic_memory.py` | **Edit** | 1 import change |
| `agency/commands/handlers/active_thoughts_handler.py` | **Edit** | 1 import change |
| `agency/curiosity/engine.py` | **Edit** | 1 import change |
| `agency/curiosity/source.py` | **Edit** | 1 import change |
| `agency/intentions/manager.py` | **Edit** | 1 import change |
| `agency/tools/executor.py` | **Edit** | 1 import change |
| `interface/web/dev/dev-common.js` | **Create** | ~100 lines |
| `interface/web/dev/dev-common.css` | **Create** | ~150 lines |
| `interface/web/dev/index.html` | **Create** | ~80 lines |
| `interface/web/dev/prompt.html` | **Create** | ~120 lines |
| `interface/web/dev/tools.html` | **Create** | ~120 lines |
| `interface/web/dev/pipeline.html` | **Create** | ~150 lines |
| `interface/web/dev/memory.html` | **Create** | ~150 lines |
| `interface/web/dev/thoughts.html` | **Create** | ~100 lines |
| `interface/web/dev/curiosity.html` | **Create** | ~130 lines |
| `interface/web/dev/intentions.html` | **Create** | ~140 lines |

## Implementation Order

```
Step 1 (dev_events.py)      ─── Foundation — must be first
Step 2 (update imports)     ─── Depends on Step 1
Step 3 (WebSocket + wiring) ─┐
Step 4 (FastAPI routes)     ─┤  Depend on Steps 1-2, can be done together
Step 5 (frontend pages)     ─┘
Step 6 (main.py wiring)    ─── After Steps 3-4
Step 7 (cleanup)            ─── Last, optional
```

Steps 3, 4, and 5 can be parallelized since they're independent files.
The frontend pages (Step 5) are the most code but each page is mechanical —
receive JSON, render HTML — with no complex state management.
