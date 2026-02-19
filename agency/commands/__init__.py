"""
Pattern Project - Command Handlers

This module provides the handler infrastructure used by the native tool
executor in agency/tools/executor.py. Each handler encapsulates the
business logic for a specific tool capability (memory search, file I/O,
reminders, communication, etc.).

The legacy [[COMMAND: arg]] pattern-matching processor was removed in
February 2026 as part of dead-code cleanup. The handlers themselves
remain active — they are instantiated and called by ToolExecutor.
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType

__all__ = [
    'CommandHandler',
    'CommandResult',
    'ToolError',
    'ToolErrorType',
]
