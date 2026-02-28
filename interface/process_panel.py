"""
Pattern Project - Process Event System

Defines the event types, data structures, and event bus used by the engine,
agency tools, and web interface to track the AI's internal processing pipeline.

The web interface subscribes to ProcessEventBus via callbacks and forwards
events over WebSocket to the browser-side process panel (process.js).
"""

from datetime import datetime
from enum import Enum, auto
from typing import Optional, List, Any
from dataclasses import dataclass, field


# =============================================================================
# PROCESS EVENT TYPES
# =============================================================================

class ProcessEventType(Enum):
    """Types of events that can appear in the process panel."""
    MESSAGE_RECEIVED = auto()
    PROMPT_ASSEMBLED = auto()
    MEMORIES_INJECTED = auto()
    STREAM_START = auto()
    STREAMING = auto()
    STREAM_COMPLETE = auto()
    TOOL_INVOKED = auto()
    CONTINUATION_START = auto()
    ROUND_COMPLETE = auto()
    PROCESSING_COMPLETE = auto()
    PROCESSING_ERROR = auto()
    MEMORY_EXTRACTION = auto()
    PULSE_FIRED = auto()
    REMINDER_FIRED = auto()
    TELEGRAM_RECEIVED = auto()
    DELEGATION_START = auto()
    DELEGATION_TOOL = auto()
    DELEGATION_COMPLETE = auto()
    CURIOSITY_SELECTED = auto()


# =============================================================================
# PROCESS EVENT DATA
# =============================================================================

@dataclass
class ProcessEvent:
    """A single event in the processing pipeline."""
    event_type: ProcessEventType
    timestamp: datetime = field(default_factory=datetime.now)
    detail: str = ""
    round_number: int = 0
    is_active: bool = False
    origin: str = "user"  # "user", "isaac", or "system"

    @property
    def label(self) -> str:
        """Human-readable label for this event type."""
        labels = {
            ProcessEventType.MESSAGE_RECEIVED: "You said something",
            ProcessEventType.PROMPT_ASSEMBLED: "Gathering thoughts",
            ProcessEventType.MEMORIES_INJECTED: "Recalling past conversations",
            ProcessEventType.STREAM_START: "Thinking...",
            ProcessEventType.STREAMING: "Thinking...",
            ProcessEventType.STREAM_COMPLETE: "Responded",
            ProcessEventType.TOOL_INVOKED: "Tool",
            ProcessEventType.CONTINUATION_START: "Thinking further...",
            ProcessEventType.ROUND_COMPLETE: "Round complete",
            ProcessEventType.PROCESSING_COMPLETE: "Settled",
            ProcessEventType.PROCESSING_ERROR: "Something went wrong",
            ProcessEventType.MEMORY_EXTRACTION: "Reflecting on what to remember",
            ProcessEventType.PULSE_FIRED: "Checking in",
            ProcessEventType.REMINDER_FIRED: "Remembered something he promised",
            ProcessEventType.TELEGRAM_RECEIVED: "You sent a Telegram",
            ProcessEventType.DELEGATION_START: "Asking for help with a task",
            ProcessEventType.DELEGATION_TOOL: "Delegate",
            ProcessEventType.DELEGATION_COMPLETE: "Got the help he needed",
            ProcessEventType.CURIOSITY_SELECTED: "Got curious about something",
        }
        return labels.get(self.event_type, "Unknown")


# =============================================================================
# PROCESS EVENT BUS
# =============================================================================

class ProcessEventBus:
    """Central event bus for process panel updates.

    Agency tools, the memory extractor, and curiosity engine emit events
    through this bus.  The web server subscribes via add_callback() to
    forward events over WebSocket.
    """

    def __init__(self):
        self._callbacks: List[Any] = []

    def add_callback(self, callback) -> None:
        """Register a callback for process events."""
        self._callbacks.append(callback)

    def emit_event(self, event_type: ProcessEventType, detail: str = "",
                   round_number: int = 0, is_active: bool = False,
                   origin: str = "user"):
        """Emit a process event to all subscribers."""
        event = ProcessEvent(
            event_type=event_type,
            detail=detail,
            round_number=round_number,
            is_active=is_active,
            origin=origin
        )
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass


# Global instance
_event_bus: Optional[ProcessEventBus] = None


def get_process_event_bus() -> ProcessEventBus:
    """Get the global process event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = ProcessEventBus()
    return _event_bus


# =============================================================================
# COLORS (shared constants used by web CSS/JS theme)
# =============================================================================

# Panel colors
PANEL_BG = "#252525"
PANEL_BORDER = "#3a3a3a"

# Event node colors
COLOR_ACTIVE = "#d4a574"       # Warm amber - something is happening now
COLOR_COMPLETE = "#7a7770"     # Muted - finished
COLOR_TOOL = "#c4a7e7"         # Purple - tool invocation
COLOR_ERROR = "#e07a6b"        # Red - error
COLOR_SYSTEM = "#5bb98c"       # Green - system events (pulse, extraction)
COLOR_CONNECTOR = "#3a3a3a"    # Very dim connector lines
COLOR_DELEGATION = "#6bb5e0"   # Blue - delegation events
COLOR_TEXT = "#e8e6e3"         # Primary text
COLOR_TEXT_DIM = "#7a7770"     # Dimmed text
COLOR_TEXT_DETAIL = "#9a9892"  # Detail/metadata text
COLOR_ROUND_BG = "#2e2e2e"    # Round group background
COLOR_ROUND_BORDER = "#424240" # Round group border
COLOR_SEPARATOR = "#3a3a3a"    # Message separator

# Origin-based left border colors (per message group)
COLOR_BORDER_ISAAC = "#c4a7e7"   # Purple - Isaac-initiated
COLOR_BORDER_USER = "#6bb5e0"    # Blue - User-initiated
COLOR_BORDER_SYSTEM = "#5bb98c"  # Green - System-initiated
