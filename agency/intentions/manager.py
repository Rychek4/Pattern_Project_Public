"""
Pattern Project - Intention Manager
CRUD operations for intentions (reminders, goals, plans)
"""

from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum

from core.database import get_database
from core.logger import log_info, log_error
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry
import config


class IntentionType(Enum):
    """Types of intentions the AI can create."""
    REMINDER = "reminder"  # Time-based follow-up
    GOAL = "goal"          # Ongoing objective


class IntentionStatus(Enum):
    """Lifecycle states for intentions."""
    PENDING = "pending"        # Not yet triggered
    TRIGGERED = "triggered"    # Due/active
    COMPLETED = "completed"    # Successfully fulfilled
    DISMISSED = "dismissed"    # Cancelled without completion


class TriggerType(Enum):
    """How the intention should trigger."""
    TIME = "time"              # At a specific datetime
    NEXT_SESSION = "next_session"  # When next conversation starts


@dataclass
class Intention:
    """
    An intention (reminder, goal) the AI has set.

    Attributes:
        id: Database primary key
        type: reminder, goal
        content: What to do/remember
        context: Why this was created
        trigger_type: time, next_session
        trigger_at: When to trigger (for time-based)
        status: pending, triggered, completed, dismissed
        priority: 1-10 (higher = more important)
        created_at: When the intention was created
        triggered_at: When it was triggered
        completed_at: When it was completed/dismissed
        outcome: Note about what happened
        source_session_id: Session where intention was created
    """
    id: int
    type: str
    content: str
    context: Optional[str]
    trigger_type: str
    trigger_at: Optional[datetime]
    status: str
    priority: int
    created_at: datetime
    triggered_at: Optional[datetime]
    completed_at: Optional[datetime]
    outcome: Optional[str]
    source_session_id: Optional[int]


class IntentionManager:
    """
    Manages intention lifecycle: create, query, update, complete.

    This is the AI's "planning memory" - forward-looking commitments
    that surface at the right time.
    """

    def __init__(self):
        self._lock_manager = get_lock_manager()

    def _emit_dev_update(self, event: str):
        """Emit intentions update to dev window if enabled."""
        if not config.DEV_MODE_ENABLED:
            return

        try:
            from interface.dev_window import emit_intentions_update

            # Get all active intentions
            intentions_list = []
            active = self.get_all_active_intentions()
            for intention in active:
                intentions_list.append({
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

            emit_intentions_update(intentions_list, event=event)
        except Exception:
            # Don't fail intention operations if dev window update fails
            pass

    @db_retry()
    def create_intention(
        self,
        intention_type: str,
        content: str,
        trigger_type: str,
        trigger_at: Optional[datetime] = None,
        context: Optional[str] = None,
        priority: int = 5,
        source_session_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Create a new intention.

        Args:
            intention_type: 'reminder' or 'goal'
            content: What to do/remember
            trigger_type: 'time' or 'next_session'
            trigger_at: When to trigger (required for time-based)
            context: Why this intention exists
            priority: 1-10 importance
            source_session_id: Session where this was created

        Returns:
            The new intention ID, or None if creation failed
        """
        # Validate type
        if intention_type not in [t.value for t in IntentionType]:
            log_error(f"Invalid intention type: {intention_type}")
            return None

        # Validate trigger_type
        if trigger_type not in [t.value for t in TriggerType]:
            log_error(f"Invalid trigger type: {trigger_type}")
            return None

        # Time-based requires trigger_at
        if trigger_type == TriggerType.TIME.value and trigger_at is None:
            log_error("Time-based intentions require trigger_at")
            return None

        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            db.execute(
                """
                INSERT INTO intentions
                (type, content, context, trigger_type, trigger_at, status, priority,
                 created_at, source_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intention_type,
                    content,
                    context,
                    trigger_type,
                    trigger_at.isoformat() if trigger_at else None,
                    IntentionStatus.PENDING.value,
                    priority,
                    now.isoformat(),
                    source_session_id
                )
            )

            result = db.execute(
                "SELECT id FROM intentions ORDER BY id DESC LIMIT 1",
                fetch=True
            )

            intention_id = result[0]["id"] if result else None

            if intention_id:
                log_info(f"Created intention [{intention_id}]: {content[:50]}...", prefix="💭")
                self._emit_dev_update("created")

            return intention_id

    @db_retry()
    def get_intention(self, intention_id: int) -> Optional[Intention]:
        """Get a specific intention by ID."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM intentions WHERE id = ?",
                (intention_id,),
                fetch=True
            )

            if result:
                return self._row_to_intention(result[0])
            return None

    @db_retry()
    def get_pending_intentions(self) -> List[Intention]:
        """Get all pending (not yet triggered) intentions."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM intentions WHERE status = ? ORDER BY priority DESC, created_at ASC",
                (IntentionStatus.PENDING.value,),
                fetch=True
            )

            return [self._row_to_intention(row) for row in result] if result else []

    @db_retry()
    def get_triggered_intentions(self) -> List[Intention]:
        """Get all triggered (due) intentions."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM intentions WHERE status = ? ORDER BY priority DESC, triggered_at ASC",
                (IntentionStatus.TRIGGERED.value,),
                fetch=True
            )

            return [self._row_to_intention(row) for row in result] if result else []

    @db_retry()
    def get_all_active_intentions(self) -> List[Intention]:
        """Get all pending and triggered intentions."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                """
                SELECT * FROM intentions
                WHERE status IN (?, ?)
                ORDER BY
                    CASE status WHEN 'triggered' THEN 0 ELSE 1 END,
                    priority DESC,
                    created_at ASC
                """,
                (IntentionStatus.PENDING.value, IntentionStatus.TRIGGERED.value),
                fetch=True
            )

            return [self._row_to_intention(row) for row in result] if result else []

    @db_retry()
    def trigger_intention(self, intention_id: int) -> bool:
        """
        Mark an intention as triggered (due).

        Args:
            intention_id: The intention to trigger

        Returns:
            True if successful
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            db.execute(
                """
                UPDATE intentions
                SET status = ?, triggered_at = ?
                WHERE id = ? AND status = ?
                """,
                (IntentionStatus.TRIGGERED.value, now.isoformat(), intention_id, IntentionStatus.PENDING.value)
            )

            log_info(f"Triggered intention [{intention_id}]", prefix="⏰")
            self._emit_dev_update("triggered")
            return True

    @db_retry()
    def complete_intention(self, intention_id: int, outcome: Optional[str] = None) -> bool:
        """
        Mark an intention as completed.

        Args:
            intention_id: The intention to complete
            outcome: Note about what happened

        Returns:
            True if successful
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            db.execute(
                """
                UPDATE intentions
                SET status = ?, completed_at = ?, outcome = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    IntentionStatus.COMPLETED.value,
                    now.isoformat(),
                    outcome,
                    intention_id,
                    IntentionStatus.PENDING.value,
                    IntentionStatus.TRIGGERED.value
                )
            )

            log_info(f"Completed intention [{intention_id}]", prefix="✓")
            self._emit_dev_update("completed")
            return True

    @db_retry()
    def dismiss_intention(self, intention_id: int) -> bool:
        """
        Dismiss an intention without completing it.

        Args:
            intention_id: The intention to dismiss

        Returns:
            True if successful
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            db.execute(
                """
                UPDATE intentions
                SET status = ?, completed_at = ?
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    IntentionStatus.DISMISSED.value,
                    now.isoformat(),
                    intention_id,
                    IntentionStatus.PENDING.value,
                    IntentionStatus.TRIGGERED.value
                )
            )

            log_info(f"Dismissed intention [{intention_id}]", prefix="✗")
            self._emit_dev_update("dismissed")
            return True

    @db_retry()
    def get_intention_count(self, status: Optional[str] = None) -> int:
        """Get count of intentions, optionally filtered by status."""
        with self._lock_manager.acquire("database"):
            db = get_database()

            if status:
                result = db.execute(
                    "SELECT COUNT(*) as count FROM intentions WHERE status = ?",
                    (status,),
                    fetch=True
                )
            else:
                result = db.execute(
                    "SELECT COUNT(*) as count FROM intentions",
                    fetch=True
                )

            return result[0]["count"] if result else 0

    def _row_to_intention(self, row) -> Intention:
        """Convert a database row to an Intention object."""
        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)

        return Intention(
            id=row["id"],
            type=row["type"],
            content=row["content"],
            context=row["context"],
            trigger_type=row["trigger_type"],
            trigger_at=parse_datetime(row["trigger_at"]),
            status=row["status"],
            priority=row["priority"],
            created_at=parse_datetime(row["created_at"]),
            triggered_at=parse_datetime(row["triggered_at"]),
            completed_at=parse_datetime(row["completed_at"]),
            outcome=row["outcome"],
            source_session_id=row["source_session_id"]
        )


# Global manager instance
_intention_manager: Optional[IntentionManager] = None


def get_intention_manager() -> IntentionManager:
    """Get the global intention manager instance."""
    global _intention_manager
    if _intention_manager is None:
        _intention_manager = IntentionManager()
    return _intention_manager


def init_intention_manager() -> IntentionManager:
    """Initialize the global intention manager."""
    global _intention_manager
    _intention_manager = IntentionManager()
    return _intention_manager
