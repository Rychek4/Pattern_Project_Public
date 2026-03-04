"""
Pattern Project - Google Calendar Command Handlers
Handles calendar operations via the Google Calendar API native tools.

NOTE: These handlers are DISABLED by default. Enable via GOOGLE_CALENDAR_ENABLED config.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class ListCalendarEventsHandler(CommandHandler):
    """
    Handles listing calendar events via the list_calendar_events native tool.

    Queries the user's primary Google Calendar for events within a date range.
    Recurring events are automatically expanded into individual instances.

    Called by ToolExecutor when the AI invokes the list_calendar_events tool.
    """

    @property
    def command_name(self) -> str:
        return "LIST_CALENDAR_EVENTS"

    @property
    def pattern(self) -> str:
        return r'\[\[LIST_CALENDAR_EVENTS:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        List calendar events in a date range.

        Args:
            query: "start_date | end_date | max_results" format
            context: Session context (unused)

        Returns:
            CommandResult with list of events
        """
        from config import GOOGLE_CALENDAR_ENABLED

        if not GOOGLE_CALENDAR_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Google Calendar disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Google Calendar is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        # Parse query
        parts = [p.strip() for p in query.split("|")]
        if len(parts) < 2:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Invalid query format",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message="list_calendar_events requires start_date and end_date",
                    expected_format="start_date | end_date | max_results (optional)",
                    example="2025-03-01T00:00:00 | 2025-03-31T23:59:59"
                )
            )

        start_date = parts[0]
        end_date = parts[1]
        max_results = 50
        if len(parts) > 2 and parts[2]:
            try:
                max_results = int(parts[2])
            except ValueError:
                pass

        # Call gateway
        try:
            from communication.calendar_gateway import get_calendar_gateway

            gateway = get_calendar_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Calendar not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Google Calendar credentials not found. Place Calendar_Google_Credentials.json in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.list_events(
                start_date=start_date,
                end_date=end_date,
                max_results=max_results,
            )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to list events",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
                        expected_format=None,
                        example=None
                    )
                )

        except RuntimeError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Calendar gateway not initialized: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error listing events: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can list calendar events by including this command in your response:
  [[LIST_CALENDAR_EVENTS: start_date | end_date]]

Use this when:
- The user asks about their schedule or calendar
- You need to check for scheduling conflicts before creating events"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  No events found in the specified date range."

        events = result.data
        lines = [f"  Found {len(events)} event(s):"]
        for event in events:
            title = event.get("title", "(No title)")
            start = event.get("start", "")
            end = event.get("end", "")
            line = f"  - {title}: {start} to {end}"
            if event.get("location"):
                line += f" @ {event['location']}"
            if event.get("recurring_event_id"):
                line += " (recurring)"
            lines.append(line)

        return "\n".join(lines)


class CreateCalendarEventHandler(CommandHandler):
    """
    Handles creating calendar events via the create_calendar_event native tool.

    Creates events on the user's primary Google Calendar with optional
    recurrence rules, descriptions, and locations.

    Called by ToolExecutor when the AI invokes the create_calendar_event tool.
    """

    @property
    def command_name(self) -> str:
        return "CREATE_CALENDAR_EVENT"

    @property
    def pattern(self) -> str:
        return r'\[\[CREATE_CALENDAR_EVENT:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Create a calendar event.

        Args:
            query: "title | start_time | end_time | description | location | recurrence" format
            context: Session context (unused)

        Returns:
            CommandResult with created event data
        """
        from config import GOOGLE_CALENDAR_ENABLED

        if not GOOGLE_CALENDAR_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Google Calendar disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Google Calendar is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        # Parse query
        parts = [p.strip() for p in query.split("|")]
        if len(parts) < 3:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Invalid event format",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message="create_calendar_event requires title, start_time, and end_time",
                    expected_format="title | start_time | end_time | description | location | recurrence",
                    example="Team Meeting | 2025-03-15T10:00:00 | 2025-03-15T11:00:00"
                )
            )

        title = parts[0]
        start_time = parts[1]
        end_time = parts[2]
        description = parts[3] if len(parts) > 3 else ""
        location = parts[4] if len(parts) > 4 else ""
        recurrence = parts[5] if len(parts) > 5 else ""

        if not title:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing event title",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="Event title cannot be empty",
                    expected_format=None,
                    example=None
                )
            )

        # Call gateway
        try:
            from communication.calendar_gateway import get_calendar_gateway

            gateway = get_calendar_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Calendar not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Google Calendar credentials not found. Place Calendar_Google_Credentials.json in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.create_event(
                title=title,
                start_time=start_time,
                end_time=end_time,
                description=description,
                location=location,
                recurrence=recurrence,
            )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to create event",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
                        expected_format=None,
                        example=None
                    )
                )

        except RuntimeError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Calendar gateway not initialized: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error creating event: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can create a calendar event by including this command in your response:
  [[CREATE_CALENDAR_EVENT: title | start_time | end_time | description | location | recurrence]]

Use this when:
- The user asks you to add something to their calendar
- You need to schedule a meeting, appointment, or reminder"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Event created."

        data = result.data
        title = data.get("title", "")
        start = data.get("start", "")
        end = data.get("end", "")
        event_id = data.get("event_id", "")

        lines = [
            f"  Event created: {title}",
            f"  Start: {start}",
            f"  End: {end}",
            f"  ID: {event_id}",
        ]

        if data.get("location"):
            lines.append(f"  Location: {data['location']}")
        if data.get("recurrence"):
            lines.append(f"  Recurrence: {data['recurrence']}")

        return "\n".join(lines)


class UpdateCalendarEventHandler(CommandHandler):
    """
    Handles updating calendar events via the update_calendar_event native tool.

    Updates existing events on the user's primary Google Calendar.
    Supports updating single instances or entire recurring series.

    Called by ToolExecutor when the AI invokes the update_calendar_event tool.
    """

    @property
    def command_name(self) -> str:
        return "UPDATE_CALENDAR_EVENT"

    @property
    def pattern(self) -> str:
        return r'\[\[UPDATE_CALENDAR_EVENT:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Update a calendar event.

        Args:
            query: Pipe-delimited string with event_id and changed fields
            context: Session context containing parsed fields from executor

        Returns:
            CommandResult with updated event data
        """
        from config import GOOGLE_CALENDAR_ENABLED

        if not GOOGLE_CALENDAR_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Google Calendar disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Google Calendar is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        # The executor passes the full params dict via context for update/delete
        # because pipe-delimited parsing doesn't work well for optional fields
        params = context.get("calendar_params", {})
        event_id = params.get("event_id", "")

        if not event_id:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing event ID",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="event_id is required to update a calendar event",
                    expected_format=None,
                    example=None
                )
            )

        # Call gateway
        try:
            from communication.calendar_gateway import get_calendar_gateway

            gateway = get_calendar_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Calendar not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Google Calendar credentials not found. Place Calendar_Google_Credentials.json in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.update_event(
                event_id=event_id,
                title=params.get("title"),
                start_time=params.get("start_time"),
                end_time=params.get("end_time"),
                description=params.get("description"),
                location=params.get("location"),
                recurrence=params.get("recurrence"),
                update_scope=params.get("update_scope", "this_event"),
            )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to update event",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
                        expected_format=None,
                        example=None
                    )
                )

        except RuntimeError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Calendar gateway not initialized: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error updating event: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can update a calendar event by including this command in your response:
  [[UPDATE_CALENDAR_EVENT: event_id | fields to change]]

Use this when:
- The user wants to reschedule, rename, or modify an existing event"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Event updated."

        data = result.data
        title = data.get("title", "")
        start = data.get("start", "")
        end = data.get("end", "")

        return f"  Updated: {title}\n  Start: {start}\n  End: {end}"


class DeleteCalendarEventHandler(CommandHandler):
    """
    Handles deleting calendar events via the delete_calendar_event native tool.

    Deletes events from the user's primary Google Calendar.
    Supports deleting single instances or entire recurring series.

    Called by ToolExecutor when the AI invokes the delete_calendar_event tool.
    """

    @property
    def command_name(self) -> str:
        return "DELETE_CALENDAR_EVENT"

    @property
    def pattern(self) -> str:
        return r'\[\[DELETE_CALENDAR_EVENT:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Delete a calendar event.

        Args:
            query: The event_id string
            context: Session context containing parsed fields from executor

        Returns:
            CommandResult with deletion confirmation
        """
        from config import GOOGLE_CALENDAR_ENABLED

        if not GOOGLE_CALENDAR_ENABLED:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Google Calendar disabled",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Google Calendar is disabled in configuration",
                    expected_format=None,
                    example=None
                )
            )

        # The executor passes params via context
        params = context.get("calendar_params", {})
        event_id = params.get("event_id", query.strip())
        delete_scope = params.get("delete_scope", "this_event")

        if not event_id:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Missing event ID",
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message="event_id is required to delete a calendar event",
                    expected_format=None,
                    example=None
                )
            )

        # Call gateway
        try:
            from communication.calendar_gateway import get_calendar_gateway

            gateway = get_calendar_gateway()

            if not gateway.is_available():
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Calendar not configured",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message="Google Calendar credentials not found. Place Calendar_Google_Credentials.json in data/.",
                        expected_format=None,
                        example=None
                    )
                )

            result = gateway.delete_event(
                event_id=event_id,
                delete_scope=delete_scope,
            )

            if result.success:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=result.data,
                    needs_continuation=True,
                    display_text=result.message,
                )
            else:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text="Failed to delete event",
                    error=ToolError(
                        error_type=ToolErrorType.SYSTEM_ERROR,
                        message=result.message,
                        expected_format=None,
                        example=None
                    )
                )

        except RuntimeError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar gateway error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Calendar gateway not initialized: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Calendar error",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Unexpected error deleting event: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        return """You can delete a calendar event by including this command in your response:
  [[DELETE_CALENDAR_EVENT: event_id]]

Use this when:
- The user asks you to remove or cancel an event from their calendar"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Event deleted."

        data = result.data
        event_id = data.get("event_id", "")
        scope = data.get("scope", "this_event")

        if scope == "all_events":
            return f"  Deleted recurring series: {event_id}"
        return f"  Deleted event: {event_id}"
