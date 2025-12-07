"""
Pattern Project - Conversation Source
Recent conversation history with semantic timestamps
"""

from typing import Optional, Dict, Any, List

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from memory.conversation import get_conversation_manager
from core.temporal import format_fuzzy_relative_time


# 15 exchanges = 30 turns (user + assistant pairs)
DEFAULT_EXCHANGE_COUNT = 15


class ConversationSource(ContextSource):
    """
    Provides recent conversation history for prompt context.

    Includes the last N exchanges (user + assistant pairs) to maintain
    coherence within the current session without growing infinitely.
    """

    def __init__(self, exchange_count: int = DEFAULT_EXCHANGE_COUNT):
        """
        Initialize conversation source.

        Args:
            exchange_count: Number of exchanges to include (user + reply pairs)
        """
        self.exchange_count = exchange_count
        # Each exchange = 2 turns (user + assistant)
        self.turn_limit = exchange_count * 2

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
        """Get recent conversation history with semantic timestamps."""
        conversation_mgr = get_conversation_manager()

        # Get full turn objects with timestamps
        turns = conversation_mgr.get_session_history(limit=self.turn_limit)

        # Filter to user/assistant only
        turns = [t for t in turns if t.role in ("user", "assistant")]

        if not turns:
            return None

        # Format for prompt with semantic timestamps
        lines = ["<recent_conversation>"]

        for turn in turns:
            # Use "Claude" for assistant, "Brian" for user
            name = "Claude" if turn.role == "assistant" else "Brian"
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
                "exchange_limit": self.exchange_count
            }
        )

    def get_raw_history(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get raw conversation history for LLM API calls.

        Args:
            limit: Max turns to return (uses default if None)

        Returns:
            List of {"role": ..., "content": ...} dicts
        """
        conversation_mgr = get_conversation_manager()
        return conversation_mgr.get_recent_history(
            limit=limit or self.turn_limit
        )


# Global instance
_conversation_source: Optional[ConversationSource] = None


def get_conversation_source() -> ConversationSource:
    """Get the global conversation source instance."""
    global _conversation_source
    if _conversation_source is None:
        _conversation_source = ConversationSource()
    return _conversation_source
