"""
Pattern Project - System Pulse Source
Provides AI with awareness of the pulse timer.

NOTE: The pulse timer is controlled via the native `set_pulse_interval` tool.
This source provides context about the current timer setting, but the AI
adjusts it using the tool, not embedded commands.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.logger import log_info


# Mapping of interval seconds to human-readable labels
PULSE_INTERVAL_OPTIONS = {
    180: "3 minutes",
    600: "10 minutes",
    1800: "30 minutes",
    3600: "1 hour",
    7200: "2 hours",
    10800: "3 hours",
    21600: "6 hours",
    43200: "12 hours",
}

# Mapping for tool input validation (used by ToolExecutor)
PULSE_COMMAND_TO_SECONDS = {
    "3m": 180,
    "10m": 600,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "3h": 10800,
    "6h": 21600,
    "12h": 43200,
}


def get_interval_label(seconds: float) -> str:
    """Get human-readable label for an interval in seconds."""
    return PULSE_INTERVAL_OPTIONS.get(int(seconds), f"{int(seconds)} seconds")


class SystemPulseSource(ContextSource):
    """
    Provides context about the system pulse timer.

    This gives the AI awareness of:
    - What the pulse timer is
    - Current timer setting
    - The set_pulse_interval tool can be used to adjust it

    The AI controls the pulse timer via the `set_pulse_interval` native tool,
    not via embedded commands.
    """

    @property
    def source_name(self) -> str:
        return "system_pulse"

    @property
    def priority(self) -> int:
        return SourcePriority.SYSTEM_PULSE

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get system pulse context for prompt injection."""
        from agency.system_pulse import get_system_pulse_timer
        import config

        # Check if pulse is enabled
        if not config.SYSTEM_PULSE_ENABLED:
            return None

        # Get current timer setting
        timer = get_system_pulse_timer()
        current_interval = timer.pulse_interval
        current_label = get_interval_label(current_interval)

        # Build a minimal context block - tool description provides the rest
        # We only need to inform the AI of the current setting
        lines = [
            "<system_pulse_info>",
            f"Pulse timer is currently set to: {current_label}",
            "(Use the set_pulse_interval tool to adjust)",
            "</system_pulse_info>",
        ]

        # Store current setting in session context for other sources
        session_context["pulse_interval_seconds"] = current_interval
        session_context["pulse_interval_label"] = current_label

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=True,
            metadata={
                "current_interval_seconds": current_interval,
                "current_interval_label": current_label,
            }
        )


# Global instance
_system_pulse_source: Optional[SystemPulseSource] = None


def get_system_pulse_source() -> SystemPulseSource:
    """Get the global system pulse source instance."""
    global _system_pulse_source
    if _system_pulse_source is None:
        _system_pulse_source = SystemPulseSource()
    return _system_pulse_source
