"""
Pattern Project - Curiosity Engine
Orchestrates the curiosity system components.
"""

from typing import Optional

from agency.curiosity.analyzer import get_curiosity_analyzer, CuriosityAnalyzer
from agency.curiosity.selector import get_curiosity_selector, CuriositySelector
from agency.curiosity.ledger import (
    get_curiosity_ledger,
    CuriosityLedger,
    CuriosityGoal,
    GoalStatus
)
from core.logger import log_info, log_error


class CuriosityEngine:
    """
    Orchestrates the curiosity system.

    The engine is the central coordinator that:
    1. Ensures there's always an active goal
    2. Handles goal resolution and rotation
    3. Provides the public API for the curiosity system

    Usage:
        engine = get_curiosity_engine()
        goal = engine.get_current_goal()  # Always returns a goal
        new_goal = engine.resolve_current_goal(GoalStatus.EXPLORED, "Discussed the topic")
    """

    def __init__(self):
        self._analyzer: CuriosityAnalyzer = get_curiosity_analyzer()
        self._selector: CuriositySelector = get_curiosity_selector()
        self._ledger: CuriosityLedger = get_curiosity_ledger()

    def get_current_goal(self) -> CuriosityGoal:
        """
        Get the current active curiosity goal.

        If no goal is active, automatically selects a new one.
        This method NEVER returns None - there is always a goal.

        Returns:
            The active CuriosityGoal
        """
        goal = self._ledger.get_active_goal()

        if goal is None:
            # No active goal - select a new one
            goal = self._select_new_goal()

        return goal

    def resolve_current_goal(
        self,
        status: GoalStatus,
        notes: Optional[str] = None
    ) -> CuriosityGoal:
        """
        Resolve the current goal and immediately select a new one.

        Args:
            status: How the goal was resolved (explored, deferred, declined)
            notes: Optional notes about the outcome

        Returns:
            The NEW active goal (not the resolved one)
        """
        current = self._ledger.get_active_goal()

        if current is not None:
            self._ledger.resolve_goal(current.id, status, notes)
            log_info(
                f"Curiosity resolved: {status.value} - {notes or 'no notes'}",
                prefix="🔍"
            )

        # Select and return new goal
        return self._select_new_goal()

    def _select_new_goal(self) -> CuriosityGoal:
        """
        Internal: Run the analysis and selection pipeline.

        Returns:
            The newly activated CuriosityGoal
        """
        # Get exclusions (memories in cooldown)
        exclusions = self._ledger.get_excluded_memory_ids()

        # Get candidates from analyzer
        candidates = self._analyzer.get_candidates(exclusions)

        # If no candidates, use fallback
        if not candidates:
            log_info("No curiosity candidates found, using fallback", prefix="🔍")
            fallback = self._analyzer.get_fallback_candidate()
            return self._ledger.activate_goal(fallback)

        # Select via weighted random
        selected = self._selector.select(candidates)

        # Activate and return
        return self._ledger.activate_goal(selected)

    def get_goal_history(self, limit: int = 20):
        """
        Get recent curiosity goal history.

        Args:
            limit: Maximum goals to return

        Returns:
            List of recent CuriosityGoal objects
        """
        return self._ledger.get_goal_history(limit)
