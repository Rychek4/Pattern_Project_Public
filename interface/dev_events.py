"""
Pattern Project - Dev Event Bus

PyQt5-free event bus for dev/debug data. Replaces the DevWindowSignals
(pyqtSignal) system with plain callbacks so dev tools work in web mode
without any Qt dependency.

The emit_*() functions have the same signatures as their dev_window.py
counterparts so callers only need an import-path change.
"""

import threading
from collections import defaultdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field, asdict

import config


# =============================================================================
# DATA CLASSES (moved from dev_window.py — no PyQt5 dependency)
# =============================================================================

@dataclass
class PromptAssemblyData:
    """Data about prompt assembly."""
    context_blocks: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens_estimate: int = 0
    timestamp: str = ""


@dataclass
class WebSearchCitationData:
    """Citation from a web search result."""
    title: str = ""
    url: str = ""
    cited_text: str = ""


@dataclass
class CommandExecutionData:
    """Data about command execution."""
    command_name: str = ""
    query: str = ""
    result_data: Any = None
    error: Optional[str] = None
    needs_continuation: bool = False
    timestamp: str = ""


@dataclass
class ResponsePassData:
    """Data about a single response pass."""
    pass_number: int = 0
    provider: str = ""
    response_text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: float = 0
    commands_detected: List[str] = field(default_factory=list)
    timestamp: str = ""
    web_searches_used: int = 0
    citations: List[WebSearchCitationData] = field(default_factory=list)


@dataclass
class MemoryRecallData:
    """Data about memory recall."""
    query: str = ""
    results: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class ActiveThoughtsData:
    """Data about active thoughts update."""
    thoughts: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class CuriosityData:
    """Data about curiosity engine state."""
    current_goal: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    cooldowns: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""
    event: str = ""


@dataclass
class IntentionData:
    """Data about intentions (reminders/goals)."""
    intentions: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""
    event: str = ""


# =============================================================================
# DEV EVENT BUS
# =============================================================================

class DevEventBus:
    """Thread-safe event bus for dev/debug data.

    Listeners register via ``add_callback(event_type, fn)`` and receive
    the relevant dataclass instance when ``emit(event_type, data)`` is called.
    """

    def __init__(self):
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def add_callback(self, event_type: str, callback: Callable):
        with self._lock:
            self._callbacks[event_type].append(callback)

    def remove_callback(self, event_type: str, callback: Callable):
        with self._lock:
            try:
                self._callbacks[event_type].remove(callback)
            except ValueError:
                pass

    def emit(self, event_type: str, data):
        with self._lock:
            listeners = list(self._callbacks.get(event_type, []))
        for fn in listeners:
            try:
                fn(data)
            except Exception:
                pass  # Don't let a bad listener break the pipeline


# Singleton
_dev_event_bus: Optional[DevEventBus] = None


def get_dev_event_bus() -> DevEventBus:
    global _dev_event_bus
    if _dev_event_bus is None:
        _dev_event_bus = DevEventBus()
    return _dev_event_bus


# =============================================================================
# SERIALIZATION HELPER
# =============================================================================

def _serialize(data) -> dict:
    """Convert a dev dataclass to a JSON-safe dict."""
    d = asdict(data)
    # result_data in CommandExecutionData can be arbitrary — stringify it
    if "result_data" in d and d["result_data"] is not None:
        try:
            # If it's already JSON-serializable, leave it
            import json
            json.dumps(d["result_data"])
        except (TypeError, ValueError):
            d["result_data"] = str(d["result_data"])
    return d


# =============================================================================
# TIMESTAMP HELPER
# =============================================================================

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# =============================================================================
# EMIT FUNCTIONS (same signatures as dev_window.py)
# =============================================================================

def emit_prompt_assembly(context_blocks: List[Dict[str, Any]], total_tokens: int = 0):
    """Emit prompt assembly data if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    data = PromptAssemblyData(
        context_blocks=context_blocks,
        total_tokens_estimate=total_tokens,
        timestamp=_now()
    )
    get_dev_event_bus().emit("prompt_assembly", data)


def emit_command_executed(
    command_name: str = "",
    query: str = "",
    result_data: Any = None,
    error: Optional[str] = None,
    needs_continuation: bool = False,
    **kwargs
):
    """Emit command execution data if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    data = CommandExecutionData(
        command_name=command_name,
        query=query,
        result_data=result_data,
        error=error,
        needs_continuation=needs_continuation,
        timestamp=_now()
    )
    get_dev_event_bus().emit("command_executed", data)


def emit_response_pass(
    pass_number: int = 0,
    provider: str = "",
    response_text: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    duration_ms: float = 0,
    commands_detected: Optional[List[str]] = None,
    web_searches_used: int = 0,
    citations: Optional[List[Any]] = None,
    **kwargs
):
    """Emit response pass data if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    citation_data = []
    if citations:
        for c in citations:
            citation_data.append(WebSearchCitationData(
                title=getattr(c, "title", "") if hasattr(c, "title") else c.get("title", ""),
                url=getattr(c, "url", "") if hasattr(c, "url") else c.get("url", ""),
                cited_text=getattr(c, "cited_text", "") if hasattr(c, "cited_text") else c.get("cited_text", "")
            ))
    data = ResponsePassData(
        pass_number=pass_number,
        provider=provider,
        response_text=response_text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_ms=duration_ms,
        commands_detected=commands_detected or [],
        timestamp=_now(),
        web_searches_used=web_searches_used,
        citations=citation_data
    )
    get_dev_event_bus().emit("response_pass", data)


def emit_memory_recall(query: str, results: List[Dict[str, Any]]):
    """Emit memory recall data if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    data = MemoryRecallData(
        query=query,
        results=results,
        timestamp=_now()
    )
    get_dev_event_bus().emit("memory_recall", data)


def emit_active_thoughts_update(thoughts: List[Dict[str, Any]]):
    """Emit active thoughts update if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    data = ActiveThoughtsData(
        thoughts=thoughts,
        timestamp=_now()
    )
    get_dev_event_bus().emit("active_thoughts", data)


def emit_curiosity_update(
    current_goal: Optional[Dict[str, Any]],
    history: Optional[List[Dict[str, Any]]] = None,
    cooldowns: Optional[List[Dict[str, Any]]] = None,
    event: str = "updated"
):
    """Emit curiosity update if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    data = CuriosityData(
        current_goal=current_goal,
        history=history or [],
        cooldowns=cooldowns or [],
        timestamp=_now(),
        event=event
    )
    get_dev_event_bus().emit("curiosity", data)


def emit_intentions_update(intentions: List[Dict[str, Any]], event: str = "updated"):
    """Emit intentions update if dev mode is active."""
    if not config.DEV_MODE_ENABLED:
        return
    data = IntentionData(
        intentions=intentions,
        timestamp=_now(),
        event=event
    )
    get_dev_event_bus().emit("intentions", data)


# =============================================================================
# INITIAL LOAD FUNCTIONS
# =============================================================================

def get_initial_active_thoughts_data() -> Optional[ActiveThoughtsData]:
    """Gather current active thoughts state. Returns None if unavailable."""
    if not config.DEV_MODE_ENABLED:
        return None
    try:
        from agency.active_thoughts import get_active_thoughts_manager
        manager = get_active_thoughts_manager()
        thoughts = manager.get_all()
        if thoughts:
            thought_dicts = [{
                "rank": t.rank,
                "slug": t.slug,
                "topic": t.topic,
                "elaboration": t.elaboration
            } for t in thoughts]
            return ActiveThoughtsData(
                thoughts=thought_dicts,
                timestamp="(initial load)"
            )
    except Exception:
        pass
    return None


def get_initial_curiosity_data() -> Optional[CuriosityData]:
    """Gather current curiosity engine state. Returns None if unavailable."""
    if not config.DEV_MODE_ENABLED:
        return None
    try:
        from agency.curiosity import is_curiosity_enabled, get_curiosity_engine

        if not is_curiosity_enabled():
            return None

        engine = get_curiosity_engine()
        goal = engine.get_current_goal()
        history = engine.get_goal_history(limit=5)

        goal_dict = {
            "id": goal.id,
            "content": goal.content,
            "category": goal.category,
            "context": goal.context,
            "activated_at": goal.activated_at.isoformat() if goal.activated_at else ""
        }

        history_dicts = []
        for h in history:
            if h.status.value != "active":
                history_dicts.append({
                    "id": h.id,
                    "content": h.content,
                    "status": h.status.value,
                    "resolved_at": h.resolved_at.isoformat() if h.resolved_at else ""
                })

        return CuriosityData(
            current_goal=goal_dict,
            history=history_dicts,
            cooldowns=[],
            timestamp="(initial load)",
            event="initial"
        )
    except Exception:
        pass
    return None


def get_initial_intentions_data() -> Optional[IntentionData]:
    """Gather current intentions state. Returns None if unavailable."""
    if not config.DEV_MODE_ENABLED:
        return None
    try:
        from agency.intentions import get_intention_manager
        manager = get_intention_manager()
        all_intentions = []
        active = manager.get_all_active_intentions()
        for intention in active:
            all_intentions.append({
                "id": intention.id,
                "type": intention.type,
                "content": intention.content,
                "context": intention.context,
                "trigger_type": intention.trigger_type,
                "trigger_at": intention.trigger_at.isoformat() if intention.trigger_at else None,
                "status": intention.status,
                "priority": intention.priority,
                "created_at": intention.created_at.isoformat() if intention.created_at else None,
                "triggered_at": intention.triggered_at.isoformat() if intention.triggered_at else None,
                "completed_at": intention.completed_at.isoformat() if intention.completed_at else None,
                "outcome": intention.outcome,
            })
        return IntentionData(
            intentions=all_intentions,
            timestamp="(initial load)",
            event="initial"
        )
    except Exception:
        pass
    return None


def load_initial_active_thoughts():
    """Load current active thoughts into the dev event bus on startup."""
    data = get_initial_active_thoughts_data()
    if data:
        get_dev_event_bus().emit("active_thoughts", data)


def load_initial_curiosity():
    """Load current curiosity state into the dev event bus on startup."""
    data = get_initial_curiosity_data()
    if data:
        get_dev_event_bus().emit("curiosity", data)


def load_initial_intentions():
    """Load current intentions into the dev event bus on startup."""
    data = get_initial_intentions_data()
    if data:
        get_dev_event_bus().emit("intentions", data)
