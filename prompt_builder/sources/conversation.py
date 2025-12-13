"""
Pattern Project - Conversation Source
Recent conversation history with semantic timestamps

ARCHITECTURE (Windowed Extraction System):
    The context window is tightly coupled with memory extraction.
    Turns flow: Context Window → Extraction → Memory Store

    When context exceeds CONTEXT_OVERFLOW_TRIGGER, oldest turns are
    extracted to memory and marked as processed, automatically removing
    them from future context loads.

    Key behaviors:
    - Context spans across sessions (for AI continuity)
    - Processed turns are excluded from context
    - Context window never drops below CONTEXT_WINDOW_SIZE (except at start)

    This replaces the old system where context and extraction were
    independent, which caused duplicate memory extraction.
"""

from typing import Optional, Dict, Any, List

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from memory.conversation import get_conversation_manager
from core.temporal import format_fuzzy_relative_time
from config import CONTEXT_WINDOW_SIZE, USER_NAME, AI_NAME


class ConversationSource(ContextSource):
    """
    Provides recent conversation history for prompt context.

    ARCHITECTURE (Windowed Extraction):
        Uses get_context_window() which:
        - Spans across sessions (NOT session-scoped) for AI continuity
        - Excludes processed turns (coordinated with extraction)
        - Returns most recent unprocessed turns up to window size

        This ensures the AI always has ~30 turns of context, and those
        turns are only extracted to memory when they overflow the window.
    """

    def __init__(self, window_size: int = CONTEXT_WINDOW_SIZE):
        """
        Initialize conversation source.

        Args:
            window_size: Number of turns to include in context window
        """
        self.window_size = window_size
        # Legacy compatibility
        self.exchange_count = window_size // 2
        self.turn_limit = window_size

    @property
    def source_name(self) -> str:
        return "conversation"

    @property
    def priority(self) -> int:
        return SourcePriority.CONVERSATION

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Get recent conversation history with semantic timestamps.

        Uses the windowed context system:
        - Loads unprocessed turns across all sessions (for continuity)
        - Processed turns are automatically excluded
        - Coordinates with extraction system to prevent duplicates
        """
        conversation_mgr = get_conversation_manager()

        # Get context window (excludes processed turns, spans sessions)
        turns = conversation_mgr.get_context_window(limit=self.window_size)

        # Filter to user/assistant only
        turns = [t for t in turns if t.role in ("user", "assistant")]

        if not turns:
            return None

        # Format for prompt with semantic timestamps
        lines = ["<recent_conversation>"]

        for turn in turns:
            # Use configured names for consistent entity naming across the system
            name = AI_NAME if turn.role == "assistant" else USER_NAME
            timestamp = format_fuzzy_relative_time(turn.created_at)
            lines.append(f"  {name}: {turn.content} ({timestamp})")

        lines.append("</recent_conversation>")

        # Calculate actual exchange count
        user_turns = sum(1 for t in turns if t.role == "user")
        assistant_turns = sum(1 for t in turns if t.role == "assistant")

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=False,
            metadata={
                "turn_count": len(turns),
                "user_turns": user_turns,
                "assistant_turns": assistant_turns,
                "window_size": self.window_size
            }
        )

    def get_raw_history(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get raw conversation history for LLM API calls.

        Uses the windowed context system for consistency with get_context().

        Args:
            limit: Max turns to return (uses window_size if None)

        Returns:
            List of {"role": ..., "content": ...} dicts
        """
        conversation_mgr = get_conversation_manager()
        turns = conversation_mgr.get_context_window(limit=limit or self.window_size)
        return [
            {"role": turn.role, "content": turn.content}
            for turn in turns
            if turn.role in ("user", "assistant")
        ]


# Global instance
_conversation_source: Optional[ConversationSource] = None


def get_conversation_source() -> ConversationSource:
    """Get the global conversation source instance."""
    global _conversation_source
    if _conversation_source is None:
        _conversation_source = ConversationSource()
    return _conversation_source
