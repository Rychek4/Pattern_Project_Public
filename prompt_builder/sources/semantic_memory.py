"""
Pattern Project - Semantic Memory Source
Retrieved memories via vector search with recency scoring
"""

from typing import Optional, Dict, Any, List

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from memory.vector_store import get_vector_store, MemorySearchResult
from core.temporal import format_fuzzy_relative_time
from config import MEMORY_MAX_PER_QUERY


class SemanticMemorySource(ContextSource):
    """
    Provides semantically relevant memories for prompt context.

    Memories are retrieved via:
    - Semantic similarity to user input
    - Recency scoring (freshness decay)
    - Access frequency scoring

    High-scoring memories may be candidates for core memory promotion.
    """

    def __init__(
        self,
        max_memories: int = MEMORY_MAX_PER_QUERY,
        min_score: float = 0.3,
        promotion_threshold: float = 0.85
    ):
        """
        Initialize the semantic memory source.

        Args:
            max_memories: Maximum memories to include
            min_score: Minimum combined score to include
            promotion_threshold: Score threshold for core memory promotion
        """
        self.max_memories = max_memories
        self.min_score = min_score
        self.promotion_threshold = promotion_threshold

    @property
    def source_name(self) -> str:
        return "semantic_memory"

    @property
    def priority(self) -> int:
        return SourcePriority.SEMANTIC_MEMORY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Search for relevant memories based on user input."""
        vector_store = get_vector_store()

        # Search for relevant memories
        results = vector_store.search(
            query=user_input,
            limit=self.max_memories,
            min_score=self.min_score
        )

        if not results:
            return None

        # Format memories as clean prose for prompt
        lines = [
            "<recalled_context>",
            "The following are relevant memories from past conversations:",
            ""
        ]

        promotion_candidates = []

        for result in results:
            mem = result.memory
            score = result.combined_score

            # Format with temporal context if timestamp available
            if mem.source_timestamp:
                timestamp = format_fuzzy_relative_time(mem.source_timestamp)
                lines.append(f"- {mem.content} ({timestamp})")
            else:
                lines.append(f"- {mem.content}")

            # Track high-scoring memories for potential promotion
            if score >= self.promotion_threshold:
                promotion_candidates.append(result)

        lines.append("")
        lines.append("</recalled_context>")

        # Store promotion candidates in session context for later processing
        if promotion_candidates:
            session_context["promotion_candidates"] = promotion_candidates

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=False,
            metadata={
                "memory_count": len(results),
                "promotion_candidates": len(promotion_candidates),
                "top_score": results[0].combined_score if results else 0
            }
        )

    def search(
        self,
        query: str,
        limit: Optional[int] = None,
        memory_type: Optional[str] = None
    ) -> List[MemorySearchResult]:
        """
        Direct search interface for memories.

        Args:
            query: Search query
            limit: Max results (uses default if None)
            memory_type: Filter by type

        Returns:
            List of MemorySearchResult
        """
        vector_store = get_vector_store()
        return vector_store.search(
            query=query,
            limit=limit or self.max_memories,
            memory_type=memory_type,
            min_score=self.min_score
        )

    def _get_type_indicator(self, memory_type: Optional[str]) -> str:
        """Get emoji indicator for memory type."""
        indicators = {
            "fact": "📌",
            "preference": "💜",
            "event": "📅",
            "reflection": "💭",
            "observation": "👁️"
        }
        return indicators.get(memory_type, "•")

    def _get_importance_indicator(self, importance: float) -> str:
        """Get importance level indicator."""
        if importance >= 0.8:
            return "high"
        elif importance >= 0.5:
            return "medium"
        else:
            return "low"


# Global instance
_semantic_memory_source: Optional[SemanticMemorySource] = None


def get_semantic_memory_source() -> SemanticMemorySource:
    """Get the global semantic memory source instance."""
    global _semantic_memory_source
    if _semantic_memory_source is None:
        _semantic_memory_source = SemanticMemorySource()
    return _semantic_memory_source
