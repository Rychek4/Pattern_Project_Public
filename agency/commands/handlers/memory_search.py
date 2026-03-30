"""
Pattern Project - Memory Search Command Handler
Handles memory retrieval via the search_memories native tool.
Supports both standard search and explore mode (neighborhood traversal).
"""

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class MemorySearchHandler(CommandHandler):
    """
    Handles AI-initiated memory retrieval via the search_memories native tool.

    This enables the AI to actively search its memory archive when it needs
    more context than the automatically-injected memories provide.

    Supports two modes:
    - Standard search: Query is embedded and scored against both stores.
    - Explore mode: Given a seed memory ID, retrieves the neighborhood
      around that memory in embedding space.

    Called by ToolExecutor when the AI invokes the search_memories tool.
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

    def execute(self, query: str, context: dict, explore_from: int = None) -> CommandResult:
        """
        Execute a memory search or explore operation.

        Args:
            query: The search query from the AI
            context: Session context
            explore_from: Optional memory ID to explore from (triggers explore mode)

        Returns:
            CommandResult with search or explore results
        """
        from memory.vector_store import get_vector_store

        try:
            vector_store = get_vector_store()

            if explore_from is not None:
                return self._execute_explore(vector_store, explore_from, query, context)
            else:
                return self._execute_search(vector_store, query, context)

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

    def _execute_search(self, vector_store, query: str, context: dict) -> CommandResult:
        """Execute standard memory search."""
        results = vector_store.search(
            query=query,
            limit=self.default_limit,
            min_score=self.min_score
        )

        return CommandResult(
            command_name=self.command_name,
            query=query,
            data={"mode": "search", "results": results},
            needs_continuation=True,
            display_text=f"Searching memories: {query}"
        )

    def _execute_explore(self, vector_store, seed_id: int, query: str, context: dict) -> CommandResult:
        """Execute explore mode from a seed memory."""
        from core.logger import log_warning

        seed_memory, explore_results = vector_store.explore(
            seed_memory_id=seed_id,
            query=query if query else None,
            limit=self.default_limit,
        )

        # Seed not found — fall back to standard search
        if seed_memory is None:
            log_warning(
                f"Explore: seed memory #{seed_id} not found, falling back to standard search"
            )
            result = self._execute_search(vector_store, query, context)
            # Annotate so format_result can add a note about the fallback
            result.data["fallback_from_explore"] = seed_id
            return result

        return CommandResult(
            command_name=self.command_name,
            query=query,
            data={
                "mode": "explore",
                "seed_memory": seed_memory,
                "results": explore_results,
            },
            needs_continuation=True,
            display_text=f"Exploring neighborhood of memory #{seed_id}"
        )

    def format_result(self, result: CommandResult) -> str:
        """
        Format search or explore results for the continuation prompt.

        Args:
            result: The CommandResult from execute()

        Returns:
            Formatted string showing results
        """
        if result.error:
            error_msg = result.get_error_message()
            return f"  {error_msg}"

        if not result.data:
            return "  No matching memories found."

        mode = result.data.get("mode", "search")

        if mode == "explore":
            return self._format_explore_result(result)
        else:
            return self._format_search_result(result)

    def _format_search_result(self, result: CommandResult) -> str:
        """Format standard search results with memory IDs for chaining."""
        results = result.data.get("results", [])
        fallback_id = result.data.get("fallback_from_explore")

        if not results:
            if fallback_id:
                return (
                    f"  Memory #{fallback_id} not found (may have been deleted or decayed). "
                    f"No matching memories found for fallback query."
                )
            return "  No matching memories found."

        lines = []

        if fallback_id:
            lines.append(
                f"  Note: Memory #{fallback_id} not found. "
                f"Fell back to standard search.\n"
            )

        for r in results:
            mem = r.memory
            score = r.combined_score

            # Add temporal context if available
            timestamp_str = ""
            if mem.source_timestamp:
                from core.temporal import format_fuzzy_relative_time
                timestamp_str = f" ({format_fuzzy_relative_time(mem.source_timestamp)})"

            # Format: memory ID, type, content, timestamp, score
            mem_type = mem.memory_type or "memory"
            lines.append(
                f"  - [memory #{mem.id}] [{mem_type}] {mem.content}{timestamp_str} [relevance: {score:.2f}]"
            )

        return "\n".join(lines)

    def _format_explore_result(self, result: CommandResult) -> str:
        """Format explore results with tier labels and memory IDs."""
        seed_memory = result.data["seed_memory"]
        explore_results = result.data.get("results", [])

        # Header: what we're exploring from
        seed_preview = seed_memory.content
        if len(seed_preview) > 100:
            seed_preview = seed_preview[:97] + "..."
        lines = [
            f'  [Exploring memories connected to memory #{seed_memory.id}: "{seed_preview}"]',
            ""
        ]

        if not explore_results:
            lines.append("  No connected memories found. This memory appears to be isolated.")
            return "\n".join(lines)

        # Group by tier
        closely = [r for r in explore_results if r.tier == "closely_connected"]
        connected = [r for r in explore_results if r.tier == "connected"]
        loose = [r for r in explore_results if r.tier == "loosely_associated"]

        # Group by category within each tier for presentation
        def format_tier_entries(entries, tier_label):
            if not entries:
                return []
            tier_lines = [f"  {tier_label}:"]

            # Separate episodic and factual
            factual = [e for e in entries if e.memory.memory_category == "factual"]
            episodic = [e for e in entries if e.memory.memory_category == "episodic"]

            for entry in factual:
                mem = entry.memory
                tier_lines.append(f"    - [memory #{mem.id}] {mem.content}")

            for entry in episodic:
                mem = entry.memory
                timestamp_str = ""
                if mem.source_timestamp:
                    from core.temporal import format_fuzzy_relative_time
                    timestamp_str = f" ({format_fuzzy_relative_time(mem.source_timestamp)})"
                tier_lines.append(f"    - [memory #{mem.id}] {mem.content}{timestamp_str}")

            return tier_lines

        tier_lines = format_tier_entries(closely, "Closely connected")
        if tier_lines:
            lines.extend(tier_lines)
            lines.append("")

        tier_lines = format_tier_entries(connected, "Connected")
        if tier_lines:
            lines.extend(tier_lines)
            lines.append("")

        tier_lines = format_tier_entries(loose, "Loosely associated")
        if tier_lines:
            lines.extend(tier_lines)
            lines.append("")

        # Note absence of a category if relevant
        has_factual = any(r.memory.memory_category == "factual" for r in explore_results)
        has_episodic = any(r.memory.memory_category == "episodic" for r in explore_results)

        if not has_factual:
            lines.append("  No strong connections found in factual memory.")
        if not has_episodic:
            lines.append("  No strong connections found in episodic memory.")

        return "\n".join(lines)
