"""
Pattern Project - Vector Store
Semantic search over memories using embeddings
"""

import json
import math
from datetime import datetime
from typing import Optional, List, Tuple
from dataclasses import dataclass

import numpy as np

from core.database import get_database
from core.embeddings import (
    get_embedding,
    get_embeddings_batch,
    cosine_similarity_batch,
    embedding_to_bytes,
    bytes_to_embedding,
    is_model_loaded
)
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry
from core.logger import log_info, log_error


@dataclass
class Memory:
    """
    A stored memory with metadata.

    Attributes:
        id: Database primary key
        content: The memory text content
        embedding: Vector embedding for semantic search
        source_conversation_ids: IDs of conversation turns this was extracted from
        source_session_id: Session during which this memory was created
        created_at: When the memory was stored in the database
        last_accessed_at: When this memory was last retrieved in a search
        access_count: Number of times this memory has been retrieved
        source_timestamp: When the original conversation occurred
        decay_category: Controls freshness decay rate:
            - 'permanent': Never decays (identity facts, lasting preferences)
            - 'standard': 30-day half-life (events, discussions)
            - 'ephemeral': 7-day half-life (situational observations)
        importance: Significance score from 0.0 to 1.0
        memory_type: Category ('fact', 'preference', 'event', 'reflection', 'observation')
        memory_category: Extraction method category:
            - 'episodic': Narrative memories about what happened
            - 'factual': Concrete facts extracted from conversations
    """
    id: int
    content: str
    embedding: np.ndarray
    source_conversation_ids: List[int]
    source_session_id: Optional[int]
    created_at: datetime
    last_accessed_at: Optional[datetime]
    access_count: int
    source_timestamp: Optional[datetime]
    decay_category: str  # 'permanent', 'standard', or 'ephemeral'
    importance: float
    memory_type: Optional[str]
    memory_category: str = "episodic"  # 'episodic' or 'factual'


@dataclass
class MemorySearchResult:
    """A memory with its relevance score."""
    memory: Memory
    semantic_score: float
    importance_score: float
    freshness_score: float
    combined_score: float


class VectorStore:
    """
    Vector store for semantic memory search.

    Stores memories with embeddings and provides
    similarity search with temporal scoring.
    """

    def __init__(
        self,
        embedding_dimensions: int = 384,
        semantic_weight: float = 0.60,
        importance_weight: float = 0.25,
        freshness_weight: float = 0.15
    ):
        """
        Initialize the vector store.

        Args:
            embedding_dimensions: Dimension of embedding vectors
            semantic_weight: Weight for semantic similarity (primary signal)
            importance_weight: Weight for memory importance score
            freshness_weight: Weight for freshness score (age penalty)
        """
        self.embedding_dimensions = embedding_dimensions
        self.semantic_weight = semantic_weight
        self.importance_weight = importance_weight
        self.freshness_weight = freshness_weight
        self._lock_manager = get_lock_manager()

    @db_retry()
    def add_memory(
        self,
        content: str,
        source_conversation_ids: List[int],
        source_session_id: Optional[int] = None,
        source_timestamp: Optional[datetime] = None,
        importance: float = 0.5,
        memory_type: Optional[str] = None,
        decay_category: str = "standard",
        memory_category: str = "episodic"
    ) -> Optional[int]:
        """
        Add a new memory to the store.

        For factual memories, performs creation-time deduplication: if a
        semantically similar fact already exists (>= MEMORY_DEDUP_THRESHOLD),
        the existing memory's timestamp and importance are refreshed instead
        of creating a duplicate. This prevents unbounded growth of duplicate
        facts across conversations.

        Args:
            content: The memory content text
            source_conversation_ids: IDs of conversation turns this came from
            source_session_id: Session ID where memory was extracted
            source_timestamp: When the original conversation occurred
            importance: Significance score (0.0-1.0)
            memory_type: Category ('fact', 'preference', 'event', etc.)
            decay_category: Controls freshness decay rate:
                - 'permanent': Never decays (core identity, lasting preferences)
                - 'standard': 30-day half-life (events, discussions)
                - 'ephemeral': 7-day half-life (situational observations)
            memory_category: Extraction method category:
                - 'episodic': Narrative memories about what happened (default)
                - 'factual': Concrete facts extracted from conversations

        Returns:
            The memory ID (new or refreshed existing), or None if embedding failed
        """
        if not is_model_loaded():
            log_error("Cannot add memory: embedding model not loaded")
            return None

        # Generate embedding (outside lock — CPU-intensive)
        embedding = get_embedding(content)
        if embedding is None:
            log_error("Failed to generate embedding for memory")
            return None

        with self._lock_manager.acquire("memory"):
            db = get_database()
            now = datetime.now()

            if source_timestamp is None:
                source_timestamp = now

            # Creation-time dedup for factual memories:
            # If a very similar fact already exists, refresh it instead of creating a duplicate.
            if memory_category == "factual":
                existing_id = self._find_duplicate_factual(db, embedding)
                if existing_id is not None:
                    # Refresh existing memory: update timestamp and bump importance if higher
                    db.execute(
                        """
                        UPDATE memories
                        SET source_timestamp = ?,
                            importance = MAX(importance, ?),
                            decay_category = CASE WHEN ? > importance THEN ? ELSE decay_category END
                        WHERE id = ?
                        """,
                        (
                            source_timestamp.isoformat(),
                            importance,
                            importance, decay_category,
                            existing_id
                        )
                    )
                    log_info(
                        f"Refreshed existing factual memory #{existing_id} "
                        f"instead of creating duplicate: '{content[:50]}...'",
                        prefix="♻️"
                    )
                    return existing_id

            db.execute(
                """
                INSERT INTO memories
                (content, embedding, source_conversation_ids, source_session_id,
                 source_timestamp, importance, memory_type, decay_category,
                 memory_category, created_at, last_accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content,
                    embedding_to_bytes(embedding),
                    json.dumps(source_conversation_ids),
                    source_session_id,
                    source_timestamp.isoformat(),
                    importance,
                    memory_type,
                    decay_category,
                    memory_category,
                    now.isoformat(),
                    now.isoformat(),
                    0
                )
            )

            result = db.execute(
                "SELECT id FROM memories ORDER BY id DESC LIMIT 1",
                fetch=True
            )

            return result[0]["id"] if result else None

    def _find_duplicate_factual(
        self,
        db,
        new_embedding: np.ndarray,
        threshold: float = 0.85
    ) -> Optional[int]:
        """
        Check if a semantically similar factual memory already exists.

        Args:
            db: Database connection (caller holds the lock)
            new_embedding: Embedding of the new memory to check
            threshold: Cosine similarity threshold for "duplicate" (default 0.85)

        Returns:
            ID of the existing duplicate memory, or None if no match found
        """
        from config import MEMORY_DEDUP_THRESHOLD
        threshold = MEMORY_DEDUP_THRESHOLD

        rows = db.execute(
            "SELECT id, embedding FROM memories WHERE memory_category = 'factual'",
            fetch=True
        )

        if not rows:
            return None

        # Batch compute similarities against all existing factual embeddings
        existing_ids = [row["id"] for row in rows]
        existing_embeddings = np.array([
            bytes_to_embedding(row["embedding"], self.embedding_dimensions)
            for row in rows
        ])

        similarities = cosine_similarity_batch(new_embedding, existing_embeddings)
        max_idx = int(np.argmax(similarities))
        max_similarity = float(similarities[max_idx])

        if max_similarity >= threshold:
            return existing_ids[max_idx]

        return None

    @db_retry()
    def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[str] = None,
        memory_category: Optional[str] = None,
        min_score: float = 0.0
    ) -> List[MemorySearchResult]:
        """
        Search for relevant memories.

        Args:
            query: The search query
            limit: Maximum results to return
            memory_type: Filter by memory type ('fact', 'preference', etc.)
            memory_category: Filter by extraction category ('episodic' or 'factual')
            min_score: Minimum combined score threshold

        Returns:
            List of MemorySearchResult, sorted by combined score
        """
        if not is_model_loaded():
            log_error("Cannot search: embedding model not loaded")
            return []

        # Generate query embedding
        query_embedding = get_embedding(query)
        if query_embedding is None:
            return []

        with self._lock_manager.acquire("memory"):
            db = get_database()
            now = datetime.now()

            # Build query with optional filters
            sql = "SELECT * FROM memories"
            conditions = []
            params = []

            if memory_type:
                conditions.append("memory_type = ?")
                params.append(memory_type)

            if memory_category:
                conditions.append("memory_category = ?")
                params.append(memory_category)

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            result = db.execute(sql, tuple(params), fetch=True)

            if not result:
                return []

            # Load all memories and embeddings
            memories = []
            embeddings = []

            for row in result:
                memory = self._row_to_memory(row)
                memories.append(memory)
                embeddings.append(memory.embedding)

            # Batch compute semantic similarities
            embeddings_matrix = np.array(embeddings)
            semantic_scores = cosine_similarity_batch(query_embedding, embeddings_matrix)

            # Compute combined scores
            results = []
            for i, memory in enumerate(memories):
                semantic_score = float(semantic_scores[i])

                # Importance score (already normalized 0.0-1.0)
                importance_score = memory.importance

                # Freshness score (exponential decay based on age and decay_category)
                freshness_score = self._compute_freshness(memory, now)

                # Combined score: weighted sum of semantic + importance + freshness
                combined_score = (
                    self.semantic_weight * semantic_score +
                    self.importance_weight * importance_score +
                    self.freshness_weight * freshness_score
                )

                if combined_score >= min_score:
                    results.append(MemorySearchResult(
                        memory=memory,
                        semantic_score=semantic_score,
                        importance_score=importance_score,
                        freshness_score=freshness_score,
                        combined_score=combined_score
                    ))

            # Sort by combined score
            results.sort(key=lambda x: x.combined_score, reverse=True)

            return results[:limit]

    def _compute_freshness(self, memory: Memory, now: datetime) -> float:
        """
        Compute freshness score based on source timestamp and decay category.

        Uses exponential decay with category-specific half-lives:
          - permanent: No decay (always returns 1.0)
          - standard: 30-day half-life (normal memories)
          - ephemeral: 7-day half-life (fast-fading observations)

        The half-life is the number of days until the score drops to 0.5.
        Formula: score = exp(-ln(2) * age_days / half_life) = 2^(-age/half_life)

        Args:
            memory: The memory to compute freshness for
            now: Current datetime for age calculation

        Returns:
            Freshness score from 0.0 to 1.0
        """
        # Import decay half-lives from config
        from config import DECAY_HALF_LIFE_STANDARD, DECAY_HALF_LIFE_EPHEMERAL

        # Permanent memories never decay - always fully fresh
        if memory.decay_category == "permanent":
            return 1.0

        # No timestamp means we can't compute age - use neutral score
        if not memory.source_timestamp:
            return 0.5

        # Calculate age in days (guard against negative age from clock skew/timezone issues)
        age_days = max(0, (now - memory.source_timestamp).days)

        # Select half-life based on decay category
        # Using a dict lookup with fallback to standard for any unexpected values
        half_life_days = {
            "standard": DECAY_HALF_LIFE_STANDARD,
            "ephemeral": DECAY_HALF_LIFE_EPHEMERAL,
            # Legacy values from old schema (pre-migration)
            "recent": DECAY_HALF_LIFE_STANDARD,
            "dated": DECAY_HALF_LIFE_EPHEMERAL,
        }.get(memory.decay_category, DECAY_HALF_LIFE_STANDARD)

        # Exponential decay: ln(2) ≈ 0.693 gives proper half-life behavior
        # At age = half_life_days, score = 0.5
        # At age = 2 * half_life_days, score = 0.25
        # Clamp to 1.0 as a safety measure (should already be <= 1.0 with non-negative age)
        return min(1.0, math.exp(-0.693 * age_days / half_life_days))

    @db_retry()
    def get_memory(self, memory_id: int) -> Optional[Memory]:
        """Get a specific memory by ID."""
        with self._lock_manager.acquire("memory"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
                fetch=True
            )

            if result:
                return self._row_to_memory(result[0])
            return None

    @db_retry()
    def get_memory_count(self) -> int:
        """Get total number of memories."""
        db = get_database()
        result = db.execute(
            "SELECT COUNT(*) as count FROM memories",
            fetch=True
        )
        return result[0]["count"] if result else 0

    @db_retry()
    def get_memories_by_session(self, session_id: int) -> List[Memory]:
        """Get all memories from a specific session."""
        with self._lock_manager.acquire("memory"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM memories WHERE source_session_id = ? ORDER BY created_at",
                (session_id,),
                fetch=True
            )

            return [self._row_to_memory(row) for row in result]

    def _row_to_memory(self, row) -> Memory:
        """
        Convert a database row to Memory object.

        Handles both old schema (temporal_relevance column) and new schema
        (decay_category column) for backward compatibility during migration.
        """
        # Parse dates
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        last_accessed_at = row["last_accessed_at"]
        if isinstance(last_accessed_at, str):
            last_accessed_at = datetime.fromisoformat(last_accessed_at)

        source_timestamp = row["source_timestamp"]
        if isinstance(source_timestamp, str):
            source_timestamp = datetime.fromisoformat(source_timestamp)

        # Parse conversation IDs
        source_conversation_ids = []
        if row["source_conversation_ids"]:
            source_conversation_ids = json.loads(row["source_conversation_ids"])

        # Handle decay_category with backward compatibility
        # The migration renames temporal_relevance -> decay_category and maps values:
        #   'recent' -> 'standard', 'dated' -> 'ephemeral', 'permanent' -> 'permanent'
        decay_category = row["decay_category"] if row["decay_category"] else "standard"

        # Map legacy values to new categories (in case migration hasn't run yet)
        legacy_mapping = {
            "recent": "standard",
            "dated": "ephemeral",
        }
        decay_category = legacy_mapping.get(decay_category, decay_category)

        # Handle memory_category with default for pre-v12 databases
        # All existing memories are treated as 'episodic' since they were extracted
        # using the narrative-focused prompts before dual-track extraction was added
        memory_category = row["memory_category"] if row["memory_category"] else "episodic"

        return Memory(
            id=row["id"],
            content=row["content"],
            embedding=bytes_to_embedding(row["embedding"], self.embedding_dimensions),
            source_conversation_ids=source_conversation_ids,
            source_session_id=row["source_session_id"],
            created_at=created_at,
            last_accessed_at=last_accessed_at,
            access_count=row["access_count"],
            source_timestamp=source_timestamp,
            decay_category=decay_category,
            importance=row["importance"],
            memory_type=row["memory_type"],
            memory_category=memory_category
        )


# Global vector store instance
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        from config import (
            EMBEDDING_DIMENSIONS,
            MEMORY_SEMANTIC_WEIGHT,
            MEMORY_IMPORTANCE_WEIGHT,
            MEMORY_FRESHNESS_WEIGHT
        )
        _vector_store = VectorStore(
            embedding_dimensions=EMBEDDING_DIMENSIONS,
            semantic_weight=MEMORY_SEMANTIC_WEIGHT,
            importance_weight=MEMORY_IMPORTANCE_WEIGHT,
            freshness_weight=MEMORY_FRESHNESS_WEIGHT
        )
    return _vector_store


def init_vector_store() -> VectorStore:
    """Initialize the global vector store."""
    global _vector_store
    from config import (
        EMBEDDING_DIMENSIONS,
        MEMORY_SEMANTIC_WEIGHT,
        MEMORY_IMPORTANCE_WEIGHT,
        MEMORY_FRESHNESS_WEIGHT
    )
    _vector_store = VectorStore(
        embedding_dimensions=EMBEDDING_DIMENSIONS,
        semantic_weight=MEMORY_SEMANTIC_WEIGHT,
        importance_weight=MEMORY_IMPORTANCE_WEIGHT,
        freshness_weight=MEMORY_FRESHNESS_WEIGHT
    )
    return _vector_store
