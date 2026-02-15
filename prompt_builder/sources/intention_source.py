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

            # Check if this is a pulse trigger
            is_pulse = session_context.get("is_pulse", False)

            # Check if this is a session start (for next_session triggers)
            is_session_start = session_context.get("is_session_start", False)
            if is_session_start:
                engine.check_and_trigger(now, is_session_start=True)

            # Get current intention state
            summary = engine.get_context_summary(now)

            triggered_count = summary["triggered_count"]
            pending_count = summary["pending_count"]

            # If no intentions at all, return context (pulse gets a proactive nudge)
            if triggered_count == 0 and pending_count == 0:
                content = self._build_pulse_empty_context() if is_pulse else self._build_empty_context()
                return ContextBlock(
                    source_name=self.source_name,
                    content=content,
                    priority=self.priority,
                    include_always=True,
                    metadata={
                        "triggered_count": 0,
                        "pending_count": 0,
                        "is_pulse": is_pulse,
                    }
                )

            # Build intention context (pulse-aware or standard)
            if is_pulse:
                content = self._build_pulse_context(summary, now)
            else:
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
                    "is_pulse": is_pulse,
                    "triggered_ids": [i.id for i in summary["triggered"]],
                    "pending_ids": [i.id for i in summary["pending"]],
                }
            )

        except Exception as e:
            log_info(f"IntentionSource error: {e}")
            return None

    def _build_empty_context(self) -> str:
        """Build context when there are no intentions."""
        return "<your_intentions>None active. Use create_reminder to schedule future autonomous pulses (params: when, what, context).</your_intentions>"

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

        # Add tool usage instructions (native tool use, not bracket syntax)
        lines.extend([
            "Tools:",
            "  create_reminder — Schedule an autonomous pulse at a future time (params: when, what, context)",
            "  complete_reminder — Mark as done; outcome is saved to memory (params: reminder_id, outcome)",
            "  dismiss_reminder — Cancel without completing; no memory created (params: reminder_id)",
            "  list_reminders — List all reminders with IDs, statuses, and trigger times",
            "",
            "When addressing a due intention, mark it complete or dismiss it.",
            "Create reminders when you want to take future autonomous action — not just to",
            "remember, but to schedule work. When a reminder fires, you get a full autonomous",
            "turn with all tools available (search, files, Telegram, memory, etc.).",
            "</your_intentions>",
        ])

        return "\n".join(lines)

    def _build_pulse_empty_context(self) -> str:
        """Build pulse context when there are no intentions."""
        return "\n".join([
            "<your_intentions_pulse>",
            "You have no active intentions.",
            "",
            "The pulse is a moment to think forward. Is there anything from recent",
            "conversations worth following up on? A question left unanswered?",
            "Something you want to revisit later?",
            "",
            "Use create_reminder to schedule future autonomous actions (params: when, what, context).",
            "Reminders fire dedicated pulses with full tool access — use them to plan real work.",
            "</your_intentions_pulse>",
        ])

    def _build_pulse_context(self, summary: dict, now: datetime) -> str:
        """Build pulse-specific context with elevated urgency for triggered items."""
        triggered_count = summary["triggered_count"]
        pending_count = summary["pending_count"]

        lines = ["<your_intentions_pulse>"]

        if triggered_count > 0:
            lines.extend([
                "ATTENTION — You have intentions that need action:",
                "",
            ])
        else:
            lines.extend([
                "Your forward-looking commitments:",
                "",
            ])

        # Add the formatted intention list (reuse existing formatting)
        if summary["formatted_context"]:
            lines.append(summary["formatted_context"])
            lines.append("")

        # Add resolution guidance
        if triggered_count > 0:
            lines.extend([
                "These are commitments you made to yourself. Address them now or",
                "consciously dismiss them with the dismiss_reminder tool.",
                "",
            ])

        # Add total count and commands
        total = triggered_count + pending_count
        lines.append(f"You have {total} active intention{'s' if total != 1 else ''}.")
        lines.append("")
        lines.extend([
            "Tools: complete_reminder (saves outcome to memory), dismiss_reminder (no memory),",
            "  create_reminder (schedule another autonomous pulse), list_reminders",
            "You have full tool access during this pulse — act on these intentions now.",
            "</your_intentions_pulse>",
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
