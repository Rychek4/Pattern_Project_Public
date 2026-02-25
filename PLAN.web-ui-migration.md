# Plan: Extract Shared ChatEngine from UI Layer

## Problem

The message processing pipeline is duplicated across GUI and CLI, with the GUI
being the "source of truth" and the CLI lagging behind. Both have their own
versions of:

- `_process_message` — user chat (GUI: streaming, CLI: non-streaming)
- `_process_typed_pulse` / `_process_pulse` — system pulse
- `_process_reminder_pulse` / `_process_reminder` — reminder
- `_process_telegram_message` — inbound Telegram
- `_schedule_deferred_retry` / `_process_deferred_retry` — retry on failure

Each copy handles: prompt building, memory injection, LLM calls, tool
execution via `process_with_tools`, conversation storage, dev mode callbacks,
process panel events, and error handling.

A web UI would be a third copy. We need one shared engine instead.

---

## Solution: `engine/chat_engine.py`

A new `ChatEngine` class that owns the full message lifecycle. UI layers
become thin consumers that feed input to the engine and react to events.

### Architecture

```
 ┌─────────────┐   ┌─────────┐   ┌─────────┐
 │  PyQt5 GUI  │   │   CLI   │   │ Web UI  │   (future)
 └──────┬──────┘   └────┬────┘   └────┬────┘
        │               │             │
        └───────┬───────┘─────────────┘
                │
         ┌──────▼──────┐
         │ ChatEngine  │  ← single source of truth
         │             │
         │  Events out ├──→  callbacks (plain Python)
         │  Input in   │
         └──────┬──────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
 prompt_builder  llm_router  process_with_tools
 conversation    temporal     system_pulse
 memory          tools        retry_manager
```

---

## Event System

The engine communicates with UIs through plain Python callbacks — no PyQt
signals, no Rich console. Each UI translates these into its own display
mechanism.

```python
class EngineEventType(Enum):
    """Events emitted by ChatEngine during message processing."""

    # Message lifecycle
    PROCESSING_STARTED = auto()      # {"source": "user"|"pulse"|"reminder"|"telegram"|"retry"}
    PROMPT_ASSEMBLED = auto()        # {"blocks": [...], "token_estimate": int}
    MEMORIES_INJECTED = auto()       # {}
    STREAM_START = auto()            # {}
    STREAM_CHUNK = auto()            # {"text": str}
    STREAM_COMPLETE = auto()         # {"text": str, "tokens_in": int, "tokens_out": int}
    RESPONSE_COMPLETE = auto()       # {"text": str, "provider": str, "source": str}
    PROCESSING_COMPLETE = auto()     # {}
    PROCESSING_ERROR = auto()        # {"error": str}

    # Tools
    TOOL_INVOKED = auto()            # {"tool_name": str, "detail": str}
    SERVER_TOOL_INVOKED = auto()     # {"tool_name": str, "detail": str}

    # Clarification
    CLARIFICATION_REQUESTED = auto() # {"question": str, "options": [...], "context": str}

    # Pulse/reminder
    PULSE_FIRED = auto()             # {"pulse_type": "reflective"|"action"}
    REMINDER_FIRED = auto()          # {"intentions": [...]}
    PULSE_INTERVAL_CHANGED = auto()  # {"pulse_type": str, "interval_seconds": int}

    # Telegram
    TELEGRAM_RECEIVED = auto()       # {"text": str, "from_user": str}

    # Status
    STATUS_UPDATE = auto()           # {"text": str, "type": str}
    NOTIFICATION = auto()            # {"message": str, "level": str}


@dataclass
class EngineEvent:
    event_type: EngineEventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
```

---

## ChatEngine API

```python
class ChatEngine:
    """UI-agnostic message processing engine.

    Owns the full lifecycle: prompt building → LLM call → tool execution →
    response storage. Emits events at every stage for UIs to react to.
    """

    def __init__(self):
        self._conversation_mgr = get_conversation_manager()
        self._llm_router = get_llm_router()
        self._prompt_builder = get_prompt_builder()
        self._temporal_tracker = get_temporal_tracker()
        self._user_settings = get_user_settings()
        self._round_recorder = RoundRecorder()
        self._retry_manager = get_retry_manager()
        self._pulse_manager = None
        self._telegram_listener = None
        self._is_processing = False
        self._cancel_requested = False
        self._is_first_message_of_session = True
        self._listeners = []

    # --- Event registration ---

    def add_listener(self, callback):
        """Register a callback to receive EngineEvents."""

    def remove_listener(self, callback):
        """Unregister a callback."""

    # --- Primary entry points (all synchronous, caller threads them) ---

    def process_message(self, user_input: str, image_data: bytes | None = None):
        """Process a user chat message with streaming."""

    def process_pulse(self, pulse_type: str):
        """Process a system pulse ('reflective' or 'action')."""

    def process_reminder(self, triggered_intentions):
        """Process triggered reminder intentions."""

    def process_telegram(self, message):
        """Process an inbound Telegram message."""

    def process_deferred_retry(self, original_input: str, source: str):
        """Retry a previously failed message."""

    # --- Control ---

    def cancel(self):
        """Request cancellation of current processing."""

    def connect_pulse(self, pulse_manager):
        """Connect the system pulse manager for timer control."""

    def connect_telegram(self, telegram_listener):
        """Connect the Telegram listener for pause/resume."""

    @property
    def is_processing(self) -> bool: ...

    @property
    def is_first_message_of_session(self) -> bool: ...
```

---

## What Moves Where

### Into the engine (extracted from gui.py)

| Current location | Engine method | Lines moved |
|---|---|---|
| `gui.py _process_message` (1715-2013) | `process_message()` | ~300 |
| `gui.py _process_typed_pulse` (2642-2785) | `process_pulse()` | ~140 |
| `gui.py _process_reflective_pulse` + `_process_action_pulse` (2787-2819) | Called via `process_pulse(type)` | ~30 |
| `gui.py _process_reminder_pulse` (2841-2970) | `process_reminder()` | ~130 |
| `gui.py _process_telegram_message` (2177-2359) | `process_telegram()` | ~180 |
| `gui.py _schedule_deferred_retry` + helpers (2361-2580) | `schedule_retry()` + `process_deferred_retry()` | ~220 |
| `gui.py _build_message_with_pasted_image` (1679-1713) | `_build_image_message(bytes)` | ~35 |
| `gui.py _capture_visuals_for_message` | `_build_visual_message()` | ~50 |

**Total moved out of gui.py: ~1,100 lines** (of 3,321)

### Stays in gui.py

- All PyQt widget code (layout, styling, themes, signals)
- `_on_stream_start`, `_on_stream_chunk`, `_on_stream_complete` (display)
- Process panel widget rendering
- Dev window rendering
- Draft persistence, keyboard shortcuts, notifications
- Timer display updates
- The thin adapter: engine event → PyQt signal

### Stays in cli.py

- Rich console formatting and display
- Slash command handling
- The main input loop
- The thin adapter: engine event → Rich output

---

## Image Handling

The GUI currently passes `QImage` objects. The engine accepts raw `bytes`
(JPEG-encoded) instead. The GUI converts `QImage → bytes` before calling
the engine. This keeps PyQt out of the engine entirely.

```python
# In gui.py (before calling engine):
buffer = QBuffer()
buffer.open(QBuffer.ReadWrite)
pasted_image.save(buffer, "JPEG", quality=85)
image_bytes = bytes(buffer.data())

# Engine receives plain bytes:
engine.process_message(user_input, image_data=image_bytes)
```

---

## Streaming

`process_message()` is the only streaming path. It iterates
`llm_router.chat_stream()` and emits `STREAM_CHUNK` events as text arrives.

Each UI handles chunks differently:
- **GUI**: `_on_stream_chunk` slot appends HTML to QTextBrowser
- **CLI**: Prints chunks (or accumulates for final display)
- **Web** (future): Pushes chunks over WebSocket

Non-streaming paths (pulse, reminder, telegram) use `router.chat()` and
emit `RESPONSE_COMPLETE` with the final text.

---

## Dev Mode & Process Panel

The engine emits events at every pipeline stage. These replace the current
direct calls to `dev_window.emit_*` functions and `ProcessEventBus`.

The existing `process_with_tools` helper already accepts a `dev_mode_callbacks`
dict. The engine constructs this dict to emit `EngineEvent`s instead of calling
dev_window directly:

```python
# Inside engine, when calling process_with_tools:
dev_callbacks = None
if config.DEV_MODE_ENABLED:
    dev_callbacks = {
        "emit_response_pass": lambda **kw: self._emit(
            EngineEventType.DEV_RESPONSE_PASS, **kw
        ),
        "emit_command_executed": lambda **kw: self._emit(
            EngineEventType.DEV_COMMAND_EXECUTED, **kw
        ),
    }
```

The GUI's dev window and process panel subscribe to these events and render
them — functionally identical to today, but decoupled.

**Pragmatic note**: The ProcessEventBus (`process_panel.py`) currently uses
PyQt signals. Rather than rewriting it now, the GUI adapter can bridge:
engine event → `get_process_event_bus().emit_event(...)`. This keeps the
process panel working unchanged.

---

## Pulse/Reminder/Telegram Integration

**Today:** GUI registers callbacks with pulse_manager → callback fires on
background thread → GUI spawns another thread → GUI method runs the full
pipeline.

**After:** GUI registers callbacks with pulse_manager → callback fires →
GUI calls `engine.process_pulse("reflective")` in a thread. The engine
handles the full pipeline and emits events. The engine pauses/resumes the
pulse_manager itself (via `connect_pulse()`).

Same pattern for reminders and Telegram. The engine manages the
pause/resume lifecycle internally:

```python
def process_pulse(self, pulse_type: str):
    try:
        self._is_processing = True
        if self._pulse_manager:
            self._pulse_manager.pause()
        if self._telegram_listener:
            self._telegram_listener.pause()

        # ... full pipeline ...

    finally:
        if self._pulse_manager:
            self._pulse_manager.mark_pulse_complete()
            self._pulse_manager.resume()
        if self._telegram_listener:
            self._telegram_listener.resume()
        self._is_processing = False
```

---

## File Changes

### New files

| File | Lines (est.) | Purpose |
|---|---|---|
| `engine/__init__.py` | ~10 | Package init, exports `ChatEngine` |
| `engine/events.py` | ~70 | `EngineEventType` enum + `EngineEvent` dataclass |
| `engine/chat_engine.py` | ~500 | The engine (extracted + unified pipeline) |

### Modified files

| File | Change | Net effect |
|---|---|---|
| `interface/gui.py` | Remove pipeline methods, add engine adapter | -1,100 lines, +150 lines (adapter) |
| `interface/cli.py` | Remove pipeline methods, add engine adapter | -500 lines, +80 lines (adapter) |
| `main.py` | Create engine, pass to GUI/CLI | +10 lines |

### Unchanged

- `agency/tools/response_helper.py` — already shared
- `prompt_builder/` — already clean
- `memory/`, `core/`, `llm/` — no changes
- `interface/gui_components.py` — pure widgets
- `interface/dev_window.py` — no changes (fed via engine events bridged through GUI)
- `interface/process_panel.py` — no changes (fed via ProcessEventBus bridge)
- `interface/http_api.py` — no changes (it has its own simpler chat path)

---

## Implementation Order

1. **`engine/events.py`** — Event types and dataclass
2. **`engine/chat_engine.py`** — Extract pipeline from gui.py, emit events
3. **`engine/__init__.py`** — Exports
4. **`main.py`** — Instantiate engine, pass to interfaces
5. **`interface/gui.py`** — Replace pipeline with engine calls + event adapter
6. **`interface/cli.py`** — Replace pipeline with engine calls + event adapter
7. **Delete dead code** — Deprecated `_process_native_tools_response` in both
   gui.py and cli.py (already marked deprecated December 2025)
8. **Test** — All paths: chat, streaming, pulse (both types), reminder,
   telegram, deferred retry, cancellation, dev mode

---

## Risk Assessment

**Low risk** — this is a mechanical refactor, not a rewrite:

- `process_with_tools` already exists and works correctly across all paths
- The pipeline steps are well-understood and identical in GUI/CLI
- No business logic changes — same prompts, same LLM calls, same tools
- GUI signals stay intact (sourced from engine events instead of inline code)
- The diff is straightforward to debug if something breaks

**Key constraint**: Thread safety for `_is_processing` and `_cancel_requested`.
The GUI already handles this correctly — we're just moving the flags to the
engine. A threading.Lock protects the state transitions.

---

## What This Enables (Future)

Once the engine exists, building a web UI becomes:

1. Add WebSocket endpoints to Flask/FastAPI
2. Create a web frontend that sends messages via HTTP/WebSocket
3. Bridge engine events → WebSocket pushes
4. The engine does all the work — the web layer is just transport + display

No third copy of the pipeline. Ever.
