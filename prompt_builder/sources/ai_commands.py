"""
Pattern Project - AI Commands Context Source
Injects available command instructions into the system prompt
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority


class AICommandsSource(ContextSource):
    """
    Injects available AI command instructions into the system prompt.

    This source provides the AI with knowledge of available commands
    (like [[SEARCH: query]]) and instructions on when/how to use them.
    """

    @property
    def source_name(self) -> str:
        return "ai_commands"

    @property
    def priority(self) -> int:
        return SourcePriority.AI_COMMANDS

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Get command instructions for prompt injection.

        Args:
            user_input: The user's current message
            session_context: Shared context dict

        Returns:
            ContextBlock with command instructions, or None if no commands registered
        """
        from agency.commands import get_command_processor

        processor = get_command_processor()

        if not processor.has_handlers():
            return None

        instructions = processor.get_all_instructions()

        if not instructions:
            return None

        content = f"""<ai_commands>
{instructions}
</ai_commands>"""

        return ContextBlock(
            source_name=self.source_name,
            content=content,
            priority=self.priority,
            include_always=True,
            metadata={
                "handler_count": len(processor.list_handlers()),
                "handlers": processor.list_handlers()
            }
        )


# Global instance
_ai_commands_source: Optional[AICommandsSource] = None


def get_ai_commands_source() -> AICommandsSource:
    """Get the global AI commands source instance."""
    global _ai_commands_source
    if _ai_commands_source is None:
        _ai_commands_source = AICommandsSource()
    return _ai_commands_source
