"""
Pattern Project - Core Memory Source
Permanent, foundational memories always included in every prompt
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.database import get_database
from concurrency.db_retry import db_retry
from core.logger import log_info, log_error


@dataclass
class CoreMemory:
    """A permanent core memory."""
    id: int
    content: str
    category: str  # identity, relationship, preference, fact
    created_at: datetime
    promoted_from_memory_id: Optional[int]  # If promoted from regular memory


class CoreMemorySource(ContextSource):
    """
    Provides core memories for prompt context.

    Core memories are:
    - Always included in full (no retrieval/scoring)
    - Permanent and foundational
    - Can be manually added or promoted from high-scoring regular memories
    """

    @property
    def source_name(self) -> str:
        return "core_memory"

    @property
    def priority(self) -> int:
        return SourcePriority.CORE_MEMORY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get all core memories formatted for prompt injection."""
        memories = self.get_all()

        if not memories:
            return None

        # Group by category for organized presentation
        by_category: Dict[str, List[CoreMemory]] = {}
        for mem in memories:
            if mem.category not in by_category:
                by_category[mem.category] = []
            by_category[mem.category].append(mem)

        lines = []

        # Narrative content comes first as a cohesive identity block
        if "narrative" in by_category:
            for mem in by_category["narrative"]:
                lines.append(mem.content)
            # Add separator if there are other memories
            other_categories = [c for c in by_category if c != "narrative"]
            if other_categories:
                lines.append("")  # Blank line separator

        # Other categories as discrete memories (if any exist)
        category_order = ["identity", "relationship", "preference", "fact"]
        has_discrete_memories = any(c in by_category for c in category_order)

        if has_discrete_memories:
            for category in category_order:
                if category in by_category:
                    for mem in by_category[category]:
                        lines.append(f"- [{category}] {mem.content}")

        # Any other categories not in standard order
        for category, mems in by_category.items():
            if category not in category_order and category != "narrative":
                for mem in mems:
                    lines.append(f"- [{category}] {mem.content}")

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=True,
            metadata={"memory_count": len(memories)}
        )

    @db_retry()
    def get_all(self) -> List[CoreMemory]:
        """Get all core memories."""
        db = get_database()
        result = db.execute(
            "SELECT * FROM core_memories ORDER BY category, created_at",
            fetch=True
        )

        if not result:
            return []

        return [self._row_to_memory(row) for row in result]

    @db_retry()
    def add(
        self,
        content: str,
        category: str = "fact",
        promoted_from: Optional[int] = None
    ) -> Optional[int]:
        """
        Add a new core memory.

        Args:
            content: The memory content
            category: identity, relationship, preference, or fact
            promoted_from: ID of regular memory if promoted

        Returns:
            New core memory ID, or None on failure
        """
        db = get_database()
        now = datetime.now()

        try:
            db.execute(
                """
                INSERT INTO core_memories
                (content, category, created_at, promoted_from_memory_id)
                VALUES (?, ?, ?, ?)
                """,
                (content, category, now.isoformat(), promoted_from)
            )

            result = db.execute(
                "SELECT id FROM core_memories ORDER BY id DESC LIMIT 1",
                fetch=True
            )

            memory_id = result[0]["id"] if result else None

            if memory_id:
                log_info(f"Added core memory [{category}]: {content[:50]}...", prefix="💎")

            return memory_id

        except Exception as e:
            log_error(f"Failed to add core memory: {e}")
            return None

    @db_retry()
    def remove(self, memory_id: int) -> bool:
        """Remove a core memory by ID."""
        db = get_database()

        try:
            db.execute(
                "DELETE FROM core_memories WHERE id = ?",
                (memory_id,)
            )
            log_info(f"Removed core memory {memory_id}", prefix="🗑️")
            return True
        except Exception as e:
            log_error(f"Failed to remove core memory: {e}")
            return False

    @db_retry()
    def get_by_category(self, category: str) -> List[CoreMemory]:
        """Get core memories by category."""
        db = get_database()
        result = db.execute(
            "SELECT * FROM core_memories WHERE category = ? ORDER BY created_at",
            (category,),
            fetch=True
        )

        return [self._row_to_memory(row) for row in result] if result else []

    def _row_to_memory(self, row) -> CoreMemory:
        """Convert database row to CoreMemory."""
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return CoreMemory(
            id=row["id"],
            content=row["content"],
            category=row["category"],
            created_at=created_at,
            promoted_from_memory_id=row["promoted_from_memory_id"]
        )


# Global instance
_core_memory_source: Optional[CoreMemorySource] = None


def get_core_memory_source() -> CoreMemorySource:
    """Get the global core memory source instance."""
    global _core_memory_source
    if _core_memory_source is None:
        _core_memory_source = CoreMemorySource()
    return _core_memory_source
