"""
Pattern Project - Growth Thread Tool Handlers
Handles set_growth_thread, remove_growth_thread, promote_growth_thread.

Extracted from agency/tools/executor.py for modularity.
"""

from typing import Any, Dict

from core.logger import log_error


def exec_set_growth_thread(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Create or update a growth thread."""
    from agency.tools.executor import ToolResult
    from agency.growth_threads import get_growth_thread_manager

    tool_name = "set_growth_thread"
    slug = input.get("slug", "")
    stage = input.get("stage", "")
    content = input.get("content", "")

    if not slug or not stage or not content:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Error: slug, stage, and content are all required.",
            is_error=True
        )

    manager = get_growth_thread_manager()

    # Check if this is an update or create
    existing = manager.get_by_slug(slug)
    success, error = manager.set(slug, stage, content)

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error: {error}",
            is_error=True
        )

    if existing:
        if existing.stage != stage:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Growth thread '{slug}' updated: {existing.stage} → {stage}"
            )
        else:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Growth thread '{slug}' content updated (stage: {stage})"
            )
    else:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Growth thread '{slug}' created (stage: {stage})"
        )


def exec_remove_growth_thread(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Remove a growth thread."""
    from agency.tools.executor import ToolResult
    from agency.growth_threads import get_growth_thread_manager

    tool_name = "remove_growth_thread"
    slug = input.get("slug", "")

    if not slug:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Error: slug is required.",
            is_error=True
        )

    manager = get_growth_thread_manager()
    success, error = manager.remove(slug)

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error: {error}",
            is_error=True
        )

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content=f"Growth thread '{slug}' removed."
    )


def exec_promote_growth_thread(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Promote an integrated growth thread to a permanent core memory.

    Atomically validates, stores the core memory, and removes the thread.
    """
    from datetime import datetime, timedelta
    from agency.tools.executor import ToolResult
    from agency.growth_threads import get_growth_thread_manager
    from prompt_builder.sources.core_memory import CoreMemorySource

    tool_name = "promote_growth_thread"
    thread_slug = input.get("thread_slug", "")
    content = input.get("core_memory_content", "")
    category = input.get("category", "")

    # --- Validate required fields ---
    if not thread_slug or not content or not category:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Error: thread_slug, core_memory_content, and category are all required.",
            is_error=True
        )

    valid_categories = ("identity", "relationship", "preference", "fact")
    if category not in valid_categories:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error: category must be one of: {', '.join(valid_categories)}",
            is_error=True
        )

    # --- Validate growth thread exists and is at integrating stage ---
    manager = get_growth_thread_manager()
    thread = manager.get_by_slug(thread_slug)

    if thread is None:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error: No growth thread found with slug '{thread_slug}'.",
            is_error=True
        )

    if thread.stage != "integrating":
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error: Thread '{thread_slug}' is at stage '{thread.stage}', "
                    f"not 'integrating'. Only threads at the integrating stage "
                    f"can be promoted to core memories.",
            is_error=True
        )

    # --- Validate minimum time at integrating stage (2 weeks) ---
    min_integrating_days = 14
    time_at_stage = datetime.now() - thread.stage_changed_at
    if time_at_stage < timedelta(days=min_integrating_days):
        days_so_far = time_at_stage.days
        days_remaining = min_integrating_days - days_so_far
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error: Thread '{thread_slug}' has only been integrating for "
                    f"{days_so_far} days. It must be at the integrating stage for "
                    f"at least {min_integrating_days} days before promotion. "
                    f"({days_remaining} days remaining)",
            is_error=True
        )

    # --- Atomically: store core memory, then remove thread ---
    source = CoreMemorySource()
    memory_id = source.add(content, category)

    if memory_id is None:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Error: Failed to store core memory. Thread was NOT removed.",
            is_error=True
        )

    success, error = manager.remove(thread_slug)

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Warning: Core memory stored (id={memory_id}) but failed to "
                    f"remove thread '{thread_slug}': {error}. "
                    f"Please remove it manually with remove_growth_thread.",
            is_error=False
        )

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content=f"Growth thread '{thread_slug}' promoted to core memory "
                f"(id={memory_id}, category={category}): {content[:80]}... "
                f"Thread has been removed."
    )
