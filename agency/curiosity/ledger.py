"""
Pattern Project - Curiosity Completion Ledger
Tracks goal lifecycle, status, and cooldowns.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Set

from core.database import get_database
from core.logger import log_info, log_error
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry
from agency.curiosity.analyzer import CuriosityCandidate

import config


class GoalStatus(Enum):
    """Status of a curiosity goal."""
    ACTIVE = "active"        # Currently being pursued
    EXPLORED = "explored"    # User engaged, learned something
    DEFERRED = "deferred"    # "Not now" - short cooldown
    DECLINED = "declined"    # User rejected - long cooldown


@dataclass
class CuriosityGoal:
    """
    A curiosity goal with its lifecycle state.

    Attributes:
        id: Database primary key
        content: The topic/question being explored
        category: Type of curiosity (dormant_revival, depth_seeking, fresh_discovery)
        context: Supporting context for natural bridging
        source_memory_id: Memory that spawned this goal
        status: Current lifecycle status
        activated_at: When this goal became active
        resolved_at: When this goal was resolved (if resolved)
        outcome_notes: Notes about what happened
        cooldown_until: When this topic can be revisited
        interaction_count: Number of exchanges on this topic
    """
    id: int
    content: str
    category: str
    context: Optional[str]
    source_memory_id: Optional[int]
    status: GoalStatus
    activated_at: datetime
    resolved_at: Optional[datetime]
    outcome_notes: Optional[str]
    cooldown_until: Optional[datetime]
    interaction_count: int = 0


class CuriosityLedger:
    """
    Manages curiosity goal persistence and cooldowns.

    Responsibilities:
    - Store and retrieve active/historical goals
    - Track cooldowns for resolved goals
    - Provide exclusion lists for analyzer
    """

    def __init__(self):
        self._lock_manager = get_lock_manager()

    @db_retry()
    def get_active_goal(self) -> Optional[CuriosityGoal]:
        """
        Get the current active curiosity goal.

        Returns:
            The active goal, or None if no goal is active
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                """
                SELECT * FROM curiosity_goals
                WHERE status = 'active'
                ORDER BY activated_at DESC
                LIMIT 1
                """,
                fetch=True
            )

            if not result:
                return None

            return self._row_to_goal(result[0])

    @db_retry()
    def activate_goal(self, candidate: CuriosityCandidate) -> CuriosityGoal:
        """
        Create a new active goal from a candidate.

        Args:
            candidate: The selected curiosity candidate

        Returns:
            The newly created CuriosityGoal
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            # Deactivate any existing active goals first
            db.execute(
                """
                UPDATE curiosity_goals
                SET status = 'declined',
                    resolved_at = ?,
                    outcome_notes = 'Superseded by new goal'
                WHERE status = 'active'
                """,
                (now.isoformat(),)
            )

            # Insert new goal
            db.execute(
                """
                INSERT INTO curiosity_goals
                (content, category, context, source_memory_id, status, activated_at)
                VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (
                    candidate.content,
                    candidate.category,
                    candidate.context,
                    candidate.source_memory_id if candidate.source_memory_id > 0 else None,
                    now.isoformat()
                )
            )

            # Get the inserted goal
            result = db.execute(
                "SELECT * FROM curiosity_goals ORDER BY id DESC LIMIT 1",
                fetch=True
            )

            goal = self._row_to_goal(result[0])
            log_info(f"Activated curiosity goal [{goal.id}]: {goal.content[:50]}...", prefix="🔍")
            return goal

    @db_retry()
    def resolve_goal(
        self,
        goal_id: int,
        status: GoalStatus,
        notes: Optional[str] = None
    ) -> None:
        """
        Mark a goal as resolved with appropriate cooldown.

        Args:
            goal_id: The goal to resolve
            status: Resolution status (explored, deferred, declined)
            notes: Optional notes about the outcome
        """
        if status == GoalStatus.ACTIVE:
            raise ValueError("Cannot resolve a goal to 'active' status")

        now = datetime.now()

        with self._lock_manager.acquire("database"):
            db = get_database()

            # Get current interaction count for scaled cooldown
            result = db.execute(
                "SELECT interaction_count FROM curiosity_goals WHERE id = ?",
                (goal_id,),
                fetch=True
            )
            interaction_count = result[0]["interaction_count"] if result else 0

            cooldown_hours = self._get_cooldown_hours(status, interaction_count)
            cooldown_until = now + timedelta(hours=cooldown_hours)

            db.execute(
                """
                UPDATE curiosity_goals
                SET status = ?,
                    resolved_at = ?,
                    outcome_notes = ?,
                    cooldown_until = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    now.isoformat(),
                    notes,
                    cooldown_until.isoformat(),
                    goal_id
                )
            )

            log_info(
                f"Resolved curiosity goal [{goal_id}] as {status.value} "
                f"(cooldown: {cooldown_hours}h, interactions: {interaction_count})",
                prefix="🔍"
            )

    @db_retry()
    def increment_interaction(self, goal_id: int) -> int:
        """
        Increment the interaction count for a goal.

        Called when an exchange occurs on the current curiosity topic.

        Args:
            goal_id: The goal to increment

        Returns:
            The new interaction count
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            db.execute(
                """
                UPDATE curiosity_goals
                SET interaction_count = interaction_count + 1
                WHERE id = ?
                """,
                (goal_id,)
            )

            result = db.execute(
                "SELECT interaction_count FROM curiosity_goals WHERE id = ?",
                (goal_id,),
                fetch=True
            )
            return result[0]["interaction_count"] if result else 0

    def get_interaction_count(self, goal_id: int) -> int:
        """
        Get the current interaction count for a goal.

        Args:
            goal_id: The goal to check

        Returns:
            The current interaction count
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT interaction_count FROM curiosity_goals WHERE id = ?",
                (goal_id,),
                fetch=True
            )
            return result[0]["interaction_count"] if result else 0

    @db_retry()
    def get_excluded_memory_ids(self) -> Set[int]:
        """
        Get memory IDs that are in cooldown.

        These should be excluded from candidate generation
        to prevent repetitive curiosity.

        Returns:
            Set of memory IDs to exclude
        """
        now = datetime.now()

        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                """
                SELECT DISTINCT source_memory_id
                FROM curiosity_goals
                WHERE source_memory_id IS NOT NULL
                AND (
                    status = 'active'
                    OR (cooldown_until IS NOT NULL AND cooldown_until > ?)
                )
                """,
                (now.isoformat(),),
                fetch=True
            )

            if not result:
                return set()

            return {row["source_memory_id"] for row in result if row["source_memory_id"]}

    @db_retry()
    def get_goal_history(self, limit: int = 20) -> List[CuriosityGoal]:
        """
        Get recent curiosity goal history.

        Args:
            limit: Maximum goals to return

        Returns:
            List of recent goals, most recent first
        """
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                """
                SELECT * FROM curiosity_goals
                ORDER BY activated_at DESC
                LIMIT ?
                """,
                (limit,),
                fetch=True
            )

            if not result:
                return []

            return [self._row_to_goal(row) for row in result]

    def _get_cooldown_hours(self, status: GoalStatus, interaction_count: int = 0) -> int:
        """
        Get cooldown hours for a status, scaled by interaction depth.

        For EXPLORED status, cooldown scales with interaction count:
        - More interactions = longer cooldown (topic was deeply explored)
        - Fewer interactions = shorter cooldown (barely touched)

        Args:
            status: Resolution status
            interaction_count: Number of exchanges on this topic

        Returns:
            Cooldown hours
        """
        if status == GoalStatus.EXPLORED:
            # Scaled cooldown based on interaction depth
            min_cooldown = getattr(config, 'CURIOSITY_COOLDOWN_EXPLORED_MIN', 4)
            max_cooldown = getattr(config, 'CURIOSITY_COOLDOWN_EXPLORED_MAX', 48)
            per_interaction = getattr(config, 'CURIOSITY_COOLDOWN_PER_INTERACTION', 8)

            cooldown = min_cooldown + (interaction_count * per_interaction)
            return min(cooldown, max_cooldown)
        elif status == GoalStatus.DEFERRED:
            return getattr(config, 'CURIOSITY_COOLDOWN_DEFERRED', 2)
        elif status == GoalStatus.DECLINED:
            return getattr(config, 'CURIOSITY_COOLDOWN_DECLINED', 72)
        else:
            return 24  # Default fallback

    def _row_to_goal(self, row) -> CuriosityGoal:
        """Convert a database row to a CuriosityGoal object."""
        def parse_datetime(value) -> Optional[datetime]:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)

        return CuriosityGoal(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            context=row["context"],
            source_memory_id=row["source_memory_id"],
            status=GoalStatus(row["status"]),
            activated_at=parse_datetime(row["activated_at"]) or datetime.now(),
            resolved_at=parse_datetime(row["resolved_at"]),
            outcome_notes=row["outcome_notes"],
            cooldown_until=parse_datetime(row["cooldown_until"]),
            interaction_count=row["interaction_count"] if "interaction_count" in row.keys() else 0
        )


# Global instance
_ledger: Optional[CuriosityLedger] = None


def get_curiosity_ledger() -> CuriosityLedger:
    """Get the global CuriosityLedger instance."""
    global _ledger
    if _ledger is None:
        _ledger = CuriosityLedger()
    return _ledger
