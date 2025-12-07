"""
Pattern Project - Temporal Context Tracking
Tracks time across all entities and provides semantic conversion for prompts
"""

import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from core.database import get_database
from core.logger import log_info


@dataclass
class TemporalContext:
    """Snapshot of current temporal context."""
    current_time: datetime
    session_started_at: Optional[datetime] = None
    session_duration: Optional[timedelta] = None
    turns_this_session: int = 0
    last_turn_at: Optional[datetime] = None
    time_since_last_turn: Optional[timedelta] = None
    last_session_ended_at: Optional[datetime] = None
    total_interaction_time: timedelta = field(default_factory=timedelta)
    total_sessions: int = 0
    first_interaction: Optional[datetime] = None


class TemporalTracker:
    """
    Tracks temporal context across the application.

    Thread-safe tracking of time-related data for sessions,
    conversations, and memories.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._current_session_id: Optional[int] = None
        self._session_started_at: Optional[datetime] = None
        self._last_turn_at: Optional[datetime] = None
        self._turns_this_session: int = 0

    def start_session(self) -> int:
        """
        Start a new session and return its ID.

        Returns:
            The new session ID
        """
        with self._lock:
            db = get_database()
            now = datetime.now()

            # Create session in database
            db.execute(
                "INSERT INTO sessions (started_at) VALUES (?)",
                (now.isoformat(),)
            )

            # Get the new session ID
            result = db.execute(
                "SELECT id FROM sessions ORDER BY id DESC LIMIT 1",
                fetch=True
            )
            session_id = result[0]["id"]

            # Update tracker state
            self._current_session_id = session_id
            self._session_started_at = now
            self._last_turn_at = now
            self._turns_this_session = 0

            log_info(f"Session {session_id} started", prefix="🆕")

            return session_id

    def end_session(self) -> Optional[Dict[str, Any]]:
        """
        End the current session.

        Returns:
            Session summary dict, or None if no active session
        """
        with self._lock:
            if self._current_session_id is None:
                return None

            db = get_database()
            now = datetime.now()
            duration = (now - self._session_started_at).total_seconds() if self._session_started_at else 0

            # Update session in database
            db.execute(
                """
                UPDATE sessions
                SET ended_at = ?, duration_seconds = ?, turn_count = ?
                WHERE id = ?
                """,
                (now.isoformat(), duration, self._turns_this_session, self._current_session_id)
            )

            summary = {
                "session_id": self._current_session_id,
                "duration_seconds": duration,
                "turn_count": self._turns_this_session,
                "started_at": self._session_started_at.isoformat() if self._session_started_at else None,
                "ended_at": now.isoformat()
            }

            log_info(
                f"Session {self._current_session_id} ended "
                f"({self._turns_this_session} turns, {duration:.0f}s)",
                prefix="🏁"
            )

            # Reset tracker state
            self._current_session_id = None
            self._session_started_at = None
            self._last_turn_at = None
            self._turns_this_session = 0

            return summary

    def record_turn(self) -> float:
        """
        Record a conversation turn and return time since last turn.

        Returns:
            Seconds since last turn (0 if first turn)
        """
        with self._lock:
            now = datetime.now()

            if self._last_turn_at:
                time_since_last = (now - self._last_turn_at).total_seconds()
            else:
                time_since_last = 0

            self._last_turn_at = now
            self._turns_this_session += 1

            # Update session turn count
            if self._current_session_id:
                db = get_database()
                db.execute(
                    "UPDATE sessions SET turn_count = ? WHERE id = ?",
                    (self._turns_this_session, self._current_session_id)
                )

            return time_since_last

    def get_context(self) -> TemporalContext:
        """
        Get the current temporal context.

        Returns:
            TemporalContext with all current temporal data
        """
        with self._lock:
            now = datetime.now()
            db = get_database()

            # Calculate session duration
            session_duration = None
            if self._session_started_at:
                session_duration = now - self._session_started_at

            # Calculate time since last turn
            time_since_last = None
            if self._last_turn_at:
                time_since_last = now - self._last_turn_at

            # Get historical data from database
            result = db.execute(
                """
                SELECT
                    COUNT(*) as total_sessions,
                    SUM(duration_seconds) as total_time,
                    MIN(started_at) as first_interaction,
                    MAX(ended_at) as last_session_end
                FROM sessions
                WHERE ended_at IS NOT NULL
                """,
                fetch=True
            )

            row = result[0] if result else None
            total_sessions = row["total_sessions"] if row else 0
            total_time = row["total_time"] or 0 if row else 0
            first_interaction = None
            last_session_ended = None

            if row and row["first_interaction"]:
                first_interaction = datetime.fromisoformat(row["first_interaction"])
            if row and row["last_session_end"]:
                last_session_ended = datetime.fromisoformat(row["last_session_end"])

            return TemporalContext(
                current_time=now,
                session_started_at=self._session_started_at,
                session_duration=session_duration,
                turns_this_session=self._turns_this_session,
                last_turn_at=self._last_turn_at,
                time_since_last_turn=time_since_last,
                last_session_ended_at=last_session_ended,
                total_interaction_time=timedelta(seconds=total_time),
                total_sessions=total_sessions,
                first_interaction=first_interaction
            )

    @property
    def current_session_id(self) -> Optional[int]:
        """Get the current session ID."""
        with self._lock:
            return self._current_session_id

    @property
    def is_session_active(self) -> bool:
        """Check if a session is currently active."""
        with self._lock:
            return self._current_session_id is not None

    def get_idle_seconds(self) -> float:
        """Get seconds since last turn (0 if no turns yet)."""
        with self._lock:
            if self._last_turn_at is None:
                return 0
            return (datetime.now() - self._last_turn_at).total_seconds()


def format_duration(seconds: float) -> str:
    """Format a duration in seconds to human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutes"
    elif seconds < 86400:
        hours = seconds / 3600
        return f"{hours:.1f} hours"
    else:
        days = seconds / 86400
        return f"{days:.1f} days"


def format_relative_time(dt: datetime) -> str:
    """Format a datetime relative to now."""
    now = datetime.now()
    diff = now - dt

    if diff.total_seconds() < 60:
        return "just now"
    elif diff.total_seconds() < 3600:
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff.days == 1:
        return f"yesterday at {dt.strftime('%H:%M')}"
    elif diff.days < 7:
        return f"{diff.days} days ago"
    else:
        return dt.strftime("%Y-%m-%d")


def temporal_context_to_semantic(context: TemporalContext) -> str:
    """
    Convert temporal context to semantic/natural language for prompts.

    Args:
        context: The temporal context to convert

    Returns:
        Natural language description of the temporal context
    """
    parts = []

    # Current time
    parts.append(f"The current time is {context.current_time.strftime('%A, %B %d, %Y at %H:%M')}.")

    # Session context
    if context.session_duration:
        duration_str = format_duration(context.session_duration.total_seconds())
        parts.append(f"This conversation session has been going for {duration_str}.")

    if context.turns_this_session > 0:
        parts.append(f"There have been {context.turns_this_session} exchanges in this session.")

    # Time since last turn
    if context.time_since_last_turn:
        if context.time_since_last_turn.total_seconds() > 60:
            gap_str = format_duration(context.time_since_last_turn.total_seconds())
            parts.append(f"It has been {gap_str} since the last message.")

    # Historical context
    if context.last_session_ended_at:
        last_session_str = format_relative_time(context.last_session_ended_at)
        parts.append(f"The previous session ended {last_session_str}.")

    if context.total_sessions > 0:
        total_time_str = format_duration(context.total_interaction_time.total_seconds())
        parts.append(
            f"Across {context.total_sessions} previous sessions, "
            f"there has been {total_time_str} of interaction."
        )

    if context.first_interaction:
        first_str = format_relative_time(context.first_interaction)
        parts.append(f"The first interaction was {first_str}.")

    return " ".join(parts)


# Global temporal tracker instance
_tracker: Optional[TemporalTracker] = None


def get_temporal_tracker() -> TemporalTracker:
    """Get the global temporal tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = TemporalTracker()
    return _tracker


def init_temporal_tracker() -> TemporalTracker:
    """Initialize the global temporal tracker."""
    global _tracker
    _tracker = TemporalTracker()
    return _tracker
