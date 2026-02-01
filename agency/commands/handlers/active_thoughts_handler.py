"""
Pattern Project - Active Thoughts Command Handler
Handles [[SET_THOUGHTS: ...]] command for updating the AI's working memory
"""

import json
import re
from typing import Optional

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType
from core.logger import log_info


class SetThoughtsHandler(CommandHandler):
    """
    Handles [[SET_THOUGHTS: json_array]] commands for updating active thoughts.

    The AI sends its complete list of active thoughts (0-10 items) and this
    handler replaces the existing list entirely. This "full rewrite" approach
    forces the AI to consider the whole list holistically when making changes.

    Example:
        [[SET_THOUGHTS: [{"rank":1,"slug":"identity","topic":"Who I am","elaboration":"Thinking about..."}]]]
    """

    @property
    def command_name(self) -> str:
        return "SET_THOUGHTS"

    @property
    def pattern(self) -> str:
        # Match [[SET_THOUGHTS: followed by a JSON array, allowing for nested brackets
        # Using a more permissive pattern that captures everything up to the closing ]]
        return r'\[\[SET_THOUGHTS:\s*(\[[\s\S]*?\])\s*\]\]'

    @property
    def needs_continuation(self) -> bool:
        # Fire-and-forget: AI doesn't need to see confirmation
        return False

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Update the active thoughts list.

        Args:
            query: The extracted JSON array string
            context: Session context

        Returns:
            CommandResult with update outcome
        """
        from agency.active_thoughts import get_active_thoughts_manager

        # Parse JSON
        try:
            thoughts = json.loads(query)
        except json.JSONDecodeError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query[:100] + "..." if len(query) > 100 else query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.PARSE_ERROR,
                    message=f"Invalid JSON: {e}",
                    expected_format="set_active_thoughts with thoughts array parameter",
                    example='set_active_thoughts(thoughts=[{"rank":1,"slug":"example","topic":"Topic","elaboration":"Details..."}])'
                )
            )

        if not isinstance(thoughts, list):
            return CommandResult(
                command_name=self.command_name,
                query=query[:100] + "..." if len(query) > 100 else query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message="Expected a JSON array, got " + type(thoughts).__name__,
                    expected_format="set_active_thoughts with thoughts array parameter",
                    example='set_active_thoughts(thoughts=[{"rank":1,"slug":"example","topic":"Topic","elaboration":"Details..."}])'
                )
            )

        # Update via manager (which handles validation)
        manager = get_active_thoughts_manager()
        success, error_msg = manager.set_all(thoughts)

        if success:
            # Emit to dev window
            self._emit_to_dev_window(thoughts)

            return CommandResult(
                command_name=self.command_name,
                query=f"{len(thoughts)} thoughts",
                data={"count": len(thoughts), "thoughts": thoughts},
                needs_continuation=False,
                display_text=f"Active thoughts updated: {len(thoughts)} item{'s' if len(thoughts) != 1 else ''}"
            )
        else:
            return CommandResult(
                command_name=self.command_name,
                query=query[:100] + "..." if len(query) > 100 else query,
                data=None,
                needs_continuation=False,
                error=ToolError(
                    error_type=ToolErrorType.VALIDATION,
                    message=error_msg or "Validation failed",
                    expected_format="Each thought needs: rank (1-10), slug, topic, elaboration",
                    example='{"rank":1,"slug":"my-thought","topic":"Short topic","elaboration":"Detailed thinking..."}'
                )
            )

    def _emit_to_dev_window(self, thoughts: list) -> None:
        """Emit update to dev window if active."""
        try:
            from interface.dev_window import emit_active_thoughts_update
            emit_active_thoughts_update(thoughts)
        except ImportError:
            # Dev window not available (e.g., CLI mode)
            pass
        except Exception:
            # Don't fail command if dev window update fails
            pass

    def get_instructions(self) -> str:
        """Return instructions for the AI on how to use this command."""
        return """Update your active thoughts - your private working memory:
  [[SET_THOUGHTS: [{"rank":1,"slug":"slug","topic":"Topic","elaboration":"Your thinking..."},...]]]

This is your compass for interacting with reality. Use it for:
  - Identity anchors you want to keep front-of-mind
  - Unresolved questions you're processing
  - Long-term goals or aspirations
  - Anything that deserves your ongoing attention

Rules:
  - Maximum 10 items, ranked 1 (most salient) to 10
  - Each item needs: rank, slug, topic, elaboration
  - Elaborations should be ~50-75 words - substantial but focused
  - Send the full list each time (replaces existing)
  - You control this completely: add, edit, rerank, delete as priorities shift"""
