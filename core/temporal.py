"""
Pattern Project - Temporal Context Tracking
Tracks time across all entities and provides semantic conversion for prompts
"""

import re
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

        NOTE (Windowed Extraction System):
            Session end NO LONGER triggers memory extraction.
            The context window persists across sessions for AI continuity.
            Extraction only happens when the context window overflows.

            This ensures the AI always has ~30 turns of recent context,
            even at the start of a new session.

        Returns:
            Session summary dict, or None if no active session
        """
        with self._lock:
            if self._current_session_id is None:
                return None

            # NOTE: We intentionally do NOT extract memories at session end.
            # The windowed extraction system handles extraction only when
            # context overflows, preserving continuity across sessions.
            # See memory/extractor.py for the windowed extraction architecture.

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


def get_time_of_day(hour: int) -> str:
    """
    Convert hour to semantic time of day.

    Args:
        hour: Hour in 24-hour format (0-23)

    Returns:
        Semantic time period: 'Morning', 'Afternoon', 'Evening', or 'Night'
    """
    if 5 <= hour < 12:
        return "Morning"
    elif 12 <= hour < 17:
        return "Afternoon"
    elif 17 <= hour < 21:
        return "Evening"
    else:
        return "Night"


def get_month_position(day: int) -> str:
    """
    Convert day of month to semantic position.

    Args:
        day: Day of month (1-31)

    Returns:
        Semantic position: 'Early', 'Mid', or 'Late'
    """
    if day <= 10:
        return "Early"
    elif day <= 20:
        return "Mid"
    else:
        return "Late"


def format_semantic_current_time(dt: datetime) -> str:
    """
    Format datetime as semantic current time description.

    Args:
        dt: The datetime to format

    Returns:
        Semantic description like 'Sunday Morning. Early December.'
    """
    day_name = dt.strftime("%A")
    time_of_day = get_time_of_day(dt.hour)
    month_position = get_month_position(dt.day)
    month_name = dt.strftime("%B")

    return f"{day_name} {time_of_day}. {month_position} {month_name}."


def format_fuzzy_relative_time(dt: datetime) -> str:
    """
    Format datetime relative to now using fuzzy, human-like descriptions.

    Args:
        dt: The datetime to format

    Returns:
        Fuzzy relative time like 'A few minutes ago', 'Earlier today', etc.
    """
    now = datetime.now()
    diff = now - dt
    seconds = diff.total_seconds()

    # Handle future times (shouldn't happen, but be safe)
    if seconds < 0:
        return "Just now"

    # Very recent
    if seconds < 30:
        return "Just now"
    elif seconds < 120:  # 2 minutes
        return "A moment ago"
    elif seconds < 600:  # 10 minutes
        return "A few minutes ago"
    elif seconds < 1200:  # 20 minutes
        return "Several minutes ago"
    elif seconds < 2700:  # 45 minutes
        return "Around half an hour ago"
    elif seconds < 5400:  # 90 minutes
        return "About an hour ago"
    elif seconds < 10800:  # 3 hours
        return "A couple hours ago"

    # Same day check
    if dt.date() == now.date():
        return "Earlier today"

    # Yesterday check
    yesterday = now.date().toordinal() - 1
    if dt.date().toordinal() == yesterday:
        return "Yesterday"

    # Days ago
    days = diff.days
    if days < 7:
        return "A few days ago"
    elif days < 14:
        return "Last week"
    elif days < 30:
        return "A couple weeks ago"
    elif days < 60:
        return "Last month"
    else:
        return "A while ago"


def get_gap_descriptor(gap_seconds: float) -> str:
    """
    Get a human-readable descriptor for a session gap.

    Args:
        gap_seconds: Duration of gap between sessions in seconds

    Returns:
        Descriptor like 'brief pause', 'overnight', etc.
    """
    if gap_seconds < 300:  # 5 minutes
        return "brief pause"
    elif gap_seconds < 1800:  # 30 minutes
        return "short break"
    elif gap_seconds < 7200:  # 2 hours
        return "stepped away"
    elif gap_seconds < 21600:  # 6 hours
        return "extended break"
    elif gap_seconds < 43200:  # 12 hours
        return "long absence"
    else:
        return "extended time away"


def format_session_duration(session_started_at: datetime) -> str:
    """
    Format how long the current session has been active.

    Args:
        session_started_at: When the session started

    Returns:
        Fuzzy duration like '45 minutes ago', 'Just now', etc.
    """
    return format_fuzzy_relative_time(session_started_at)


def temporal_context_to_semantic(context: TemporalContext) -> str:
    """
    Convert temporal context to semantic/natural language for prompts.

    Returns a human-like time description with exact time for functional purposes.
    Includes session duration and gap since last session when available.

    Args:
        context: The temporal context to convert

    Returns:
        Semantic description with current time, exact time, session duration, and session gap.
    """
    lines = [format_semantic_current_time(context.current_time)]

    # Add exact time for functional/scheduling purposes
    # Use %I and lstrip to avoid platform-specific %-I format specifier
    exact_time = context.current_time.strftime("%I:%M %p").lstrip("0")
    lines.append(f"Exact time: {exact_time}")

    # Add session duration if available
    if context.session_started_at:
        duration_str = format_session_duration(context.session_started_at)
        lines.append(f"Session started: {duration_str}")

    # Add gap since last session if available
    if context.last_session_ended_at:
        gap_str = format_fuzzy_relative_time(context.last_session_ended_at)

        # Calculate gap descriptor based on time between sessions
        if context.session_started_at:
            gap_seconds = (context.session_started_at - context.last_session_ended_at).total_seconds()
            if gap_seconds > 0:
                descriptor = get_gap_descriptor(gap_seconds)
                lines.append(f"Last session ended: {gap_str} ({descriptor})")
            else:
                lines.append(f"Last session ended: {gap_str}")
        else:
            lines.append(f"Last session ended: {gap_str}")

    return "\n".join(lines)


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


# --- Output filtering ---

_TEMPORAL_ECHO_RE = re.compile(r'\(Just now\) ?')


def strip_temporal_echoes(text: str) -> str:
    """Remove '(Just now)' markers the LLM may echo from temporal prompt context.

    Applied before display and storage so the marker never reaches the user
    or pollutes conversation history / memory.
    """
    if "(Just now)" not in text:
        return text
    cleaned = _TEMPORAL_ECHO_RE.sub('', text)
    # Collapse any double-spaces left behind
    cleaned = re.sub(r'  +', ' ', cleaned)
    # Strip leading blank lines that may result from removal at line start
    cleaned = cleaned.lstrip('\n')
    return cleaned
