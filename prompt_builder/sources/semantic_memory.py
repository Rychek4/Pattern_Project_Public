"""
Pattern Project - Semantic Memory Source
Retrieved memories via vector search with recency scoring

Dual-Track Retrieval:
    Memories are now extracted in two categories:
    - Episodic: Narrative memories about what happened ("We discussed X")
    - Factual: Concrete facts extracted from conversation ("User is 45")

    Retrieval queries both categories separately to ensure balanced results.
    The prompt formatting uses Option B: separated sections for clarity.

Warmth Cache System:
    The WarmthCache provides session-scoped memory boosting for conversational
    continuity. It tracks two types of "warmth":

    1. Retrieval Warmth: Memories retrieved in recent turns stay accessible
       even if the next query doesn't directly reference them.

    2. Topic Warmth: Memories semantically related to retrieved memories are
       pre-warmed for predictive loading via same-session clustering.

    Both decay each turn, creating a natural conversational memory window.
"""

from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from memory.vector_store import get_vector_store, MemorySearchResult, Memory
from core.temporal import format_fuzzy_relative_time
from config import (
    MEMORY_MAX_PER_QUERY,
    MEMORY_MAX_EPISODIC_PER_QUERY,
    MEMORY_MAX_FACTUAL_PER_QUERY,
    MEMORY_RELEVANCE_FLOOR,
    MEMORY_DEDUP_ENABLED,
    MEMORY_DEDUP_THRESHOLD,
    MEMORY_OVERFETCH_MULTIPLIER,
    WARMTH_RETRIEVAL_INITIAL,
    WARMTH_RETRIEVAL_DECAY,
    WARMTH_TOPIC_INITIAL,
    WARMTH_TOPIC_DECAY,
    WARMTH_CAP,
    WARMTH_TOPIC_SIMILARITY_THRESHOLD,
    WARMTH_TOPIC_MAX_EXPANSION
)
from core.embeddings import cosine_similarity, cosine_similarity_batch
import numpy as np


@dataclass
class WarmthEntry:
    """A single entry in the warmth cache."""
    retrieval_warmth: float = 0.0
    topic_warmth: float = 0.0

    @property
    def combined(self) -> float:
        """Get combined warmth, capped at WARMTH_CAP."""
        return min(WARMTH_CAP, self.retrieval_warmth + self.topic_warmth)


class WarmthCache:
    """
    Session-scoped cache for memory warmth scoring.

    Tracks two types of warmth:
    - Retrieval Warmth: Memories directly retrieved in recent turns
    - Topic Warmth: Memories associated with retrieved memories

    Both decay each turn, creating a natural conversational memory window.
    """

    def __init__(self):
        """Initialize an empty warmth cache."""
        self._cache: Dict[int, WarmthEntry] = {}
        self._last_retrieved_ids: Set[int] = set()

    def decay_all(self) -> None:
        """
        Decay all warmth scores. Called at the start of each retrieval.

        Retrieval warmth decays by WARMTH_RETRIEVAL_DECAY (0.6).
        Topic warmth decays by WARMTH_TOPIC_DECAY (0.5).

        Entries with negligible warmth (<0.01) are removed.
        """
        to_remove = []

        for memory_id, entry in self._cache.items():
            entry.retrieval_warmth *= WARMTH_RETRIEVAL_DECAY
            entry.topic_warmth *= WARMTH_TOPIC_DECAY

            # Remove negligible entries to prevent unbounded growth
            if entry.combined < 0.01:
                to_remove.append(memory_id)

        for memory_id in to_remove:
            del self._cache[memory_id]

    def get_warmth(self, memory_id: int) -> float:
        """Get combined warmth for a memory (0.0 if not cached)."""
        entry = self._cache.get(memory_id)
        return entry.combined if entry else 0.0

    def get_entry(self, memory_id: int) -> Optional[WarmthEntry]:
        """Get the warmth entry for a memory (None if not cached)."""
        return self._cache.get(memory_id)

    def set_retrieval_warmth(self, memory_ids: List[int]) -> None:
        """
        Set retrieval warmth for memories that were just retrieved.

        Args:
            memory_ids: IDs of memories that were retrieved and injected
        """
        self._last_retrieved_ids = set(memory_ids)

        for memory_id in memory_ids:
            if memory_id not in self._cache:
                self._cache[memory_id] = WarmthEntry()
            # Set (not add) to WARMTH_RETRIEVAL_INITIAL - no stacking
            self._cache[memory_id].retrieval_warmth = WARMTH_RETRIEVAL_INITIAL

    def expand_topic_warmth(
        self,
        retrieved_memories: List[Memory],
        vector_store
    ) -> int:
        """
        Expand topic warmth to memories associated with retrieved ones.

        Association rules:
        1. Same source_session_id as a retrieved memory
        2. Embedding similarity > WARMTH_TOPIC_SIMILARITY_THRESHOLD

        Args:
            retrieved_memories: Memories that were just retrieved
            vector_store: VectorStore instance for loading related memories

        Returns:
            Number of memories that were topic-warmed
        """
        if not retrieved_memories:
            return 0

        # Collect session IDs from retrieved memories
        session_ids = set()
        retrieved_ids = set()
        for mem in retrieved_memories:
            retrieved_ids.add(mem.id)
            if mem.source_session_id:
                session_ids.add(mem.source_session_id)

        if not session_ids:
            return 0

        # Load all memories from those sessions
        candidate_memories: List[Memory] = []
        for session_id in session_ids:
            session_memories = vector_store.get_memories_by_session(session_id)
            for mem in session_memories:
                # Skip already-retrieved memories
                if mem.id not in retrieved_ids:
                    candidate_memories.append(mem)

        if not candidate_memories:
            return 0

        # Build embedding matrices for batch similarity computation
        retrieved_embeddings = np.array([m.embedding for m in retrieved_memories])
        candidate_embeddings = np.array([m.embedding for m in candidate_memories])

        # For each candidate, find max similarity to any retrieved memory
        warmed_count = 0
        for i, candidate in enumerate(candidate_memories):
            if warmed_count >= WARMTH_TOPIC_MAX_EXPANSION:
                break

            # Compute similarity to all retrieved memories
            similarities = cosine_similarity_batch(
                candidate_embeddings[i],
                retrieved_embeddings
            )
            max_similarity = float(np.max(similarities))

            # If similar enough, add topic warmth
            if max_similarity >= WARMTH_TOPIC_SIMILARITY_THRESHOLD:
                if candidate.id not in self._cache:
                    self._cache[candidate.id] = WarmthEntry()
                # Set (not add) to WARMTH_TOPIC_INITIAL
                self._cache[candidate.id].topic_warmth = WARMTH_TOPIC_INITIAL
                warmed_count += 1

        return warmed_count

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the warmth cache for debugging."""
        if not self._cache:
            return {
                "total_entries": 0,
                "retrieval_warm": 0,
                "topic_warm": 0,
                "avg_combined": 0.0
            }

        retrieval_warm = sum(1 for e in self._cache.values() if e.retrieval_warmth > 0.01)
        topic_warm = sum(1 for e in self._cache.values() if e.topic_warmth > 0.01)
        avg_combined = sum(e.combined for e in self._cache.values()) / len(self._cache)

        return {
            "total_entries": len(self._cache),
            "retrieval_warm": retrieval_warm,
            "topic_warm": topic_warm,
            "avg_combined": round(avg_combined, 3)
        }

    def clear(self) -> None:
        """Clear all warmth data (e.g., on session end)."""
        self._cache.clear()
        self._last_retrieved_ids.clear()


class SemanticMemorySource(ContextSource):
    """
    Provides semantically relevant memories for prompt context.

    Uses dual-track retrieval to ensure balanced episodic and factual memories:
    - Episodic: Narrative memories capturing relationship texture and experiences
    - Factual: Concrete facts about people, preferences, and world knowledge

    Both categories are queried separately with their own limits, then combined
    using Option B formatting (separated sections) for prompt clarity.

    The WarmthCache system provides session-scoped boosting for conversational
    continuity, keeping recently-discussed topics accessible and pre-warming
    related memories for predictive loading.
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
        # Warmth cache for session-scoped memory boosting
        self._warmth_cache = WarmthCache()

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
        Search for relevant memories using dual-track retrieval with warmth boosting.

        Pipeline:
        1. Decay all warmth scores (per-turn decay)
        2. Over-fetch memories (2.4x limit) from both categories (no floor — applied later)
        3. Apply warmth boosts (multiplicative) and re-rank by adjusted scores
        4. Filter by min_score on ADJUSTED score (warmth can rescue borderline memories)
        5. Deduplicate (using adjusted scores to preserve warmth ranking)
        6. Take top N per category
        7. Update retrieval warmth for returned memories
        8. Expand topic warmth to associated memories
        """
        import config
        vector_store = get_vector_store()

        # Step 1: Decay warmth from previous turn
        self._warmth_cache.decay_all()

        # Calculate over-fetch limits
        overfetch_episodic = int(self.max_episodic * MEMORY_OVERFETCH_MULTIPLIER)
        overfetch_factual = int(self.max_factual * MEMORY_OVERFETCH_MULTIPLIER)

        # Step 2: Over-fetch from both categories with NO floor.
        # The relevance floor is applied AFTER warmth boosting (step 4) so that
        # warm memories with base scores slightly below the floor can survive.
        episodic_results = vector_store.search(
            query=user_input,
            limit=overfetch_episodic,
            memory_category="episodic",
            min_score=0.0
        )

        factual_results = vector_store.search(
            query=user_input,
            limit=overfetch_factual,
            memory_category="factual",
            min_score=0.0
        )

        # Step 3: Apply multiplicative warmth boosts and re-rank
        # Returns 4-tuples: (result, warmth, entry, adjusted_score)
        episodic_with_warmth = self._apply_warmth_and_rerank(episodic_results)
        factual_with_warmth = self._apply_warmth_and_rerank(factual_results)

        # Step 4: Filter by min_score on ADJUSTED score (post-warmth)
        episodic_with_warmth = [
            t for t in episodic_with_warmth if t[3] >= self.min_score
        ]
        factual_with_warmth = [
            t for t in factual_with_warmth if t[3] >= self.min_score
        ]

        # Step 5: Deduplicate using adjusted scores to preserve warmth ranking
        if self.dedup_enabled:
            episodic_with_warmth = self._deduplicate_results(episodic_with_warmth)
            factual_with_warmth = self._deduplicate_results(factual_with_warmth)

        # Step 6: Take top N after warmth-based re-ranking
        episodic_final = episodic_with_warmth[:self.max_episodic]
        factual_final = factual_with_warmth[:self.max_factual]

        # Extract just the results for formatting
        episodic_results = [r for r, _, _, _ in episodic_final]
        factual_results = [r for r, _, _, _ in factual_final]
        all_results = episodic_results + factual_results

        # Step 7: Update retrieval warmth for returned memories
        returned_ids = [r.memory.id for r in all_results]
        self._warmth_cache.set_retrieval_warmth(returned_ids)

        # Step 8: Expand topic warmth to associated memories
        returned_memories = [r.memory for r in all_results]
        topic_warmed_count = self._warmth_cache.expand_topic_warmth(
            returned_memories,
            vector_store
        )

        # Emit memory recall to dev window with warmth info
        if config.DEV_MODE_ENABLED and all_results:
            from interface.dev_window import emit_memory_recall
            warmth_stats = self._warmth_cache.get_stats()
            recall_data = []
            for r in all_results:
                entry = self._warmth_cache.get_entry(r.memory.id)
                warmth = self._warmth_cache.get_warmth(r.memory.id)
                recall_data.append({
                    "content": r.memory.content,
                    "score": r.combined_score,
                    "semantic_score": r.semantic_score,
                    "importance_score": r.importance_score,
                    "freshness_score": r.freshness_score,
                    "memory_type": r.memory.memory_type,
                    "memory_category": r.memory.memory_category,
                    "importance": r.memory.importance,
                    # Warmth info
                    "warmth_boost": warmth,
                    "retrieval_warmth": entry.retrieval_warmth if entry else 0.0,
                    "topic_warmth": entry.topic_warmth if entry else 0.0,
                    "adjusted_score": r.combined_score * (1 + warmth)
                })
            # Add warmth stats to the first entry for display
            if recall_data:
                recall_data[0]["_warmth_stats"] = warmth_stats
                recall_data[0]["_topic_warmed_count"] = topic_warmed_count
            emit_memory_recall(user_input, recall_data)

        if not all_results:
            return None

        # Format memories for injection into user message (not system prompt)
        # This places relevant memories closer to the user's question
        lines = ["<relevant_memories>"]
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

        lines.append("</relevant_memories>")

        # Store promotion candidates in session context for later processing
        if promotion_candidates:
            session_context["promotion_candidates"] = promotion_candidates

        # Store formatted memories in session_context for injection into user message
        # This is NOT added to system prompt - it will be prefixed to the user message
        # at the entry point (CLI, HTTP API, etc.) to keep memories close to the question
        formatted_memories = "\n".join(lines)
        session_context["relevant_memories"] = formatted_memories
        session_context["relevant_memories_metadata"] = {
            "memory_count": len(all_results),
            "episodic_count": len(episodic_results),
            "factual_count": len(factual_results),
            "promotion_candidates": len(promotion_candidates),
            "top_score": max((r.combined_score for r in all_results), default=0),
            "warmth_cache_size": self._warmth_cache.get_stats()["total_entries"],
            "topic_warmed_count": topic_warmed_count
        }

        # Return None - memories are injected into user message, not system prompt
        return None

    def _apply_warmth_and_rerank(
        self,
        results: List[MemorySearchResult]
    ) -> List[tuple]:
        """
        Apply multiplicative warmth boosts to results and re-rank by adjusted score.

        Warmth is applied as a multiplicative factor: adjusted = base * (1 + warmth).
        This ensures that low-relevance warm memories cannot leap past high-relevance
        cold memories. A warmth of 0.25 gives a 25% boost proportional to base score.

        Args:
            results: Original search results from vector store

        Returns:
            List of (result, warmth_boost, warmth_entry, adjusted_score) tuples
            sorted by adjusted score (descending)
        """
        results_with_warmth = []
        for result in results:
            warmth = self._warmth_cache.get_warmth(result.memory.id)
            entry = self._warmth_cache.get_entry(result.memory.id)
            # Multiplicative boost: proportional to base relevance
            adjusted_score = result.combined_score * (1 + warmth)
            results_with_warmth.append((result, warmth, entry, adjusted_score))

        # Sort by adjusted score (descending)
        results_with_warmth.sort(key=lambda x: x[3], reverse=True)

        return results_with_warmth

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
        results_with_warmth: List[tuple]
    ) -> List[tuple]:
        """
        Collapse near-identical memories to prevent redundant context.

        When the same fact is extracted from multiple conversations (e.g., "User is 45"
        mentioned in different sessions), this method collapses them to keep only the
        highest-scored version.

        Algorithm:
            1. Sort by adjusted_score (highest first) — preserves warmth ranking
            2. For each result, check embedding similarity against kept results
            3. If similar to existing (>= threshold), skip it (it's a duplicate)
            4. Otherwise, keep it

        Args:
            results_with_warmth: List of (result, warmth, entry, adjusted_score) tuples

        Returns:
            Deduplicated list of tuples with near-identical memories collapsed

        Performance: O(n²) but n is small (typically 10-15 results)
        """
        if not results_with_warmth:
            return results_with_warmth

        # Sort by adjusted_score so we keep the best version of duplicates
        # (already sorted from _apply_warmth_and_rerank, but re-sort for safety)
        sorted_results = sorted(results_with_warmth, key=lambda t: t[3], reverse=True)

        kept: List[tuple] = []
        for item in sorted_results:
            result = item[0]
            is_duplicate = False
            for kept_item in kept:
                kept_result = kept_item[0]
                # Compare embeddings to detect semantic duplicates
                similarity = cosine_similarity(
                    result.memory.embedding,
                    kept_result.memory.embedding
                )
                if similarity >= self.dedup_threshold:
                    is_duplicate = True
                    break

            if not is_duplicate:
                kept.append(item)

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

    def get_warmth_stats(self) -> Dict[str, Any]:
        """Get current warmth cache statistics for debugging."""
        return self._warmth_cache.get_stats()

    def clear_warmth_cache(self) -> None:
        """Clear the warmth cache (e.g., on session end)."""
        self._warmth_cache.clear()


# Global instance
_semantic_memory_source: Optional[SemanticMemorySource] = None


def get_semantic_memory_source() -> SemanticMemorySource:
    """Get the global semantic memory source instance."""
    global _semantic_memory_source
    if _semantic_memory_source is None:
        _semantic_memory_source = SemanticMemorySource()
    return _semantic_memory_source
