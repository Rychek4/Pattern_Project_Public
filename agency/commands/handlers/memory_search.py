"""
Pattern Project - Memory Search Command Handler
Handles [[SEARCH: query]] commands for memory retrieval
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class MemorySearchHandler(CommandHandler):
    """
    Handles [[SEARCH: query]] commands for AI-initiated memory retrieval.

    This enables the AI to actively search its memory archive when it needs
    more context than the automatically-injected memories provide.

    Example AI usage:
        "Let me check my memories... [[SEARCH: book recommendations]]"
    """

    def __init__(self, default_limit: int = None, min_score: float = None):
        """
        Initialize the memory search handler.

        Args:
            default_limit: Maximum number of memories to return (uses config default)
            min_score: Minimum relevance score threshold (uses config default)
        """
        from config import COMMAND_SEARCH_LIMIT, COMMAND_SEARCH_MIN_SCORE

        self.default_limit = default_limit if default_limit is not None else COMMAND_SEARCH_LIMIT
        self.min_score = min_score if min_score is not None else COMMAND_SEARCH_MIN_SCORE

    @property
    def command_name(self) -> str:
        return "SEARCH"

    @property
    def pattern(self) -> str:
        # Matches [[SEARCH: anything here]]
        # Non-greedy to handle multiple commands in one response
        return r'\[\[SEARCH:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        # AI needs to see search results to formulate response
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Execute a memory search.

        Args:
            query: The search query from the AI
            context: Session context (unused currently)

        Returns:
            CommandResult with search results or error
        """
        from memory.vector_store import get_vector_store

        try:
            vector_store = get_vector_store()
            results = vector_store.search(
                query=query,
                limit=self.default_limit,
                min_score=self.min_score
            )

            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=results,
                needs_continuation=True,
                display_text=f"Searching memories: {query}"
            )

        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Memory search failed: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def get_instructions(self) -> str:
        """Return instructions for the AI on how to use this command."""
        return """You can search your memory archive by including this command in your response:
  [[SEARCH: your query here]]

Use this when:
- The user asks about past conversations ("What did we discuss about...")
- You need more context than the automatically-recalled memories provide
- The user references something with "remember when..." or similar

The search executes and results are provided for you to continue your response."""

    def format_result(self, result: CommandResult) -> str:
        """
        Format memory search results for the continuation prompt.

        Args:
            result: The CommandResult from execute()

        Returns:
            Formatted string showing search results
        """
        if result.error:
            error_msg = result.get_error_message()
            return f"  {error_msg}"

        if not result.data:
            return "  No matching memories found."

        lines = []
        for r in result.data:
            mem = r.memory
            score = r.combined_score

            # Add temporal context if available
            timestamp_str = ""
            if mem.source_timestamp:
                from core.temporal import format_fuzzy_relative_time
                timestamp_str = f" ({format_fuzzy_relative_time(mem.source_timestamp)})"

            # Format: type, content, timestamp, score
            mem_type = mem.memory_type or "memory"
            lines.append(
                f"  - [{mem_type}] {mem.content}{timestamp_str} [relevance: {score:.2f}]"
            )

        return "\n".join(lines)
