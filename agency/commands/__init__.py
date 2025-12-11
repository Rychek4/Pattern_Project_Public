"""
Pattern Project - AI Command System
Enables AI-initiated information retrieval via embedded commands
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

    # Register goal and economy handlers
    if config.AGENCY_ECONOMY_ENABLED:
        from agency.commands.handlers.goal_handler import (
            SetGoalHandler,
            CompleteGoalHandler,
            ActivateGoalHandler,
            SelectTopGoalHandler,
        )
        from agency.commands.handlers.economy_handler import SetTempoHandler

        processor.register(SetGoalHandler())
        processor.register(CompleteGoalHandler())
        processor.register(ActivateGoalHandler())
        processor.register(SelectTopGoalHandler())
        processor.register(SetTempoHandler())


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
