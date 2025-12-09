"""
Pattern Project - Command Handler Base
Abstract interface for AI command handlers
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CommandResult:
    """
    Result from executing a command.

    Attributes:
        command_name: The command identifier (e.g., "SEARCH")
        query: What the AI requested
        data: Retrieved data (None for fire-and-forget commands)
        needs_continuation: Whether AI needs to see results in pass 2
        display_text: Optional user-facing status text
        error: Error message if execution failed
    """
    command_name: str
    query: str
    data: Any
    needs_continuation: bool
    display_text: Optional[str] = None
    error: Optional[str] = None


class CommandHandler(ABC):
    """
    Base class for AI command handlers.

    Each handler processes a specific command type (e.g., [[SEARCH: query]]).
    Handlers define:
    - The command syntax (regex pattern)
    - Execution logic
    - Whether results need to be shown to AI (continuation)
    - Instructions for the AI on how to use the command
    """

    @property
    @abstractmethod
    def command_name(self) -> str:
        """
        Command identifier (e.g., 'SEARCH').
        Used in [[COMMAND_NAME: query]] syntax.
        """
        pass

    @property
    @abstractmethod
    def pattern(self) -> str:
        """
        Regex pattern to match the command in AI responses.
        Must include a capture group for the query.
        Example: r'\\[\\[SEARCH:\\s*(.+?)\\]\\]'
        """
        pass

    @property
    def needs_continuation(self) -> bool:
        """
        Whether this command type requires a second LLM pass.

        True for query commands (AI needs to see results).
        False for fire-and-forget commands (like pulse timer).

        Default: False
        """
        return False

    @abstractmethod
    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Execute the command.

        Args:
            query: The extracted query from the command
            context: Session context dict for cross-component data

        Returns:
            CommandResult with execution outcome
        """
        pass

    @abstractmethod
    def get_instructions(self) -> str:
        """
        Return prompt instructions explaining this command to the AI.

        These instructions are injected into the system prompt so the AI
        knows how and when to use this command.
        """
        pass

    def format_result(self, result: CommandResult) -> str:
        """
        Format result data for the continuation prompt.

        Override this method for custom formatting of specific data types.

        Args:
            result: The CommandResult from execute()

        Returns:
            Formatted string for inclusion in continuation prompt
        """
        if result.error:
            return f"  Error: {result.error}"
        if result.data is None:
            return "  No results."
        return str(result.data)
