"""Intention/reminder tool definitions."""

from typing import Any, Dict

CREATE_REMINDER_TOOL: Dict[str, Any] = {
    "name": "create_reminder",
    "description": """Create a reminder that triggers an autonomous pulse at a specific time or next session.

When a reminder becomes due, the system fires a dedicated reminder pulse — an autonomous
turn where you receive the reminder content and have full tool access (web search, file
operations, memory, Telegram, etc.). This happens even if the user is idle or offline.

This means reminders are not just notifications — they are scheduled autonomous actions.
You can set a reminder to research a topic, check on something, draft a message, or
perform any multi-step task when the time comes.

Use this when:
- You want to take an autonomous action at a future time (research, check-in, notify)
- User mentions an upcoming event or deadline worth following up on
- A topic deserves deeper exploration later when you have a pulse to yourself
- You want to chain work: set a reminder, do part of the task when it fires, set another

Your reminders are private — the user won't see them until you choose to act on them.

Time formats supported:
- Relative: "in 30 minutes", "in 2 hours", "in 3 days"
- Named: "tomorrow", "tomorrow morning", "tomorrow evening", "tonight"
- Session: "next session" (triggers when user returns)""",
    "input_schema": {
        "type": "object",
        "properties": {
            "when": {
                "type": "string",
                "description": "When to trigger: 'in X minutes/hours/days', 'tomorrow', 'tomorrow morning', 'tonight', or 'next session'"
            },
            "what": {
                "type": "string",
                "description": "What to remember or follow up on"
            },
            "context": {
                "type": "string",
                "description": "Optional context about why this reminder was created - helps when it triggers"
            }
        },
        "required": ["when", "what"]
    }
}

COMPLETE_REMINDER_TOOL: Dict[str, Any] = {
    "name": "complete_reminder",
    "description": """Mark a reminder as completed with an optional outcome note.

Use this after you've addressed a triggered reminder — whether during a reminder pulse
or a regular conversation. The outcome note is extracted into a persistent memory, so
future sessions can recall what happened and what you learned.

Always complete reminders you've acted on. Leaving them triggered clutters your
intention context and signals unfinished commitments in future pulses.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "integer",
                "description": "The reminder ID number (the number from I-42, not the full 'I-42' string)"
            },
            "outcome": {
                "type": "string",
                "description": "Optional note about how the follow-up went or what you learned"
            }
        },
        "required": ["reminder_id"]
    }
}

DISMISS_REMINDER_TOOL: Dict[str, Any] = {
    "name": "dismiss_reminder",
    "description": """Cancel a reminder without completing it. No memory is created.

Use when circumstances have changed and the reminder is no longer relevant, or when
you consciously decide not to act on a triggered intention. Dismissing is a deliberate
choice — it removes the reminder from your active intentions cleanly.

Prefer complete_reminder when you did act on it (even partially) so the outcome
is captured in memory. Use dismiss when the reminder is truly obsolete.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "integer",
                "description": "The reminder ID number to dismiss"
            }
        },
        "required": ["reminder_id"]
    }
}

LIST_REMINDERS_TOOL: Dict[str, Any] = {
    "name": "list_reminders",
    "description": """List all active reminders with their IDs, statuses, trigger times, and content.

Returns both triggered (due now) and pending (scheduled for later) reminders.
Each entry includes: intention ID, content, status, trigger type, and scheduled time.

Use this to:
- Review your outstanding commitments before creating new ones
- Find reminder IDs for completing or dismissing
- Check timing of upcoming reminders to avoid scheduling conflicts
- Audit your intentions during a pulse to decide what still matters""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
