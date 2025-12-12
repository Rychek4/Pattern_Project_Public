"""
Pattern Project - AI Capabilities Context Source
Provides information about web search and other AI capabilities.

NOTE: Tool instructions are provided via native tool schemas in the API call.
This source no longer injects legacy [[COMMAND]] syntax instructions.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.logger import log_error
import config


class AICommandsSource(ContextSource):
    """
    Provides AI capability information in the system prompt.

    This source includes:
    - Web search capability status

    NOTE: Tool instructions are provided via native tool schemas in the API call.
    The legacy [[COMMAND]] syntax is no longer supported (December 2025).
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
        Get AI capability context for prompt injection.

        Tool instructions are provided via native tool schemas in the API call,
        so this source only provides web search status.

        Args:
            user_input: The user's current message
            session_context: Shared context dict

        Returns:
            ContextBlock with capability info, or None if no info to add
        """
        content_parts = []

        # NOTE: Tool instructions are provided via native tool schemas.
        # The legacy [[COMMAND]] syntax is no longer supported.
        # Only web search status is included here.

        # Add web search status if enabled and available
        web_search_status = self._get_web_search_status()
        if web_search_status:
            content_parts.append(web_search_status)

        if not content_parts:
            return None

        content = "\n\n".join(content_parts)

        # Build metadata
        metadata = {
            "native_tools_mode": True,  # Always true now
        }
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
