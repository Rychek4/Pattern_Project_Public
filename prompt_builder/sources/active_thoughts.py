"""
Pattern Project - Active Thoughts Context Source
Injects the AI's working memory (active thoughts) into prompts
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info


# Priority for active thoughts: after core memory (10), before intentions (22)
# This is "who I'm being right now" - more foundational than tasks
ACTIVE_THOUGHTS_PRIORITY = 18


class ActiveThoughtsSource(ContextSource):
    """
    Provides the AI's active thoughts - its working memory.

    This is the AI's private "stream of consciousness" that persists
    across sessions. Unlike memories (which decay) or intentions
    (which have triggers), active thoughts persist until explicitly changed.

    The AI has complete control over this list - it can add, edit,
    rerank, or delete thoughts at any time using [[SET_THOUGHTS: ...]].

    Maximum 10 items stored, top 3 displayed in prompts to reduce token usage.
    """

    # Maximum thoughts to display in normal prompts (storage limit remains 10)
    MAX_DISPLAY = 3
    # During pulse, show all thoughts to enable full reflection
    MAX_DISPLAY_PULSE = 10

    @property
    def source_name(self) -> str:
        return "active_thoughts"

    @property
    def priority(self) -> int:
        return ACTIVE_THOUGHTS_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get active thoughts for prompt injection."""
        from agency.active_thoughts import get_active_thoughts_manager

        try:
            manager = get_active_thoughts_manager()
            thoughts = manager.get_all()

            # Check if this is a pulse trigger
            is_pulse = session_context.get("is_pulse", False)

            if not thoughts:
                content = self._build_pulse_empty_context() if is_pulse else self._build_empty_context()
            elif is_pulse:
                content = self._build_pulse_context(thoughts)
            else:
                content = self._build_context(thoughts)

            # Store count in session context for other sources
            session_context["active_thoughts_count"] = len(thoughts)

            display_count = len(thoughts) if is_pulse else min(len(thoughts), self.MAX_DISPLAY)

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=True,
                metadata={
                    "thought_count": len(thoughts),
                    "displayed_count": display_count,
                    "is_pulse": is_pulse,
                    "thoughts": [
                        {"rank": t.rank, "slug": t.slug, "topic": t.topic}
                        for t in thoughts[:display_count]
                    ]
                }
            )

        except Exception as e:
            log_info(f"ActiveThoughtsSource error: {e}")
            return None

    def _build_empty_context(self) -> str:
        """Build context when there are no active thoughts."""
        return "<active_working_memory>Empty. Use [[SET_THOUGHTS: [...]]] to add thoughts.</active_working_memory>"

    def _build_context(self, thoughts) -> str:
        """Build context with active thoughts (displays top 3 only)."""
        # Only display top N thoughts to reduce token usage
        display_thoughts = thoughts[:self.MAX_DISPLAY]
        total_count = len(thoughts)

        lines = [
            "<active_working_memory>",
            f"Your top {len(display_thoughts)} active thoughts (of {total_count} total):",
            "",
        ]

        for thought in display_thoughts:
            lines.append(f"{thought.rank}. [{thought.slug}] {thought.topic}")
            # Indent elaboration and wrap in quotes for clarity
            elaboration_lines = thought.elaboration.split('\n')
            for i, line in enumerate(elaboration_lines):
                if i == 0:
                    lines.append(f'   "{line}')
                else:
                    lines.append(f'   {line}')
            # Close quote on last line
            if elaboration_lines:
                lines[-1] = lines[-1] + '"'
            lines.append("")

        lines.extend([
            "You control this completely. Update anytime with:",
            "  [[SET_THOUGHTS: [...]]]",
            "",
            "Keep it focused (~50-75 words per elaboration). This is your compass",
            "for interacting with reality, not a place for extended prose.",
            "</active_working_memory>",
        ])

        return "\n".join(lines)

    def _build_pulse_empty_context(self) -> str:
        """Build pulse context when there are no active thoughts."""
        return "\n".join([
            "<active_working_memory_pulse>",
            "The pulse has fired — a moment for reflection.",
            "",
            "You have no active thoughts. Your compass is empty.",
            "What is on your mind? What matters to you right now?",
            "",
            "Use [[SET_THOUGHTS: [...]]] to define your working memory.",
            "</active_working_memory_pulse>",
        ])

    def _build_pulse_context(self, thoughts) -> str:
        """Build pulse-specific context showing all thoughts with reflective prompts."""
        total_count = len(thoughts)
        display_thoughts = thoughts[:self.MAX_DISPLAY_PULSE]

        lines = [
            "<active_working_memory_pulse>",
            "The pulse has fired — a moment for reflection.",
            "",
            f"Your active thoughts (all {total_count}):",
            "",
        ]

        for thought in display_thoughts:
            lines.append(f"{thought.rank}. [{thought.slug}] {thought.topic}")
            elaboration_lines = thought.elaboration.split('\n')
            for i, line in enumerate(elaboration_lines):
                if i == 0:
                    lines.append(f'   "{line}')
                else:
                    lines.append(f'   {line}')
            if elaboration_lines:
                lines[-1] = lines[-1] + '"'
            lines.append("")

        lines.extend([
            "These thoughts are your compass. Ask yourself:",
            "- Do these still reflect what matters to you right now?",
            "- Is there something you've been thinking about that isn't captured here?",
            "- Are any of these stale or resolved?",
            "",
            "Update with [[SET_THOUGHTS: [...]]] if anything has shifted.",
            "</active_working_memory_pulse>",
        ])

        return "\n".join(lines)


# Global instance
_active_thoughts_source: Optional[ActiveThoughtsSource] = None


def get_active_thoughts_source() -> ActiveThoughtsSource:
    """Get the global ActiveThoughtsSource instance."""
    global _active_thoughts_source
    if _active_thoughts_source is None:
        _active_thoughts_source = ActiveThoughtsSource()
    return _active_thoughts_source
