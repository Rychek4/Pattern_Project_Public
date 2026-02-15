"""
Pattern Project - Curiosity State Analyzer
Identifies dormant topics and fresh discoveries from memory state.
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
        category: Type of curiosity (dormant_revival, fresh_discovery, depth_seeking)
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
    - Fresh discoveries: New high-importance memories worth exploring

    Candidates are weighted by:
    - Days since last access (dormancy) OR recency (freshness)
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

        Combines two sources:
        - Dormant topics: Old memories not accessed in N days
        - Fresh discoveries: New high-importance memories

        Args:
            excluded_memory_ids: Memory IDs to exclude (in cooldown)
            limit: Maximum candidates to return

        Returns:
            List of CuriosityCandidate sorted by weight descending
        """
        candidates = []

        # Get dormant candidates
        dormant = self._get_dormant_candidates(excluded_memory_ids, limit)
        candidates.extend(dormant)

        # Get fresh discovery candidates
        fresh = self._get_fresh_candidates(excluded_memory_ids, limit)
        candidates.extend(fresh)

        # Sort by weight descending and limit
        candidates.sort(key=lambda c: c.weight, reverse=True)
        return candidates[:limit]

    def _get_dormant_candidates(
        self,
        excluded_memory_ids: Set[int],
        limit: int = 20
    ) -> List[CuriosityCandidate]:
        """
        Get candidates from dormant (old, unaccessed) memories.

        Dormant eligibility:
        - Previously accessed but not in the last N days, OR
        - Never accessed and created at least M days ago

        This avoids a "dead zone" where memories are too old for fresh
        but too new for dormant.

        Args:
            excluded_memory_ids: Memory IDs to exclude (in cooldown)
            limit: Maximum candidates to return

        Returns:
            List of dormant revival candidates
        """
        dormant_days = getattr(config, 'CURIOSITY_DORMANT_DAYS', 7)
        min_age_days = getattr(config, 'CURIOSITY_DORMANT_MIN_AGE_DAYS', 2)
        min_importance = getattr(config, 'CURIOSITY_MIN_IMPORTANCE', 0.4)

        # Two thresholds:
        # - dormant_threshold: for memories that HAVE been accessed (not in last N days)
        # - min_age_threshold: for memories NEVER accessed (at least M days old)
        dormant_threshold = datetime.now() - timedelta(days=dormant_days)
        min_age_threshold = datetime.now() - timedelta(days=min_age_days)

        with self._lock_manager.acquire("database"):
            db = get_database()

            # Query for dormant, important memories
            # Two paths to eligibility:
            # 1. Previously accessed, but not recently (> dormant_days)
            # 2. Never accessed, but old enough (> min_age_days)
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
                    (last_accessed_at IS NOT NULL AND last_accessed_at < ?)
                    OR
                    (last_accessed_at IS NULL AND created_at < ?)
                )
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                (min_importance, dormant_threshold.strftime('%Y-%m-%d %H:%M:%S'), min_age_threshold.strftime('%Y-%m-%d %H:%M:%S'), limit * 2),
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

                # Build context from memory content
                context = content[:200] + "..." if len(content) > 200 else content

                candidates.append(CuriosityCandidate(
                    content=content,
                    source_memory_id=memory_id,
                    weight=weight,
                    category="dormant_revival",
                    context=context,
                    last_discussed=last_accessed,
                    importance=importance
                ))

            return candidates

    def _get_fresh_candidates(
        self,
        excluded_memory_ids: Set[int],
        limit: int = 20
    ) -> List[CuriosityCandidate]:
        """
        Get candidates from fresh (recently created) high-importance memories.

        These are new facts or events that are significant enough to explore
        further, even though they're recent.

        Args:
            excluded_memory_ids: Memory IDs to exclude (in cooldown)
            limit: Maximum candidates to return

        Returns:
            List of fresh discovery candidates
        """
        fresh_hours = getattr(config, 'CURIOSITY_FRESH_HOURS', 48)
        min_importance = getattr(config, 'CURIOSITY_FRESH_MIN_IMPORTANCE', 0.7)

        # Calculate the freshness threshold
        threshold_date = datetime.now() - timedelta(hours=fresh_hours)

        with self._lock_manager.acquire("database"):
            db = get_database()

            # Query for fresh, high-importance memories
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
                AND created_at >= ?
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                (min_importance, threshold_date.strftime('%Y-%m-%d %H:%M:%S'), limit * 2),
                fetch=True
            )

            if not result:
                return []

            candidates = []
            weight_freshness = getattr(config, 'CURIOSITY_WEIGHT_FRESHNESS', 1.8)
            weight_importance = getattr(config, 'CURIOSITY_WEIGHT_IMPORTANCE', 2.0)

            for row in result:
                memory_id = row["id"]

                # Skip excluded memories
                if memory_id in excluded_memory_ids:
                    continue

                content = row["content"]
                importance = row["importance"] or 0.5
                memory_category = row["memory_category"] or "episodic"

                # Parse created_at
                created = row["created_at"]
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)

                # Calculate freshness factor (newer = higher weight)
                hours_old = (datetime.now() - created).total_seconds() / 3600
                freshness_factor = max(0, (fresh_hours - hours_old) / fresh_hours)

                # Calculate weight
                weight = (
                    (freshness_factor * weight_freshness) +
                    (importance * weight_importance)
                )

                # Boost factual memories (more concrete topics)
                if memory_category == "factual":
                    weight *= 1.2

                # Build context from memory content
                context = content[:200] + "..." if len(content) > 200 else content

                # Parse last_accessed_at for the candidate
                last_accessed = None
                if row["last_accessed_at"]:
                    if isinstance(row["last_accessed_at"], str):
                        last_accessed = datetime.fromisoformat(row["last_accessed_at"])
                    else:
                        last_accessed = row["last_accessed_at"]

                candidates.append(CuriosityCandidate(
                    content=content,
                    source_memory_id=memory_id,
                    weight=weight,
                    category="fresh_discovery",
                    context=context,
                    last_discussed=last_accessed,
                    importance=importance
                ))

            return candidates

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
