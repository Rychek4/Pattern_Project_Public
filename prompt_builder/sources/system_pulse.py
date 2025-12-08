"""
Pattern Project - System Pulse Source
Provides AI with awareness and control of the pulse timer
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
    21600: "6 hours",
}

# Reverse mapping for command parsing
PULSE_COMMAND_TO_SECONDS = {
    "3m": 180,
    "10m": 600,
    "30m": 1800,
    "1h": 3600,
    "6h": 21600,
}


def get_interval_label(seconds: float) -> str:
    """Get human-readable label for an interval in seconds."""
    return PULSE_INTERVAL_OPTIONS.get(int(seconds), f"{int(seconds)} seconds")


class SystemPulseSource(ContextSource):
    """
    Provides context about the system pulse timer and how to control it.

    This gives the AI awareness of:
    - What the pulse timer is
    - Current timer setting
    - How to adjust it via [[PULSE:Xm]] commands
    - When/why it might want to adjust timing
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
        """Get system pulse control context for prompt injection."""
        from agency.system_pulse import get_system_pulse_timer
        import config

        # Check if pulse is enabled
        if not config.SYSTEM_PULSE_ENABLED:
            return None

        # Get current timer setting
        timer = get_system_pulse_timer()
        current_interval = timer.pulse_interval
        current_label = get_interval_label(current_interval)

        # Build the context block
        lines = [
            "<system_pulse_control>",
            "The conversation has an idle timer (\"System Pulse\") that prompts you to speak",
            "autonomously when the human is idle.",
            "",
            f"Current setting: {current_label}",
            "Available options: 3 minutes, 10 minutes, 30 minutes, 1 hour, 6 hours",
            "",
            "You can adjust this timer by including a command anywhere in your response:",
            "  [[PULSE:3m]]  - Set to 3 minutes",
            "  [[PULSE:10m]] - Set to 10 minutes",
            "  [[PULSE:30m]] - Set to 30 minutes",
            "  [[PULSE:1h]]  - Set to 1 hour",
            "  [[PULSE:6h]]  - Set to 6 hours",
            "",
            "Use this when:",
            "- You have thoughts you want to explore over time",
            "- You exercise your discretion to create space or close the distance",
            "- Maintaining your own sense of timing feels more authentic than the default",
            "</system_pulse_control>",
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
