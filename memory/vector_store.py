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
    """A stored memory with metadata."""
    id: int
    content: str
    embedding: np.ndarray
    source_conversation_ids: List[int]
    source_session_id: Optional[int]
    created_at: datetime
    last_accessed_at: Optional[datetime]
    access_count: int
    source_timestamp: Optional[datetime]
    temporal_relevance: str
    importance: float
    memory_type: Optional[str]


@dataclass
class MemorySearchResult:
    """A memory with its relevance score."""
    memory: Memory
    semantic_score: float
    freshness_score: float
    access_score: float
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
        freshness_half_life_days: float = 30.0,
        semantic_weight: float = 0.6,
        freshness_weight: float = 0.3,
        access_weight: float = 0.1
    ):
        """
        Initialize the vector store.

        Args:
            embedding_dimensions: Dimension of embedding vectors
            freshness_half_life_days: Days for freshness decay
            semantic_weight: Weight for semantic similarity
            freshness_weight: Weight for freshness score
            access_weight: Weight for access recency score
        """
        self.embedding_dimensions = embedding_dimensions
        self.freshness_half_life_days = freshness_half_life_days
        self.semantic_weight = semantic_weight
        self.freshness_weight = freshness_weight
        self.access_weight = access_weight
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
        temporal_relevance: str = "recent"
    ) -> Optional[int]:
        """
        Add a new memory to the store.

        Args:
            content: The memory content
            source_conversation_ids: IDs of source conversations
            source_session_id: Source session ID
            source_timestamp: When the memory event occurred
            importance: Importance score (0-1)
            memory_type: Type of memory
            temporal_relevance: 'permanent', 'recent', or 'dated'

        Returns:
            The new memory ID, or None if embedding failed
        """
        if not is_model_loaded():
            log_error("Cannot add memory: embedding model not loaded")
            return None

        # Generate embedding
        embedding = get_embedding(content)
        if embedding is None:
            log_error("Failed to generate embedding for memory")
            return None

        with self._lock_manager.acquire("memory"):
            db = get_database()
            now = datetime.now()

            if source_timestamp is None:
                source_timestamp = now

            db.execute(
                """
                INSERT INTO memories
                (content, embedding, source_conversation_ids, source_session_id,
                 source_timestamp, importance, memory_type, temporal_relevance,
                 created_at, last_accessed_at, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content,
                    embedding_to_bytes(embedding),
                    json.dumps(source_conversation_ids),
                    source_session_id,
                    source_timestamp.isoformat(),
                    importance,
                    memory_type,
                    temporal_relevance,
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

    @db_retry()
    def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[str] = None,
        min_score: float = 0.0
    ) -> List[MemorySearchResult]:
        """
        Search for relevant memories.

        Args:
            query: The search query
            limit: Maximum results to return
            memory_type: Filter by memory type
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

            # Build query
            sql = "SELECT * FROM memories"
            params = []

            if memory_type:
                sql += " WHERE memory_type = ?"
                params.append(memory_type)

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

                # Freshness score
                freshness_score = self._compute_freshness(memory, now)

                # Access recency score
                access_score = self._compute_access_score(memory, now)

                # Combined score
                combined_score = (
                    self.semantic_weight * semantic_score +
                    self.freshness_weight * freshness_score +
                    self.access_weight * access_score
                )

                if combined_score >= min_score:
                    results.append(MemorySearchResult(
                        memory=memory,
                        semantic_score=semantic_score,
                        freshness_score=freshness_score,
                        access_score=access_score,
                        combined_score=combined_score
                    ))

            # Sort by combined score
            results.sort(key=lambda x: x.combined_score, reverse=True)

            # Update access times for returned results
            if results:
                top_ids = [r.memory.id for r in results[:limit]]
                self._update_access(top_ids, now)

            return results[:limit]

    def _compute_freshness(self, memory: Memory, now: datetime) -> float:
        """Compute freshness score based on source timestamp."""
        if memory.temporal_relevance == "permanent":
            return 1.0

        if memory.source_timestamp:
            age_days = (now - memory.source_timestamp).days
            return math.exp(-age_days / self.freshness_half_life_days)

        return 0.5

    def _compute_access_score(self, memory: Memory, now: datetime) -> float:
        """Compute access recency score."""
        if memory.last_accessed_at:
            hours_since_access = (now - memory.last_accessed_at).total_seconds() / 3600
            return math.exp(-hours_since_access / 24)  # Decays over ~1 day
        return 0.0

    @db_retry()
    def _update_access(self, memory_ids: List[int], access_time: datetime) -> None:
        """Update access time and count for memories."""
        if not memory_ids:
            return

        db = get_database()
        placeholders = ",".join("?" * len(memory_ids))

        db.execute(
            f"""
            UPDATE memories
            SET last_accessed_at = ?,
                access_count = access_count + 1
            WHERE id IN ({placeholders})
            """,
            (access_time.isoformat(), *memory_ids)
        )

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
        """Convert a database row to Memory object."""
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
            temporal_relevance=row["temporal_relevance"],
            importance=row["importance"],
            memory_type=row["memory_type"]
        )


# Global vector store instance
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get the global vector store instance."""
    global _vector_store
    if _vector_store is None:
        from config import (
            EMBEDDING_DIMENSIONS,
            MEMORY_FRESHNESS_HALF_LIFE_DAYS,
            MEMORY_SEMANTIC_WEIGHT,
            MEMORY_FRESHNESS_WEIGHT,
            MEMORY_ACCESS_WEIGHT
        )
        _vector_store = VectorStore(
            embedding_dimensions=EMBEDDING_DIMENSIONS,
            freshness_half_life_days=MEMORY_FRESHNESS_HALF_LIFE_DAYS,
            semantic_weight=MEMORY_SEMANTIC_WEIGHT,
            freshness_weight=MEMORY_FRESHNESS_WEIGHT,
            access_weight=MEMORY_ACCESS_WEIGHT
        )
    return _vector_store


def init_vector_store() -> VectorStore:
    """Initialize the global vector store."""
    global _vector_store
    from config import (
        EMBEDDING_DIMENSIONS,
        MEMORY_FRESHNESS_HALF_LIFE_DAYS,
        MEMORY_SEMANTIC_WEIGHT,
        MEMORY_FRESHNESS_WEIGHT,
        MEMORY_ACCESS_WEIGHT
    )
    _vector_store = VectorStore(
        embedding_dimensions=EMBEDDING_DIMENSIONS,
        freshness_half_life_days=MEMORY_FRESHNESS_HALF_LIFE_DAYS,
        semantic_weight=MEMORY_SEMANTIC_WEIGHT,
        freshness_weight=MEMORY_FRESHNESS_WEIGHT,
        access_weight=MEMORY_ACCESS_WEIGHT
    )
    return _vector_store
