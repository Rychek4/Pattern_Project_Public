"""Project tool definitions.

Two tools for managing structured multi-step projects:
- manage_project: Project lifecycle (create, update, complete, abandon, pause, resume, get)
- manage_project_actions: Action CRUD (add, update, remove, reorder, complete)
"""

from typing import Any, Dict

MANAGE_PROJECT_TOOL: Dict[str, Any] = {
    "name": "manage_project",
    "description": """Manage a structured multi-step project.

Projects track concrete deliverables with ordered actions. Use this to plan and
track multi-step work that spans multiple conversations.

Operations:
- create: Start a new project with a name, description, and optional initial actions.
- update: Edit a project's name or description.
- get: View the current state of a project (actions, progress).
- complete: Mark a project as done.
- abandon: Stop working on a project (requires a reason — learn from it).
- pause: Park an active project to work on something else.
- resume: Reactivate a paused project.

Only one active project at a time. Pause or complete the current one before starting another.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "update", "get", "complete", "abandon", "pause", "resume"],
                "description": "The operation to perform"
            },
            "project_id": {
                "type": "integer",
                "description": "Project ID (required for all operations except 'create'). Omit for 'create'."
            },
            "name": {
                "type": "string",
                "description": "Project name (required for 'create', optional for 'update')"
            },
            "description": {
                "type": "string",
                "description": "What this project is about (required for 'create', optional for 'update')"
            },
            "actions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Initial action descriptions in order (optional, only for 'create')"
            },
            "reason": {
                "type": "string",
                "description": "Why you're abandoning this project (required for 'abandon')"
            }
        },
        "required": ["operation"]
    }
}

MANAGE_PROJECT_ACTIONS_TOOL: Dict[str, Any] = {
    "name": "manage_project_actions",
    "description": """Manage actions (steps) within a project.

Actions are the individual steps that make up a project. Each has a description,
optional notes, a status (pending/in_progress/completed), and a sort order.

Operations:
- add: Add a new action to the project.
- update: Edit an action's description, notes, or status.
- remove: Delete an action from the project.
- reorder: Rearrange action order by providing action IDs in desired sequence.
- complete: Mark an action as completed (shorthand for update with status=completed).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "update", "remove", "reorder", "complete"],
                "description": "The operation to perform"
            },
            "project_id": {
                "type": "integer",
                "description": "Project ID (required for 'add' and 'reorder')"
            },
            "action_id": {
                "type": "integer",
                "description": "Action ID (required for 'update', 'remove', 'complete')"
            },
            "description": {
                "type": "string",
                "description": "Action description (required for 'add', optional for 'update')"
            },
            "notes": {
                "type": "string",
                "description": "Notes on progress or approach (optional for 'add' and 'update')"
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "completed"],
                "description": "Action status (optional for 'update')"
            },
            "action_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Ordered list of all action IDs (required for 'reorder')"
            }
        },
        "required": ["operation"]
    }
}
