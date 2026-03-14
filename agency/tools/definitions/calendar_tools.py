"""Google Calendar tool definitions."""

from typing import Any, Dict

LIST_CALENDAR_EVENTS_TOOL: Dict[str, Any] = {
    "name": "list_calendar_events",
    "description": """List events from the user's Google Calendar within a date range.

Use this when:
- The user asks about their schedule, agenda, or upcoming events
- You need to check for scheduling conflicts before creating an event
- The user asks "what's on my calendar" for a specific day or range

Events are returned in chronological order. Recurring events are automatically
expanded into individual instances within the queried range, each with its own
event_id (use this ID for updates/deletions of specific instances).

Date format: ISO 8601 (e.g., "2025-03-15T00:00:00" or "2025-03-15").
Omitting the time component defaults to midnight.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Start of date range in ISO 8601 format (e.g., '2025-03-01T00:00:00')"
            },
            "end_date": {
                "type": "string",
                "description": "End of date range in ISO 8601 format (e.g., '2025-03-31T23:59:59')"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default 50)",
                "minimum": 1,
                "maximum": 250
            }
        },
        "required": ["start_date", "end_date"]
    }
}

CREATE_CALENDAR_EVENT_TOOL: Dict[str, Any] = {
    "name": "create_calendar_event",
    "description": """Create a new event on the user's Google Calendar.

Use this when:
- The user asks to add, schedule, or create a calendar event
- You need to set a meeting, appointment, or time block

For recurring events, use the recurrence parameter with an RFC 5733 RRULE string.
Examples:
  "RRULE:FREQ=WEEKLY;BYDAY=TU,TH" — every Tuesday and Thursday
  "RRULE:FREQ=MONTHLY;BYMONTHDAY=15" — 15th of every month
  "RRULE:FREQ=DAILY;COUNT=5" — daily for 5 days
  "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20250630T000000Z" — MWF until June 30

For all-day events, use date-only format (e.g., "2025-03-15") for start and end.
The end date for all-day events is exclusive (end="2025-03-16" means a single-day event on March 15).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Event title/summary"
            },
            "start_time": {
                "type": "string",
                "description": "Start time in ISO 8601 format (e.g., '2025-03-15T10:00:00' or '2025-03-15' for all-day)"
            },
            "end_time": {
                "type": "string",
                "description": "End time in ISO 8601 format (e.g., '2025-03-15T11:00:00' or '2025-03-16' for all-day)"
            },
            "description": {
                "type": "string",
                "description": "Optional event description or notes"
            },
            "location": {
                "type": "string",
                "description": "Optional event location (address or place name)"
            },
            "recurrence": {
                "type": "string",
                "description": "Optional RFC 5733 RRULE string for recurring events (e.g., 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR')"
            },
            "reminders": {
                "type": "array",
                "description": "Optional list of reminders for this event. Each item has 'method' ('popup' or 'email') and 'minutes' (minutes before event start). Max 5 entries. If omitted, defaults to a 30-minute and 10-minute popup reminder. Set to an empty list [] to create the event with no reminders.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["popup", "email"],
                            "description": "Reminder method: 'popup' for a notification or 'email' for an email reminder"
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Minutes before the event start to trigger the reminder"
                        }
                    },
                    "required": ["method", "minutes"]
                }
            }
        },
        "required": ["title", "start_time", "end_time"]
    }
}

UPDATE_CALENDAR_EVENT_TOOL: Dict[str, Any] = {
    "name": "update_calendar_event",
    "description": """Update an existing event on the user's Google Calendar.

Use this when:
- The user wants to reschedule, rename, or modify a calendar event
- You need to change the time, title, description, or location of an event

You must provide the event_id (obtained from list_calendar_events).
Only include the fields you want to change — unchanged fields are preserved.

For recurring events:
- update_scope="this_event" (default): Updates only this specific instance
- update_scope="all_events": Updates the entire recurring series

To change recurrence rules, use update_scope="all_events" and provide a new
recurrence RRULE string. To remove recurrence (make it a single event),
set recurrence to an empty string with update_scope="all_events".""",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "The event ID to update (from list_calendar_events results)"
            },
            "title": {
                "type": "string",
                "description": "New event title (if changing)"
            },
            "start_time": {
                "type": "string",
                "description": "New start time in ISO 8601 format (if changing)"
            },
            "end_time": {
                "type": "string",
                "description": "New end time in ISO 8601 format (if changing)"
            },
            "description": {
                "type": "string",
                "description": "New event description (if changing)"
            },
            "location": {
                "type": "string",
                "description": "New event location (if changing)"
            },
            "recurrence": {
                "type": "string",
                "description": "New RRULE string (if changing recurrence). Empty string removes recurrence."
            },
            "update_scope": {
                "type": "string",
                "enum": ["this_event", "all_events"],
                "description": "Scope of update for recurring events: 'this_event' (default) or 'all_events' for entire series"
            },
            "reminders": {
                "type": "array",
                "description": "Optional updated reminders. Each item has 'method' ('popup' or 'email') and 'minutes' (minutes before event start). Max 5 entries. Set to an empty list [] to remove all reminders.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["popup", "email"],
                            "description": "Reminder method: 'popup' for a notification or 'email' for an email reminder"
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Minutes before the event start to trigger the reminder"
                        }
                    },
                    "required": ["method", "minutes"]
                }
            }
        },
        "required": ["event_id"]
    }
}

DELETE_CALENDAR_EVENT_TOOL: Dict[str, Any] = {
    "name": "delete_calendar_event",
    "description": """Delete an event from the user's Google Calendar.

Use this when:
- The user asks to remove, cancel, or delete a calendar event
- An event has been cancelled and should be removed from the calendar

You must provide the event_id (obtained from list_calendar_events).

For recurring events:
- delete_scope="this_event" (default): Deletes only this specific instance
- delete_scope="all_events": Deletes the entire recurring series

Always confirm with the user before deleting events, especially recurring series.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "The event ID to delete (from list_calendar_events results)"
            },
            "delete_scope": {
                "type": "string",
                "enum": ["this_event", "all_events"],
                "description": "Scope of deletion for recurring events: 'this_event' (default) or 'all_events' for entire series"
            }
        },
        "required": ["event_id"]
    }
}
