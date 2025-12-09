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

    # Register memory search handler
    processor.register(MemorySearchHandler())


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
