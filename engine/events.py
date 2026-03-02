"""
Pattern Project - Engine Event Types

Events emitted by ChatEngine during message processing.
UI layers subscribe to these events and translate them into
their own display mechanisms (WebSocket, Rich console, etc.).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict


class EngineEventType(Enum):
    """Events emitted by the ChatEngine at each pipeline stage."""

    # Message lifecycle
    PROCESSING_STARTED = auto()     # {"source": "user"|"pulse"|"reminder"|"telegram"|"retry"}
    PROMPT_ASSEMBLED = auto()       # {"blocks": list, "token_estimate": int}
    MEMORIES_INJECTED = auto()      # {}
    STREAM_START = auto()           # {}
    STREAM_CHUNK = auto()           # {"text": str}
    STREAM_COMPLETE = auto()        # {"text": str, "tokens_in": int, "tokens_out": int, "stop_reason": str}
    RESPONSE_COMPLETE = auto()      # {"text": str, "provider": str, "source": str}
    PROCESSING_COMPLETE = auto()    # {}
    PROCESSING_ERROR = auto()       # {"error": str, "error_type": str|None}

    # Tool lifecycle
    TOOL_INVOKED = auto()           # {"tool_name": str, "detail": str}
    SERVER_TOOL_INVOKED = auto()    # {"tool_name": str, "detail": str}

    # Clarification
    CLARIFICATION_REQUESTED = auto()  # {"data": dict}  (question, options, context)

    # Pulse / reminder
    PULSE_FIRED = auto()              # {"pulse_type": "reflective"|"action"}
    REMINDER_FIRED = auto()           # {"intentions": list}
    PULSE_INTERVAL_CHANGED = auto()   # {"pulse_type": str, "interval_seconds": int}

    # Telegram
    TELEGRAM_RECEIVED = auto()        # {"text": str, "from_user": str}
    TELEGRAM_SENT = auto()            # {"text": str}

    # Status
    STATUS_UPDATE = auto()            # {"text": str, "type": str}
    NOTIFICATION = auto()             # {"message": str, "level": str}

    # Retry
    RETRY_SCHEDULED = auto()          # {"source": str}
    RETRY_FAILED = auto()             # {"source": str, "error": str}

    # Dev mode (forwarded from process_with_tools callbacks)
    DEV_RESPONSE_PASS = auto()        # pass info dict
    DEV_COMMAND_EXECUTED = auto()     # command execution dict


@dataclass
class EngineEvent:
    """A single event emitted by the ChatEngine."""
    event_type: EngineEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
