"""
Pattern Project - Semantic Memory Source
Retrieved memories via vector search with recency scoring

Dual-Track Retrieval:
    Memories are now extracted in two categories:
    - Episodic: Narrative memories about what happened ("We discussed X")
    - Factual: Concrete facts extracted from conversation ("Brian is 45")

    Retrieval queries both categories separately to ensure balanced results.
    The prompt formatting uses Option B: separated sections for clarity.
"""

from typing import Optional, Dict, Any, List

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from memory.vector_store import get_vector_store, MemorySearchResult
from core.temporal import format_fuzzy_relative_time
from config import (
    MEMORY_MAX_PER_QUERY,
    MEMORY_MAX_EPISODIC_PER_QUERY,
    MEMORY_MAX_FACTUAL_PER_QUERY,
    MEMORY_RELEVANCE_FLOOR
)


class SemanticMemorySource(ContextSource):
    """
    Provides semantically relevant memories for prompt context.

    Uses dual-track retrieval to ensure balanced episodic and factual memories:
    - Episodic: Narrative memories capturing relationship texture and experiences
    - Factual: Concrete facts about people, preferences, and world knowledge

    Both categories are queried separately with their own limits, then combined
    using Option B formatting (separated sections) for prompt clarity.
    """

    def __init__(
        self,
        max_episodic: int = MEMORY_MAX_EPISODIC_PER_QUERY,
        max_factual: int = MEMORY_MAX_FACTUAL_PER_QUERY,
        min_score: float = MEMORY_RELEVANCE_FLOOR,
        promotion_threshold: float = 0.85
    ):
        """
        Initialize the semantic memory source.

        Args:
            max_episodic: Maximum episodic memories to include
            max_factual: Maximum factual memories to include
            min_score: Minimum combined score to include (relevance floor)
            promotion_threshold: Score threshold for core memory promotion
        """
        self.max_episodic = max_episodic
        self.max_factual = max_factual
        self.min_score = min_score
        self.promotion_threshold = promotion_threshold
        # Legacy compatibility
        self.max_memories = MEMORY_MAX_PER_QUERY

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
        """
        Search for relevant memories using dual-track retrieval.

        Queries both episodic and factual categories separately to ensure
        balanced representation, then formats using Option B (separated sections).
        """
        import config
        vector_store = get_vector_store()

        # Dual-track retrieval: query each category separately
        episodic_results = vector_store.search(
            query=user_input,
            limit=self.max_episodic,
            memory_category="episodic",
            min_score=self.min_score
        )

        factual_results = vector_store.search(
            query=user_input,
            limit=self.max_factual,
            memory_category="factual",
            min_score=self.min_score
        )

        all_results = episodic_results + factual_results

        # Emit memory recall to dev window
        if config.DEV_MODE_ENABLED and all_results:
            from interface.dev_window import emit_memory_recall
            recall_data = [
                {
                    "content": r.memory.content,
                    "score": r.combined_score,
                    "semantic_score": r.semantic_score,
                    "importance_score": r.importance_score,
                    "freshness_score": r.freshness_score,
                    "memory_type": r.memory.memory_type,
                    "memory_category": r.memory.memory_category,
                    "importance": r.memory.importance
                }
                for r in all_results
            ]
            emit_memory_recall(user_input, recall_data)

        if not all_results:
            return None

        # Format using Option B: separated sections for clarity
        lines = ["<recalled_context>"]
        promotion_candidates = []

        # Section 1: Factual memories ("What I know")
        if factual_results:
            lines.append("What I know:")
            for result in factual_results:
                mem = result.memory
                lines.append(f"- {mem.content}")
                if result.combined_score >= self.promotion_threshold:
                    promotion_candidates.append(result)
            lines.append("")

        # Section 2: Episodic memories ("Recent experiences")
        if episodic_results:
            lines.append("Recent experiences:")
            for result in episodic_results:
                mem = result.memory
                # Include temporal context for episodic memories
                if mem.source_timestamp:
                    timestamp = format_fuzzy_relative_time(mem.source_timestamp)
                    lines.append(f"- {mem.content} ({timestamp})")
                else:
                    lines.append(f"- {mem.content}")
                if result.combined_score >= self.promotion_threshold:
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
                "memory_count": len(all_results),
                "episodic_count": len(episodic_results),
                "factual_count": len(factual_results),
                "promotion_candidates": len(promotion_candidates),
                "top_score": max((r.combined_score for r in all_results), default=0)
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
