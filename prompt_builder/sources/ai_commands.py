"""
Pattern Project - AI Capabilities Context Source
Provides information about web search, web fetch, and other AI capabilities.

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
    - Web fetch capability status
    - Combined web research guidance (when both are available)

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

            # Only show detailed budget when running low (< 10 remaining)
            if remaining < 10:
                return f"<web_search_capability>Web search available. Budget: {remaining} remaining ({used}/{total} used)</web_search_capability>"

            # When budget is ample, minimal reminder (AI already knows how to search)
            return "<web_search_capability>Web search available.</web_search_capability>"

        except Exception as e:
            log_error(f"Failed to get web search status: {e}")
            return None  # Silently omit web search status from prompt

    def _get_web_fetch_status(self) -> Optional[str]:
        """Get web fetch availability status for the prompt."""
        if not config.WEB_FETCH_ENABLED:
            return None

        try:
            from agency.web_fetch_limiter import get_web_fetch_limiter
            limiter = get_web_fetch_limiter()
            used, total = limiter.get_usage()
            remaining = limiter.get_remaining()

            if remaining <= 0:
                return None  # Will be handled by router with unavailable message

            # Only show detailed budget when running low (< 10 remaining)
            if remaining < 10:
                return (
                    f"<web_fetch_capability>Web fetch available for retrieving full page/PDF content "
                    f"from URLs. Budget: {remaining} remaining ({used}/{total} used).</web_fetch_capability>"
                )

            # When budget is ample, minimal reminder
            return (
                "<web_fetch_capability>Web fetch available. You can retrieve full content from "
                "URLs provided by the user or found through web search.</web_fetch_capability>"
            )

        except Exception as e:
            log_error(f"Failed to get web fetch status: {e}")
            return None  # Silently omit web fetch status from prompt

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Get AI capability context for prompt injection.

        Tool instructions are provided via native tool schemas in the API call,
        so this source only provides web search/fetch status.

        Args:
            user_input: The user's current message
            session_context: Shared context dict

        Returns:
            ContextBlock with capability info, or None if no info to add
        """
        content_parts = []

        # NOTE: Tool instructions are provided via native tool schemas.
        # The legacy [[COMMAND]] syntax is no longer supported.

        # Add web search status if enabled and available
        web_search_status = self._get_web_search_status()
        if web_search_status:
            content_parts.append(web_search_status)

        # Add web fetch status if enabled and available
        web_fetch_status = self._get_web_fetch_status()
        if web_fetch_status:
            content_parts.append(web_fetch_status)

        # When both are available, add combined research guidance
        if web_search_status and web_fetch_status:
            content_parts.append(
                "<web_research_capability>Both web search and web fetch are available. "
                "For thorough research: search to discover sources, then fetch to read "
                "full content. Citations from both tools are automatically tracked.</web_research_capability>"
            )

        if not content_parts:
            return None

        content = "\n\n".join(content_parts)

        # Build metadata
        metadata = {
            "native_tools_mode": True,  # Always true now
        }
        if web_search_status:
            metadata["web_search_enabled"] = True
        if web_fetch_status:
            metadata["web_fetch_enabled"] = True

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
