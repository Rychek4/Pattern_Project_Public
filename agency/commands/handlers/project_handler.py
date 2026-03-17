"""
Pattern Project - Project Tool Handlers
Handles manage_project and manage_project_actions tool calls.

Extracted as standalone functions following the growth_thread_handler pattern.
"""

from typing import Any, Dict


def _format_project(project) -> str:
    """Format a project for display in tool results."""
    total = len(project.actions)
    completed = sum(1 for a in project.actions if a.status == 'completed')
    in_progress = sum(1 for a in project.actions if a.status == 'in_progress')
    pending = sum(1 for a in project.actions if a.status == 'pending')

    lines = [
        f"Project: {project.name} (id={project.id})",
        f"Status: {project.status}",
        f"Description: {project.description}",
        f"Progress: {completed}/{total} actions completed",
    ]

    if project.abandonment_reason:
        lines.append(f"Abandonment reason: {project.abandonment_reason}")

    if project.actions:
        lines.append("")
        lines.append("Actions:")
        for a in project.actions:
            status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}[a.status]
            line = f"  {status_icon} (id={a.id}) {a.description}"
            if a.notes:
                line += f" — notes: {a.notes}"
            lines.append(line)

    return "\n".join(lines)


def exec_manage_project(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Handle manage_project tool calls."""
    from agency.tools.executor import ToolResult
    from agency.projects import get_project_manager

    tool_name = "manage_project"
    operation = input.get("operation", "")
    manager = get_project_manager()

    if operation == "create":
        name = input.get("name", "")
        description = input.get("description", "")
        actions = input.get("actions")

        if not name:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'name' is required for create.", is_error=True
            )
        if not description:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'description' is required for create.", is_error=True
            )

        project, error = manager.create(name, description, actions)
        if error:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Project created.\n\n{_format_project(project)}"
        )

    elif operation == "get":
        project_id = input.get("project_id")
        if project_id is None:
            # Default to active project
            project = manager.get_active()
            if project is None:
                return ToolResult(
                    tool_use_id=tool_use_id, tool_name=tool_name,
                    content="No active project found."
                )
        else:
            project = manager.get(project_id)
            if project is None:
                return ToolResult(
                    tool_use_id=tool_use_id, tool_name=tool_name,
                    content=f"No project found with id {project_id}.", is_error=True
                )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=_format_project(project)
        )

    elif operation == "update":
        project_id = input.get("project_id")
        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for update.", is_error=True
            )
        success, error = manager.update(
            project_id,
            name=input.get("name"),
            description=input.get("description")
        )
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        project = manager.get(project_id)
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Project updated.\n\n{_format_project(project)}"
        )

    elif operation == "complete":
        project_id = input.get("project_id")
        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for complete.", is_error=True
            )
        success, error = manager.complete(project_id)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Project {project_id} marked as completed."
        )

    elif operation == "abandon":
        project_id = input.get("project_id")
        reason = input.get("reason", "")
        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for abandon.", is_error=True
            )
        if not reason:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'reason' is required for abandon.", is_error=True
            )
        success, error = manager.abandon(project_id, reason)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Project {project_id} abandoned. Reason: {reason}"
        )

    elif operation == "pause":
        project_id = input.get("project_id")
        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for pause.", is_error=True
            )
        success, error = manager.pause(project_id)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Project {project_id} paused."
        )

    elif operation == "resume":
        project_id = input.get("project_id")
        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for resume.", is_error=True
            )
        success, error = manager.resume(project_id)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        project = manager.get(project_id)
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Project resumed.\n\n{_format_project(project)}"
        )

    else:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Error: Unknown operation '{operation}'. "
                    f"Valid: create, update, get, complete, abandon, pause, resume",
            is_error=True
        )


def exec_manage_project_actions(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Handle manage_project_actions tool calls."""
    from agency.tools.executor import ToolResult
    from agency.projects import get_project_manager

    tool_name = "manage_project_actions"
    operation = input.get("operation", "")
    manager = get_project_manager()

    if operation == "add":
        project_id = input.get("project_id")
        description = input.get("description", "")
        notes = input.get("notes")

        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for add.", is_error=True
            )
        if not description:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'description' is required for add.", is_error=True
            )

        action_id, error = manager.add_action(project_id, description, notes)
        if error:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Action added (id={action_id}): {description}"
        )

    elif operation == "update":
        action_id = input.get("action_id")
        if action_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'action_id' is required for update.", is_error=True
            )
        success, error = manager.update_action(
            action_id,
            description=input.get("description"),
            notes=input.get("notes"),
            status=input.get("status")
        )
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Action {action_id} updated."
        )

    elif operation == "remove":
        action_id = input.get("action_id")
        if action_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'action_id' is required for remove.", is_error=True
            )
        success, error = manager.remove_action(action_id)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Action {action_id} removed."
        )

    elif operation == "reorder":
        project_id = input.get("project_id")
        action_ids = input.get("action_ids")
        if project_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'project_id' is required for reorder.", is_error=True
            )
        if not action_ids or not isinstance(action_ids, list):
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'action_ids' (list of ints) is required for reorder.", is_error=True
            )
        success, error = manager.reorder_actions(project_id, action_ids)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Actions reordered for project {project_id}."
        )

    elif operation == "complete":
        action_id = input.get("action_id")
        if action_id is None:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content="Error: 'action_id' is required for complete.", is_error=True
            )
        success, error = manager.complete_action(action_id)
        if not success:
            return ToolResult(
                tool_use_id=tool_use_id, tool_name=tool_name,
                content=f"Error: {error}", is_error=True
            )
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Action {action_id} completed."
        )

    else:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Error: Unknown operation '{operation}'. "
                    f"Valid: add, update, remove, reorder, complete",
            is_error=True
        )
