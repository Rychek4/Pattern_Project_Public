"""
Pattern Project - Curiosity Context Source
Injects curiosity goals into all AI prompts.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info

import config


# Priority: after active thoughts (18), before intentions (22)
# Curiosity is part of the AI's internal state
CURIOSITY_PRIORITY = 20


class CuriositySource(ContextSource):
    """
    Injects the AI's current curiosity goal into every prompt.

    The curiosity goal is always present (when system enabled) and
    influences all responses:

    - During normal conversation: Background context encouraging
      the AI to find natural bridges to the curiosity topic

    - During pulse (idle): Foreground directive to explore the
      curiosity topic directly

    The AI resolves curiosity via the advance_curiosity tool with an outcome.
    """

    @property
    def source_name(self) -> str:
        return "curiosity"

    @property
    def priority(self) -> int:
        return CURIOSITY_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Get curiosity context for prompt injection.

        Always returns context when enabled. Content varies based on
        whether this is a pulse trigger or normal conversation.
        """
        if not getattr(config, 'CURIOSITY_ENABLED', True):
            return None

        try:
            from agency.curiosity import get_curiosity_engine

            engine = get_curiosity_engine()
            goal = engine.get_current_goal()

            # Check if this is a pulse trigger
            is_pulse = session_context.get("is_pulse", False)

            if is_pulse:
                content = self._format_pulse_context(goal)
            else:
                content = self._format_background_context(goal)

            # Store goal info in session context for other sources
            session_context["curiosity_goal_id"] = goal.id
            session_context["curiosity_goal_content"] = goal.content

            # Emit to DEV window so current curiosity is visible during conversations
            self._emit_dev_update(goal, is_pulse)

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=True,
                metadata={
                    "goal_id": goal.id,
                    "goal_category": goal.category,
                    "is_pulse": is_pulse
                }
            )

        except Exception as e:
            log_info(f"CuriositySource error: {e}", prefix="🔍")
            return None

    def _emit_dev_update(self, goal, is_pulse: bool) -> None:
        """Emit curiosity state to DEV window during prompt build."""
        if not config.DEV_MODE_ENABLED:
            return

        try:
            from interface.dev_window import emit_curiosity_update

            goal_dict = {
                "id": goal.id,
                "content": goal.content,
                "category": goal.category,
                "context": goal.context,
                "activated_at": goal.activated_at.isoformat() if goal.activated_at else ""
            }

            # Use different event types for pulse vs normal conversation
            event = "pulse_inject" if is_pulse else "context_inject"

            emit_curiosity_update(
                current_goal=goal_dict,
                history=[],  # Don't fetch history on every prompt - too expensive
                cooldowns=[],
                event=event
            )
        except Exception:
            # Don't let DEV window issues break prompt building
            pass

    def _format_background_context(self, goal) -> str:
        """
        Format curiosity as subtle background influence.

        Used during normal conversation to encourage natural bridging.
        """
        return f"""<current_curiosity>
Topic: {goal.content}
Context: {goal.context or 'None'}

When explored, use advance_curiosity: explored/deferred/declined.
If conversation flows to a new topic, add next_topic.
</current_curiosity>"""

    def _format_pulse_context(self, goal) -> str:
        """
        Format curiosity as direct pulse directive.

        Used when the idle pulse fires - this is the AI's opportunity
        to actively explore its curiosity.
        """
        return f"""<curiosity_pulse>
Idle pulse fired. Topic on your mind:

TOPIC: {goal.content}
CONTEXT: {goal.context or 'None'}

This is your moment to explore. Use tools if helpful (web search, journal, reminders).

After the exchange, use advance_curiosity: explored/deferred/declined.
If conversation flows to a new topic, add next_topic.
</curiosity_pulse>"""


# Global instance
_curiosity_source: Optional[CuriositySource] = None


def get_curiosity_source() -> CuriositySource:
    """Get the global CuriositySource instance."""
    global _curiosity_source
    if _curiosity_source is None:
        _curiosity_source = CuriositySource()
    return _curiosity_source
