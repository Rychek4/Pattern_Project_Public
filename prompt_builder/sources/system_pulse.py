"""
Pattern Project - System Pulse Context Source
Provides AI with awareness of both pulse timers (reflective + action).

NOTE: The pulse timers are controlled via the native `set_pulse_interval` tool.
This source provides context about the current timer settings.
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.logger import log_info


# ─── Interval Mappings ───────────────────────────────────────────────────────

# Human-readable labels for all supported intervals
PULSE_INTERVAL_OPTIONS = {
    3600: "1 hour",
    7200: "2 hours",
    10800: "3 hours",
    21600: "6 hours",
    43200: "12 hours",
    86400: "24 hours",
}

# Valid intervals per pulse type
REFLECTIVE_INTERVALS = {"6h": 21600, "12h": 43200, "24h": 86400}
ACTION_INTERVALS = {"1h": 3600, "2h": 7200, "3h": 10800, "6h": 21600}

# Combined mapping for tool input validation (used by ToolExecutor)
PULSE_COMMAND_TO_SECONDS = {
    "1h": 3600,
    "2h": 7200,
    "3h": 10800,
    "6h": 21600,
    "12h": 43200,
    "24h": 86400,
}


def get_interval_label(seconds: float) -> str:
    """Get human-readable label for an interval in seconds."""
    return PULSE_INTERVAL_OPTIONS.get(int(seconds), f"{int(seconds)} seconds")


# ─── Context Source ──────────────────────────────────────────────────────────

class SystemPulseSource(ContextSource):
    """
    Provides context about both pulse timers to the AI.

    Injects current interval settings so the AI knows its own pulse schedule
    and can adjust via the set_pulse_interval tool.
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
        from agency.system_pulse import get_pulse_manager
        import config

        if not config.SYSTEM_PULSE_ENABLED:
            return None

        manager = get_pulse_manager()
        reflective_interval = manager.reflective_timer.interval
        reflective_label = get_interval_label(reflective_interval)
        action_interval = manager.action_timer.interval
        action_label = get_interval_label(action_interval)

        lines = [
            "<pulse_info>",
            f"Reflective pulse: {reflective_label} (Opus 4.6)",
            f"Action pulse: {action_label} (Sonnet 4.6)",
            "(Use set_pulse_interval with pulse_type to adjust either)",
            "</pulse_info>",
        ]

        # Store in session context for other sources
        session_context["reflective_pulse_interval_seconds"] = reflective_interval
        session_context["reflective_pulse_interval_label"] = reflective_label
        session_context["action_pulse_interval_seconds"] = action_interval
        session_context["action_pulse_interval_label"] = action_label

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=True,
            metadata={
                "reflective_interval_seconds": reflective_interval,
                "reflective_interval_label": reflective_label,
                "action_interval_seconds": action_interval,
                "action_interval_label": action_label,
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
