"""
Pattern Project - Web Fetch Domain Tool Handlers
Handles manage_fetch_domains and list_fetch_domains.

Extracted from agency/tools/executor.py for modularity.
"""

from typing import Any, Dict


def exec_manage_fetch_domains(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Manage web fetch domain allow/block lists."""
    from agency.tools.executor import ToolResult
    from agency.web_fetch_domains import get_web_fetch_domain_manager

    tool_name = "manage_fetch_domains"
    action = input.get("action", "")
    domain = input.get("domain", "")

    if not action or not domain:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Both 'action' and 'domain' are required",
            is_error=True
        )

    manager = get_web_fetch_domain_manager()

    action_map = {
        "allow": manager.add_allowed_domain,
        "block": manager.add_blocked_domain,
        "remove_allowed": manager.remove_allowed_domain,
        "unblock": manager.remove_blocked_domain,
    }

    handler_fn = action_map.get(action)
    if not handler_fn:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Invalid action '{action}'. Valid: allow, block, remove_allowed, unblock",
            is_error=True
        )

    result_msg = handler_fn(domain)

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content=result_msg
    )


def exec_list_fetch_domains(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """List current web fetch domain configuration."""
    from agency.tools.executor import ToolResult
    from agency.web_fetch_domains import get_web_fetch_domain_manager

    manager = get_web_fetch_domain_manager()
    summary = manager.get_status_summary()

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name="list_fetch_domains",
        content=summary
    )
