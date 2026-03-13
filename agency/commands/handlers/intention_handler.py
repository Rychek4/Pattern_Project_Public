"""
Pattern Project - Intention Command Handlers
Handles create_reminder, complete_reminder, dismiss_reminder, and list_reminders native tools.
"""

from datetime import datetime
from typing import Optional

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType
from agency.intentions import (
    get_intention_manager,
    get_trigger_engine,
    parse_time_expression,
    format_trigger_time,
    format_relative_past,
    IntentionType,
)
from core.temporal import get_temporal_tracker


class RemindHandler(CommandHandler):
    """
    Handles reminder creation via the create_reminder native tool.

    Called by ToolExecutor when the AI invokes the create_reminder tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Create a reminder from the command.

        Args:
            query: The extracted query (e.g., "in 2 hours | ask about meeting")
            context: Session context

        Returns:
            CommandResult with creation outcome
        """
        manager = get_intention_manager()

        # Parse the query: when | what | context (optional)
        parts = [p.strip() for p in query.split('|')]

        if len(parts) < 2:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message="Missing 'what' part - reminder needs both when and what",
                    expected_format="create_reminder with when and what parameters",
                    example="create_reminder(when='in 2 hours', what='ask about the meeting')"
                )
            )

        when_str = parts[0]
        what = parts[1]
        intention_context = parts[2] if len(parts) > 2 else None

        # Parse the time expression
        trigger_at, trigger_type = parse_time_expression(when_str)

        # For time-based triggers, we need a valid datetime
        if trigger_type == 'time' and trigger_at is None:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.PARSE_ERROR,
                    message=f"Could not parse time expression: '{when_str}'",
                    expected_format="Use relative time like 'in X minutes/hours' or 'tomorrow morning'",
                    example="create_reminder(when='in 30 minutes', what='check on the build')"
                )
            )

        # Get current session ID if available
        session_id = None
        try:
            tracker = get_temporal_tracker()
            session_id = tracker.session_id
        except Exception:
            pass

        # Create the intention
        intention_id = manager.create_intention(
            intention_type=IntentionType.REMINDER.value,
            content=what,
            trigger_type=trigger_type,
            trigger_at=trigger_at,
            context=intention_context,
            priority=5,
            source_session_id=session_id
        )

        if intention_id:
            when_display = format_trigger_time(trigger_at, trigger_type)
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data={"intention_id": intention_id, "trigger_at": trigger_at},
                needs_continuation=False,
                display_text=f"Reminder set: {what} ({when_display})"
            )
        else:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message="Failed to create reminder in database",
                    expected_format=None,
                    example=None
                )
            )


class CompleteHandler(CommandHandler):
    """
    Handles intention completion via the complete_reminder native tool.

    Called by ToolExecutor when the AI invokes the complete_reminder tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Complete an intention.

        Args:
            query: "I-id | outcome" or just "I-id"
            context: Session context

        Returns:
            CommandResult with completion outcome
        """
        manager = get_intention_manager()

        # Parse: I-id | outcome (optional)
        parts = [p.strip() for p in query.split('|')]
        id_part = parts[0]
        outcome = parts[1] if len(parts) > 1 else None

        # Extract the ID number
        try:
            # Handle both "I-42" and "42" formats
            if id_part.upper().startswith('I-'):
                intention_id = int(id_part[2:])
            else:
                intention_id = int(id_part)
        except ValueError:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message=f"Invalid intention ID: '{id_part}' is not a valid number",
                    expected_format="complete_reminder with reminder_id (integer) and outcome parameters",
                    example="complete_reminder(reminder_id=42, outcome='task completed successfully')"
                )
            )

        # Get the intention to check it exists
        intention = manager.get_intention(intention_id)
        if not intention:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.NOT_FOUND,
                    message=f"Intention I-{intention_id} not found - it may have been completed or dismissed already",
                    expected_format=None,
                    example=None
                )
            )

        # Complete it
        success = manager.complete_intention(intention_id, outcome)

        if success:
            # Create a memory from the completed intention
            self._create_memory_from_intention(intention, outcome)

            return CommandResult(
                command_name=self.command_name,
                query=query,
                data={"intention_id": intention_id, "outcome": outcome},
                needs_continuation=False,
                display_text=f"Completed intention I-{intention_id}"
            )
        else:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Failed to complete intention I-{intention_id} in database",
                    expected_format=None,
                    example=None
                )
            )

    def _create_memory_from_intention(self, intention, outcome: Optional[str]) -> None:
        """Create a memory from a completed intention."""
        try:
            from memory.vector_store import get_vector_store
            from core.embeddings import is_model_loaded

            if not is_model_loaded():
                return

            vector_store = get_vector_store()

            # Build memory content
            if outcome:
                content = f"Followed up: {intention.content} — {outcome}"
            else:
                content = f"Followed up on: {intention.content}"

            # Add context if available
            if intention.context:
                content += f" (originally noted because: {intention.context})"

            vector_store.add_memory(
                content=content,
                source_conversation_ids=[],
                source_session_id=intention.source_session_id,
                importance=0.5,
                memory_type="event",
                decay_category="standard"
            )

        except Exception:
            # Don't fail the complete if memory creation fails
            pass


class DismissHandler(CommandHandler):
    """
    Handles intention dismissal via the dismiss_reminder native tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """Dismiss an intention."""
        manager = get_intention_manager()

        # Extract the ID number
        id_part = query.strip()
        try:
            if id_part.upper().startswith('I-'):
                intention_id = int(id_part[2:])
            else:
                intention_id = int(id_part)
        except ValueError:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message=f"Invalid intention ID: '{id_part}' is not a valid number",
                    expected_format="dismiss_reminder with reminder_id (integer) parameter",
                    example="dismiss_reminder(reminder_id=42)"
                )
            )

        success = manager.dismiss_intention(intention_id)

        if success:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data={"intention_id": intention_id},
                needs_continuation=False,
                display_text=f"Dismissed intention I-{intention_id}"
            )
        else:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.NOT_FOUND,
                    message=f"Intention I-{intention_id} not found or already dismissed",
                    expected_format=None,
                    example=None
                )
            )


class ListIntentionsHandler(CommandHandler):
    """
    Handles listing active intentions via the list_reminders native tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """Get all active intentions."""
        engine = get_trigger_engine()
        now = datetime.now()

        summary = engine.get_context_summary(now)

        return CommandResult(
            command_name=self.command_name,
            query="list all",
            data=summary,
            needs_continuation=True,
            display_text="Reviewing intentions..."
        )

    def format_result(self, result: CommandResult) -> str:
        """Format the intention list for continuation prompt."""
        if result.error:
            return f"  Error: {result.error}"

        summary = result.data
        if not summary:
            return "  No intentions data available."

        triggered = summary.get("triggered", [])
        pending = summary.get("pending", [])

        if not triggered and not pending:
            return "  You have no active intentions."

        lines = ["  Your active intentions:"]
        now = datetime.now()

        if triggered:
            lines.append("")
            lines.append("  TRIGGERED (due now):")
            for i in triggered:
                age = format_relative_past(i.created_at, now)
                ctx = f" — Context: {i.context}" if i.context else ""
                lines.append(f"    [I-{i.id}] {i.content} (set {age}){ctx}")

        if pending:
            lines.append("")
            lines.append("  PENDING:")
            for i in pending:
                when = format_trigger_time(i.trigger_at, i.trigger_type, now)
                ctx = f" — Context: {i.context}" if i.context else ""
                lines.append(f"    [I-{i.id}] {i.content} (due {when}){ctx}")

        return "\n".join(lines)

