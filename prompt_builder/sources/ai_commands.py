"""
Pattern Project - AI Commands Context Source
Injects available command instructions into the system prompt
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.logger import log_error
import config


class AICommandsSource(ContextSource):
    """
    Injects available AI command instructions into the system prompt.

    This source provides the AI with knowledge of available commands
    (like [[SEARCH: query]]) and instructions on when/how to use them.
    Also includes web search capability status.
    """

    @property
    def source_name(self) -> str:
        return "ai_commands"

    @property
    def priority(self) -> int:
        return SourcePriority.AI_COMMANDS

    def _get_web_search_status(self) -> Optional[str]:
        """Get web search availability status for the prompt."""
        if not config.WEB_SEARCH_ENABLED:
            return None

        try:
            from agency.web_search_limiter import get_web_search_limiter
            limiter = get_web_search_limiter()
            used, total = limiter.get_usage()
            remaining = limiter.get_remaining()

            if remaining <= 0:
                return None  # Will be handled by router with unavailable message

            return f"""<web_search_capability>
You have access to real-time web search. When the user asks about current events,
recent information, or topics that may have changed since your knowledge cutoff,
you can search the web automatically. Web searches happen seamlessly - you don't
need special syntax. Just respond naturally and search when needed.

Today's budget: {remaining} searches remaining ({used}/{total} used)
</web_search_capability>"""

        except Exception as e:
            log_error(f"Failed to get web search status: {e}")
            return None  # Silently omit web search status from prompt

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Get command instructions for prompt injection.

        When USE_NATIVE_TOOLS is enabled, command instructions are skipped
        because tool schemas provide this information. Only web search
        status is included.

        Args:
            user_input: The user's current message
            session_context: Shared context dict

        Returns:
            ContextBlock with command instructions, or None if no commands registered
        """
        content_parts = []

        # Only add command instructions if NOT using native tools
        # Native tools get their instructions from tool schemas in the API call
        if not config.USE_NATIVE_TOOLS:
            from agency.commands import get_command_processor

            processor = get_command_processor()

            # Add command instructions if any handlers registered
            if processor.has_handlers():
                instructions = processor.get_all_instructions()
                if instructions:
                    content_parts.append(f"""<ai_commands>
{instructions}
</ai_commands>""")

        # Add web search status if enabled and available
        web_search_status = self._get_web_search_status()
        if web_search_status:
            content_parts.append(web_search_status)

        if not content_parts:
            return None

        content = "\n\n".join(content_parts)

        # Build metadata
        metadata = {}
        if config.USE_NATIVE_TOOLS:
            metadata["native_tools_mode"] = True
        else:
            from agency.commands import get_command_processor
            processor = get_command_processor()
            if processor.has_handlers():
                metadata["handler_count"] = len(processor.list_handlers())
                metadata["handlers"] = processor.list_handlers()
        if web_search_status:
            metadata["web_search_enabled"] = True

        return ContextBlock(
            source_name=self.source_name,
            content=content,
            priority=self.priority,
            include_always=True,
            metadata=metadata
        )


# Global instance
_ai_commands_source: Optional[AICommandsSource] = None


def get_ai_commands_source() -> AICommandsSource:
    """Get the global AI commands source instance."""
    global _ai_commands_source
    if _ai_commands_source is None:
        _ai_commands_source = AICommandsSource()
    return _ai_commands_source
