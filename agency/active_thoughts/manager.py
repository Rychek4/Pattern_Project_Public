"""
Pattern Project - Active Thoughts Manager
Manages the AI's working memory - a ranked list of current priorities
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.database import get_database
from concurrency.db_retry import db_retry
from core.logger import log_info, log_error


@dataclass
class ActiveThought:
    """A single active thought in the AI's working memory."""
    id: int
    rank: int  # 1-10, lower = more salient
    slug: str  # Short identifier
    topic: str  # One-line summary
    elaboration: str  # Detailed thinking
    created_at: datetime
    updated_at: datetime


class ActiveThoughtsManager:
    """
    Manages the AI's active thoughts - its working memory.

    This is the AI's private "stream of consciousness" that persists
    across sessions. The AI has full control over this list:
    - Add, edit, delete thoughts at will
    - Rerank to reflect shifting priorities
    - Maximum 10 items to force prioritization

    Unlike semantic memories (which decay) or intentions (which have triggers),
    active thoughts persist until the AI explicitly changes them.
    """

    MAX_THOUGHTS = 10

    @db_retry()
    def get_all(self) -> List[ActiveThought]:
        """
        Get all active thoughts, ordered by rank.

        Returns:
            List of ActiveThought objects, sorted by rank ascending
        """
        db = get_database()
        result = db.execute(
            "SELECT * FROM active_thoughts ORDER BY rank ASC",
            fetch=True
        )

        if not result:
            return []

        return [self._row_to_thought(row) for row in result]

    @db_retry()
    def get_by_rank(self, rank: int) -> Optional[ActiveThought]:
        """Get a thought by its rank (1-10)."""
        if not 1 <= rank <= self.MAX_THOUGHTS:
            return None

        db = get_database()
        result = db.execute(
            "SELECT * FROM active_thoughts WHERE rank = ?",
            (rank,),
            fetch=True
        )

        if not result:
            return None

        return self._row_to_thought(result[0])

    @db_retry()
    def get_by_slug(self, slug: str) -> Optional[ActiveThought]:
        """Get a thought by its slug identifier."""
        db = get_database()
        result = db.execute(
            "SELECT * FROM active_thoughts WHERE slug = ?",
            (slug,),
            fetch=True
        )

        if not result:
            return None

        return self._row_to_thought(result[0])

    @db_retry()
    def count(self) -> int:
        """Get the number of active thoughts."""
        db = get_database()
        result = db.execute(
            "SELECT COUNT(*) as count FROM active_thoughts",
            fetch=True
        )
        return result[0]["count"] if result else 0

    def set_all(self, thoughts: List[Dict[str, Any]]) -> tuple[bool, Optional[str]]:
        """
        Replace all active thoughts with a new list.

        This is the primary way to update thoughts - send the complete
        new list and it replaces whatever was there before.

        Args:
            thoughts: List of thought dicts with keys:
                - rank: int (1-10, required)
                - slug: str (required)
                - topic: str (required)
                - elaboration: str (required)

        Returns:
            Tuple of (success: bool, error_message: Optional[str])
        """
        # Validate input
        validation_error = self._validate_thoughts(thoughts)
        if validation_error:
            return False, validation_error

        try:
            db = get_database()
            now = datetime.now().isoformat()

            with db.get_connection() as conn:
                # Get existing thoughts to preserve created_at and updated_at
                # for items whose content hasn't changed
                existing = {}
                cursor = conn.execute(
                    "SELECT slug, topic, elaboration, created_at, updated_at FROM active_thoughts"
                )
                for row in cursor.fetchall():
                    existing[row["slug"]] = {
                        "topic": row["topic"],
                        "elaboration": row["elaboration"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"]
                    }

                # Archive current thoughts to history before replacing
                if existing:
                    conn.execute(
                        """
                        INSERT INTO active_thoughts_history
                        (archived_at, rank, slug, topic, elaboration, created_at, updated_at)
                        SELECT ?, rank, slug, topic, elaboration, created_at, updated_at
                        FROM active_thoughts
                        """,
                        (now,)
                    )

                # Clear existing thoughts
                conn.execute("DELETE FROM active_thoughts")

                # Insert new thoughts
                for thought in thoughts:
                    # Check if this thought existed before and if content changed
                    if thought["slug"] in existing:
                        existing_thought = existing[thought["slug"]]
                        created_at = existing_thought["created_at"]

                        # Only update updated_at if content actually changed
                        content_changed = (
                            existing_thought["topic"] != thought["topic"] or
                            existing_thought["elaboration"] != thought["elaboration"]
                        )
                        updated_at = now if content_changed else existing_thought["updated_at"]
                    else:
                        # New thought
                        created_at = now
                        updated_at = now

                    conn.execute(
                        """
                        INSERT INTO active_thoughts
                        (rank, slug, topic, elaboration, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            thought["rank"],
                            thought["slug"],
                            thought["topic"],
                            thought["elaboration"],
                            created_at,
                            updated_at
                        )
                    )

            log_info(f"Active thoughts updated: {len(thoughts)} items", prefix="💭")
            return True, None

        except Exception as e:
            error_msg = f"Failed to update active thoughts: {e}"
            log_error(error_msg)
            return False, error_msg

    @db_retry()
    def clear_all(self) -> bool:
        """
        Remove all active thoughts.

        Returns:
            True if successful, False otherwise
        """
        try:
            db = get_database()
            now = datetime.now().isoformat()

            with db.get_connection() as conn:
                # Archive current thoughts to history before clearing
                conn.execute(
                    """
                    INSERT INTO active_thoughts_history
                    (archived_at, rank, slug, topic, elaboration, created_at, updated_at)
                    SELECT ?, rank, slug, topic, elaboration, created_at, updated_at
                    FROM active_thoughts
                    """,
                    (now,)
                )
                conn.execute("DELETE FROM active_thoughts")

            log_info("Active thoughts cleared", prefix="💭")
            return True
        except Exception as e:
            log_error(f"Failed to clear active thoughts: {e}")
            return False

    def _validate_thoughts(self, thoughts: List[Dict[str, Any]]) -> Optional[str]:
        """
        Validate a list of thoughts before saving.

        Returns:
            Error message if invalid, None if valid
        """
        if not isinstance(thoughts, list):
            return "Thoughts must be a list"

        if len(thoughts) > self.MAX_THOUGHTS:
            return f"Maximum {self.MAX_THOUGHTS} thoughts allowed, got {len(thoughts)}"

        required_fields = ["rank", "slug", "topic", "elaboration"]
        seen_ranks = set()
        seen_slugs = set()

        for i, thought in enumerate(thoughts):
            if not isinstance(thought, dict):
                return f"Item {i} is not an object"

            # Check required fields
            for field in required_fields:
                if field not in thought:
                    return f"Item {i} missing required field '{field}'"
                if not thought[field] and thought[field] != 0:
                    return f"Item {i} has empty '{field}'"

            # Validate rank
            rank = thought["rank"]
            if not isinstance(rank, int):
                return f"Item {i}: rank must be an integer, got {type(rank).__name__}"
            if not 1 <= rank <= self.MAX_THOUGHTS:
                return f"Item {i}: rank must be 1-{self.MAX_THOUGHTS}, got {rank}"
            if rank in seen_ranks:
                return f"Duplicate rank {rank} found"
            seen_ranks.add(rank)

            # Validate slug uniqueness
            slug = thought["slug"]
            if slug in seen_slugs:
                return f"Duplicate slug '{slug}' found"
            seen_slugs.add(slug)

            # Validate string fields
            for field in ["slug", "topic", "elaboration"]:
                if not isinstance(thought[field], str):
                    return f"Item {i}: {field} must be a string"

        return None

    def _row_to_thought(self, row) -> ActiveThought:
        """Convert a database row to an ActiveThought object."""
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        updated_at = row["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return ActiveThought(
            id=row["id"],
            rank=row["rank"],
            slug=row["slug"],
            topic=row["topic"],
            elaboration=row["elaboration"],
            created_at=created_at,
            updated_at=updated_at
        )


# Global instance
_manager: Optional[ActiveThoughtsManager] = None


def get_active_thoughts_manager() -> ActiveThoughtsManager:
    """Get the global ActiveThoughtsManager instance."""
    global _manager
    if _manager is None:
        _manager = ActiveThoughtsManager()
    return _manager
