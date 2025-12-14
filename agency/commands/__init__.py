"""
Pattern Project - AI Command System (DEPRECATED)

DEPRECATION NOTICE (December 2025):
This module implements the legacy [[COMMAND: arg]] pattern system.
It has been superseded by the native tool use system in agency/tools/.

The native tool system provides:
- Structured JSON arguments (no regex parsing)
- Parallel tool execution
- Typed error handling
- Reduced prompt size (no command documentation needed)

This module is kept for:
1. Backwards compatibility during transition
2. Reference implementation for handlers (still used by ToolExecutor)
3. Historical context

For new code, use agency/tools/ instead:
    from agency.tools import get_tool_definitions, process_with_tools

The underlying handlers in agency/commands/handlers/ are still actively used
by the ToolExecutor - only the pattern-matching processor is deprecated.
"""

from typing import Optional

from agency.commands.processor import CommandProcessor, ProcessedResponse
from agency.commands.handlers.base import CommandHandler, CommandResult


# Global processor instance
_command_processor: Optional[CommandProcessor] = None


def get_command_processor() -> CommandProcessor:
    """
    Get the global command processor instance.

    Lazily initializes the processor and registers default handlers.

    Returns:
        The global CommandProcessor instance
    """
    global _command_processor
    if _command_processor is None:
        _command_processor = CommandProcessor()
        _register_default_handlers(_command_processor)
    return _command_processor


def init_command_processor() -> CommandProcessor:
    """
    Initialize or reset the global command processor.

    Use this to reinitialize the processor with fresh handlers.

    Returns:
        The newly initialized CommandProcessor instance
    """
    global _command_processor
    _command_processor = CommandProcessor()
    _register_default_handlers(_command_processor)
    return _command_processor


def _register_default_handlers(processor: CommandProcessor) -> None:
    """
    Register the default command handlers.

    Args:
        processor: CommandProcessor to register handlers with
    """
    # Import handlers here to avoid circular imports
    from agency.commands.handlers.memory_search import MemorySearchHandler
    from agency.commands.handlers.intention_handler import (
        RemindHandler,
        CompleteHandler,
        DismissHandler,
        ListIntentionsHandler,
    )
    from agency.commands.handlers.file_handler import (
        ReadFileHandler,
        WriteFileHandler,
        AppendFileHandler,
        ListFilesHandler,
    )
    from agency.commands.handlers.active_thoughts_handler import SetThoughtsHandler

    # Register memory search handler
    processor.register(MemorySearchHandler())

    # Register active thoughts handler
    processor.register(SetThoughtsHandler())

    # Register intention handlers
    processor.register(RemindHandler())
    processor.register(CompleteHandler())
    processor.register(DismissHandler())
    processor.register(ListIntentionsHandler())

    # Register file handlers
    processor.register(ReadFileHandler())
    processor.register(WriteFileHandler())
    processor.register(AppendFileHandler())
    processor.register(ListFilesHandler())

    # Register communication handlers (Telegram/Email)
    # Import config to check feature flags
    import config

    if config.TELEGRAM_ENABLED:
        from agency.commands.handlers.telegram_handler import SendTelegramHandler
        processor.register(SendTelegramHandler())

    if config.EMAIL_GATEWAY_ENABLED:
        from agency.commands.handlers.email_handler import SendEmailHandler
        processor.register(SendEmailHandler())

    # Register visual capture handlers (only for sources in on_demand mode)
    # Each source has independent mode: "auto", "on_demand", or "disabled"
    # In auto mode, images are automatically attached to every prompt
    # In on_demand mode, AI can request captures via [[SCREENSHOT]] and [[WEBCAM]]
    if config.VISUAL_ENABLED:
        from agency.commands.handlers.visual_handler import (
            ScreenshotHandler,
            WebcamHandler
        )
        from core.logger import log_info

        registered = []
        if config.VISUAL_SCREENSHOT_MODE == "on_demand":
            processor.register(ScreenshotHandler())
            registered.append("screenshot")

        if config.VISUAL_WEBCAM_MODE == "on_demand":
            processor.register(WebcamHandler())
            registered.append("webcam")

        if registered:
            log_info(f"Visual capture commands registered: {', '.join(registered)}", prefix="📷")


__all__ = [
    # Processor
    'CommandProcessor',
    'ProcessedResponse',
    # Handlers
    'CommandHandler',
    'CommandResult',
    # Functions
    'get_command_processor',
    'init_command_processor',
]
