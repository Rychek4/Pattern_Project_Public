"""
Pattern Project - Curiosity Tool Handler
Handles advance_curiosity tool execution.

Extracted from agency/tools/executor.py for modularity.
"""

from typing import Any, Dict

from core.logger import log_info, log_error
import config


def exec_advance_curiosity(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """
    Three-mode curiosity advancement:

    1. Progress only (note) - increment interaction count
    2. Resolve, system picks (note + outcome) - close and auto-select next
    3. Resolve, AI picks (note + outcome + next_topic) - close and use specified topic
    """
    from agency.tools.executor import ToolResult
    from agency.curiosity import get_curiosity_engine, is_curiosity_enabled
    from agency.curiosity.ledger import GoalStatus, get_curiosity_ledger

    tool_name = "advance_curiosity"

    if not is_curiosity_enabled():
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="Curiosity system is disabled",
            is_error=True
        )

    note = input.get("note", "")
    outcome = input.get("outcome")  # None = progress only mode
    next_topic = input.get("next_topic")  # None = system picks next

    try:
        ledger = get_curiosity_ledger()
        engine = get_curiosity_engine()
        current_goal = ledger.get_active_goal()

        if not current_goal:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content="No active curiosity goal to advance",
                is_error=True
            )

        # Always increment interaction count
        new_count = ledger.increment_interaction(current_goal.id)
        min_interactions = getattr(config, 'CURIOSITY_MIN_INTERACTIONS', 2)

        # ===== MODE 1: Progress only (no outcome) =====
        if outcome is None:
            if next_topic:
                return ToolResult(
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    content="Cannot specify next_topic without an outcome. Add outcome to resolve the topic.",
                    is_error=True
                )

            status_msg = f"Progress: {new_count}/{min_interactions}"
            if new_count >= min_interactions:
                status_msg += " (ready to resolve)"

            log_info(f"Curiosity interaction recorded: {status_msg}", prefix="🔍")
            _emit_curiosity_progress(current_goal, new_count, min_interactions, note)

            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Curiosity progress recorded. {status_msg}"
            )

        # ===== MODE 2 & 3: Resolving (outcome provided) =====
        status_map = {
            "explored": GoalStatus.EXPLORED,
            "deferred": GoalStatus.DEFERRED,
            "declined": GoalStatus.DECLINED,
        }

        if outcome not in status_map:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Invalid outcome '{outcome}'. Valid options: explored, deferred, declined",
                is_error=True
            )

        status = status_map[outcome]

        # Enforce minimum interactions for "explored"
        if status == GoalStatus.EXPLORED and new_count < min_interactions:
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=(
                    f"Cannot mark as 'explored' - only {new_count} interaction(s) "
                    f"(minimum: {min_interactions}). Continue exploring, or use 'deferred'."
                ),
                is_error=True
            )

        # Resolve and get next goal
        if next_topic:
            # MODE 3: AI specifies next topic
            new_goal = engine.resolve_current_goal_with_next(status, note, next_topic)
            log_info(f"Curiosity resolved as '{outcome}', AI specified next: {next_topic[:50]}...", prefix="🔍")
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Resolved as '{outcome}'. New curiosity (your choice): {new_goal.content[:80]}..."
            )
        else:
            # MODE 2: System selects next
            new_goal = engine.resolve_current_goal(status, note)
            log_info(f"Curiosity resolved as '{outcome}', system selected next", prefix="🔍")
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Resolved as '{outcome}'. New curiosity: {new_goal.content[:80]}..."
            )

    except Exception as e:
        log_error(f"Error in advance_curiosity: {e}")
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Error advancing curiosity: {str(e)}",
            is_error=True
        )


def _emit_curiosity_progress(
    goal, interaction_count: int, min_interactions: int, note: str
) -> None:
    """Emit curiosity progress update to DEV window."""
    if not config.DEV_MODE_ENABLED:
        return

    try:
        from interface.dev_events import emit_curiosity_update

        goal_dict = {
            "id": goal.id,
            "content": f"{goal.content} (Progress: {interaction_count}/{min_interactions})",
            "category": goal.category,
            "context": f"Last note: {note}" if note else goal.context,
            "activated_at": goal.activated_at.isoformat() if goal.activated_at else ""
        }

        emit_curiosity_update(
            current_goal=goal_dict,
            history=[],
            cooldowns=[],
            event="interaction"
        )
    except Exception:
        pass  # Don't let DEV window issues break tool execution
