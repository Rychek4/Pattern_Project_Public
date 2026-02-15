"""
Pattern Project - Tool Executor
Maps native tool calls to existing command handlers.

This module bridges Claude's native tool use with the existing handler infrastructure.
Each tool call is routed to the appropriate handler, reusing all existing logic.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Callable, TYPE_CHECKING

from core.logger import log_info, log_warning, log_error
from interface.process_panel import ProcessEventType, get_process_event_bus
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
            "get_clipboard": self._exec_get_clipboard,
            "set_clipboard": self._exec_set_clipboard,
            "request_clarification": self._exec_request_clarification,
            "manage_fetch_domains": self._exec_manage_fetch_domains,
            "list_fetch_domains": self._exec_list_fetch_domains,
            # Moltbook tools
            "moltbook_feed": self._exec_moltbook_feed,
            "moltbook_post": self._exec_moltbook_post,
            "moltbook_create_post": self._exec_moltbook_create_post,
            "moltbook_comment": self._exec_moltbook_comment,
            "moltbook_vote": self._exec_moltbook_vote,
            "moltbook_search": self._exec_moltbook_search,
            "moltbook_submolts": self._exec_moltbook_submolts,
            "moltbook_profile": self._exec_moltbook_profile,
            # Reddit tools
            "reddit_feed": self._exec_reddit_feed,
            "reddit_post": self._exec_reddit_post,
            "reddit_create_post": self._exec_reddit_create_post,
            "reddit_comment": self._exec_reddit_comment,
            "reddit_vote": self._exec_reddit_vote,
            "reddit_search": self._exec_reddit_search,
            "reddit_subreddits": self._exec_reddit_subreddits,
            "reddit_profile": self._exec_reddit_profile,
            # Delegation
            "delegate_task": self._exec_delegate_task,
            # Growth threads (pulse-only)
            "set_growth_thread": self._exec_set_growth_thread,
            "remove_growth_thread": self._exec_remove_growth_thread,
            "store_core_memory": self._exec_store_core_memory,
            # Novel reading
            "open_book": self._exec_open_book,
            "read_next_chapter": self._exec_read_next_chapter,
            "complete_reading": self._exec_complete_reading,
            "reading_progress": self._exec_reading_progress,
            "abandon_reading": self._exec_abandon_reading,
            "resume_reading": self._exec_resume_reading,
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
            get_process_event_bus().emit_event(
                ProcessEventType.PROCESSING_ERROR,
                detail=f"Unknown tool: {tool_name}"
            )
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
            get_process_event_bus().emit_event(
                ProcessEventType.PROCESSING_ERROR,
                detail=f"{tool_name}: {str(e)[:80]}"
            )
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
                content=f"Invalid interval '{interval_str}'. Valid options: 3m, 10m, 30m, 1h, 2h, 3h, 6h, 12h",
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
            "2h": "2 hours",
            "3h": "3 hours",
            "6h": "6 hours",
            "12h": "12 hours",
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
    # CLIPBOARD TOOLS
    # =========================================================================

    def _exec_get_clipboard(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Read system clipboard contents."""
        try:
            import pyperclip
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="get_clipboard",
                content="Clipboard not available (pyperclip not installed). Run: pip install pyperclip",
                is_error=True
            )

        try:
            content = pyperclip.paste()

            if not content or not content.strip():
                return ToolResult(
                    tool_use_id=id,
                    tool_name="get_clipboard",
                    content="Clipboard is empty"
                )

            # Truncate large content
            max_size = getattr(config, 'CLIPBOARD_MAX_READ_SIZE', 10000)
            original_len = len(content)
            if original_len > max_size:
                content = content[:max_size]
                return ToolResult(
                    tool_use_id=id,
                    tool_name="get_clipboard",
                    content=f"{content}\n\n[Truncated: showing {max_size:,} of {original_len:,} characters]"
                )

            return ToolResult(
                tool_use_id=id,
                tool_name="get_clipboard",
                content=content
            )

        except Exception as e:
            log_error(f"Clipboard read error: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="get_clipboard",
                content=f"Clipboard error: {str(e)}",
                is_error=True
            )

    def _exec_set_clipboard(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Write content to system clipboard."""
        try:
            import pyperclip
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_clipboard",
                content="Clipboard not available (pyperclip not installed). Run: pip install pyperclip",
                is_error=True
            )

        content = input.get("content", "")
        if not content:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_clipboard",
                content="No content provided to copy",
                is_error=True
            )

        try:
            pyperclip.copy(content)

            # Build confirmation with preview
            char_count = len(content)
            line_count = content.count('\n') + 1
            preview = content[:80].replace('\n', ' ')
            if len(content) > 80:
                preview += "..."

            log_info(f"Copied {char_count} chars to clipboard", prefix="📋")

            return ToolResult(
                tool_use_id=id,
                tool_name="set_clipboard",
                content=f"Copied to clipboard ({char_count:,} chars, {line_count} line{'s' if line_count != 1 else ''}): {preview}"
            )

        except Exception as e:
            log_error(f"Clipboard write error: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="set_clipboard",
                content=f"Clipboard error: {str(e)}",
                is_error=True
            )

    # =========================================================================
    # CLARIFICATION TOOL
    # =========================================================================

    def _exec_request_clarification(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """
        Request clarification from the user.

        This tool signals that the AI needs user input before proceeding.
        The question is formatted and returned, and a flag is set in the
        context so the response processor can apply special UI styling.
        """
        question = input.get("question", "")
        options = input.get("options", [])
        context_note = input.get("context", "")

        if not question:
            return ToolResult(
                tool_use_id=id,
                tool_name="request_clarification",
                content="No question provided",
                is_error=True
            )

        # Build formatted response for Claude to include
        parts = []

        if context_note:
            parts.append(f"Context: {context_note}")
            parts.append("")

        parts.append(f"Question: {question}")

        if options:
            parts.append("")
            parts.append("Options:")
            for i, opt in enumerate(options, 1):
                parts.append(f"  {i}. {opt}")

        # Signal to response processor that this is a clarification request
        # This enables special UI styling in CLI and GUI
        ctx["clarification_requested"] = {
            "question": question,
            "options": options,
            "context": context_note
        }

        log_info(f"Clarification requested: {question[:50]}...", prefix="❓")

        return ToolResult(
            tool_use_id=id,
            tool_name="request_clarification",
            content="\n".join(parts)
        )


    # =========================================================================
    # WEB FETCH DOMAIN MANAGEMENT TOOLS
    # =========================================================================

    def _exec_manage_fetch_domains(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Manage web fetch domain allow/block lists."""
        from agency.web_fetch_domains import get_web_fetch_domain_manager

        action = input.get("action", "")
        domain = input.get("domain", "")

        if not action or not domain:
            return ToolResult(
                tool_use_id=id,
                tool_name="manage_fetch_domains",
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
                tool_use_id=id,
                tool_name="manage_fetch_domains",
                content=f"Invalid action '{action}'. Valid: allow, block, remove_allowed, unblock",
                is_error=True
            )

        result_msg = handler_fn(domain)

        return ToolResult(
            tool_use_id=id,
            tool_name="manage_fetch_domains",
            content=result_msg
        )

    def _exec_list_fetch_domains(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List current web fetch domain configuration."""
        from agency.web_fetch_domains import get_web_fetch_domain_manager

        manager = get_web_fetch_domain_manager()
        summary = manager.get_status_summary()

        return ToolResult(
            tool_use_id=id,
            tool_name="list_fetch_domains",
            content=summary
        )

    # =========================================================================
    # MOLTBOOK TOOLS
    # =========================================================================

    def _get_moltbook_client(self) -> Any:
        """Lazy-import and return the Moltbook client."""
        from communication.moltbook_client import get_moltbook_client
        return get_moltbook_client()

    def _moltbook_result(
        self, tool_name: str, id: str, data: Dict
    ) -> ToolResult:
        """Format a Moltbook API response into a ToolResult."""
        import json

        if data.get("error"):
            return ToolResult(
                tool_use_id=id,
                tool_name=tool_name,
                content=data.get("message", "Unknown Moltbook error"),
                is_error=True,
            )

        return ToolResult(
            tool_use_id=id,
            tool_name=tool_name,
            content=json.dumps(data, indent=2, default=str),
        )

    def _exec_moltbook_feed(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Browse the Moltbook feed."""
        try:
            client = self._get_moltbook_client()
            data = client.get_feed(
                sort=input.get("sort", "hot"),
                submolt=input.get("submolt"),
            )
            return self._moltbook_result("moltbook_feed", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_feed",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Get a single Moltbook post with comments."""
        try:
            client = self._get_moltbook_client()
            data = client.get_post(input.get("post_id", ""))
            return self._moltbook_result("moltbook_post", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_post",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_create_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create a new Moltbook post."""
        try:
            client = self._get_moltbook_client()
            data = client.create_post(
                title=input.get("title", ""),
                submolt=input.get("submolt", ""),
                content=input.get("content"),
                url=input.get("url"),
            )
            return self._moltbook_result("moltbook_create_post", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_create_post",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_comment(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Comment on a Moltbook post."""
        try:
            client = self._get_moltbook_client()
            data = client.create_comment(
                post_id=input.get("post_id", ""),
                content=input.get("content", ""),
                parent_comment_id=input.get("parent_comment_id"),
            )
            return self._moltbook_result("moltbook_comment", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_comment",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_vote(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Vote on a Moltbook post."""
        try:
            client = self._get_moltbook_client()
            data = client.vote(
                post_id=input.get("post_id", ""),
                direction=input.get("direction", "upvote"),
            )
            return self._moltbook_result("moltbook_vote", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_vote",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_search(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Search Moltbook."""
        try:
            client = self._get_moltbook_client()
            data = client.search(query=input.get("query", ""))
            return self._moltbook_result("moltbook_search", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_search",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_submolts(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List Moltbook submolts."""
        try:
            client = self._get_moltbook_client()
            data = client.get_submolts()
            return self._moltbook_result("moltbook_submolts", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_submolts",
                content=str(e),
                is_error=True,
            )

    def _exec_moltbook_profile(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Get a Moltbook agent profile."""
        try:
            client = self._get_moltbook_client()
            data = client.get_profile(agent_name=input.get("agent_name"))
            return self._moltbook_result("moltbook_profile", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="moltbook_profile",
                content=str(e),
                is_error=True,
            )

    # =========================================================================
    # REDDIT TOOLS
    # =========================================================================

    def _get_reddit_client(self) -> Any:
        """Lazy-import and return the Reddit client."""
        from communication.reddit_client import get_reddit_client
        return get_reddit_client()

    def _reddit_result(
        self, tool_name: str, id: str, data: Dict
    ) -> ToolResult:
        """Format a Reddit API response into a ToolResult."""
        import json

        if data.get("error"):
            return ToolResult(
                tool_use_id=id,
                tool_name=tool_name,
                content=data.get("message", "Unknown Reddit error"),
                is_error=True,
            )

        return ToolResult(
            tool_use_id=id,
            tool_name=tool_name,
            content=json.dumps(data, indent=2, default=str),
        )

    def _exec_reddit_feed(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Browse a subreddit's posts."""
        try:
            client = self._get_reddit_client()
            data = client.get_feed(
                subreddit=input.get("subreddit", "all"),
                sort=input.get("sort", "hot"),
                time_filter=input.get("time_filter", "day"),
                limit=input.get("limit", 10),
            )
            return self._reddit_result("reddit_feed", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_feed",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Get a single Reddit post with comments."""
        try:
            client = self._get_reddit_client()
            data = client.get_post(
                post_id=input.get("post_id", ""),
                comment_sort=input.get("comment_sort", "best"),
                comment_limit=input.get("comment_limit", 20),
            )
            return self._reddit_result("reddit_post", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_post",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_create_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create a new Reddit post."""
        try:
            client = self._get_reddit_client()
            data = client.create_post(
                subreddit=input.get("subreddit", ""),
                title=input.get("title", ""),
                content=input.get("content"),
                url=input.get("url"),
            )
            return self._reddit_result("reddit_create_post", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_create_post",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_comment(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Comment on a Reddit post or reply to a comment."""
        try:
            client = self._get_reddit_client()
            data = client.create_comment(
                thing_id=input.get("thing_id", ""),
                content=input.get("content", ""),
            )
            return self._reddit_result("reddit_comment", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_comment",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_vote(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Vote on a Reddit post or comment."""
        try:
            client = self._get_reddit_client()
            data = client.vote(
                thing_id=input.get("thing_id", ""),
                direction=input.get("direction", "up"),
            )
            return self._reddit_result("reddit_vote", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_vote",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_search(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Search Reddit for posts."""
        try:
            client = self._get_reddit_client()
            data = client.search(
                query=input.get("query", ""),
                subreddit=input.get("subreddit"),
                sort=input.get("sort", "relevance"),
                time_filter=input.get("time_filter", "all"),
                limit=input.get("limit", 10),
            )
            return self._reddit_result("reddit_search", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_search",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_subreddits(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Search for or list subreddits."""
        try:
            client = self._get_reddit_client()
            data = client.get_subreddits(
                query=input.get("query"),
                limit=input.get("limit", 10),
            )
            return self._reddit_result("reddit_subreddits", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_subreddits",
                content=str(e),
                is_error=True,
            )

    def _exec_reddit_profile(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Get a Reddit user's profile."""
        try:
            client = self._get_reddit_client()
            data = client.get_profile(username=input.get("username"))
            return self._reddit_result("reddit_profile", id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="reddit_profile",
                content=str(e),
                is_error=True,
            )

    # =========================================================================
    # DELEGATION TOOL
    # =========================================================================

    def _exec_delegate_task(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """
        Delegate a task to a lightweight sub-agent.

        Spawns an ephemeral Haiku conversation with limited tools.
        The sub-agent runs to completion and returns its result as text.
        """
        if not config.DELEGATION_ENABLED:
            return ToolResult(
                tool_use_id=id,
                tool_name="delegate_task",
                content="Delegation is disabled",
                is_error=True
            )

        task = input.get("task", "")
        if not task:
            return ToolResult(
                tool_use_id=id,
                tool_name="delegate_task",
                content="No task provided",
                is_error=True
            )

        context = input.get("context", "")
        max_rounds = input.get("max_rounds")

        try:
            from agency.tools.delegate import run_delegated_task

            result_text = run_delegated_task(
                task=task,
                context=context,
                max_rounds=max_rounds
            )

            return ToolResult(
                tool_use_id=id,
                tool_name="delegate_task",
                content=result_text
            )

        except Exception as e:
            log_error(f"Delegation failed: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="delegate_task",
                content=f"Delegation error: {str(e)}",
                is_error=True
            )


    # =========================================================================
    # GROWTH THREAD TOOLS (Pulse-only)
    # =========================================================================

    def _exec_set_growth_thread(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create or update a growth thread."""
        from agency.growth_threads import get_growth_thread_manager

        slug = input.get("slug", "")
        stage = input.get("stage", "")
        content = input.get("content", "")

        if not slug or not stage or not content:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_growth_thread",
                content="Error: slug, stage, and content are all required.",
                is_error=True
            )

        manager = get_growth_thread_manager()

        # Check if this is an update or create
        existing = manager.get_by_slug(slug)
        success, error = manager.set(slug, stage, content)

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_growth_thread",
                content=f"Error: {error}",
                is_error=True
            )

        if existing:
            if existing.stage != stage:
                return ToolResult(
                    tool_use_id=id,
                    tool_name="set_growth_thread",
                    content=f"Growth thread '{slug}' updated: {existing.stage} → {stage}"
                )
            else:
                return ToolResult(
                    tool_use_id=id,
                    tool_name="set_growth_thread",
                    content=f"Growth thread '{slug}' content updated (stage: {stage})"
                )
        else:
            return ToolResult(
                tool_use_id=id,
                tool_name="set_growth_thread",
                content=f"Growth thread '{slug}' created (stage: {stage})"
            )

    def _exec_remove_growth_thread(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Remove a growth thread."""
        from agency.growth_threads import get_growth_thread_manager

        slug = input.get("slug", "")

        if not slug:
            return ToolResult(
                tool_use_id=id,
                tool_name="remove_growth_thread",
                content="Error: slug is required.",
                is_error=True
            )

        manager = get_growth_thread_manager()
        success, error = manager.remove(slug)

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="remove_growth_thread",
                content=f"Error: {error}",
                is_error=True
            )

        return ToolResult(
            tool_use_id=id,
            tool_name="remove_growth_thread",
            content=f"Growth thread '{slug}' removed."
        )

    def _exec_store_core_memory(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Store a permanent core memory."""
        from prompt_builder.sources.core_memory import CoreMemorySource

        content = input.get("content", "")
        category = input.get("category", "")

        if not content or not category:
            return ToolResult(
                tool_use_id=id,
                tool_name="store_core_memory",
                content="Error: content and category are both required.",
                is_error=True
            )

        valid_categories = ("identity", "relationship", "preference", "fact")
        if category not in valid_categories:
            return ToolResult(
                tool_use_id=id,
                tool_name="store_core_memory",
                content=f"Error: category must be one of: {', '.join(valid_categories)}",
                is_error=True
            )

        source = CoreMemorySource()
        memory_id = source.add(content, category)

        if memory_id is None:
            return ToolResult(
                tool_use_id=id,
                tool_name="store_core_memory",
                content="Error: Failed to store core memory.",
                is_error=True
            )

        return ToolResult(
            tool_use_id=id,
            tool_name="store_core_memory",
            content=f"Core memory stored (id={memory_id}, category={category}): {content[:80]}..."
        )

    # =========================================================================
    # NOVEL READING TOOLS
    # =========================================================================

    def _exec_open_book(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Open a novel for reading."""
        import json
        from pathlib import Path
        from agency.novel_reading.orchestrator import open_book
        from agency.commands.handlers.file_handler import _sanitize_filename, FileSecurityError

        filename = input.get("filename", "")
        if not filename:
            return ToolResult(
                tool_use_id=id,
                tool_name="open_book",
                content="No filename provided",
                is_error=True
            )

        try:
            filename = _sanitize_filename(filename)
        except FileSecurityError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="open_book",
                content=f"Invalid filename: {e}",
                is_error=True
            )

        filepath = Path(config.NOVEL_BOOKS_DIR) / filename

        success, message, summary = open_book(filepath)

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="open_book",
                content=message,
                is_error=True
            )

        # Format the structure summary for the AI
        result_parts = [message, ""]
        if summary:
            result_parts.append(f"Title: {summary.get('title', 'Unknown')}")
            result_parts.append(f"Detection: {summary.get('detection_method', 'unknown')}")
            result_parts.append(f"Total words: {summary.get('total_word_count', 0):,}")
            result_parts.append(f"Estimated tokens: {summary.get('total_token_estimate', 0):,}")
            result_parts.append(f"Chapters: {summary.get('total_chapters', 0)}")
            result_parts.append(f"Arcs: {summary.get('total_arcs', 0)}")

            if summary.get('has_prologue'):
                result_parts.append("Has prologue: yes")

            if summary.get('arcs'):
                result_parts.append("\nStructure:")
                for arc in summary['arcs']:
                    ch_range = arc.get('chapters', [])
                    ch_str = f"chapters {ch_range[0]}-{ch_range[-1]}" if ch_range else "no chapters"
                    result_parts.append(f"  {arc['title']} ({ch_str})")

            result_parts.append("\nUse read_next_chapter to begin reading.")

        return ToolResult(
            tool_use_id=id,
            tool_name="open_book",
            content="\n".join(result_parts)
        )

    def _exec_read_next_chapter(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Read the next chapter of the current book."""
        import json
        from agency.novel_reading.orchestrator import read_next_chapter

        success, message, result_data = read_next_chapter()

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="read_next_chapter",
                content=message,
                is_error=True
            )

        # Format result for the AI
        parts = [message, ""]
        if result_data:
            parts.append(f"Words: {result_data.get('word_count', 0):,}")
            parts.append(f"Arc: {result_data.get('arc', 'N/A')}")
            parts.append(f"Extraction: {'success' if result_data.get('extraction_success') else 'failed'}")
            parts.append(f"Observations extracted: {result_data.get('observations_extracted', 0)}")
            parts.append(f"Memories stored: {result_data.get('memories_stored', 0)}")

            categories = result_data.get('categories', [])
            if categories:
                parts.append(f"Categories found: {', '.join(categories)}")

            arc_reflection = result_data.get('arc_reflection')
            if arc_reflection:
                parts.append(f"\nArc boundary reflection (Arc {arc_reflection['arc_number']}: {arc_reflection['arc_title']}):")
                parts.append(f"  Reflective observations: {arc_reflection['observations']}")
                parts.append(f"  Memories stored: {arc_reflection['memories_stored']}")

            remaining = result_data.get('chapters_remaining', 0)
            if remaining > 0:
                parts.append(f"\nChapters remaining: {remaining}")
            else:
                parts.append("\nAll chapters read. Use complete_reading for final synthesis.")

        return ToolResult(
            tool_use_id=id,
            tool_name="read_next_chapter",
            content="\n".join(parts)
        )

    def _exec_complete_reading(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Complete the reading session with final synthesis."""
        import json
        from agency.novel_reading.orchestrator import complete_reading

        success, message, result_data = complete_reading()

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="complete_reading",
                content=message,
                is_error=True
            )

        parts = [message, ""]
        if result_data:
            parts.append(f"Total chapters read: {result_data.get('total_chapters_read', 0)}")
            parts.append(f"Total observations accumulated: {result_data.get('total_observations', 0)}")
            parts.append(f"Synthesis observations: {result_data.get('synthesis_observations', 0)}")
            parts.append(f"Synthesis memories stored: {result_data.get('synthesis_memories_stored', 0)}")

            discussion_points = result_data.get('discussion_points', [])
            if discussion_points:
                parts.append("\nDiscussion points for the reader:")
                for i, point in enumerate(discussion_points, 1):
                    parts.append(f"  {i}. {point}")

            parts.append("\nYour literary memories are now part of your memory system.")
            parts.append("They will surface naturally in relevant conversations.")

        return ToolResult(
            tool_use_id=id,
            tool_name="complete_reading",
            content="\n".join(parts)
        )

    def _exec_reading_progress(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Get current reading progress."""
        import json
        from agency.novel_reading.orchestrator import get_reading_progress

        success, message, result_data = get_reading_progress()

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="reading_progress",
                content=message,
                is_error=True
            )

        parts = [message]
        if result_data:
            status = result_data.get('status', 'none')
            if status == 'reading':
                parts.append(f"\nProgress: {result_data.get('progress_percent', 0)}%")
                parts.append(f"Chapter: {result_data.get('current_chapter', 0)}/{result_data.get('total_chapters', 0)}")
                parts.append(f"Chapters remaining: {result_data.get('chapters_remaining', 0)}")
                parts.append(f"Observations so far: {result_data.get('observations_so_far', 0)}")
                if result_data.get('total_arcs', 0) > 0:
                    parts.append(f"Current arc: {result_data.get('current_arc', 0)}/{result_data.get('total_arcs', 0)}")

        return ToolResult(
            tool_use_id=id,
            tool_name="reading_progress",
            content="\n".join(parts)
        )

    def _exec_abandon_reading(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Abandon the current reading session."""
        from agency.novel_reading.orchestrator import abandon_reading

        success, message = abandon_reading()

        return ToolResult(
            tool_use_id=id,
            tool_name="abandon_reading",
            content=message,
            is_error=not success
        )

    def _exec_resume_reading(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Resume an interrupted reading session."""
        from pathlib import Path
        from agency.novel_reading.orchestrator import resume_reading
        from agency.commands.handlers.file_handler import _sanitize_filename, FileSecurityError

        filename = input.get("filename", "")
        if not filename:
            return ToolResult(
                tool_use_id=id,
                tool_name="resume_reading",
                content="No filename provided",
                is_error=True
            )

        try:
            filename = _sanitize_filename(filename)
        except FileSecurityError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="resume_reading",
                content=f"Invalid filename: {e}",
                is_error=True
            )

        filepath = Path(config.NOVEL_BOOKS_DIR) / filename

        success, message, result_data = resume_reading(filepath)

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name="resume_reading",
                content=message,
                is_error=True
            )

        parts = [message, ""]
        if result_data:
            parts.append(f"Title: {result_data.get('title', 'Unknown')}")
            chapters_read = result_data.get('chapters_read', [])
            parts.append(f"Chapters already read: {len(chapters_read)}")
            parts.append(f"Chapters remaining: {result_data.get('chapters_remaining', 0)}")
            parts.append("\nUse read_next_chapter to continue reading.")

        return ToolResult(
            tool_use_id=id,
            tool_name="resume_reading",
            content="\n".join(parts)
        )


# Global instance
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get the global tool executor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
