"""
Pattern Project - Web Server

FastAPI + WebSocket server for the browser-based interface.
Bridges ChatEngine events to connected browser clients over WebSocket.

Usage:
    Called from main.py via run_web() -- not invoked directly.
"""

import asyncio
import json
import secrets
import threading
import time
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import config
from core.logger import log_info, log_error, log_warning
from engine.events import EngineEvent, EngineEventType
from interface.process_panel import (
    ProcessEvent, ProcessEventType, get_process_event_bus
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WEB_DIR = Path(__file__).parent / "web"
DEV_DIR = WEB_DIR / "dev"
AUTH_COOKIE_NAME = "pattern_session"
AUTH_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------
_active_sessions: Dict[str, float] = {}  # token -> expiry timestamp


def _get_auth_password() -> str:
    """Return the configured auth password (empty = auth disabled)."""
    return getattr(config, "WEB_AUTH_PASSWORD", "") or ""


def _create_session_token() -> str:
    token = secrets.token_urlsafe(32)
    _active_sessions[token] = time.time() + AUTH_COOKIE_MAX_AGE
    return token


_last_session_cleanup = 0.0  # timestamp of last cleanup run


def _validate_session(token: str) -> bool:
    global _last_session_cleanup
    if not token:
        return False

    # Periodically purge expired tokens (at most once per hour)
    now = time.time()
    if now - _last_session_cleanup > 3600:
        _cleanup_expired_sessions()
        _last_session_cleanup = now

    expiry = _active_sessions.get(token)
    if expiry is None:
        return False
    if now > expiry:
        _active_sessions.pop(token, None)
        return False
    return True


def _auth_required() -> bool:
    """Return True if authentication is configured."""
    return bool(_get_auth_password())


def _cleanup_expired_sessions():
    """Remove expired session tokens to prevent unbounded dict growth."""
    now = time.time()
    expired = [t for t, exp in _active_sessions.items() if now > exp]
    for t in expired:
        _active_sessions.pop(t, None)


# ---------------------------------------------------------------------------
# Auth Middleware
# ---------------------------------------------------------------------------
class AuthMiddleware(BaseHTTPMiddleware):
    """Protect all routes except /auth/* and static assets when auth is enabled."""

    async def dispatch(self, request: Request, call_next):
        if not _auth_required():
            return await call_next(request)

        path = request.url.path

        # Allow auth endpoints, health check, and static files through
        if path.startswith("/auth") or path.startswith("/static") or path == "/health":
            return await call_next(request)

        # Check session cookie
        token = request.cookies.get(AUTH_COOKIE_NAME, "")
        if _validate_session(token):
            return await call_next(request)

        # Not authenticated -- redirect to login for page requests, 401 for API
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            from starlette.responses import RedirectResponse
            return RedirectResponse(url="/auth/login", status_code=303)
        return JSONResponse({"error": "unauthorized"}, status_code=401)


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------
class ConnectionManager:
    """Manages active WebSocket connections and broadcasts engine events."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def accept(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        log_info(f"WebSocket connected ({len(self._connections)} total)", prefix="🌐")

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)
        log_info(f"WebSocket disconnected ({len(self._connections)} total)", prefix="🌐")

    async def _send_json(self, ws: WebSocket, data: dict):
        try:
            await ws.send_json(data)
        except Exception as exc:
            self._connections.discard(ws)
            log_info(f"WebSocket send failed, client removed: {exc.__class__.__name__}", prefix="🌐")

    async def broadcast(self, data: dict):
        """Send a message to all connected clients."""
        if not self._connections:
            return
        tasks = [self._send_json(ws, data) for ws in list(self._connections)]
        await asyncio.gather(*tasks, return_exceptions=True)

    def broadcast_sync(self, data: dict):
        """Thread-safe broadcast from synchronous code (engine callbacks)."""
        if self._loop is None or not self._connections:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(data), self._loop)


# ---------------------------------------------------------------------------
# Engine event → WebSocket message mapper
# ---------------------------------------------------------------------------
def _engine_event_to_ws(event: EngineEvent) -> Optional[dict]:
    """Convert an EngineEvent into a JSON-serialisable dict for WebSocket."""
    etype = event.event_type
    data = event.data

    if etype == EngineEventType.PROCESSING_STARTED:
        return {"type": "processing_started", "source": data.get("source", "user")}

    elif etype == EngineEventType.PROMPT_ASSEMBLED:
        return {"type": "prompt_assembled"}

    elif etype == EngineEventType.MEMORIES_INJECTED:
        return {"type": "memories_injected"}

    elif etype == EngineEventType.STREAM_START:
        return {"type": "stream_start", "timestamp": datetime.now().isoformat()}

    elif etype == EngineEventType.STREAM_CHUNK:
        return {"type": "stream_chunk", "text": data.get("text", "")}

    elif etype == EngineEventType.STREAM_COMPLETE:
        return {
            "type": "stream_complete",
            "text": data.get("text", ""),
            "tokens_in": data.get("tokens_in", 0),
            "tokens_out": data.get("tokens_out", 0),
        }

    elif etype == EngineEventType.RESPONSE_COMPLETE:
        return {
            "type": "response_complete",
            "text": data.get("text", ""),
            "source": data.get("source", "user"),
        }

    elif etype == EngineEventType.PROCESSING_COMPLETE:
        return {"type": "processing_complete"}

    elif etype == EngineEventType.PROCESSING_ERROR:
        return {
            "type": "processing_error",
            "error": data.get("error", "Unknown error"),
            "error_type": data.get("error_type"),
        }

    elif etype == EngineEventType.SERVER_TOOL_INVOKED:
        return {
            "type": "tool_invoked",
            "tool_name": data.get("tool_name", ""),
            "detail": data.get("detail", ""),
        }

    elif etype == EngineEventType.CLARIFICATION_REQUESTED:
        return {
            "type": "clarification",
            "data": data.get("data", {}),
        }

    elif etype == EngineEventType.PULSE_FIRED:
        return {
            "type": "pulse_fired",
            "pulse_type": data.get("pulse_type", "action"),
        }

    elif etype == EngineEventType.REMINDER_FIRED:
        return {"type": "reminder_fired"}

    elif etype == EngineEventType.PULSE_INTERVAL_CHANGED:
        return {
            "type": "pulse_interval_changed",
            "pulse_type": data.get("pulse_type", ""),
            "interval_seconds": data.get("interval_seconds", 0),
        }

    elif etype == EngineEventType.STATUS_UPDATE:
        return {
            "type": "status_update",
            "text": data.get("text", ""),
            "status_type": data.get("type", "ready"),
        }

    elif etype == EngineEventType.NOTIFICATION:
        return {
            "type": "notification",
            "message": data.get("message", ""),
            "level": data.get("level", "info"),
        }

    elif etype == EngineEventType.TELEGRAM_RECEIVED:
        return {
            "type": "telegram_received",
            "text": data.get("text", ""),
            "from_user": data.get("from_user", ""),
        }

    elif etype == EngineEventType.RETRY_SCHEDULED:
        return {"type": "retry_scheduled", "source": data.get("source", "")}

    elif etype == EngineEventType.RETRY_FAILED:
        return {"type": "retry_failed", "source": data.get("source", "")}

    return None  # Unknown event -- skip


# ---------------------------------------------------------------------------
# ProcessEventBus → WebSocket message mapper
# ---------------------------------------------------------------------------
_FORWARDED_PROCESS_EVENTS = frozenset({
    ProcessEventType.DELEGATION_START,
    ProcessEventType.DELEGATION_TOOL,
    ProcessEventType.DELEGATION_COMPLETE,
    ProcessEventType.CURIOSITY_SELECTED,
    ProcessEventType.MEMORY_EXTRACTION,
    ProcessEventType.TOOL_INVOKED,
})


def _process_event_to_ws(event: ProcessEvent) -> Optional[dict]:
    """Convert a ProcessEvent into a JSON-serialisable dict for WebSocket."""
    etype = event.event_type

    if etype == ProcessEventType.DELEGATION_START:
        return {"type": "delegation_start", "detail": event.detail}

    elif etype == ProcessEventType.DELEGATION_TOOL:
        return {"type": "delegation_tool", "detail": event.detail}

    elif etype == ProcessEventType.DELEGATION_COMPLETE:
        return {"type": "delegation_complete", "detail": event.detail}

    elif etype == ProcessEventType.CURIOSITY_SELECTED:
        return {
            "type": "curiosity_selected",
            "detail": event.detail,
            "origin": event.origin,
        }

    elif etype == ProcessEventType.MEMORY_EXTRACTION:
        return {"type": "memory_extraction", "detail": event.detail}

    elif etype == ProcessEventType.TOOL_INVOKED:
        detail = event.detail or ""
        # _build_tool_detail() formats as "tool_name: description"
        tool_name = detail.split(":")[0].strip() if ":" in detail else detail
        return {
            "type": "tool_invoked",
            "tool_name": tool_name,
            "detail": detail,
        }

    return None


# ---------------------------------------------------------------------------
# Web Server
# ---------------------------------------------------------------------------
class WebServer:
    """
    FastAPI application serving the web UI and WebSocket endpoint.

    Main web interface server:
    - Listens to engine events and forwards them to clients
    - Accepts user input via WebSocket and dispatches to engine
    - Manages pulse/reminder/telegram callbacks
    """

    def __init__(self):
        self._engine = None
        self._pulse_manager = None
        self._telegram_listener = None
        self._reminder_scheduler = None
        self._temporal_tracker = None
        self._is_processing = False
        self._processing_lock = threading.Lock()

        self.manager = ConnectionManager()
        self.dev_manager = ConnectionManager()  # Separate WS pool for /ws/dev
        self.app = self._create_app()

    # -----------------------------------------------------------------------
    # Broadcast helpers (delegate to ConnectionManager)
    # -----------------------------------------------------------------------
    async def broadcast(self, data: dict):
        """Broadcast to all clients from async context."""
        await self.manager.broadcast(data)

    def broadcast_sync(self, data: dict):
        """Thread-safe broadcast from synchronous/threaded code."""
        self.manager.broadcast_sync(data)

    def set_backend(
        self,
        engine,
        pulse_manager=None,
        telegram_listener=None,
        reminder_scheduler=None,
        temporal_tracker=None,
    ):
        """Wire up backend components (mirrors ChatWindow.set_backend)."""
        self._engine = engine
        self._pulse_manager = pulse_manager
        self._telegram_listener = telegram_listener
        self._reminder_scheduler = reminder_scheduler
        self._temporal_tracker = temporal_tracker

        # Register as engine event listener
        if self._engine:
            self._engine.add_listener(self._on_engine_event)

        # Subscribe to ProcessEventBus for delegation/curiosity/memory events
        get_process_event_bus().add_callback(self._on_process_event)

        # Set up pulse callbacks
        if self._pulse_manager:
            self._pulse_manager.set_reflective_callback(self._on_reflective_pulse_fired)
            self._pulse_manager.set_action_callback(self._on_action_pulse_fired)

        # Set up Telegram listener callback
        if self._telegram_listener:
            self._telegram_listener.set_callback(self._on_telegram_message)

        # Set up reminder scheduler callback
        if self._reminder_scheduler:
            self._reminder_scheduler.set_callback(self._on_reminder_fired)

        # Start session if not active
        if self._temporal_tracker and not self._temporal_tracker.is_session_active:
            self._temporal_tracker.start_session()

        # Check for overdue reminders that may have been missed while offline
        if self._reminder_scheduler and self._engine:
            self._check_overdue_reminders()

        # Subscribe to DevEventBus for dev tool pages
        if config.DEV_MODE_ENABLED:
            self._wire_dev_event_bus()

    # -----------------------------------------------------------------------
    # DevEventBus → /ws/dev bridge
    # -----------------------------------------------------------------------
    def _wire_dev_event_bus(self):
        """Subscribe to DevEventBus and forward events to /ws/dev clients."""
        from interface.dev_events import get_dev_event_bus, _serialize

        bus = get_dev_event_bus()
        event_types = [
            "prompt_assembly", "command_executed", "response_pass",
            "memory_recall", "active_thoughts", "curiosity", "intentions",
        ]
        for etype in event_types:
            bus.add_callback(etype, self._make_dev_forwarder(etype))

    def _make_dev_forwarder(self, event_type: str):
        """Return a callback that serializes a dev dataclass and broadcasts."""
        from interface.dev_events import _serialize

        def _forward(data):
            msg = _serialize(data)
            msg["type"] = f"dev_{event_type}"
            self.dev_manager.broadcast_sync(msg)

        return _forward

    async def _send_initial_dev_state(self, ws: WebSocket):
        """Send current thoughts/curiosity/intentions state to a newly-connected dev client."""
        from interface.dev_events import (
            get_initial_active_thoughts_data,
            get_initial_curiosity_data,
            get_initial_intentions_data,
            _serialize,
        )

        for event_type, getter in [
            ("active_thoughts", get_initial_active_thoughts_data),
            ("curiosity", get_initial_curiosity_data),
            ("intentions", get_initial_intentions_data),
        ]:
            data = getter()
            if data is not None:
                msg = _serialize(data)
                msg["type"] = f"dev_{event_type}"
                await ws.send_json(msg)

    def _forward_dev_engine_event(self, event: EngineEvent):
        """Forward dev-relevant engine events to the DevEventBus emit functions."""
        from interface.dev_events import emit_prompt_assembly, emit_response_pass, emit_command_executed

        etype = event.event_type
        data = event.data

        if etype == EngineEventType.PROMPT_ASSEMBLED:
            blocks = data.get("blocks", [])
            token_estimate = data.get("token_estimate", 0)
            emit_prompt_assembly(blocks, token_estimate)

        elif etype == EngineEventType.DEV_RESPONSE_PASS:
            emit_response_pass(**data)

        elif etype == EngineEventType.DEV_COMMAND_EXECUTED:
            emit_command_executed(**data)

    # -----------------------------------------------------------------------
    # ProcessEventBus callback (delegation / curiosity / memory extraction)
    # -----------------------------------------------------------------------
    def _on_process_event(self, event: ProcessEvent):
        """Forward relevant ProcessEventBus events to WebSocket clients."""
        if event.event_type not in _FORWARDED_PROCESS_EVENTS:
            return
        msg = _process_event_to_ws(event)
        if msg:
            self.broadcast_sync(msg)

    # -----------------------------------------------------------------------
    # Engine event listener (called from background threads)
    # -----------------------------------------------------------------------
    def _on_engine_event(self, event: EngineEvent):
        """Bridge engine events to WebSocket broadcasts."""
        msg = _engine_event_to_ws(event)
        if msg:
            self.broadcast_sync(msg)

        # Forward dev-relevant engine events to DevEventBus
        if config.DEV_MODE_ENABLED:
            self._forward_dev_engine_event(event)

        # Track processing state
        if event.event_type == EngineEventType.PROCESSING_COMPLETE:
            with self._processing_lock:
                self._is_processing = False
            # Resume pulse timers and telegram
            if self._pulse_manager:
                self._pulse_manager.resume()
            if self._telegram_listener:
                self._telegram_listener.resume()

    # -----------------------------------------------------------------------
    # Engine task wrapper (safety net for _is_processing flag)
    # -----------------------------------------------------------------------
    def _run_engine_task(self, fn, *args):
        """Run an engine function with a safety net that resets _is_processing
        if the function raises before emitting PROCESSING_COMPLETE."""
        try:
            fn(*args)
        except Exception as e:
            log_error(f"Engine task failed: {e}")
            with self._processing_lock:
                self._is_processing = False
            self.broadcast_sync({
                "type": "processing_error",
                "error": str(e),
            })

    # -----------------------------------------------------------------------
    # Pulse callbacks (called from PulseManager background thread)
    # -----------------------------------------------------------------------
    def _on_reflective_pulse_fired(self):
        with self._processing_lock:
            if self._is_processing or (self._engine and self._engine.is_processing):
                if self._pulse_manager:
                    self._pulse_manager.mark_pulse_complete()
                return
            self._is_processing = True

        thread = threading.Thread(
            target=self._run_engine_task,
            args=(self._engine.process_pulse, "reflective"),
            daemon=True,
        )
        thread.start()

    def _on_action_pulse_fired(self):
        with self._processing_lock:
            if self._is_processing or (self._engine and self._engine.is_processing):
                if self._pulse_manager:
                    self._pulse_manager.mark_pulse_complete()
                return
            self._is_processing = True

        thread = threading.Thread(
            target=self._run_engine_task,
            args=(self._engine.process_pulse, "action"),
            daemon=True,
        )
        thread.start()

    # -----------------------------------------------------------------------
    # Telegram callback (called from TelegramListener background thread)
    # -----------------------------------------------------------------------
    def _on_telegram_message(self, message):
        log_info(f"Telegram message received: {message.text[:50]}...", prefix="📱")

        if self._engine and self._engine.retry_manager.has_pending():
            self._engine.retry_manager.cancel()

        with self._processing_lock:
            if self._is_processing or (self._engine and self._engine.is_processing):
                log_warning("Skipping Telegram message - already processing")
                return
            self._is_processing = True

        thread = threading.Thread(
            target=self._run_engine_task,
            args=(self._engine.process_telegram, message),
            daemon=True,
        )
        thread.start()

    # -----------------------------------------------------------------------
    # Boot-time overdue reminder check
    # -----------------------------------------------------------------------
    def _check_overdue_reminders(self):
        """Fire reminders that became due while the app was offline.

        The scheduler thread may have already flipped overdue intentions from
        PENDING → TRIGGERED before the callback was wired.  This one-time
        boot check picks up those (and any still-PENDING) so the AI can
        address them immediately.
        """
        try:
            from agency.intentions.trigger_engine import get_trigger_engine

            engine = get_trigger_engine()
            # Trigger any PENDING reminders that are past due
            engine.check_and_trigger(datetime.now(), is_session_start=False)

            # Collect all TRIGGERED reminders (includes ones just triggered
            # above AND ones the scheduler already flipped before callback existed)
            from agency.intentions.manager import get_intention_manager
            overdue = get_intention_manager().get_triggered_intentions()

            if overdue:
                log_info(
                    f"Boot check: {len(overdue)} overdue reminder(s) found",
                    prefix="⏰",
                )
                self._on_reminder_fired(overdue)
        except Exception as e:
            log_error(f"Boot overdue-reminder check failed: {e}")

    # -----------------------------------------------------------------------
    # Reminder callback (called from ReminderScheduler background thread)
    # -----------------------------------------------------------------------
    def _on_reminder_fired(self, triggered_intentions):
        with self._processing_lock:
            if self._is_processing or (self._engine and self._engine.is_processing):
                return
            self._is_processing = True

        thread = threading.Thread(
            target=self._run_engine_task,
            args=(self._engine.process_reminder, triggered_intentions),
            daemon=True,
        )
        thread.start()

    # -----------------------------------------------------------------------
    # WebSocket message handler
    # -----------------------------------------------------------------------
    async def _handle_ws_message(self, ws: WebSocket, raw: str):
        """Dispatch an incoming WebSocket message from the client."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send_json({"type": "error", "error": "Invalid JSON"})
            return

        msg_type = msg.get("type", "")

        if msg_type == "chat":
            await self._handle_chat(ws, msg)
        elif msg_type == "cancel":
            if self._engine:
                self._engine.cancel()
        elif msg_type == "set_pulse_interval":
            await self._handle_set_pulse_interval(msg)
        elif msg_type == "pulse_now":
            self._handle_pulse_now(msg)
        elif msg_type == "new_session":
            self._handle_new_session()
        elif msg_type == "set_model":
            self._handle_set_model(msg)
        elif msg_type == "set_thinking":
            self._handle_set_thinking(msg)
        elif msg_type == "get_state":
            await self._send_state(ws)
        else:
            await ws.send_json({"type": "error", "error": f"Unknown type: {msg_type}"})

    async def _handle_chat(self, ws: WebSocket, msg: dict):
        """Handle a chat message from the client."""
        text = msg.get("text", "").strip()
        if not text and "image" not in msg:
            return

        with self._processing_lock:
            if self._is_processing:
                await ws.send_json({"type": "error", "error": "Already processing"})
                return
            self._is_processing = True

        # Cancel pending retries
        if self._engine and self._engine.retry_manager.has_pending():
            self._engine.retry_manager.cancel()

        # Pause pulse and telegram
        if self._pulse_manager:
            self._pulse_manager.reset_all()
            self._pulse_manager.pause()
        if self._telegram_listener:
            self._telegram_listener.pause()

        # Decode image if present
        image_bytes = None
        image_media_type = None
        if msg.get("image"):
            try:
                image_bytes = base64.b64decode(msg["image"])
                image_media_type = msg.get("image_media_type")
            except Exception as e:
                log_error(f"Failed to decode image: {e}")

        # Echo user message to all clients
        display_text = text
        if image_bytes:
            display_text = f"[Image] {text}" if text else "[Image attached]"
        self.broadcast_sync({
            "type": "user_message",
            "text": display_text,
            "timestamp": datetime.now().isoformat(),
        })

        # Run engine in background thread (synchronous)
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_engine_task,
            self._engine.process_message,
            text,
            image_bytes,
            image_media_type,
        )

    async def _handle_set_pulse_interval(self, msg: dict):
        pulse_type = msg.get("pulse_type", "")
        interval = msg.get("interval_seconds", 0)
        if not self._pulse_manager or not pulse_type or not interval:
            return
        if pulse_type == "reflective":
            self._pulse_manager.set_reflective_interval(float(interval))
        elif pulse_type == "action":
            self._pulse_manager.set_action_interval(float(interval))
        # Broadcast updated countdown so all clients refresh their display
        await self.broadcast({
            "type": "state",
            "pulse_intervals": {
                "reflective": self._pulse_manager.reflective_timer.interval,
                "action": self._pulse_manager.action_timer.interval,
            },
            "pulse_remaining": {
                "reflective": self._pulse_manager.reflective_timer.get_seconds_remaining(),
                "action": self._pulse_manager.action_timer.get_seconds_remaining(),
            },
        })

    def _handle_pulse_now(self, msg: dict):
        pulse_type = msg.get("pulse_type", "reflective")
        if pulse_type == "reflective":
            self._on_reflective_pulse_fired()
        else:
            self._on_action_pulse_fired()

    def _handle_new_session(self):
        if self._temporal_tracker:
            if self._temporal_tracker.is_session_active:
                self._temporal_tracker.end_session()
            self._temporal_tracker.start_session()

    def _handle_set_model(self, msg: dict):
        model = msg.get("model", "")
        if model:
            from core.user_settings import get_user_settings
            get_user_settings().conversation_model = model

    def _handle_set_thinking(self, msg: dict):
        enabled = msg.get("enabled", True)
        from core.user_settings import get_user_settings
        get_user_settings().thinking_enabled = enabled

    async def _poll_voice_events(self):
        """Background task: poll for ESP32 voice transcripts."""
        while True:
            try:
                from voice.api import voice_event_queue
            except ImportError:
                return  # Voice module not available, stop polling
            try:
                while not voice_event_queue.empty():
                    event = voice_event_queue.get_nowait()
                    user_text = event.get("user_text", "")
                    isaac_text = event.get("isaac_text", "")
                    ts = event.get("timestamp")
                    if user_text:
                        await self.manager.broadcast({
                            "type": "user_message",
                            "text": f"\U0001f399 {user_text}",
                            "timestamp": ts,
                        })
                    if isaac_text:
                        await self.manager.broadcast({
                            "type": "response_complete",
                            "text": isaac_text,
                            "source": "user",
                        })
            except Exception:
                pass  # Queue empty or other transient error
            await asyncio.sleep(0.5)

    async def _send_state(self, ws: WebSocket):
        """Send current system state to a single client."""
        from core.user_settings import get_user_settings
        settings = get_user_settings()

        state = {
            "type": "state",
            "model": settings.conversation_model,
            "thinking_enabled": settings.thinking_enabled,
            "pulse_enabled": config.SYSTEM_PULSE_ENABLED,
        }

        if self._pulse_manager and config.SYSTEM_PULSE_ENABLED:
            state["pulse_intervals"] = {
                "reflective": self._pulse_manager.reflective_timer.interval,
                "action": self._pulse_manager.action_timer.interval,
            }
            state["pulse_remaining"] = {
                "reflective": self._pulse_manager.reflective_timer.get_seconds_remaining(),
                "action": self._pulse_manager.action_timer.get_seconds_remaining(),
            }
            state["pulse_paused"] = self._pulse_manager.is_paused()

        state["is_processing"] = self._is_processing

        # Include session start time so the browser timer survives page refresh
        if self._temporal_tracker and self._temporal_tracker.is_session_active:
            ctx = self._temporal_tracker.get_context()
            if ctx and ctx.session_started_at:
                state["session_start_iso"] = ctx.session_started_at.isoformat()

        await ws.send_json(state)

    # -----------------------------------------------------------------------
    # FastAPI app creation
    # -----------------------------------------------------------------------
    def _create_app(self) -> FastAPI:
        app = FastAPI(title="Pattern Project", docs_url=None, redoc_url=None)

        # Auth middleware
        app.add_middleware(AuthMiddleware)

        # Static files
        if WEB_DIR.exists():
            app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        server = self  # closure ref

        # --- Auth endpoints ---

        @app.get("/auth/login", response_class=HTMLResponse)
        async def login_page():
            if not _auth_required():
                from starlette.responses import RedirectResponse
                return RedirectResponse(url="/", status_code=303)
            login_html = WEB_DIR / "login.html"
            if login_html.exists():
                return HTMLResponse(login_html.read_text())
            # Inline fallback login form
            return HTMLResponse(_FALLBACK_LOGIN_HTML)

        @app.post("/auth/login")
        async def login(request: Request):
            form = await request.form()
            password = form.get("password", "")
            if password == _get_auth_password():
                token = _create_session_token()
                response = JSONResponse({"ok": True})
                response.set_cookie(
                    AUTH_COOKIE_NAME,
                    token,
                    max_age=AUTH_COOKIE_MAX_AGE,
                    httponly=True,
                    samesite="lax",
                )
                return response
            return JSONResponse({"error": "Invalid password"}, status_code=401)

        @app.post("/auth/logout")
        async def logout(request: Request):
            token = request.cookies.get(AUTH_COOKIE_NAME, "")
            _active_sessions.pop(token, None)
            response = JSONResponse({"ok": True})
            response.delete_cookie(AUTH_COOKIE_NAME)
            return response

        # --- Main page ---

        @app.get("/", response_class=HTMLResponse)
        async def index():
            index_html = WEB_DIR / "index.html"
            if index_html.exists():
                return HTMLResponse(index_html.read_text())
            return HTMLResponse("<h1>Pattern Project</h1><p>Web UI files not found.</p>")

        # --- Health ---

        @app.on_event("startup")
        async def startup_background_tasks():
            """Start background tasks like voice event polling."""
            asyncio.ensure_future(server._poll_voice_events())

        @app.get("/health")
        async def health():
            return {"status": "healthy", "service": "pattern-project-web"}

        # --- WebSocket ---

        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            # Auth check for WebSocket
            if _auth_required():
                token = ws.cookies.get(AUTH_COOKIE_NAME, "")
                if not _validate_session(token):
                    await ws.close(code=4001, reason="Unauthorized")
                    return

            await server.manager.accept(ws)

            # Send initial state
            await server._send_state(ws)

            try:
                while True:
                    raw = await ws.receive_text()
                    await server._handle_ws_message(ws, raw)
            except WebSocketDisconnect:
                server.manager.disconnect(ws)
            except Exception as e:
                log_error(f"WebSocket error: {e}")
                server.manager.disconnect(ws)

        # --- Dev tools WebSocket + pages ---

        @app.websocket("/ws/dev")
        async def dev_websocket_endpoint(ws: WebSocket):
            if not config.DEV_MODE_ENABLED:
                await ws.close(code=4003, reason="Dev mode not enabled")
                return
            # Auth check
            if _auth_required():
                token = ws.cookies.get(AUTH_COOKIE_NAME, "")
                if not _validate_session(token):
                    await ws.close(code=4001, reason="Unauthorized")
                    return

            await server.dev_manager.accept(ws)
            await server._send_initial_dev_state(ws)
            try:
                while True:
                    await ws.receive_text()  # Keep alive; no client→server msgs
            except WebSocketDisconnect:
                server.dev_manager.disconnect(ws)
            except Exception as e:
                log_error(f"Dev WebSocket error: {e}")
                server.dev_manager.disconnect(ws)

        @app.get("/dev", response_class=HTMLResponse)
        async def dev_index():
            if not config.DEV_MODE_ENABLED:
                raise HTTPException(404, "Dev mode not enabled")
            html = DEV_DIR / "index.html"
            if html.exists():
                return HTMLResponse(html.read_text())
            raise HTTPException(404, "Dev index page not found")

        _DEV_PAGES = ["prompt", "tools", "pipeline", "memory", "thoughts", "curiosity", "intentions"]

        @app.get("/dev/{page}", response_class=HTMLResponse)
        async def dev_page(page: str):
            if not config.DEV_MODE_ENABLED:
                raise HTTPException(404, "Dev mode not enabled")
            if page not in _DEV_PAGES:
                raise HTTPException(404, f"Unknown dev page: {page}")
            html = DEV_DIR / f"{page}.html"
            if html.exists():
                return HTMLResponse(html.read_text())
            raise HTTPException(404, f"Dev page not found: {page}")

        # Dev static files (CSS/JS) are served via the existing /static mount
        # since dev/ is a subdirectory of web/ → /static/dev/dev-common.js etc.

        # --- REST API (ported from http_api.py) ---

        @app.get("/api/stats")
        async def stats():
            from core.database import get_database
            from core.temporal import get_temporal_tracker
            from memory.extractor import get_memory_extractor

            db = get_database()
            db_stats = db.get_stats()
            tracker = get_temporal_tracker()
            context = tracker.get_context()
            extractor = get_memory_extractor()
            ext_stats = extractor.get_stats()

            return {
                "database": db_stats,
                "session": {
                    "active": tracker.is_session_active,
                    "session_id": tracker.current_session_id,
                    "turns_this_session": context.turns_this_session,
                    "duration_seconds": (
                        context.session_duration.total_seconds()
                        if context.session_duration
                        else 0
                    ),
                },
                "extractor": ext_stats,
            }

        @app.post("/api/memories/search")
        async def search_memories(request: Request):
            data = await request.json()
            query = data.get("query", "")
            if not query:
                raise HTTPException(400, "Missing 'query' field")

            from memory.vector_store import get_vector_store
            vector_store = get_vector_store()
            results = vector_store.search(
                query=query,
                limit=data.get("limit", 10),
                memory_type=data.get("memory_type"),
            )
            return {
                "results": [
                    {
                        "id": r.memory.id,
                        "content": r.memory.content,
                        "type": r.memory.memory_type,
                        "importance": r.memory.importance,
                        "combined_score": r.combined_score,
                    }
                    for r in results
                ]
            }

        # --- Blog API ---

        @app.get("/blog/write", response_class=HTMLResponse)
        async def blog_write_page():
            """Serve the blog writing/publishing form."""
            blog_html = WEB_DIR / "blog.html"
            if blog_html.exists():
                return HTMLResponse(blog_html.read_text())
            return HTMLResponse("<p>Blog write page not found.</p>")

        @app.post("/api/blog/publish")
        async def api_blog_publish(request: Request):
            """Create a blog post via the web UI (author: Brian)."""
            data = await request.json()
            title = (data.get("title") or "").strip()
            content = (data.get("content") or "").strip()
            if not title or not content:
                raise HTTPException(400, "Title and content are required")

            from blog.blog_manager import create_post
            result = create_post(
                title=title,
                content=content,
                author="Brian",
                tags=data.get("tags", []),
                summary=(data.get("summary") or "").strip(),
                status=data.get("status", "published"),
                in_response_to=(data.get("in_response_to") or "").strip(),
            )
            if "error" in result:
                raise HTTPException(400, result["error"])
            return result

        @app.get("/api/blog/posts")
        async def api_blog_list(status: str = None):
            """List blog posts."""
            from blog.blog_manager import list_posts
            return {"posts": list_posts(status=status)}

        return app


# ---------------------------------------------------------------------------
# Fallback login HTML (used if login.html doesn't exist)
# ---------------------------------------------------------------------------
_FALLBACK_LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Pattern - Login</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui;background:#1a1a2e;color:#e0e0e0;display:flex;
justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#16213e;padding:2rem;border-radius:12px;width:320px}
h2{margin-top:0;text-align:center}
input{width:100%;padding:10px;margin:8px 0;border:1px solid #334;
background:#0f3460;color:#e0e0e0;border-radius:6px;box-sizing:border-box}
button{width:100%;padding:10px;background:#533483;color:white;border:none;
border-radius:6px;cursor:pointer;font-size:1rem;margin-top:8px}
button:hover{background:#6a4c9c}
.err{color:#ff6b6b;text-align:center;margin-top:8px;display:none}
</style></head><body>
<div class="box"><h2>Pattern Project</h2>
<form id="f"><input type="password" name="password" placeholder="Password" autofocus>
<button type="submit">Login</button></form>
<div class="err" id="e">Invalid password</div></div>
<script>
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const r = await fetch('/auth/login', {method:'POST', body:fd});
  if(r.ok) window.location.href='/';
  else document.getElementById('e').style.display='block';
});
</script></body></html>"""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_web_server: Optional[WebServer] = None


def get_web_server() -> WebServer:
    global _web_server
    if _web_server is None:
        _web_server = WebServer()
    return _web_server


def init_web_server() -> WebServer:
    global _web_server
    _web_server = WebServer()
    return _web_server
