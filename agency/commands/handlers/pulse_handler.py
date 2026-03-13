"""
Pattern Project - Pulse Tool Handler
Handles set_pulse_interval tool execution.

Extracted from agency/tools/executor.py for modularity.
"""

from typing import Any, Dict

from core.logger import log_info


def exec_set_pulse_interval(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """
    Set a pulse timer interval (reflective or action).

    Validates pulse_type + interval combination, then stores in context
    for the caller to pick up and signal to the UI.
    """
    from agency.tools.executor import ToolResult
    from prompt_builder.sources.system_pulse import (
        REFLECTIVE_INTERVALS, ACTION_INTERVALS, get_interval_label
    )

    tool_name = "set_pulse_interval"
    pulse_type = input.get("pulse_type", "")
    interval_str = input.get("interval", "")

    # Validate pulse_type
    if pulse_type not in ("reflective", "action"):
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Invalid pulse_type '{pulse_type}'. Must be 'reflective' or 'action'.",
            is_error=True
        )

    # Validate interval for the specific pulse type
    valid_intervals = REFLECTIVE_INTERVALS if pulse_type == "reflective" else ACTION_INTERVALS
    if interval_str not in valid_intervals:
        valid_opts = ", ".join(valid_intervals.keys())
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Invalid interval '{interval_str}' for {pulse_type} pulse. Valid options: {valid_opts}",
            is_error=True
        )

    interval_seconds = valid_intervals[interval_str]
    label = get_interval_label(interval_seconds)

    # Store in context for caller to handle UI signaling
    ctx["pulse_interval_change"] = {
        "pulse_type": pulse_type,
        "interval_seconds": interval_seconds,
    }

    log_info(f"{pulse_type.capitalize()} pulse interval change requested: {label}", prefix="⏱️")

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content=f"{pulse_type.capitalize()} pulse timer set to {label}"
    )
