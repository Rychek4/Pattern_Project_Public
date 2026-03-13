"""
Pattern Project - Warmth Cache
Session-scoped memory boosting for conversational continuity.

The WarmthCache tracks two types of "warmth":

1. Retrieval Warmth: Memories retrieved in recent turns stay accessible
   even if the next query doesn't directly reference them.

2. Topic Warmth: Memories semantically related to retrieved memories are
   pre-warmed for predictive loading via same-session clustering.

Both decay each turn, creating a natural conversational memory window.
"""

from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass

from config import (
    WARMTH_RETRIEVAL_INITIAL,
    WARMTH_RETRIEVAL_DECAY,
    WARMTH_TOPIC_INITIAL,
    WARMTH_TOPIC_DECAY,
    WARMTH_CAP,
    WARMTH_TOPIC_SIMILARITY_THRESHOLD,
    WARMTH_TOPIC_MAX_EXPANSION
)
from core.embeddings import cosine_similarity_batch
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
        retrieved_memories,
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
        candidate_memories = []
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
