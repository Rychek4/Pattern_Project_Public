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
    MEMORY_RELEVANCE_FLOOR,
    MEMORY_DEDUP_ENABLED,
    MEMORY_DEDUP_THRESHOLD
)
from core.embeddings import cosine_similarity


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
        promotion_threshold: float = 0.85,
        dedup_enabled: bool = MEMORY_DEDUP_ENABLED,
        dedup_threshold: float = MEMORY_DEDUP_THRESHOLD
    ):
        """
        Initialize the semantic memory source.

        Args:
            max_episodic: Maximum episodic memories to include
            max_factual: Maximum factual memories to include
            min_score: Minimum combined score to include (relevance floor)
            promotion_threshold: Score threshold for core memory promotion
            dedup_enabled: Whether to deduplicate near-identical results
            dedup_threshold: Embedding similarity threshold for "duplicate" (0.85 = 85% similar)
        """
        self.max_episodic = max_episodic
        self.max_factual = max_factual
        self.min_score = min_score
        self.promotion_threshold = promotion_threshold
        self.dedup_enabled = dedup_enabled
        self.dedup_threshold = dedup_threshold
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

        # Deduplicate near-identical memories to prevent redundant context
        # This handles cases where the same fact was extracted from multiple conversations
        if self.dedup_enabled and all_results:
            original_count = len(all_results)
            all_results = self._deduplicate_results(all_results)
            # Also deduplicate the separate lists for proper formatting
            episodic_results = [r for r in all_results if r.memory.memory_category == "episodic"]
            factual_results = [r for r in all_results if r.memory.memory_category == "factual"]
            if len(all_results) < original_count:
                from core.logger import log_info
                log_info(
                    f"Deduplicated {original_count} → {len(all_results)} memories "
                    f"(threshold: {self.dedup_threshold})",
                    prefix="🔄"
                )

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

    def _deduplicate_results(
        self,
        results: List[MemorySearchResult]
    ) -> List[MemorySearchResult]:
        """
        Collapse near-identical memories to prevent redundant context.

        When the same fact is extracted from multiple conversations (e.g., "Brian is 45"
        mentioned in different sessions), this method collapses them to keep only the
        highest-scored version.

        Algorithm:
            1. Sort by combined_score (highest first)
            2. For each result, check embedding similarity against kept results
            3. If similar to existing (>= threshold), skip it (it's a duplicate)
            4. Otherwise, keep it

        Args:
            results: List of MemorySearchResult from search

        Returns:
            Deduplicated list with near-identical memories collapsed

        Performance: O(n²) but n is small (typically 10-15 results)
        """
        if not results:
            return results

        # Sort by score so we keep the best version of duplicates
        sorted_results = sorted(results, key=lambda r: r.combined_score, reverse=True)

        kept: List[MemorySearchResult] = []
        for result in sorted_results:
            is_duplicate = False
            for kept_result in kept:
                # Compare embeddings to detect semantic duplicates
                similarity = cosine_similarity(
                    result.memory.embedding,
                    kept_result.memory.embedding
                )
                if similarity >= self.dedup_threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                kept.append(result)

        return kept

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
