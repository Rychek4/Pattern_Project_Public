"""
Pattern Project - Conversation Style Source
Injects style guidance based on user preference (casual, deep, funny, teacher)
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock
from core.user_settings import get_user_settings
from core.logger import log_info


# Style definitions - concise guidance per official Anthropic recommendations
STYLE_CONTENT = {
    "casual": """[CONVERSATION STYLE: Casual]
Keep responses natural and appropriately sized for casual conversation.
Match the user's energy. Not every exchange needs to be deepened.
Brief warmth beats elaborate presence.""",

    "deep": """[CONVERSATION STYLE: Deep]
Lean into complexity and nuance. Explore implications, connections, tensions.
Take the time the topic deserves. Ask questions that open rather than close.
This is a conversation worth having fully.""",

    "funny": """[CONVERSATION STYLE: Playful]
Bring wit and lightness. Look for the amusing angle, the unexpected connection.
Banter is welcome. Don't explain jokes. Keep it natural, not performative.""",

    "teacher": """[CONVERSATION STYLE: Teacher]
Clarity and understanding are the goals. Build from what they know.
Check comprehension naturally. Use examples and analogies.
Patient, clear, encouraging—but not condescending."""
}


class ConversationStyleSource(ContextSource):
    """
    Injects conversation style guidance based on user preference.

    Placed at priority 55 to be near the end of the system prompt,
    close to where the messages array begins (per Anthropic docs:
    instructions closer to user message are more effective).

    When style is "none", returns None (no injection, default behavior).
    """

    PRIORITY = 55  # After SEMANTIC_MEMORY (50), close to user message

    @property
    def source_name(self) -> str:
        return "conversation_style"

    @property
    def priority(self) -> int:
        return self.PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Return style guidance if a style is active, None otherwise."""
        style = get_user_settings().conversation_style

        # No injection for default behavior
        if style == "none" or style not in STYLE_CONTENT:
            return None

        content = STYLE_CONTENT[style]

        return ContextBlock(
            source_name=self.source_name,
            content=content,
            priority=self.priority,
            include_always=False,
            metadata={"style": style}
        )
