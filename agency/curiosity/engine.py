"""
Pattern Project - Curiosity Engine
Orchestrates the curiosity system components.
"""

from typing import Optional

from agency.curiosity.analyzer import get_curiosity_analyzer, CuriosityAnalyzer, CuriosityCandidate
from agency.curiosity.selector import get_curiosity_selector, CuriositySelector
from agency.curiosity.ledger import (
    get_curiosity_ledger,
    CuriosityLedger,
    CuriosityGoal,
    GoalStatus
)
from core.logger import log_info, log_error
from interface.process_panel import get_process_event_bus, ProcessEventType
import config


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
            self._emit_dev_update("activated", goal)

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
        new_goal = self._select_new_goal()
        self._emit_dev_update("resolved", new_goal)
        return new_goal

    def resolve_current_goal_with_next(
        self,
        status: GoalStatus,
        notes: Optional[str] = None,
        next_topic: str = None
    ) -> CuriosityGoal:
        """
        Resolve the current goal and activate an AI-specified next topic.

        This allows the AI to follow conversational flow by specifying
        what to be curious about next, rather than letting the system
        auto-select from memory candidates.

        Args:
            status: How the goal was resolved (explored, deferred, declined)
            notes: Optional notes about the outcome
            next_topic: The AI-specified next curiosity topic

        Returns:
            The NEW active goal (the AI-specified topic)
        """
        current = self._ledger.get_active_goal()

        if current is not None:
            self._ledger.resolve_goal(current.id, status, notes)
            log_info(
                f"Curiosity resolved: {status.value} - {notes or 'no notes'}",
                prefix="🔍"
            )

        # Create candidate from AI-specified topic
        ai_candidate = CuriosityCandidate(
            content=next_topic,
            source_memory_id=0,  # No source memory - AI discovered this
            weight=1.0,
            category="fresh_discovery",  # AI discoveries are always fresh
            context=f"Discovered during conversation: {notes or 'No context'}",
            last_discussed=None,
            importance=0.8  # High importance - AI chose this deliberately
        )

        # Activate directly (bypass analyzer/selector pipeline)
        new_goal = self._ledger.activate_goal(ai_candidate)
        self._emit_dev_update("ai_specified", new_goal)
        self._emit_curiosity_event(new_goal)

        log_info(f"AI-specified curiosity activated: {next_topic[:50]}...", prefix="🔍")
        return new_goal

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
            goal = self._ledger.activate_goal(fallback)
            self._emit_curiosity_event(goal)
            return goal

        # Select via weighted random
        selected = self._selector.select(candidates)

        # Activate and return
        goal = self._ledger.activate_goal(selected)
        self._emit_curiosity_event(goal)
        return goal

    def get_goal_history(self, limit: int = 20):
        """
        Get recent curiosity goal history.

        Args:
            limit: Maximum goals to return

        Returns:
            List of recent CuriosityGoal objects
        """
        return self._ledger.get_goal_history(limit)

    def _emit_dev_update(self, event: str, goal: CuriosityGoal) -> None:
        """Emit curiosity update to dev window."""
        if not config.DEV_MODE_ENABLED:
            return

        try:
            from interface.dev_window import emit_curiosity_update, get_dev_window

            # Check if dev window is initialized
            dev_window = get_dev_window()
            if not dev_window:
                log_info(f"Curiosity emit skipped: dev window not initialized (event={event})", prefix="🔍")
                return

            # Build goal dict
            goal_dict = {
                "id": goal.id,
                "content": goal.content,
                "category": goal.category,
                "context": goal.context,
                "activated_at": goal.activated_at.isoformat() if goal.activated_at else ""
            }

            # Get recent history
            history = self._ledger.get_goal_history(limit=5)
            history_dicts = []
            for h in history:
                if h.status.value != "active":
                    history_dicts.append({
                        "id": h.id,
                        "content": h.content,
                        "status": h.status.value,
                        "resolved_at": h.resolved_at.isoformat() if h.resolved_at else ""
                    })

            # Get cooldowns
            excluded = self._ledger.get_excluded_memory_ids()
            cooldown_dicts = [{"memory_id": mid, "expires_at": "in cooldown"} for mid in list(excluded)[:10]]

            emit_curiosity_update(
                current_goal=goal_dict,
                history=history_dicts,
                cooldowns=cooldown_dicts,
                event=event
            )
            log_info(f"Curiosity DEV update emitted: event={event}, goal_id={goal.id}", prefix="🔍")
        except Exception as e:
            log_info(f"Failed to emit dev curiosity update: {e}", prefix="🔍")

    def _emit_curiosity_event(self, goal: CuriosityGoal) -> None:
        """Emit curiosity selection to the process panel."""
        try:
            get_process_event_bus().emit_event(
                ProcessEventType.CURIOSITY_SELECTED,
                detail=goal.content[:80] if goal.content else "",
                origin="isaac"
            )
        except Exception:
            pass  # Process panel may not be initialized yet
