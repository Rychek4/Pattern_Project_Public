"""
Pattern Project - Temporal Source
Time awareness and session context
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.temporal import (
    get_temporal_tracker,
    temporal_context_to_semantic,
    TemporalContext
)


class TemporalSource(ContextSource):
    """
    Provides temporal context for prompt injection.

    Includes:
    - Current time and date
    - Session duration and turn count
    - Time since last interaction
    - Historical interaction data
    """

    @property
    def source_name(self) -> str:
        return "temporal"

    @property
    def priority(self) -> int:
        return SourcePriority.TEMPORAL

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get temporal context for prompt injection."""
        tracker = get_temporal_tracker()
        context = tracker.get_context()

        # Convert to semantic description
        semantic_text = temporal_context_to_semantic(context)

        # Format for prompt (handle multi-line content with proper indentation)
        lines = ["<temporal_context>"]
        for line in semantic_text.split("\n"):
            lines.append(f"  {line}")
        lines.append("</temporal_context>")

        # Store context in session for other sources
        session_context["temporal_context"] = context

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=True,
            metadata={
                "current_time": context.current_time.isoformat(),
                "session_duration_seconds": (
                    context.session_duration.total_seconds()
                    if context.session_duration else 0
                ),
                "turns_this_session": context.turns_this_session,
                "total_sessions": context.total_sessions
            }
        )

    def get_raw_context(self) -> TemporalContext:
        """Get raw temporal context object."""
        tracker = get_temporal_tracker()
        return tracker.get_context()


# Global instance
_temporal_source: Optional[TemporalSource] = None


def get_temporal_source() -> TemporalSource:
    """Get the global temporal source instance."""
    global _temporal_source
    if _temporal_source is None:
        _temporal_source = TemporalSource()
    return _temporal_source
