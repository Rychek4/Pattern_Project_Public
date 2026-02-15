"""
Pattern Project - Growth Threads Manager
Manages the AI's long-term developmental aspirations.

Growth threads sit between active thoughts (volatile, present-tense) and
memories (passive, past-tense). They represent "what I am becoming" —
patterns the AI has noticed and wants to integrate over weeks or months.

Lifecycle:
    SEED → GROWING → INTEGRATING → (promoted to core memory + removed)
    Any active stage → DORMANT (can reactivate)
    Any stage → ABANDONED (removed)

The AI manages all transitions during pulse reflection. The system provides
storage and prompt injection; the AI does the cognitive work.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple

from core.database import get_database
from concurrency.db_retry import db_retry
from core.logger import log_info, log_error

# Valid stages for growth threads
VALID_STAGES = ('seed', 'growing', 'integrating', 'dormant', 'abandoned')
# Active stages (injected into normal conversation prompts)
ACTIVE_STAGES = ('seed', 'growing', 'integrating')
# Maximum active threads (seed + growing + integrating)
MAX_ACTIVE_THREADS = 5


@dataclass
class GrowthThread:
    """A single growth thread representing a developmental aspiration."""
    id: int
    slug: str
    content: str  # The evolving prose — the literary record
    stage: str  # seed, growing, integrating, dormant, abandoned
    stage_changed_at: datetime
    created_at: datetime
    updated_at: datetime


class GrowthThreadManager:
    """
    Manages growth threads — the AI's long-term developmental aspirations.

    Two operations:
    - set: Create or update a thread by slug (covers seeding, evidence
           accumulation, stage transitions, and content rewrites)
    - remove: Delete a thread by slug (for post-promotion cleanup or abandonment)
    """

    @db_retry()
    def get_all(self) -> List[GrowthThread]:
        """
        Get all growth threads, ordered by stage priority then creation date.

        Returns:
            List of GrowthThread objects
        """
        db = get_database()
        result = db.execute(
            """
            SELECT * FROM growth_threads
            ORDER BY
                CASE stage
                    WHEN 'integrating' THEN 1
                    WHEN 'growing' THEN 2
                    WHEN 'seed' THEN 3
                    WHEN 'dormant' THEN 4
                    WHEN 'abandoned' THEN 5
                END,
                created_at ASC
            """,
            fetch=True
        )

        if not result:
            return []

        return [self._row_to_thread(row) for row in result]

    @db_retry()
    def get_active(self) -> List[GrowthThread]:
        """
        Get only active threads (seed, growing, integrating).
        These are injected into normal conversation prompts.

        Returns:
            List of active GrowthThread objects
        """
        db = get_database()
        result = db.execute(
            """
            SELECT * FROM growth_threads
            WHERE stage IN ('seed', 'growing', 'integrating')
            ORDER BY
                CASE stage
                    WHEN 'integrating' THEN 1
                    WHEN 'growing' THEN 2
                    WHEN 'seed' THEN 3
                END,
                created_at ASC
            """,
            fetch=True
        )

        if not result:
            return []

        return [self._row_to_thread(row) for row in result]

    @db_retry()
    def get_dormant(self) -> List[GrowthThread]:
        """
        Get dormant threads (shown during pulse only).

        Returns:
            List of dormant GrowthThread objects
        """
        db = get_database()
        result = db.execute(
            "SELECT * FROM growth_threads WHERE stage = 'dormant' ORDER BY created_at ASC",
            fetch=True
        )

        if not result:
            return []

        return [self._row_to_thread(row) for row in result]

    @db_retry()
    def get_by_slug(self, slug: str) -> Optional[GrowthThread]:
        """Get a growth thread by its slug."""
        db = get_database()
        result = db.execute(
            "SELECT * FROM growth_threads WHERE slug = ?",
            (slug,),
            fetch=True
        )

        if not result:
            return None

        return self._row_to_thread(result[0])

    def set(self, slug: str, stage: str, content: str) -> Tuple[bool, Optional[str]]:
        """
        Create or update a growth thread.

        If the slug exists, updates content and stage. If stage changed,
        updates stage_changed_at. Always updates updated_at.

        If the slug doesn't exist, creates a new thread.

        Args:
            slug: Short identifier for the thread
            stage: One of: seed, growing, integrating, dormant, abandoned
            content: The evolving prose (should start with FOCUS: line)

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        # Validate stage
        if stage not in VALID_STAGES:
            return False, f"Invalid stage '{stage}'. Must be one of: {', '.join(VALID_STAGES)}"

        # Validate slug
        if not slug or not isinstance(slug, str):
            return False, "Slug is required and must be a non-empty string"

        if not content or not isinstance(content, str):
            return False, "Content is required and must be a non-empty string"

        try:
            db = get_database()
            now = datetime.now().isoformat()

            # Check if thread exists
            existing = db.execute(
                "SELECT id, stage FROM growth_threads WHERE slug = ?",
                (slug,),
                fetch=True
            )

            if existing:
                # Update existing thread
                old_stage = existing[0]["stage"]
                stage_changed = old_stage != stage

                if stage_changed:
                    db.execute(
                        """
                        UPDATE growth_threads
                        SET content = ?, stage = ?, stage_changed_at = ?, updated_at = ?
                        WHERE slug = ?
                        """,
                        (content, stage, now, now, slug)
                    )
                    log_info(
                        f"Growth thread [{slug}] updated: {old_stage} → {stage}",
                        prefix="🌱"
                    )
                else:
                    db.execute(
                        """
                        UPDATE growth_threads
                        SET content = ?, updated_at = ?
                        WHERE slug = ?
                        """,
                        (content, now, slug)
                    )
                    log_info(f"Growth thread [{slug}] content updated", prefix="🌱")
            else:
                # Check active thread count before creating
                if stage in ACTIVE_STAGES:
                    active_count = self._count_active()
                    if active_count >= MAX_ACTIVE_THREADS:
                        return False, (
                            f"Maximum {MAX_ACTIVE_THREADS} active threads allowed "
                            f"(currently {active_count}). "
                            f"Complete, dormant, or abandon a thread first."
                        )

                # Create new thread
                db.execute(
                    """
                    INSERT INTO growth_threads
                    (slug, content, stage, stage_changed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (slug, content, stage, now, now, now)
                )
                log_info(f"Growth thread [{slug}] created (stage: {stage})", prefix="🌱")

            return True, None

        except Exception as e:
            error_msg = f"Failed to set growth thread [{slug}]: {e}"
            log_error(error_msg)
            return False, error_msg

    def remove(self, slug: str) -> Tuple[bool, Optional[str]]:
        """
        Remove a growth thread by slug.

        Used after promoting to core memory or when abandoning.

        Args:
            slug: The thread slug to remove

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        try:
            db = get_database()

            # Verify it exists
            existing = db.execute(
                "SELECT id FROM growth_threads WHERE slug = ?",
                (slug,),
                fetch=True
            )

            if not existing:
                return False, f"No growth thread found with slug '{slug}'"

            db.execute(
                "DELETE FROM growth_threads WHERE slug = ?",
                (slug,)
            )

            log_info(f"Growth thread [{slug}] removed", prefix="🌱")
            return True, None

        except Exception as e:
            error_msg = f"Failed to remove growth thread [{slug}]: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def _count_active(self) -> int:
        """Count threads in active stages."""
        db = get_database()
        result = db.execute(
            "SELECT COUNT(*) as count FROM growth_threads WHERE stage IN ('seed', 'growing', 'integrating')",
            fetch=True
        )
        return result[0]["count"] if result else 0

    def _row_to_thread(self, row) -> GrowthThread:
        """Convert a database row to a GrowthThread object."""
        stage_changed_at = row["stage_changed_at"]
        if isinstance(stage_changed_at, str):
            stage_changed_at = datetime.fromisoformat(stage_changed_at)

        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        updated_at = row["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return GrowthThread(
            id=row["id"],
            slug=row["slug"],
            content=row["content"],
            stage=row["stage"],
            stage_changed_at=stage_changed_at,
            created_at=created_at,
            updated_at=updated_at
        )


# Global instance
_manager: Optional[GrowthThreadManager] = None


def get_growth_thread_manager() -> GrowthThreadManager:
    """Get the global GrowthThreadManager instance."""
    global _manager
    if _manager is None:
        _manager = GrowthThreadManager()
    return _manager
