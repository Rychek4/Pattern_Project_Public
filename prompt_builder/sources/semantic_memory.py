"""
Pattern Project - Semantic Memory Source
Retrieved memories via vector search with recency scoring

Dual-Track Retrieval:
    Memories are now extracted in two categories:
    - Episodic: Narrative memories about what happened ("We discussed X")
    - Factual: Concrete facts extracted from conversation ("Brian is 45")

    Retrieval queries both categories separately to ensure balanced results.
    The prompt formatting uses Option B: separated sections for clarity.

Warmth Cache System:
    The WarmthCache (memory/warmth_cache.py) provides session-scoped memory
    boosting for conversational continuity. See that module for details.
"""

from typing import Optional, Dict, Any, List, Set

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from memory.vector_store import get_vector_store, MemorySearchResult, Memory
from memory.warmth_cache import WarmthCache
from core.temporal import format_fuzzy_relative_time
from config import (
    MEMORY_MAX_PER_QUERY,
    MEMORY_MAX_EPISODIC_PER_QUERY,
    MEMORY_MAX_FACTUAL_PER_QUERY,
    MEMORY_RELEVANCE_FLOOR,
    MEMORY_DEDUP_ENABLED,
    MEMORY_DEDUP_THRESHOLD,
    MEMORY_OVERFETCH_MULTIPLIER,
    MEMORY_CHUNK_TOKEN_SIZE,
    MEMORY_CHUNK_MIN_THRESHOLD,
    MEMORY_CHUNK_OVERLAP_RATIO,
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
        # Track which image_ids have been injected in the current context window.
        # Images are only injected once — if the memory is recalled again while
        # the image is still visible in the conversation window, only the text
        # description is included. The set is cleared when memory extraction runs
        # (which is when old turns roll off the context window).
        self._injected_image_ids: Set[int] = set()

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
        1b. Chunk long inputs by token count for focused retrieval vectors
            - Short input (under threshold): embed as-is (single query)
            - Long input: split into ~45-token chunks, retrieve per chunk
        2. Over-fetch memories (2.4x limit) from both categories (no floor — applied later)
        3. Apply warmth boosts (multiplicative) and re-rank by adjusted scores
        4. Filter by min_score on ADJUSTED score (warmth can rescue borderline memories)
        5. Deduplicate (using adjusted scores to preserve warmth ranking)
        6. Take top N per category (scaled for multi-chunk)
        7. Update retrieval warmth for returned memories
        8. Expand topic warmth to associated memories
        """
        import config
        vector_store = get_vector_store()

        # Step 1: Decay warmth from previous turn
        self._warmth_cache.decay_all()

        # Calculate over-fetch limits (per-query, used for both paths)
        overfetch_episodic = int(self.max_episodic * MEMORY_OVERFETCH_MULTIPLIER)
        overfetch_factual = int(self.max_factual * MEMORY_OVERFETCH_MULTIPLIER)

        # Step 1b: Chunk long inputs by token count for focused retrieval vectors
        chunks = self._chunk_by_token_count(user_input)
        is_multi_chunk = len(chunks) > 1

        if is_multi_chunk:
            # Step 2 (multi-chunk): Retrieve per chunk, merge by memory ID.
            # Each chunk gets its own retrieval pass. When the same memory
            # appears across chunks, keep the version with the highest score.
            episodic_by_id: Dict[int, MemorySearchResult] = {}
            factual_by_id: Dict[int, MemorySearchResult] = {}

            for chunk in chunks:
                chunk_episodic = vector_store.search(
                    query=chunk,
                    limit=overfetch_episodic,
                    memory_category="episodic",
                    min_score=0.0
                )
                chunk_factual = vector_store.search(
                    query=chunk,
                    limit=overfetch_factual,
                    memory_category="factual",
                    min_score=0.0
                )

                for r in chunk_episodic:
                    existing = episodic_by_id.get(r.memory.id)
                    if existing is None or r.combined_score > existing.combined_score:
                        episodic_by_id[r.memory.id] = r

                for r in chunk_factual:
                    existing = factual_by_id.get(r.memory.id)
                    if existing is None or r.combined_score > existing.combined_score:
                        factual_by_id[r.memory.id] = r

            episodic_results = list(episodic_by_id.values())
            factual_results = list(factual_by_id.values())

            # Budget scales with chunk count: 5+5 per chunk
            effective_max_episodic = self.max_episodic * len(chunks)
            effective_max_factual = self.max_factual * len(chunks)
        else:
            # Step 2 (single-chunk): Input is short enough for one focused embedding.
            # Over-fetch from both categories with NO floor.
            # The relevance floor is applied AFTER warmth boosting (step 4) so
            # that warm memories with base scores slightly below floor survive.
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
            effective_max_episodic = self.max_episodic
            effective_max_factual = self.max_factual

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

        # Step 6: Take top N after warmth-based re-ranking (scaled for multi-chunk)
        episodic_final = episodic_with_warmth[:effective_max_episodic]
        factual_final = factual_with_warmth[:effective_max_factual]

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
            from interface.dev_events import emit_memory_recall
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
            "topic_warmed_count": topic_warmed_count,
            "topic_chunks": len(chunks)
        }

        # Load images for recalled visual memories (inject-once per context window)
        self._load_memory_images(all_results, session_context)

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

        When the same fact is extracted from multiple conversations (e.g., "Brian is 45"
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

    @staticmethod
    def _chunk_by_token_count(user_input: str) -> List[str]:
        """
        Split user input into overlapping token chunks for focused retrieval vectors.

        Long inputs produce unfocused embeddings (centroid blur). Splitting by
        token count keeps each retrieval vector semantically tight — the same
        principle that makes corpus-side chunking work in RAG, applied to the query.

        Token count is estimated via character heuristic (len / 4). Chunks overlap
        by MEMORY_CHUNK_OVERLAP_RATIO at each boundary so concepts that straddle a
        split appear fully in at least one chunk. Downstream merge-by-ID dedup
        collapses duplicate retrievals across overlapping chunks.

        Returns the original input as a single-item list if under threshold.
        """
        # Estimate token count via character heuristic
        estimated_tokens = len(user_input) / 4

        if estimated_tokens <= MEMORY_CHUNK_MIN_THRESHOLD:
            return [user_input]

        # Target character count per chunk (token target * 4)
        chars_per_chunk = MEMORY_CHUNK_TOKEN_SIZE * 4
        overlap_chars = int(chars_per_chunk * MEMORY_CHUNK_OVERLAP_RATIO)
        stride = chars_per_chunk - overlap_chars

        # Split into overlapping character windows
        chunks = []
        start = 0
        text_len = len(user_input)
        while start < text_len:
            chunk = user_input[start:start + chars_per_chunk].strip()
            if chunk:
                chunks.append(chunk)
            start += stride

        return chunks if len(chunks) > 1 else [user_input]

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

    def _load_memory_images(
        self,
        all_results: List[MemorySearchResult],
        session_context: Dict[str, Any]
    ) -> None:
        """Load images from recalled visual memories into session_context.

        Only loads images that haven't been injected yet in this context window.
        Subsequent recalls of the same memory will include the text description
        but skip re-injecting the image (it's still visible in conversation).

        The _injected_image_ids set is cleared when clear_injected_images() is
        called (triggered by memory extraction, i.e., when old turns roll off).

        Args:
            all_results: All recalled memory search results
            session_context: Shared context dict; images stored in "memory_images"
        """
        import config
        if not getattr(config, 'IMAGE_MEMORY_ENABLED', False):
            return

        from agency.commands.handlers.image_memory_handler import load_image_for_memory

        images = []
        for result in all_results:
            mem = result.memory
            if mem.image_id and mem.image_id not in self._injected_image_ids:
                img = load_image_for_memory(mem.image_id)
                if img:
                    images.append(img)
                    self._injected_image_ids.add(mem.image_id)

        if images:
            session_context["memory_images"] = images

    def clear_injected_images(self) -> None:
        """Clear the injected image tracking set.

        Call when memory extraction runs (old turns roll off the context window),
        so images can be re-injected if recalled again in the future.
        """
        self._injected_image_ids.clear()

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
