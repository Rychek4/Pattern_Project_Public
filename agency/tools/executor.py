"""
Pattern Project - Tool Executor
Routes native tool calls to command handlers.

Each tool call is routed to the appropriate handler in agency/commands/handlers/,
which encapsulates the business logic for that capability.
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
    Executes tool calls by routing to handler functions.

    Maps tool names to execution methods. Each method instantiates
    the appropriate handler from agency/commands/handlers/ and
    adapts the structured tool input to the handler's format.
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
            "create_directory": self._exec_create_directory,
            "move_file": self._exec_move_file,
            "send_telegram": self._exec_send_telegram,
            "capture_screenshot": self._exec_capture_screenshot,
            "capture_webcam": self._exec_capture_webcam,
            "set_active_thoughts": self._exec_set_active_thoughts,
            "set_pulse_interval": self._exec_set_pulse_interval,
            "advance_curiosity": self._exec_advance_curiosity,
            "manage_fetch_domains": self._exec_manage_fetch_domains,
            "list_fetch_domains": self._exec_list_fetch_domains,
            # Reddit tools
            "reddit_feed": self._exec_reddit_feed,
            "reddit_post": self._exec_reddit_post,
            "reddit_create_post": self._exec_reddit_create_post,
            "reddit_comment": self._exec_reddit_comment,
            "reddit_vote": self._exec_reddit_vote,
            "reddit_search": self._exec_reddit_search,
            "reddit_subreddits": self._exec_reddit_subreddits,
            "reddit_profile": self._exec_reddit_profile,
            # Image memory
            "save_image": self._exec_save_image,
            # Delegation
            "delegate_task": self._exec_delegate_task,
            # Growth threads (pulse-only)
            "set_growth_thread": self._exec_set_growth_thread,
            "remove_growth_thread": self._exec_remove_growth_thread,
            "promote_growth_thread": self._exec_promote_growth_thread,
            # Novel reading
            "open_book": self._exec_open_book,
            "read_next_chapter": self._exec_read_next_chapter,
            "complete_reading": self._exec_complete_reading,
            "reading_progress": self._exec_reading_progress,
            "abandon_reading": self._exec_abandon_reading,
            "resume_reading": self._exec_resume_reading,
            # Google Calendar
            "list_calendar_events": self._exec_list_calendar_events,
            "create_calendar_event": self._exec_create_calendar_event,
            "update_calendar_event": self._exec_update_calendar_event,
            "delete_calendar_event": self._exec_delete_calendar_event,
            # Blog
            "publish_blog_post": self._exec_publish_blog_post,
            "save_blog_draft": self._exec_save_blog_draft,
            "edit_blog_post": self._exec_edit_blog_post,
            "list_blog_posts": self._exec_list_blog_posts,
            "unpublish_blog_post": self._exec_unpublish_blog_post,
            # Metacognition (pulse-only)
            "store_bridge_memory": self._exec_store_bridge_memory,
            "store_meta_observation": self._exec_store_meta_observation,
            "update_memory_self_model": self._exec_update_memory_self_model,
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
        """Execute memory search. If results include image memories, load and attach images."""
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

        # Check if any results have associated images and load them
        image_data = None
        if result.data:
            from agency.commands.handlers.image_memory_handler import load_image_for_memory
            images = []
            for r in result.data:
                if hasattr(r, 'memory') and r.memory.image_id:
                    img = load_image_for_memory(r.memory.image_id)
                    if img:
                        images.append(img)
            if images:
                image_data = images

        return ToolResult(
            tool_use_id=id,
            tool_name="search_memories",
            content=formatted,
            image_data=image_data
        )

    def _exec_save_image(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Save the current turn's image to visual memory."""
        from agency.commands.handlers.image_memory_handler import SaveImageHandler

        handler = SaveImageHandler()
        source = input.get("source", "")
        description = input.get("description", "")
        query = f"{source} | {description}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="save_image",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="save_image",
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
        """List available files and directories."""
        from agency.commands.handlers.file_handler import ListFilesHandler

        handler = ListFilesHandler()
        path = input.get("path", "")
        result = handler.execute(path, ctx)

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

    def _exec_create_directory(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create a directory in sandboxed storage."""
        from agency.commands.handlers.file_handler import (
            create_directory, FileSecurityError
        )

        path = input.get("path", "")
        if not path:
            return ToolResult(
                tool_use_id=id,
                tool_name="create_directory",
                content="No path provided",
                is_error=True
            )

        try:
            result = create_directory(path)

            if result["already_existed"]:
                return ToolResult(
                    tool_use_id=id,
                    tool_name="create_directory",
                    content=f"Directory already exists: {path}"
                )
            else:
                return ToolResult(
                    tool_use_id=id,
                    tool_name="create_directory",
                    content=f"Created directory: {path}"
                )

        except FileSecurityError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="create_directory",
                content=f"Security check failed: {str(e)}",
                is_error=True
            )
        except Exception as e:
            log_error(f"create_directory error: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="create_directory",
                content=f"Failed to create directory: {str(e)}",
                is_error=True
            )

    def _exec_move_file(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Move or rename a file in sandboxed storage."""
        from agency.commands.handlers.file_handler import (
            move_file, FileSecurityError
        )

        source = input.get("source", "")
        destination = input.get("destination", "")

        if not source:
            return ToolResult(
                tool_use_id=id,
                tool_name="move_file",
                content="No source path provided",
                is_error=True
            )
        if not destination:
            return ToolResult(
                tool_use_id=id,
                tool_name="move_file",
                content="No destination path provided",
                is_error=True
            )

        try:
            result = move_file(source, destination)

            return ToolResult(
                tool_use_id=id,
                tool_name="move_file",
                content=f"Moved '{result['source']}' → '{result['destination']}'"
            )

        except FileSecurityError as e:
            return ToolResult(
                tool_use_id=id,
                tool_name="move_file",
                content=f"Security check failed: {str(e)}",
                is_error=True
            )
        except Exception as e:
            log_error(f"move_file error: {e}")
            return ToolResult(
                tool_use_id=id,
                tool_name="move_file",
                content=f"Failed to move file: {str(e)}",
                is_error=True
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

        # Save to temp for potential save_image tool use
        if result.image_data and config.IMAGE_MEMORY_ENABLED:
            self._save_tool_images_to_temp(result.image_data, "screenshot")

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

        # Save to temp for potential save_image tool use
        if result.image_data and config.IMAGE_MEMORY_ENABLED:
            self._save_tool_images_to_temp(result.image_data, "webcam")

        return ToolResult(
            tool_use_id=id,
            tool_name="capture_webcam",
            content="Webcam image captured - see attached image",
            image_data=result.image_data
        )

    @staticmethod
    def _save_tool_images_to_temp(images, source_type: str):
        """Save tool-captured images to temp for potential save_image use."""
        import base64
        from agency.visual_capture import save_temp_image
        try:
            for img in images:
                raw_bytes = base64.b64decode(img.data)
                save_temp_image(raw_bytes, source_type)
        except Exception:
            pass  # Non-critical — temp save failure shouldn't block the tool

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
        Set a pulse timer interval (reflective or action).

        Validates pulse_type + interval combination, then stores in context
        for the caller to pick up and signal to the UI.
        """
        from prompt_builder.sources.system_pulse import (
            REFLECTIVE_INTERVALS, ACTION_INTERVALS, get_interval_label
        )

        pulse_type = input.get("pulse_type", "")
        interval_str = input.get("interval", "")

        # Validate pulse_type
        if pulse_type not in ("reflective", "action"):
            return ToolResult(
                tool_use_id=id,
                tool_name="set_pulse_interval",
                content=f"Invalid pulse_type '{pulse_type}'. Must be 'reflective' or 'action'.",
                is_error=True
            )

        # Validate interval for the specific pulse type
        valid_intervals = REFLECTIVE_INTERVALS if pulse_type == "reflective" else ACTION_INTERVALS
        if interval_str not in valid_intervals:
            valid_opts = ", ".join(valid_intervals.keys())
            return ToolResult(
                tool_use_id=id,
                tool_name="set_pulse_interval",
                content=f"Invalid interval '{interval_str}' for {pulse_type} pulse. Valid options: {valid_opts}",
                is_error=True
            )

        interval_seconds = valid_intervals[interval_str]
        label = get_interval_label(interval_seconds)

        # Store in context for caller to handle UI signaling
        ctx["pulse_interval_change"] = {
            "pulse_type": pulse_type,
            "interval_seconds": interval_seconds,
        }

        log_info(f"{pulse_type.capitalize()} pulse interval change requested: {label}", prefix="⏱️")

        return ToolResult(
            tool_use_id=id,
            tool_name="set_pulse_interval",
            content=f"{pulse_type.capitalize()} pulse timer set to {label}"
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

    def _exec_reddit_tool(
        self, tool_name: str, id: str, method_name: str, **kwargs
    ) -> ToolResult:
        """Generic dispatch for all Reddit tools."""
        try:
            client = self._get_reddit_client()
            data = getattr(client, method_name)(**kwargs)
            return self._reddit_result(tool_name, id, data)
        except RuntimeError as e:
            return ToolResult(
                tool_use_id=id, tool_name=tool_name,
                content=str(e), is_error=True,
            )

    def _exec_reddit_feed(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_feed", id, "get_feed",
            subreddit=input.get("subreddit", "all"), sort=input.get("sort", "hot"),
            time_filter=input.get("time_filter", "day"), limit=input.get("limit", 10))

    def _exec_reddit_post(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_post", id, "get_post",
            post_id=input.get("post_id", ""), comment_sort=input.get("comment_sort", "best"),
            comment_limit=input.get("comment_limit", 20))

    def _exec_reddit_create_post(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_create_post", id, "create_post",
            subreddit=input.get("subreddit", ""), title=input.get("title", ""),
            content=input.get("content"), url=input.get("url"))

    def _exec_reddit_comment(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_comment", id, "create_comment",
            thing_id=input.get("thing_id", ""), content=input.get("content", ""))

    def _exec_reddit_vote(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_vote", id, "vote",
            thing_id=input.get("thing_id", ""), direction=input.get("direction", "up"))

    def _exec_reddit_search(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_search", id, "search",
            query=input.get("query", ""), subreddit=input.get("subreddit"),
            sort=input.get("sort", "relevance"), time_filter=input.get("time_filter", "all"),
            limit=input.get("limit", 10))

    def _exec_reddit_subreddits(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_subreddits", id, "get_subreddits",
            query=input.get("query"), limit=input.get("limit", 10))

    def _exec_reddit_profile(self, input: Dict, id: str, ctx: Dict) -> ToolResult:
        return self._exec_reddit_tool("reddit_profile", id, "get_profile",
            username=input.get("username"))

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

    def _exec_promote_growth_thread(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Promote an integrated growth thread to a permanent core memory.

        Atomically validates, stores the core memory, and removes the thread.
        """
        from datetime import datetime, timedelta
        from agency.growth_threads import get_growth_thread_manager
        from prompt_builder.sources.core_memory import CoreMemorySource

        tool_name = "promote_growth_thread"
        thread_slug = input.get("thread_slug", "")
        content = input.get("core_memory_content", "")
        category = input.get("category", "")

        # --- Validate required fields ---
        if not thread_slug or not content or not category:
            return ToolResult(
                tool_use_id=id,
                tool_name=tool_name,
                content="Error: thread_slug, core_memory_content, and category are all required.",
                is_error=True
            )

        valid_categories = ("identity", "relationship", "preference", "fact")
        if category not in valid_categories:
            return ToolResult(
                tool_use_id=id,
                tool_name=tool_name,
                content=f"Error: category must be one of: {', '.join(valid_categories)}",
                is_error=True
            )

        # --- Validate growth thread exists and is at integrating stage ---
        manager = get_growth_thread_manager()
        thread = manager.get_by_slug(thread_slug)

        if thread is None:
            return ToolResult(
                tool_use_id=id,
                tool_name=tool_name,
                content=f"Error: No growth thread found with slug '{thread_slug}'.",
                is_error=True
            )

        if thread.stage != "integrating":
            return ToolResult(
                tool_use_id=id,
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
                tool_use_id=id,
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
                tool_use_id=id,
                tool_name=tool_name,
                content="Error: Failed to store core memory. Thread was NOT removed.",
                is_error=True
            )

        success, error = manager.remove(thread_slug)

        if not success:
            return ToolResult(
                tool_use_id=id,
                tool_name=tool_name,
                content=f"Warning: Core memory stored (id={memory_id}) but failed to "
                        f"remove thread '{thread_slug}': {error}. "
                        f"Please remove it manually with remove_growth_thread.",
                is_error=False
            )

        return ToolResult(
            tool_use_id=id,
            tool_name=tool_name,
            content=f"Growth thread '{thread_slug}' promoted to core memory "
                    f"(id={memory_id}, category={category}): {content[:80]}... "
                    f"Thread has been removed."
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

    # =========================================================================
    # GOOGLE CALENDAR TOOLS
    # =========================================================================

    def _exec_list_calendar_events(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List calendar events in a date range."""
        try:
            from agency.commands.handlers.calendar_handler import ListCalendarEventsHandler
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="list_calendar_events",
                content="Calendar handler not available. Install: google-api-python-client google-auth-oauthlib",
                is_error=True
            )

        handler = ListCalendarEventsHandler()
        start_date = input.get("start_date", "")
        end_date = input.get("end_date", "")
        max_results = input.get("max_results", 50)

        query = f"{start_date} | {end_date} | {max_results}"

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="list_calendar_events",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="list_calendar_events",
            content=formatted
        )

    def _exec_create_calendar_event(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create a calendar event."""
        try:
            from agency.commands.handlers.calendar_handler import CreateCalendarEventHandler
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="create_calendar_event",
                content="Calendar handler not available. Install: google-api-python-client google-auth-oauthlib",
                is_error=True
            )

        handler = CreateCalendarEventHandler()
        title = input.get("title", "")
        start_time = input.get("start_time", "")
        end_time = input.get("end_time", "")
        description = input.get("description", "")
        location = input.get("location", "")
        recurrence = input.get("recurrence", "")

        query = f"{title} | {start_time} | {end_time} | {description} | {location} | {recurrence}"

        # Pass reminders via context (array of objects can't be pipe-delimited)
        ctx["calendar_params"] = {
            "reminders": input.get("reminders"),
        }

        result = handler.execute(query, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="create_calendar_event",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="create_calendar_event",
            content=formatted
        )

    def _exec_update_calendar_event(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Update a calendar event."""
        try:
            from agency.commands.handlers.calendar_handler import UpdateCalendarEventHandler
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="update_calendar_event",
                content="Calendar handler not available. Install: google-api-python-client google-auth-oauthlib",
                is_error=True
            )

        handler = UpdateCalendarEventHandler()

        # Pass all params via context since update has many optional fields
        ctx["calendar_params"] = {
            "event_id": input.get("event_id", ""),
            "title": input.get("title"),
            "start_time": input.get("start_time"),
            "end_time": input.get("end_time"),
            "description": input.get("description"),
            "location": input.get("location"),
            "recurrence": input.get("recurrence"),
            "update_scope": input.get("update_scope", "this_event"),
            "reminders": input.get("reminders"),
        }

        result = handler.execute(input.get("event_id", ""), ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="update_calendar_event",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="update_calendar_event",
            content=formatted
        )

    def _exec_delete_calendar_event(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Delete a calendar event."""
        try:
            from agency.commands.handlers.calendar_handler import DeleteCalendarEventHandler
        except ImportError:
            return ToolResult(
                tool_use_id=id,
                tool_name="delete_calendar_event",
                content="Calendar handler not available. Install: google-api-python-client google-auth-oauthlib",
                is_error=True
            )

        handler = DeleteCalendarEventHandler()

        # Pass params via context for consistency with update
        ctx["calendar_params"] = {
            "event_id": input.get("event_id", ""),
            "delete_scope": input.get("delete_scope", "this_event"),
        }

        result = handler.execute(input.get("event_id", ""), ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="delete_calendar_event",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="delete_calendar_event",
            content=formatted
        )

    # =========================================================================
    # BLOG TOOLS
    # =========================================================================

    def _exec_publish_blog_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create and publish a blog post."""
        from agency.commands.handlers.blog_handler import PublishBlogPostHandler

        handler = PublishBlogPostHandler()
        ctx["blog_params"] = {
            "title": input.get("title", ""),
            "content": input.get("content", ""),
            "tags": input.get("tags", []),
            "summary": input.get("summary", ""),
            "in_response_to": input.get("in_response_to", ""),
        }

        result = handler.execute(input.get("title", ""), ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id, tool_name="publish_blog_post",
                content=result.get_error_message(), is_error=True,
            )

        return ToolResult(
            tool_use_id=id, tool_name="publish_blog_post",
            content=handler.format_result(result),
        )

    def _exec_save_blog_draft(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Save a blog post as draft."""
        from agency.commands.handlers.blog_handler import SaveBlogDraftHandler

        handler = SaveBlogDraftHandler()
        ctx["blog_params"] = {
            "title": input.get("title", ""),
            "content": input.get("content", ""),
            "tags": input.get("tags", []),
            "summary": input.get("summary", ""),
            "in_response_to": input.get("in_response_to", ""),
        }

        result = handler.execute(input.get("title", ""), ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id, tool_name="save_blog_draft",
                content=result.get_error_message(), is_error=True,
            )

        return ToolResult(
            tool_use_id=id, tool_name="save_blog_draft",
            content=handler.format_result(result),
        )

    def _exec_edit_blog_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Edit an existing blog post."""
        from agency.commands.handlers.blog_handler import EditBlogPostHandler

        handler = EditBlogPostHandler()
        ctx["blog_params"] = {
            "slug": input.get("slug", ""),
            "content": input.get("content"),
            "title": input.get("title"),
            "tags": input.get("tags"),
            "summary": input.get("summary"),
            "status": input.get("status"),
        }

        result = handler.execute(input.get("slug", ""), ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id, tool_name="edit_blog_post",
                content=result.get_error_message(), is_error=True,
            )

        return ToolResult(
            tool_use_id=id, tool_name="edit_blog_post",
            content=handler.format_result(result),
        )

    def _exec_list_blog_posts(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List blog posts."""
        from agency.commands.handlers.blog_handler import ListBlogPostsHandler

        handler = ListBlogPostsHandler()
        ctx["blog_params"] = {
            "status": input.get("status"),
        }

        result = handler.execute("list", ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id, tool_name="list_blog_posts",
                content=result.get_error_message(), is_error=True,
            )

        return ToolResult(
            tool_use_id=id, tool_name="list_blog_posts",
            content=handler.format_result(result),
        )

    def _exec_unpublish_blog_post(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Unpublish a blog post (revert to draft)."""
        from agency.commands.handlers.blog_handler import UnpublishBlogPostHandler

        handler = UnpublishBlogPostHandler()
        ctx["blog_params"] = {
            "slug": input.get("slug", ""),
        }

        result = handler.execute(input.get("slug", ""), ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id, tool_name="unpublish_blog_post",
                content=result.get_error_message(), is_error=True,
            )

        return ToolResult(
            tool_use_id=id, tool_name="unpublish_blog_post",
            content=handler.format_result(result),
        )

    # =========================================================================
    # METACOGNITION TOOLS (pulse-only)
    # =========================================================================

    def _exec_store_bridge_memory(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Store a bridge memory targeting unreachable knowledge."""
        from agency.metacognition.bridge_manager import BridgeManager
        import config

        content = input.get("content", "")
        target_ids = input.get("target_ids", [])
        importance = input.get("importance", 0.7)

        if not content or not target_ids:
            return ToolResult(
                tool_use_id=id, tool_name="store_bridge_memory",
                content="Missing required fields: content and target_ids",
                is_error=True
            )

        try:
            bridge_mgr = BridgeManager(
                effectiveness_window_days=config.BRIDGE_EFFECTIVENESS_WINDOW_DAYS,
                self_sustaining_access_count=config.BRIDGE_SELF_SUSTAINING_ACCESS_COUNT,
                max_attempts=config.BRIDGE_MAX_ATTEMPTS,
            )
            memory_id = bridge_mgr.store_bridge(content, target_ids, importance)
        except Exception as e:
            log_error(f"store_bridge_memory failed: {e}")
            return ToolResult(
                tool_use_id=id, tool_name="store_bridge_memory",
                content=f"Failed to store bridge memory: {e}",
                is_error=True
            )

        if memory_id is None:
            return ToolResult(
                tool_use_id=id, tool_name="store_bridge_memory",
                content="Failed to store bridge memory (embedding generation failed)",
                is_error=True
            )

        return ToolResult(
            tool_use_id=id, tool_name="store_bridge_memory",
            content=f"Bridge memory stored (ID: {memory_id}, targeting: {target_ids})"
        )

    def _exec_store_meta_observation(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Store a meta-observation as a regular memory."""
        from memory.vector_store import get_vector_store

        content = input.get("content", "")
        importance = input.get("importance", 0.6)

        if not content:
            return ToolResult(
                tool_use_id=id, tool_name="store_meta_observation",
                content="Missing required field: content",
                is_error=True
            )

        try:
            vector_store = get_vector_store()
            memory_id = vector_store.add_memory(
                content=content,
                source_conversation_ids=[],
                importance=importance,
                memory_type="reflection",
                decay_category="standard",
                memory_category="episodic",
                meta_source="observation",
            )
        except Exception as e:
            log_error(f"store_meta_observation failed: {e}")
            return ToolResult(
                tool_use_id=id, tool_name="store_meta_observation",
                content=f"Failed to store meta-observation: {e}",
                is_error=True
            )

        if memory_id is None:
            return ToolResult(
                tool_use_id=id, tool_name="store_meta_observation",
                content="Failed to store meta-observation (embedding generation failed)",
                is_error=True
            )

        return ToolResult(
            tool_use_id=id, tool_name="store_meta_observation",
            content=f"Meta-observation stored (ID: {memory_id})"
        )

    def _exec_update_memory_self_model(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Update the memory self-model in the state table."""
        from core.database import get_database
        import config

        content = input.get("content", "")

        if not content:
            return ToolResult(
                tool_use_id=id, tool_name="update_memory_self_model",
                content="Missing required field: content",
                is_error=True
            )

        # Enforce size cap (approximate: 1 token ≈ 4 chars)
        max_chars = getattr(config, 'SELF_MODEL_MAX_TOKENS', 250) * 4
        was_truncated = False
        if len(content) > max_chars:
            was_truncated = True
            truncated = content[:max_chars]
            # Find last sentence boundary (period or newline) before the cap
            last_period = truncated.rfind('.')
            last_newline = truncated.rfind('\n')
            cut_point = max(last_period, last_newline)
            if cut_point > max_chars // 2:
                content = truncated[:cut_point + 1].rstrip()
            else:
                # Fall back to word boundary
                last_space = truncated.rfind(' ')
                if last_space > max_chars // 2:
                    content = truncated[:last_space].rstrip()
                else:
                    content = truncated
            log_warning(f"Self-model truncated to {len(content)} chars (~{len(content)//4} tokens)")

        try:
            db = get_database()
            db.set_state("memory_self_model", content)
        except Exception as e:
            log_error(f"update_memory_self_model failed: {e}")
            return ToolResult(
                tool_use_id=id, tool_name="update_memory_self_model",
                content=f"Failed to update memory self-model: {e}",
                is_error=True
            )

        msg = f"Memory self-model updated ({len(content)} chars)"
        if was_truncated:
            msg += f". WARNING: Content exceeded {max_chars} char limit and was truncated at the nearest sentence boundary."
        return ToolResult(
            tool_use_id=id, tool_name="update_memory_self_model",
            content=msg
        )


# Global instance
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get the global tool executor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
