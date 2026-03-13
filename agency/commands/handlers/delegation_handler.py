"""
Pattern Project - Delegation Tool Handler
Handles delegate_task tool execution.

Extracted from agency/tools/executor.py for modularity.
"""

from typing import Any, Dict

from core.logger import log_error
import config


def exec_delegate_task(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """
    Delegate a task to a lightweight sub-agent.

    Spawns an ephemeral Haiku conversation with limited tools.
    The sub-agent runs to completion and returns its result as text.
    """
    from agency.tools.executor import ToolResult

    tool_name = "delegate_task"

    if not config.DELEGATION_ENABLED:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Delegation is disabled",
            is_error=True
        )

    task = input.get("task", "")
    if not task:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="No task provided",
            is_error=True
        )

    context = input.get("context", "")
    max_rounds = input.get("max_rounds")

    try:
        from agency.tools.delegate import run_delegated_task

        result_text = run_delegated_task(
            task=task,
            context=context,
            max_rounds=max_rounds
        )

        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=result_text
        )

    except Exception as e:
        log_error(f"Delegation failed: {e}")
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Delegation error: {str(e)}",
            is_error=True
        )
