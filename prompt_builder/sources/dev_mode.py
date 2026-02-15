"""
Pattern Project - Dev Mode Source
Informs the AI when dev mode is active
"""

from typing import Optional, Dict, Any

import config
from prompt_builder.sources.base import ContextSource, ContextBlock


# Priority 5 - very early, before most other context
DEV_MODE_PRIORITY = 5


class DevModeSource(ContextSource):
    """
    Provides dev mode awareness to the AI.

    When dev mode is enabled (via --dev flag), this source injects
    a notification so the AI knows its internal operations are visible
    to the user in a debug window.
    """

    @property
    def source_name(self) -> str:
        return "dev_mode"

    @property
    def priority(self) -> int:
        return DEV_MODE_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """
        Get dev mode notification if enabled.

        Only returns content when DEV_MODE_ENABLED is True.
        """
        if not config.DEV_MODE_ENABLED:
            return None

        # Store dev mode status in session context for other sources
        session_context["dev_mode"] = True

        notification = """<dev_mode_notice>
Development mode is active. The user can see diagnostic information including:
- Your tool/command usage and execution results
- Memory recall with relevance scores
- Prompt assembly and context blocks
- Multi-pass response processing details
- Token counts and response timing

This is for debugging purposes. Respond naturally - this does not change
how you should interact, but be aware that your "internal" operations
(like memory searches and tool use) are visible in a separate debug window.
</dev_mode_notice>"""

        return ContextBlock(
            source_name=self.source_name,
            content=notification,
            priority=self.priority,
            include_always=False,  # Only include when dev mode is on
            metadata={"dev_mode_enabled": True}
        )


# Global instance
_dev_mode_source: Optional[DevModeSource] = None


def get_dev_mode_source() -> DevModeSource:
    """Get the global dev mode source instance."""
    global _dev_mode_source
    if _dev_mode_source is None:
        _dev_mode_source = DevModeSource()
    return _dev_mode_source
