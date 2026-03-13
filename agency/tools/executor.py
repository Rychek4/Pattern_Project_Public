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
        """Set a pulse timer interval (reflective or action)."""
        from agency.commands.handlers.pulse_handler import exec_set_pulse_interval
        return exec_set_pulse_interval(input, id, ctx)

    # =========================================================================
    # CURIOSITY TOOLS
    # =========================================================================

    def _exec_advance_curiosity(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Advance a curiosity goal (progress, resolve, or resolve+pick next)."""
        from agency.commands.handlers.curiosity_handler import exec_advance_curiosity
        return exec_advance_curiosity(input, id, ctx)


    # =========================================================================
    # WEB FETCH DOMAIN MANAGEMENT TOOLS
    # =========================================================================

    def _exec_manage_fetch_domains(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Manage web fetch domain allow/block lists."""
        from agency.commands.handlers.fetch_domain_handler import exec_manage_fetch_domains
        return exec_manage_fetch_domains(input, id, ctx)

    def _exec_list_fetch_domains(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """List current web fetch domain configuration."""
        from agency.commands.handlers.fetch_domain_handler import exec_list_fetch_domains
        return exec_list_fetch_domains(input, id, ctx)

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
        """Delegate a task to a lightweight sub-agent."""
        from agency.commands.handlers.delegation_handler import exec_delegate_task
        return exec_delegate_task(input, id, ctx)


    # =========================================================================
    # GROWTH THREAD TOOLS (Pulse-only)
    # =========================================================================

    def _exec_set_growth_thread(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Create or update a growth thread."""
        from agency.commands.handlers.growth_thread_handler import exec_set_growth_thread
        return exec_set_growth_thread(input, id, ctx)

    def _exec_remove_growth_thread(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Remove a growth thread."""
        from agency.commands.handlers.growth_thread_handler import exec_remove_growth_thread
        return exec_remove_growth_thread(input, id, ctx)

    def _exec_promote_growth_thread(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Promote an integrated growth thread to a permanent core memory."""
        from agency.commands.handlers.growth_thread_handler import exec_promote_growth_thread
        return exec_promote_growth_thread(input, id, ctx)

    # =========================================================================
    # NOVEL READING TOOLS
    # =========================================================================

    def _exec_open_book(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Open a novel for reading."""
        from agency.commands.handlers.novel_handler import exec_open_book
        return exec_open_book(input, id, ctx)

    def _exec_read_next_chapter(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Read the next chapter of the current book."""
        from agency.commands.handlers.novel_handler import exec_read_next_chapter
        return exec_read_next_chapter(input, id, ctx)

    def _exec_complete_reading(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Complete the reading session with final synthesis."""
        from agency.commands.handlers.novel_handler import exec_complete_reading
        return exec_complete_reading(input, id, ctx)

    def _exec_reading_progress(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Get current reading progress."""
        from agency.commands.handlers.novel_handler import exec_reading_progress
        return exec_reading_progress(input, id, ctx)

    def _exec_abandon_reading(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Abandon the current reading session."""
        from agency.commands.handlers.novel_handler import exec_abandon_reading
        return exec_abandon_reading(input, id, ctx)

    def _exec_resume_reading(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Resume an interrupted reading session."""
        from agency.commands.handlers.novel_handler import exec_resume_reading
        return exec_resume_reading(input, id, ctx)

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
        from agency.commands.handlers.metacognition_exec_handler import exec_store_bridge_memory
        return exec_store_bridge_memory(input, id, ctx)

    def _exec_store_meta_observation(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Store a meta-observation as a regular memory."""
        from agency.commands.handlers.metacognition_exec_handler import exec_store_meta_observation
        return exec_store_meta_observation(input, id, ctx)

    def _exec_update_memory_self_model(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Update the memory self-model in the state table."""
        from agency.commands.handlers.metacognition_exec_handler import exec_update_memory_self_model
        return exec_update_memory_self_model(input, id, ctx)


# Global instance
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get the global tool executor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor
