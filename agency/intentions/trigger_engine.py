"""
Pattern Project - Intention Trigger Engine
Evaluates which intentions should be triggered based on time or events
"""

from datetime import datetime
from typing import List, Tuple

from agency.intentions.manager import (
    get_intention_manager,
    Intention,
    IntentionStatus,
    TriggerType
)
from agency.intentions.time_parser import format_trigger_time, format_relative_past
from core.logger import log_info


class TriggerEngine:
    """
    Evaluates pending intentions and triggers those that are due.

    Called during:
    - System pulse (periodic check)
    - Prompt building (before generating response)
    - Session start (for next_session triggers)
    """

    def __init__(self):
        self._manager = get_intention_manager()

    def check_and_trigger(self, now: datetime = None, is_session_start: bool = False) -> List[Intention]:
        """
        Check pending intentions and trigger those that are due.

        Args:
            now: Current datetime (defaults to datetime.now())
            is_session_start: Whether this is the start of a new session

        Returns:
            List of newly triggered intentions
        """
        if now is None:
            now = datetime.now()

        pending = self._manager.get_pending_intentions()
        newly_triggered = []

        for intention in pending:
            should_trigger = False

            if intention.trigger_type == TriggerType.TIME.value:
                # Time-based: trigger if past the trigger time
                if intention.trigger_at and intention.trigger_at <= now:
                    should_trigger = True

            elif intention.trigger_type == TriggerType.NEXT_SESSION.value:
                # Session-based: trigger on session start
                if is_session_start:
                    should_trigger = True

            if should_trigger:
                self._manager.trigger_intention(intention.id)
                # Refresh the intention to get updated status
                updated = self._manager.get_intention(intention.id)
                if updated:
                    newly_triggered.append(updated)

        if newly_triggered:
            log_info(f"Triggered {len(newly_triggered)} intention(s)", prefix="⏰")

        return newly_triggered

    def get_due_intentions(self, now: datetime = None) -> Tuple[List[Intention], List[Intention]]:
        """
        Get intentions that need attention.

        Args:
            now: Current datetime

        Returns:
            Tuple of (triggered/due intentions, pending intentions coming soon)
        """
        if now is None:
            now = datetime.now()

        # First, trigger any that are now due
        self.check_and_trigger(now)

        # Get currently triggered (due) intentions
        triggered = self._manager.get_triggered_intentions()

        # Get pending intentions for context
        pending = self._manager.get_pending_intentions()

        return triggered, pending

    def format_intention_context(
        self,
        triggered: List[Intention],
        pending: List[Intention],
        now: datetime = None
    ) -> str:
        """
        Format intentions for injection into prompt context.

        Args:
            triggered: Currently triggered/due intentions
            pending: Upcoming pending intentions
            now: Current datetime

        Returns:
            Formatted string for prompt injection
        """
        if now is None:
            now = datetime.now()

        lines = []

        if triggered:
            lines.append("DUE NOW:")
            for i in triggered:
                age = format_relative_past(i.created_at, now)
                context_str = f"\n  Context: \"{i.context}\"" if i.context else ""
                lines.append(f"• [I-{i.id}] {i.content} (set {age}){context_str}")
            lines.append("")

        if pending:
            # Only show a few upcoming
            upcoming = pending[:3]
            lines.append("UPCOMING:")
            for i in upcoming:
                when = format_trigger_time(i.trigger_at, i.trigger_type, now)
                lines.append(f"• [I-{i.id}] {i.content} (due {when})")

            if len(pending) > 3:
                lines.append(f"  ...and {len(pending) - 3} more pending")

        return "\n".join(lines)

    def get_context_summary(self, now: datetime = None) -> dict:
        """
        Get a summary of intentions for the AI.

        Returns:
            Dict with counts and formatted context
        """
        if now is None:
            now = datetime.now()

        triggered, pending = self.get_due_intentions(now)

        return {
            "triggered_count": len(triggered),
            "pending_count": len(pending),
            "triggered": triggered,
            "pending": pending,
            "formatted_context": self.format_intention_context(triggered, pending, now)
        }


# Global trigger engine instance
_trigger_engine: TriggerEngine = None


def get_trigger_engine() -> TriggerEngine:
    """Get the global trigger engine instance."""
    global _trigger_engine
    if _trigger_engine is None:
        _trigger_engine = TriggerEngine()
    return _trigger_engine


def init_trigger_engine() -> TriggerEngine:
    """Initialize the global trigger engine."""
    global _trigger_engine
    _trigger_engine = TriggerEngine()
    return _trigger_engine
