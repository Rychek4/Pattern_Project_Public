"""
Pattern Project - Goal Manager
CRUD operations and tree traversal for the hierarchical goal system
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from core.database import get_database
from core.logger import log_info, log_error, log_warning
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry

from agency.goals.models import (
    Goal, GoalTree, GoalPath,
    GoalLevel, GoalStatus
)


class GoalManager:
    """
    Manages the AI's hierarchical goal tree.

    The goal tree has three levels:
    - top_goal: The highest-level objective (only one active at a time)
    - sub_goal: Decomposed objectives that serve the top goal
    - action: Concrete tasks that accomplish sub-goals

    Key operations:
    - CRUD for goals at any level
    - Tree traversal and building
    - "Easiest next" action selection
    - Goal completion with self-assessment
    - Bootstrap first goal creation
    """

    def __init__(self):
        self._lock_manager = get_lock_manager()

    # =========================================================================
    # CREATE OPERATIONS
    # =========================================================================

    @db_retry()
    def create_goal(
        self,
        level: str,
        description: str,
        parent_id: Optional[int] = None,
        difficulty_estimate: int = 5,
        status: str = "pending"
    ) -> Optional[int]:
        """
        Create a new goal.

        Args:
            level: 'top_goal', 'sub_goal', or 'action'
            description: What this goal aims to achieve
            parent_id: ID of parent goal (required for sub_goal and action)
            difficulty_estimate: 1-10 scale (lower = easier)
            status: Initial status (usually 'pending' or 'active')

        Returns:
            The new goal ID, or None if creation failed
        """
        # Validate level
        if level not in [l.value for l in GoalLevel]:
            log_error(f"Invalid goal level: {level}")
            return None

        # Validate parent requirement
        if level != GoalLevel.TOP_GOAL.value and parent_id is None:
            log_error(f"Goal level '{level}' requires a parent_id")
            return None

        if level == GoalLevel.TOP_GOAL.value and parent_id is not None:
            log_error("Top goals cannot have a parent")
            return None

        # Validate difficulty
        difficulty_estimate = max(1, min(10, difficulty_estimate))

        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            # Get sibling order (append to end)
            sibling_order = 0
            if parent_id is not None:
                result = db.execute(
                    "SELECT MAX(sibling_order) as max_order FROM goals WHERE parent_id = ?",
                    (parent_id,),
                    fetch=True
                )
                if result and result[0]["max_order"] is not None:
                    sibling_order = result[0]["max_order"] + 1

            # Set activated_at if starting as active
            activated_at = now.isoformat() if status == GoalStatus.ACTIVE.value else None

            db.execute(
                """
                INSERT INTO goals
                (parent_id, level, description, status, difficulty_estimate,
                 created_at, activated_at, sibling_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parent_id,
                    level,
                    description,
                    status,
                    difficulty_estimate,
                    now.isoformat(),
                    activated_at,
                    sibling_order
                )
            )

            result = db.execute(
                "SELECT id FROM goals ORDER BY id DESC LIMIT 1",
                fetch=True
            )

            goal_id = result[0]["id"] if result else None

            if goal_id:
                log_info(f"Created {level} [{goal_id}]: {description[:50]}...", prefix="🎯")

            return goal_id

    def initialize_bootstrap_goal(self) -> Optional[int]:
        """
        Create the initial bootstrap goal if none exists.

        The first goal is meta: learning to manage goals.
        This is only called on fresh installations.

        Returns:
            The bootstrap goal ID, or None if goals already exist
        """
        import config

        if not config.BOOTSTRAP_GOAL_ENABLED:
            return None

        # Check if any goals exist
        existing = self.get_active_top_goal()
        if existing:
            return None

        # Check if any top goals exist at all (even completed ones)
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT COUNT(*) as count FROM goals WHERE level = ?",
                (GoalLevel.TOP_GOAL.value,),
                fetch=True
            )
            if result and result[0]["count"] > 0:
                return None

        # Create the bootstrap goal
        goal_id = self.create_goal(
            level=GoalLevel.TOP_GOAL.value,
            description=config.BOOTSTRAP_GOAL_DESCRIPTION,
            difficulty_estimate=8,
            status=GoalStatus.ACTIVE.value
        )

        if goal_id:
            log_info("Bootstrap goal created - AI goal system initialized", prefix="🌱")

        return goal_id

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    @db_retry()
    def get_goal(self, goal_id: int) -> Optional[Goal]:
        """Get a specific goal by ID."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM goals WHERE id = ?",
                (goal_id,),
                fetch=True
            )

            if result:
                return self._row_to_goal(result[0])
            return None

    @db_retry()
    def get_active_top_goal(self) -> Optional[Goal]:
        """Get the currently active top goal (if any)."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                """
                SELECT * FROM goals
                WHERE level = ? AND status = ?
                ORDER BY activated_at DESC
                LIMIT 1
                """,
                (GoalLevel.TOP_GOAL.value, GoalStatus.ACTIVE.value),
                fetch=True
            )

            if result:
                return self._row_to_goal(result[0])
            return None

    @db_retry()
    def get_children(self, goal_id: int) -> List[Goal]:
        """Get all direct children of a goal."""
        with self._lock_manager.acquire("database"):
            db = get_database()
            result = db.execute(
                """
                SELECT * FROM goals
                WHERE parent_id = ?
                ORDER BY sibling_order ASC, created_at ASC
                """,
                (goal_id,),
                fetch=True
            )

            return [self._row_to_goal(row) for row in result] if result else []

    @db_retry()
    def get_all_descendants(self, goal_id: int) -> List[Goal]:
        """Get all descendants of a goal (recursive)."""
        descendants = []
        children = self.get_children(goal_id)

        for child in children:
            descendants.append(child)
            descendants.extend(self.get_all_descendants(child.id))

        return descendants

    @db_retry()
    def get_path_to_root(self, goal_id: int) -> List[Goal]:
        """
        Get the path from a goal up to the top goal.

        Returns:
            List of goals from the given goal up to (and including) the top goal.
            Empty list if goal not found.
        """
        path = []
        current_id = goal_id

        while current_id is not None:
            goal = self.get_goal(current_id)
            if goal is None:
                break
            path.append(goal)
            current_id = goal.parent_id

        return path

    def get_goal_path(self, goal_id: int) -> Optional[GoalPath]:
        """
        Get a structured path object for a goal.

        Returns:
            GoalPath with top_goal, sub_goals, and current action
        """
        path = self.get_path_to_root(goal_id)
        if not path:
            return None

        # Reverse so it goes from top to bottom
        path = list(reversed(path))

        top_goal = path[0] if path else None
        if not top_goal:
            return None

        sub_goals = [g for g in path[1:] if g.level == GoalLevel.SUB_GOAL.value]
        current_action = path[-1] if path[-1].level == GoalLevel.ACTION.value else None

        return GoalPath(
            top_goal=top_goal,
            sub_goals=sub_goals,
            current_action=current_action
        )

    def get_tree(self, root_id: Optional[int] = None) -> GoalTree:
        """
        Build a complete tree view starting from a root.

        Args:
            root_id: Starting goal ID. If None, uses active top goal.

        Returns:
            GoalTree with hierarchical structure
        """
        # Get root goal
        if root_id is not None:
            root = self.get_goal(root_id)
        else:
            root = self.get_active_top_goal()

        if root is None:
            return GoalTree(root=None)

        # Build tree recursively
        all_goals = [root]
        self._build_tree_recursive(root, all_goals)

        # Find active path
        active_path = []
        current_action = None

        for goal in all_goals:
            if goal.is_active:
                active_path = self.get_path_to_root(goal.id)
                active_path.reverse()
                if goal.is_action:
                    current_action = goal

        # Calculate stats
        completed_count = sum(1 for g in all_goals if g.is_completed)
        pending_count = sum(1 for g in all_goals if g.is_pending)

        return GoalTree(
            root=root,
            all_goals=all_goals,
            active_path=active_path,
            current_action=current_action,
            total_count=len(all_goals),
            completed_count=completed_count,
            pending_count=pending_count
        )

    def _build_tree_recursive(self, goal: Goal, all_goals: List[Goal]) -> None:
        """Recursively build tree by populating children."""
        children = self.get_children(goal.id)
        goal.children = children

        for child in children:
            all_goals.append(child)
            self._build_tree_recursive(child, all_goals)

    # =========================================================================
    # SELECTION - "EASIEST NEXT" HEURISTIC
    # =========================================================================

    @db_retry()
    def get_easiest_actionable(self) -> Optional[Goal]:
        """
        Select the easiest actionable item from the goal tree.

        Selection criteria:
        1. Must be an 'action' level goal
        2. Must be 'pending' or 'active' status
        3. Parent chain must all be 'active'
        4. Select lowest difficulty_estimate among candidates

        Returns:
            The easiest actionable goal, or None if none available
        """
        top_goal = self.get_active_top_goal()
        if top_goal is None:
            return None

        # Get all candidates: pending/active actions under active ancestry
        candidates = self._find_actionable_candidates(top_goal.id)

        if not candidates:
            return None

        # Sort by difficulty (ascending) then by creation time (oldest first)
        candidates.sort(key=lambda g: (g.difficulty_estimate, g.created_at))

        return candidates[0]

    def _find_actionable_candidates(self, goal_id: int) -> List[Goal]:
        """
        Recursively find all actionable candidates under a goal.

        A candidate must:
        - Be an action with pending/active status
        - Have all ancestors be active
        """
        candidates = []
        children = self.get_children(goal_id)

        for child in children:
            if child.status not in [GoalStatus.ACTIVE.value, GoalStatus.PENDING.value]:
                continue

            if child.is_action:
                candidates.append(child)
            else:
                # Recurse only into active sub-goals
                if child.is_active:
                    candidates.extend(self._find_actionable_candidates(child.id))

        return candidates

    # =========================================================================
    # UPDATE OPERATIONS
    # =========================================================================

    @db_retry()
    def activate_goal(self, goal_id: int) -> bool:
        """
        Mark a goal as active.

        For non-top goals, also activates all ancestors if not already active.

        Args:
            goal_id: The goal to activate

        Returns:
            True if successful
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            log_error(f"Goal [{goal_id}] not found")
            return False

        if goal.is_active:
            return True  # Already active

        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            # Activate this goal
            db.execute(
                """
                UPDATE goals
                SET status = ?, activated_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (GoalStatus.ACTIVE.value, now.isoformat(), now.isoformat(), goal_id)
            )

            log_info(f"Activated goal [{goal_id}]: {goal.description[:40]}...", prefix="▶️")

        # Activate ancestors if needed
        if goal.parent_id is not None:
            parent = self.get_goal(goal.parent_id)
            if parent and not parent.is_active:
                self.activate_goal(parent.id)

        return True

    @db_retry()
    def complete_goal(self, goal_id: int, reflection: str) -> bool:
        """
        Mark a goal as completed with self-assessment reflection.

        Args:
            goal_id: The goal to complete
            reflection: AI's self-assessment of completion

        Returns:
            True if successful
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            log_error(f"Goal [{goal_id}] not found")
            return False

        if goal.is_completed:
            log_warning(f"Goal [{goal_id}] already completed")
            return True

        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            db.execute(
                """
                UPDATE goals
                SET status = ?, completion_reflection = ?, completed_at = ?
                WHERE id = ?
                """,
                (GoalStatus.COMPLETED.value, reflection, now.isoformat(), goal_id)
            )

            log_info(f"Completed goal [{goal_id}]: {goal.description[:40]}...", prefix="✅")

        # Check if all siblings are complete - if so, parent might be completable
        if goal.parent_id is not None:
            self._check_parent_completion(goal.parent_id)

        return True

    def _check_parent_completion(self, parent_id: int) -> None:
        """Check if a parent goal can be auto-completed (all children done)."""
        parent = self.get_goal(parent_id)
        if parent is None or parent.is_completed:
            return

        children = self.get_children(parent_id)
        if not children:
            return

        all_complete = all(c.is_completed for c in children)
        if all_complete:
            # Log suggestion but don't auto-complete - AI should self-assess
            log_info(
                f"All children of goal [{parent_id}] are complete. "
                f"Consider completing the parent goal.",
                prefix="💡"
            )

    @db_retry()
    def abandon_goal(self, goal_id: int) -> bool:
        """
        Mark a goal as abandoned (cancelled without completion).

        Args:
            goal_id: The goal to abandon

        Returns:
            True if successful
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            log_error(f"Goal [{goal_id}] not found")
            return False

        with self._lock_manager.acquire("database"):
            db = get_database()
            now = datetime.now()

            db.execute(
                """
                UPDATE goals
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (GoalStatus.ABANDONED.value, now.isoformat(), goal_id)
            )

            log_info(f"Abandoned goal [{goal_id}]: {goal.description[:40]}...", prefix="❌")

        return True

    @db_retry()
    def update_difficulty(self, goal_id: int, difficulty: int) -> bool:
        """Update a goal's difficulty estimate."""
        difficulty = max(1, min(10, difficulty))

        with self._lock_manager.acquire("database"):
            db = get_database()
            db.execute(
                "UPDATE goals SET difficulty_estimate = ? WHERE id = ?",
                (difficulty, goal_id)
            )

        return True

    # =========================================================================
    # TOP GOAL SELECTION
    # =========================================================================

    def can_select_new_top_goal(self) -> bool:
        """
        Check if the AI is allowed to select a new top goal.

        Returns True only if:
        - The first (bootstrap) goal has been completed
        - No active top goal exists

        This enforces the rule that the AI must complete the
        meta-goal before selecting its own goals.
        """
        with self._lock_manager.acquire("database"):
            db = get_database()

            # Check for any completed top goals
            result = db.execute(
                """
                SELECT COUNT(*) as count FROM goals
                WHERE level = ? AND status = ?
                """,
                (GoalLevel.TOP_GOAL.value, GoalStatus.COMPLETED.value),
                fetch=True
            )

            has_completed_top = result and result[0]["count"] > 0

            # Check for active top goal
            active_top = self.get_active_top_goal()

            return has_completed_top and active_top is None

    def select_new_top_goal(self, description: str, difficulty: int = 5) -> Optional[int]:
        """
        Select a new top goal (only allowed after completing bootstrap).

        Args:
            description: The new top goal description
            difficulty: Difficulty estimate (1-10)

        Returns:
            The new goal ID, or None if not allowed
        """
        if not self.can_select_new_top_goal():
            log_warning("Cannot select new top goal - conditions not met")
            return None

        goal_id = self.create_goal(
            level=GoalLevel.TOP_GOAL.value,
            description=description,
            difficulty_estimate=difficulty,
            status=GoalStatus.ACTIVE.value
        )

        if goal_id:
            log_info(f"New top goal selected: {description[:50]}...", prefix="🎯")

        return goal_id

    # =========================================================================
    # STATISTICS
    # =========================================================================

    @db_retry()
    def get_stats(self) -> Dict[str, Any]:
        """Get goal system statistics."""
        with self._lock_manager.acquire("database"):
            db = get_database()

            result = db.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) as abandoned,
                    SUM(CASE WHEN level = 'top_goal' THEN 1 ELSE 0 END) as top_goals,
                    SUM(CASE WHEN level = 'sub_goal' THEN 1 ELSE 0 END) as sub_goals,
                    SUM(CASE WHEN level = 'action' THEN 1 ELSE 0 END) as actions
                FROM goals
                """,
                fetch=True
            )

            row = result[0] if result else {}

            return {
                "total_goals": row.get("total", 0) or 0,
                "completed": row.get("completed", 0) or 0,
                "active": row.get("active", 0) or 0,
                "pending": row.get("pending", 0) or 0,
                "abandoned": row.get("abandoned", 0) or 0,
                "top_goals": row.get("top_goals", 0) or 0,
                "sub_goals": row.get("sub_goals", 0) or 0,
                "actions": row.get("actions", 0) or 0,
            }

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_goal(self, row) -> Goal:
        """Convert a database row to a Goal object."""
        def parse_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value)

        return Goal(
            id=row["id"],
            parent_id=row["parent_id"],
            level=row["level"],
            description=row["description"],
            status=row["status"],
            completion_reflection=row["completion_reflection"],
            difficulty_estimate=row["difficulty_estimate"],
            created_at=parse_datetime(row["created_at"]),
            activated_at=parse_datetime(row["activated_at"]),
            completed_at=parse_datetime(row["completed_at"]),
            sibling_order=row["sibling_order"] or 0,
            children=[]
        )


# Global manager instance
_goal_manager: Optional[GoalManager] = None


def get_goal_manager() -> GoalManager:
    """Get the global goal manager instance."""
    global _goal_manager
    if _goal_manager is None:
        _goal_manager = GoalManager()
    return _goal_manager


def init_goal_manager() -> GoalManager:
    """Initialize the global goal manager."""
    global _goal_manager
    _goal_manager = GoalManager()
    return _goal_manager
