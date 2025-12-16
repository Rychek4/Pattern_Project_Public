"""
Pattern Project - Intention Context Source
Injects AI intentions (reminders, goals) into prompts
"""

from typing import Optional, Dict, Any
from datetime import datetime

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.logger import log_info


# Priority for intentions: after core memory, before AI commands
# This ensures the AI sees its intentions early in context
INTENTION_PRIORITY = 22


class IntentionSource(ContextSource):
    """
    Provides the AI with awareness of its own intentions.

    This is the AI's "forward-looking memory" - things it has
    committed to follow up on, goals it's working toward.

    The intentions are private - the user doesn't see them,
    but the AI knows they're hidden and acts on them naturally.
    """

    @property
    def source_name(self) -> str:
        return "intentions"

    @property
    def priority(self) -> int:
        return INTENTION_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get intention context for prompt injection."""
        from agency.intentions import get_trigger_engine

        try:
            engine = get_trigger_engine()
            now = datetime.now()

            # Check if this is a session start (for next_session triggers)
            is_session_start = session_context.get("is_session_start", False)
            if is_session_start:
                engine.check_and_trigger(now, is_session_start=True)

            # Get current intention state
            summary = engine.get_context_summary(now)

            triggered_count = summary["triggered_count"]
            pending_count = summary["pending_count"]

            # If no intentions at all, return minimal context
            if triggered_count == 0 and pending_count == 0:
                return ContextBlock(
                    source_name=self.source_name,
                    content=self._build_empty_context(),
                    priority=self.priority,
                    include_always=True,
                    metadata={
                        "triggered_count": 0,
                        "pending_count": 0,
                    }
                )

            # Build full intention context
            content = self._build_context(summary, now)

            # Store in session context for other sources
            session_context["intention_triggered_count"] = triggered_count
            session_context["intention_pending_count"] = pending_count

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=True,
                metadata={
                    "triggered_count": triggered_count,
                    "pending_count": pending_count,
                    "triggered_ids": [i.id for i in summary["triggered"]],
                    "pending_ids": [i.id for i in summary["pending"]],
                }
            )

        except Exception as e:
            log_info(f"IntentionSource error: {e}")
            return None

    def _build_empty_context(self) -> str:
        """Build context when there are no intentions."""
        return "<your_intentions>None active. Use [[REMIND: when | what]] to create reminders.</your_intentions>"

    def _build_context(self, summary: dict, now: datetime) -> str:
        """Build context with active intentions."""
        lines = [
            "<your_intentions>",
            "These are your private intentions — the user cannot see them.",
            "",
        ]

        # Add the formatted intention list
        if summary["formatted_context"]:
            lines.append(summary["formatted_context"])
            lines.append("")

        # Add total count
        total = summary["triggered_count"] + summary["pending_count"]
        lines.append(f"You have {total} active intention{'s' if total != 1 else ''}.")
        lines.append("")

        # Add command instructions
        lines.extend([
            "Commands:",
            "  [[REMIND: when | what]] — Create a new reminder",
            "  [[COMPLETE: I-id | outcome]] — Mark as done with note",
            "  [[DISMISS: I-id]] — Cancel without completing",
            "  [[LIST_INTENTIONS]] — Review all your intentions",
            "",
            "When addressing a due intention, mark it complete or dismiss it.",
            "Create reminders when you notice things worth following up on.",
            "",
            "Note: Time-based reminders automatically trigger a pulse prompt when due,",
            "even if the user hasn't messaged. You will receive an automated reminder pulse.",
            "</your_intentions>",
        ])

        return "\n".join(lines)


# Global instance
_intention_source: Optional[IntentionSource] = None


def get_intention_source() -> IntentionSource:
    """Get the global intention source instance."""
    global _intention_source
    if _intention_source is None:
        _intention_source = IntentionSource()
    return _intention_source
