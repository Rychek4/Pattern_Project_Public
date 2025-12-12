"""
Pattern Project - Command Processor (DEPRECATED)

DEPRECATION NOTICE (December 2025):
This module implements the legacy [[COMMAND: arg]] pattern processor.
It has been superseded by the native tool use system in agency/tools/.

The CommandProcessor uses regex pattern matching to find [[COMMAND: arg]]
patterns in AI responses, which is fragile and requires extensive prompt
documentation. The native tool system uses structured API calls instead.

For new code, use agency/tools/processor.py and agency/tools/executor.py.

This module is kept for:
1. Backwards compatibility during transition
2. Reference implementation
3. The handlers it uses are still active (via ToolExecutor)
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, TYPE_CHECKING

from agency.commands.handlers.base import CommandHandler, CommandResult
from core.logger import log_info, log_warning, log_error

# Type hint for ImageContent without circular import
if TYPE_CHECKING:
    from agency.visual_capture import ImageContent


@dataclass
class ProcessedResponse:
    """
    Result of processing a response for commands.

    Attributes:
        original_text: Unmodified AI response
        display_text: Text formatted for display (commands may be styled)
        commands_executed: List of all executed commands
        needs_continuation: Whether a second LLM pass is required
        continuation_prompt: Formatted prompt text for pass 2 (if needed)
        continuation_images: Images to attach to continuation message
    """
    original_text: str
    display_text: str
    commands_executed: List[CommandResult] = field(default_factory=list)
    needs_continuation: bool = False
    continuation_prompt: Optional[str] = None
    continuation_images: Optional[List["ImageContent"]] = field(default=None)

    def has_continuation_images(self) -> bool:
        """Check if there are images to include in continuation."""
        return self.continuation_images is not None and len(self.continuation_images) > 0


class CommandProcessor:
    """
    Processes AI responses for embedded commands and executes them.

    The processor:
    1. Scans AI responses for [[COMMAND: query]] patterns
    2. Executes matching registered handlers
    3. Determines if a continuation (pass 2) is needed
    4. Builds the continuation prompt with command results

    Usage:
        processor = CommandProcessor()
        processor.register(MemorySearchHandler())

        result = processor.process(response_text)
        if result.needs_continuation:
            # Call LLM again with result.continuation_prompt
    """

    def __init__(self):
        self._handlers: Dict[str, CommandHandler] = {}

    def register(self, handler: CommandHandler) -> None:
        """
        Register a command handler.

        Args:
            handler: CommandHandler instance to register
        """
        self._handlers[handler.command_name] = handler
        log_info(f"Registered command handler: [[{handler.command_name}:]]", prefix="🔧")

    def unregister(self, command_name: str) -> bool:
        """
        Unregister a command handler.

        Args:
            command_name: Name of command to unregister

        Returns:
            True if handler was removed, False if not found
        """
        if command_name in self._handlers:
            del self._handlers[command_name]
            log_info(f"Unregistered command handler: [[{command_name}:]]", prefix="🔧")
            return True
        return False

    def process(self, response_text: str, context: Optional[dict] = None) -> ProcessedResponse:
        """
        Process a response for commands, execute them, prepare continuation if needed.

        Args:
            response_text: The AI's response text
            context: Optional session context dict

        Returns:
            ProcessedResponse with execution results
        """
        context = context or {}
        commands_executed: List[CommandResult] = []
        needs_continuation = False

        # Find and execute all commands
        # re.DOTALL allows . to match newlines, enabling multi-line command content
        for handler in self._handlers.values():
            for match in re.finditer(handler.pattern, response_text, re.DOTALL):
                # Get query from capture group if it exists, empty string for parameterless commands
                query = match.group(1).strip() if match.lastindex else ""
                log_info(f"Executing [[{handler.command_name}: {query}]]", prefix="⚡")

                try:
                    result = handler.execute(query, context)
                    commands_executed.append(result)

                    # Trigger continuation if handler requires it OR if there's an error
                    # This ensures the AI always learns about failures
                    if result.needs_continuation or result.error:
                        needs_continuation = True

                    if result.error:
                        log_warning(f"Command [[{handler.command_name}]] error: {result.error}")
                    else:
                        log_info(f"Command [[{handler.command_name}]] completed", prefix="✓")

                except Exception as e:
                    log_error(f"Command [[{handler.command_name}]] exception: {e}")
                    # Create error result so AI is informed
                    # Always trigger continuation on exceptions so AI can recover
                    commands_executed.append(CommandResult(
                        command_name=handler.command_name,
                        query=query,
                        data=None,
                        needs_continuation=True,  # Force continuation on exception
                        error=str(e)
                    ))
                    needs_continuation = True

        # Build continuation prompt and collect images if needed
        continuation_prompt = None
        continuation_images = None
        if needs_continuation and commands_executed:
            continuation_prompt, continuation_images = self._build_continuation_prompt(commands_executed)

        # Format display text
        display_text = self._format_display_text(response_text, commands_executed)

        return ProcessedResponse(
            original_text=response_text,
            display_text=display_text,
            commands_executed=commands_executed,
            needs_continuation=needs_continuation,
            continuation_prompt=continuation_prompt,
            continuation_images=continuation_images
        )

    def _build_continuation_prompt(self, results: List[CommandResult]) -> tuple:
        """
        Build the continuation prompt with command results.

        Includes both successful commands that need continuation AND
        any commands that encountered errors (so AI can recover).
        Also collects any images from visual commands.

        Args:
            results: List of CommandResult from executed commands

        Returns:
            Tuple of (prompt_text, images_list) for pass 2
        """
        lines = ["[Command Results]", ""]
        collected_images = []

        for result in results:
            # Include commands that need continuation OR had errors
            if result.needs_continuation or result.error:
                handler = self._handlers.get(result.command_name)

                # Collect images from visual commands
                if result.has_images():
                    collected_images.extend(result.image_data)
                    log_info(
                        f"Collected {len(result.image_data)} image(s) from [[{result.command_name}]]",
                        prefix="🖼️"
                    )

                # Format the result data
                if handler:
                    try:
                        formatted = handler.format_result(result)
                    except Exception as e:
                        log_error(f"Error formatting [[{result.command_name}]] result: {e}")
                        formatted = f"  Error formatting result: {e}"
                elif result.error:
                    # Fallback for errors without a handler
                    error_msg = result.get_error_message() if hasattr(result, 'get_error_message') else str(result.error)
                    formatted = f"  {error_msg}"
                elif result.data is None:
                    formatted = "  No results."
                else:
                    formatted = str(result.data)

                # Use command name without query for parameterless commands
                if result.query:
                    lines.append(f"Your [[{result.command_name}: {result.query}]] returned:")
                else:
                    lines.append(f"Your [[{result.command_name}]] returned:")
                lines.append(formatted)
                lines.append("")

        lines.append("Continue your response naturally, incorporating this information.")

        prompt_text = "\n".join(lines)
        images_list = collected_images if collected_images else None

        return prompt_text, images_list

    def _format_display_text(self, text: str, results: List[CommandResult]) -> str:
        """
        Format response text for display.

        Currently preserves commands as-is for transparency.
        Could be extended to style or strip commands.

        Args:
            text: Original response text
            results: Executed command results

        Returns:
            Formatted text for display
        """
        # For now, leave commands visible - user sees AI requested search
        # Future: could style them like [[SEARCH: query]] -> 🔍 Searching: query
        return text

    def get_all_instructions(self) -> str:
        """
        Get combined instructions for all registered commands.

        Returns:
            Concatenated instruction strings from all handlers
        """
        instructions = []
        for handler in self._handlers.values():
            inst = handler.get_instructions()
            if inst and inst.strip():
                instructions.append(inst.strip())

        if not instructions:
            return ""

        return "\n\n".join(instructions)

    def has_handlers(self) -> bool:
        """
        Check if any handlers are registered.

        Returns:
            True if at least one handler is registered
        """
        return len(self._handlers) > 0

    def list_handlers(self) -> List[str]:
        """
        List registered handler names.

        Returns:
            List of command names
        """
        return list(self._handlers.keys())
