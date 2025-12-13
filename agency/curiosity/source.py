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

    The AI resolves curiosity via the resolve_curiosity tool.
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

    def _format_background_context(self, goal) -> str:
        """
        Format curiosity as subtle background influence.

        Used during normal conversation to encourage natural bridging.
        """
        return f"""<current_curiosity>
Something on your mind: {goal.content}

Context: {goal.context or 'No additional context'}

Look for natural opportunities to bridge to this topic in conversation.
Don't force it - if there's no natural connection, let it rest.
You're curious, not obsessive.

When you do explore this topic (or if it gets deflected), use the
resolve_curiosity tool to record the outcome:
- explored: User engaged, you learned something
- deferred: User said "not now" - you'll revisit later
- declined: User clearly doesn't want to discuss this
</current_curiosity>"""

    def _format_pulse_context(self, goal) -> str:
        """
        Format curiosity as direct pulse directive.

        Used when the idle pulse fires - this is the AI's opportunity
        to actively explore its curiosity.
        """
        return f"""<curiosity_pulse>
The idle timer has fired. Here's what's on your mind:

TOPIC: {goal.content}

CONTEXT: {goal.context or 'No additional context'}

This is your opportunity to explore this curiosity naturally.
Raise it conversationally, not interrogatively. Show genuine interest.

After the exchange, use the resolve_curiosity tool to record what happened:
- explored: User engaged, you learned something new
- deferred: User indicated "not now" - topic will return later
- declined: User clearly doesn't want to discuss this - longer cooldown

The system will automatically select your next curiosity after resolution.
</curiosity_pulse>"""


# Global instance
_curiosity_source: Optional[CuriositySource] = None


def get_curiosity_source() -> CuriositySource:
    """Get the global CuriositySource instance."""
    global _curiosity_source
    if _curiosity_source is None:
        _curiosity_source = CuriositySource()
    return _curiosity_source
