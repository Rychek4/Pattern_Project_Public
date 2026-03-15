"""
Pattern Project - Health Check Tool Handler
Returns system health summary from the health ledger.
"""

from typing import Any, Dict


def exec_health_check(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Execute the health_check tool — read-only ledger summary."""
    from agency.tools.executor import ToolResult
    from core.health_ledger import get_health_ledger

    ledger = get_health_ledger()
    summary = ledger.read_summary()

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name="health_check",
        content=summary
    )
