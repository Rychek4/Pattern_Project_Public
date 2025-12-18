"""
Pattern Project - Tool Executor
Maps native tool calls to existing command handlers.

This module bridges Claude's native tool use with the existing handler infrastructure.
Each tool call is routed to the appropriate handler, reusing all existing logic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Callable, TYPE_CHECKING

from core.logger import log_info, log_warning, log_error
import config

if TYPE_CHECKING:
    from agency.visual_capture import ImageContent


@dataclass
class ToolResult:
    """Result from executing a tool."""
    tool_use_id: str
    tool_name: str
    content: Any  # Result data (will be formatted as string for Claude)
    is_error: bool = False
    image_data: Optional[List["ImageContent"]] = field(default=None)

    def has_images(self) -> bool:
        """Check if result includes images."""
        return self.image_data is not None and len(self.image_data) > 0


class ToolExecutor:
    """
    Executes tool calls by routing to existing handlers.

    This class maps tool names to handler execution functions.
    Each function wraps an existing CommandHandler, adapting the
    structured tool input to the handler's expected format.
    """

    def __init__(self):
        """Initialize the executor with tool-to-handler mappings."""
        # Map tool names to execution methods
        self._handlers: Dict[str, Callable] = {
            "search_memories": self._exec_search_memories,
            "create_reminder": self._exec_create_reminder,
            "complete_reminder": self._exec_complete_reminder,
            "dismiss_reminder": self._exec_dismiss_reminder,
            "list_reminders": self._exec_list_reminders,
            "read_file": self._exec_read_file,
            "write_file": self._exec_write_file,
            "append_file": self._exec_append_file,
            "list_files": self._exec_list_files,
            "send_telegram": self._exec_send_telegram,
            "send_email": self._exec_send_email,
            "capture_screenshot": self._exec_capture_screenshot,
            "capture_webcam": self._exec_capture_webcam,
            "set_active_thoughts": self._exec_set_active_thoughts,
            "set_pulse_interval": self._exec_set_pulse_interval,
            "advance_curiosity": self._exec_advance_curiosity,
            "resolve_curiosity": self._exec_resolve_curiosity,
            "set_conversation_style": self._exec_set_conversation_style,
        }

    def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_use_id: str,
        context: Optional[Dict] = None
    ) -> ToolResult:
        """
        Execute a tool call and return the result.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Structured input arguments from Claude
            tool_use_id: Unique ID for this tool use (for result correlation)
            context: Optional session context dict

        Returns:
            ToolResult with execution outcome
        """
        # Use 'is None' check instead of 'or {}' because empty dict is falsy
        # and 'or {}' would create a NEW dict, breaking context propagation
        if context is None:
            context = {}

        handler_fn = self._handlers.get(tool_name)
        if not handler_fn:
            log_warning(f"Unknown tool: {tool_name}")
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Unknown tool: {tool_name}. Available tools: {list(self._handlers.keys())}",
                is_error=True
            )

        try:
            log_info(f"Executing tool: {tool_name}", prefix="🔧")
            return handler_fn(tool_input, tool_use_id, context)
        except Exception as e:
            log_error(f"Tool execution error ({tool_name}): {e}")
            return ToolResult(
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                content=f"Tool execution error: {str(e)}",
                is_error=True
            )

    # =========================================================================
    # MEMORY TOOLS
    # =========================================================================

    def _exec_search_memories(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Execute memory search."""
        from agency.commands.handlers.memory_search import MemorySearchHandler

        handler = MemorySearchHandler()
        query = input.get("query", "")

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="search_memories",
                content=result.get_error_message(),
                is_error=True
            )

        # Format the result using existing formatter
        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="search_memories",
            content=formatted
        )

    # =========================================================================
    # INTENTION/REMINDER TOOLS
    # =========================================================================

    def _exec_create_reminder(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create a reminder."""
        from agency.commands.handlers.intention_handler import RemindHandler

        handler = RemindHandler()

        # Build query string in handler's expected format: "when | what | context"
        when = input.get("when", "")
        what = input.get("what", "")
        context_note = input.get("context", "")

        if context_note:
            query = f"{when} | {what} | {context_note}"
        else:
            query = f"{when} | {what}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="create_reminder",
                content=result.get_error_message(),
                is_error=True
            )

        # Return success message
        data = result.data or {}
        intention_id = data.get("intention_id", "?")
        return ToolResult(
            tool_use_id=id,
            tool_name="create_reminder",
            content=f"Reminder created (I-{intention_id}): {what}"
        )

    def _exec_complete_reminder(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Complete a reminder."""
        from agency.commands.handlers.intention_handler import CompleteHandler

        handler = CompleteHandler()

        # Build query: "I-id | outcome"
        reminder_id = input.get("reminder_id", 0)
        outcome = input.get("outcome", "")

        if outcome:
            query = f"I-{reminder_id} | {outcome}"
        else:
            query = f"I-{reminder_id}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="complete_reminder",
                content=result.get_error_message(),
                is_error=True
            )

        return ToolResult(
            tool_use_id=id,
            tool_name="complete_reminder",
            content=f"Completed reminder I-{reminder_id}"
        )

    def _exec_dismiss_reminder(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Dismiss a reminder."""
        from agency.commands.handlers.intention_handler import DismissHandler

        handler = DismissHandler()
        reminder_id = input.get("reminder_id", 0)

        result = handler.execute(f"I-{reminder_id}", ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="dismiss_reminder",
                content=result.get_error_message(),
                is_error=True
            )

        return ToolResult(
            tool_use_id=id,
            tool_name="dismiss_reminder",
            content=f"Dismissed reminder I-{reminder_id}"
        )

    def _exec_list_reminders(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List all active reminders."""
        from agency.commands.handlers.intention_handler import ListIntentionsHandler

        handler = ListIntentionsHandler()
        result = handler.execute("", ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="list_reminders",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="list_reminders",
            content=formatted
        )

    # =========================================================================
    # FILE TOOLS
    # =========================================================================

    def _exec_read_file(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Read a file."""
        from agency.commands.handlers.file_handler import ReadFileHandler

        handler = ReadFileHandler()
        filename = input.get("filename", "")

        result = handler.execute(filename, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="read_file",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="read_file",
            content=formatted
        )

    def _exec_write_file(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Write a file."""
        from agency.commands.handlers.file_handler import WriteFileHandler

        handler = WriteFileHandler()
        filename = input.get("filename", "")
        content = input.get("content", "")

        # Build query in handler's expected format: "filename | content"
        query = f"{filename} | {content}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="write_file",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="write_file",
            content=formatted
        )

    def _exec_append_file(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Append to a file."""
        from agency.commands.handlers.file_handler import AppendFileHandler

        handler = AppendFileHandler()
        filename = input.get("filename", "")
        content = input.get("content", "")

        query = f"{filename} | {content}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="append_file",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="append_file",
            content=formatted
        )

    def _exec_list_files(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List available files."""
        from agency.commands.handlers.file_handler import ListFilesHandler

        handler = ListFilesHandler()
        result = handler.execute("", ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="list_files",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="list_files",
            content=formatted
        )

    # =========================================================================
    # COMMUNICATION TOOLS
    # =========================================================================

    def _exec_send_telegram(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Send a Telegram message."""
        from agency.commands.handlers.telegram_handler import SendTelegramHandler

        handler = SendTelegramHandler()
        message = input.get("message", "")

        result = handler.execute(message, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="send_telegram",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="send_telegram",
            content=formatted
        )

    def _exec_send_email(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Send an email."""
        try:
            from agency.commands.handlers.email_handler import SendEmailHandler
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="send_email",
                content="Email handler not available",
                is_error=True
            )

        handler = SendEmailHandler()
        to = input.get("to", "")
        subject = input.get("subject", "")
        body = input.get("body", "")

        # Build query in handler's expected format: "to | subject | body"
        query = f"{to} | {subject} | {body}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="send_email",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="send_email",
            content=formatted
        )

    # =========================================================================
    # VISUAL CAPTURE TOOLS
    # =========================================================================

    def _exec_capture_screenshot(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Capture screenshot."""
        from agency.commands.handlers.visual_handler import ScreenshotHandler

        handler = ScreenshotHandler()
        result = handler.execute("", ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="capture_screenshot",
                content=result.get_error_message(),
                is_error=True
            )

        # Return with image data
        return ToolResult(
            tool_use_id=id,
            tool_name="capture_screenshot",
            content="Screenshot captured - see attached image",
            image_data=result.image_data
        )

    def _exec_capture_webcam(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Capture webcam image."""
        from agency.commands.handlers.visual_handler import WebcamHandler

        handler = WebcamHandler()
        result = handler.execute("", ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="capture_webcam",
                content=result.get_error_message(),
                is_error=True
            )

        return ToolResult(
            tool_use_id=id,
            tool_name="capture_webcam",
            content="Webcam image captured - see attached image",
            image_data=result.image_data
        )

    # =========================================================================
    # ACTIVE THOUGHTS TOOL
    # =========================================================================

    def _exec_set_active_thoughts(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Update active thoughts."""
        import json
        from agency.commands.handlers.active_thoughts_handler import SetThoughtsHandler

        handler = SetThoughtsHandler()

        # The handler expects a JSON array string
        thoughts = input.get("thoughts", [])
        query = json.dumps(thoughts)

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_active_thoughts",
                content=result.get_error_message(),
                is_error=True
            )

        count = len(thoughts)
        return ToolResult(
            tool_use_id=id,
            tool_name="set_active_thoughts",
            content=f"Active thoughts updated: {count} item{'s' if count != 1 else ''}"
        )

    # =========================================================================
    # PULSE TIMER TOOL
    # =========================================================================

    def _exec_set_pulse_interval(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """
        Set the pulse timer interval.

        This tool stores the requested interval in the context for the caller
        to pick up and signal to the UI. The actual timer adjustment happens
        in the interface layer (GUI/CLI) which has access to the timer.

        The interval is validated here but applied by the caller.
        """
        from prompt_builder.sources.system_pulse import PULSE_COMMAND_TO_SECONDS

        interval_str = input.get("interval", "")

        # Validate the interval
        if interval_str not in PULSE_COMMAND_TO_SECONDS:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_pulse_interval",
                content=f"Invalid interval '{interval_str}'. Valid options: 3m, 10m, 30m, 1h, 6h",
                is_error=True
            )

        # Get interval in seconds
        interval_seconds = PULSE_COMMAND_TO_SECONDS[interval_str]

        # Store in context for caller to handle UI signaling
        # The caller (response processor) will check for this and emit the signal
        ctx["pulse_interval_change"] = interval_seconds

        # Human-readable label
        interval_labels = {
            "3m": "3 minutes",
            "10m": "10 minutes",
            "30m": "30 minutes",
            "1h": "1 hour",
            "6h": "6 hours",
        }
        label = interval_labels.get(interval_str, interval_str)

        log_info(f"Pulse interval change requested: {label}", prefix="⏱️")

        return ToolResult(
            tool_use_id=id,
            tool_name="set_pulse_interval",
            content=f"Pulse timer set to {label}"
        )

    # =========================================================================
    # CURIOSITY TOOLS
    # =========================================================================

    def _exec_advance_curiosity(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """
        Three-mode curiosity advancement:

        1. Progress only (note) - increment interaction count
        2. Resolve, system picks (note + outcome) - close and auto-select next
        3. Resolve, AI picks (note + outcome + next_topic) - close and use specified topic
        """
        from agency.curiosity import get_curiosity_engine, is_curiosity_enabled
        from agency.curiosity.ledger import GoalStatus, get_curiosity_ledger

        if not is_curiosity_enabled():
            return ToolResult(
                tool_use_id=id,
                tool_name="advance_curiosity",
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
                    tool_use_id=id,
                    tool_name="advance_curiosity",
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
                        tool_use_id=id,
                        tool_name="advance_curiosity",
                        content="Cannot specify next_topic without an outcome. Add outcome to resolve the topic.",
                        is_error=True
                    )

                status_msg = f"Progress: {new_count}/{min_interactions}"
                if new_count >= min_interactions:
                    status_msg += " (ready to resolve)"

                log_info(f"Curiosity interaction recorded: {status_msg}", prefix="🔍")
                self._emit_curiosity_progress(current_goal, new_count, min_interactions, note)

                return ToolResult(
                    tool_use_id=id,
                    tool_name="advance_curiosity",
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
                    tool_use_id=id,
                    tool_name="advance_curiosity",
                    content=f"Invalid outcome '{outcome}'. Valid options: explored, deferred, declined",
                    is_error=True
                )

            status = status_map[outcome]

            # Enforce minimum interactions for "explored"
            if status == GoalStatus.EXPLORED and new_count < min_interactions:
                return ToolResult(
                    tool_use_id=id,
                    tool_name="advance_curiosity",
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
                    tool_use_id=id,
                    tool_name="advance_curiosity",
                    content=f"Resolved as '{outcome}'. New curiosity (your choice): {new_goal.content[:80]}..."
                )
            else:
                # MODE 2: System selects next
                new_goal = engine.resolve_current_goal(status, note)
                log_info(f"Curiosity resolved as '{outcome}', system selected next", prefix="🔍")
                return ToolResult(
                    tool_use_id=id,
                    tool_name="advance_curiosity",
                    content=f"Resolved as '{outcome}'. New curiosity: {new_goal.content[:80]}..."
                )

        except Exception as e:
            log_error(f"Error in advance_curiosity: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="advance_curiosity",
                content=f"Error advancing curiosity: {str(e)}",
                is_error=True
            )

    def _emit_curiosity_progress(
        self, goal, interaction_count: int, min_interactions: int, note: str
    ) -> None:
        """Emit curiosity progress update to DEV window."""
        if not config.DEV_MODE_ENABLED:
            return

        try:
            from interface.dev_window import emit_curiosity_update

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

    def _exec_resolve_curiosity(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """
        Resolve the current curiosity goal and select a new one.

        This records the outcome of the AI's curiosity exploration and
        automatically rotates to a new curiosity topic.

        For "explored" outcomes, enforces minimum interaction count to
        ensure topics are actually explored, not just mentioned once.
        """
        from agency.curiosity import get_curiosity_engine, is_curiosity_enabled
        from agency.curiosity.ledger import GoalStatus, get_curiosity_ledger

        if not is_curiosity_enabled():
            return ToolResult(
                tool_use_id=id,
                tool_name="resolve_curiosity",
                content="Curiosity system is disabled",
                is_error=True
            )

        outcome_str = input.get("outcome", "")
        notes = input.get("notes", "")

        # Map string to GoalStatus enum
        status_map = {
            "explored": GoalStatus.EXPLORED,
            "deferred": GoalStatus.DEFERRED,
            "declined": GoalStatus.DECLINED,
        }

        if outcome_str not in status_map:
            return ToolResult(
                tool_use_id=id,
                tool_name="resolve_curiosity",
                content=f"Invalid outcome '{outcome_str}'. Valid options: explored, deferred, declined",
                is_error=True
            )

        status = status_map[outcome_str]

        try:
            engine = get_curiosity_engine()
            ledger = get_curiosity_ledger()

            # For "explored" outcomes, check minimum interaction requirement
            if status == GoalStatus.EXPLORED:
                current_goal = ledger.get_active_goal()
                if current_goal:
                    min_interactions = getattr(config, 'CURIOSITY_MIN_INTERACTIONS', 2)
                    interaction_count = current_goal.interaction_count

                    if interaction_count < min_interactions:
                        # Not enough interactions - refuse to mark as explored
                        return ToolResult(
                            tool_use_id=id,
                            tool_name="resolve_curiosity",
                            content=(
                                f"Cannot mark as 'explored' yet - only {interaction_count} interaction(s) "
                                f"recorded (minimum: {min_interactions}). Continue exploring this topic, "
                                f"or use 'deferred' if the user wants to discuss something else."
                            ),
                            is_error=True
                        )

            new_goal = engine.resolve_current_goal(status, notes)

            # Return confirmation with new goal preview
            return ToolResult(
                tool_use_id=id,
                tool_name="resolve_curiosity",
                content=f"Curiosity resolved as '{outcome_str}'. New curiosity: {new_goal.content[:80]}..."
            )

        except Exception as e:
            log_error(f"Error resolving curiosity: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="resolve_curiosity",
                content=f"Error resolving curiosity: {str(e)}",
                is_error=True
            )

    # =========================================================================
    # CONVERSATION STYLE TOOL
    # =========================================================================

    def _exec_set_conversation_style(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """
        Set the conversation style mode.

        Updates the user settings to change how the AI approaches conversation.
        The style is persisted and affects the system prompt on subsequent messages.
        """
        from core.user_settings import get_user_settings

        style = input.get("style", "none")
        valid_styles = {"none", "casual", "deep", "funny", "teacher"}

        if style not in valid_styles:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_conversation_style",
                content=f"Invalid style '{style}'. Valid options: {', '.join(sorted(valid_styles))}",
                is_error=True
            )

        # Update the setting (persists to disk)
        settings = get_user_settings()
        settings.conversation_style = style

        # Human-readable descriptions
        style_descriptions = {
            "none": "default (no style guidance)",
            "casual": "casual (brief, warm, low-energy)",
            "deep": "deep (exploring complexity and nuance)",
            "funny": "playful (wit and lightness)",
            "teacher": "teacher (clear explanations)",
        }
        description = style_descriptions.get(style, style)

        log_info(f"Conversation style changed to: {description}", prefix="💬")

        return ToolResult(
            tool_use_id=id,
            tool_name="set_conversation_style",
            content=f"Conversation style set to {description}"
        )


# Global instance
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get the global tool executor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
