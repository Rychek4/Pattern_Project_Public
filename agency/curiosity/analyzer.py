"""
Pattern Project - Curiosity State Analyzer
Identifies dormant topics and knowledge gaps from memory state.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Set, Optional

from core.database import get_database
from core.logger import log_info, log_error
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry

import config


@dataclass
class CuriosityCandidate:
    """
    A potential curiosity goal derived from memory analysis.

    Attributes:
        content: The topic/question to explore
        source_memory_id: Which memory spawned this candidate
        weight: Selection probability weight (higher = more likely to be selected)
        category: Type of curiosity (dormant_revival, depth_seeking)
        context: Supporting detail for natural bridging in conversation
        last_discussed: When this topic was last accessed
        importance: Importance score from source memory
    """
    content: str
    source_memory_id: int
    weight: float
    category: str
    context: str
    last_discussed: Optional[datetime]
    importance: float


class CuriosityAnalyzer:
    """
    Analyzes memory state to identify curiosity candidates.

    The analyzer queries the memories table to find:
    - Dormant topics: Important memories not accessed in N days
    - (Future: Depth seeking, pattern acknowledgment)

    Candidates are weighted by:
    - Days since last access (dormancy)
    - Memory importance score
    """

    def __init__(self):
        self._lock_manager = get_lock_manager()

    @db_retry()
    def get_candidates(
        self,
        excluded_memory_ids: Set[int],
        limit: int = 20
    ) -> List[CuriosityCandidate]:
        """
        Get weighted curiosity candidates from memory state.

        Args:
            excluded_memory_ids: Memory IDs to exclude (in cooldown)
            limit: Maximum candidates to return

        Returns:
            List of CuriosityCandidate sorted by weight descending
        """
        dormant_days = getattr(config, 'CURIOSITY_DORMANT_DAYS', 14)
        min_importance = getattr(config, 'CURIOSITY_MIN_IMPORTANCE', 0.4)

        # Calculate the dormancy threshold date
        threshold_date = datetime.now() - timedelta(days=dormant_days)

        with self._lock_manager.acquire("database"):
            db = get_database()

            # Query for dormant, important memories
            # Prioritize factual memories about the user (more concrete topics)
            # Also include episodic memories with high importance
            result = db.execute(
                """
                SELECT
                    id,
                    content,
                    importance,
                    memory_type,
                    memory_category,
                    last_accessed_at,
                    created_at,
                    source_timestamp
                FROM memories
                WHERE importance >= ?
                AND (
                    last_accessed_at IS NULL
                    OR last_accessed_at < ?
                )
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                (min_importance, threshold_date.isoformat(), limit * 2),
                fetch=True
            )

            if not result:
                return []

            candidates = []
            weight_dormancy = getattr(config, 'CURIOSITY_WEIGHT_DORMANCY', 1.5)
            weight_importance = getattr(config, 'CURIOSITY_WEIGHT_IMPORTANCE', 2.0)

            for row in result:
                memory_id = row["id"]

                # Skip excluded memories
                if memory_id in excluded_memory_ids:
                    continue

                content = row["content"]
                importance = row["importance"] or 0.5
                memory_type = row["memory_type"]
                memory_category = row["memory_category"] or "episodic"

                # Parse last_accessed_at
                last_accessed = None
                if row["last_accessed_at"]:
                    if isinstance(row["last_accessed_at"], str):
                        last_accessed = datetime.fromisoformat(row["last_accessed_at"])
                    else:
                        last_accessed = row["last_accessed_at"]

                # Calculate days dormant
                if last_accessed:
                    days_dormant = (datetime.now() - last_accessed).days
                else:
                    # Never accessed - use created_at
                    created = row["created_at"]
                    if isinstance(created, str):
                        created = datetime.fromisoformat(created)
                    days_dormant = (datetime.now() - created).days

                # Calculate weight
                # Higher dormancy and higher importance = higher weight
                dormancy_factor = min(days_dormant / dormant_days, 3.0)  # Cap at 3x
                weight = (
                    (dormancy_factor * weight_dormancy) +
                    (importance * weight_importance)
                )

                # Boost factual memories slightly (more concrete topics)
                if memory_category == "factual":
                    weight *= 1.2

                # Determine category
                category = "dormant_revival"

                # Build context from memory content
                # Truncate if too long
                context = content[:200] + "..." if len(content) > 200 else content

                candidates.append(CuriosityCandidate(
                    content=content,
                    source_memory_id=memory_id,
                    weight=weight,
                    category=category,
                    context=context,
                    last_discussed=last_accessed,
                    importance=importance
                ))

            # Sort by weight descending and limit
            candidates.sort(key=lambda c: c.weight, reverse=True)
            return candidates[:limit]

    def get_fallback_candidate(self) -> CuriosityCandidate:
        """
        Generate a fallback candidate when no memories qualify.

        This should rarely be called - it exists to ensure there's
        always SOMETHING for the curiosity system to work with.

        Returns:
            A generic reflection-based curiosity candidate
        """
        return CuriosityCandidate(
            content="Reflect on recent conversations and identify something meaningful to explore",
            source_memory_id=0,  # No source memory
            weight=1.0,
            category="depth_seeking",
            context="No specific dormant topics found - explore what feels most relevant",
            last_discussed=None,
            importance=0.5
        )


# Global instance
_analyzer: Optional[CuriosityAnalyzer] = None


def get_curiosity_analyzer() -> CuriosityAnalyzer:
    """Get the global CuriosityAnalyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = CuriosityAnalyzer()
    return _analyzer
