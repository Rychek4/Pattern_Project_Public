"""
Pattern Project - Relationship Source
Affinity and trust tracking with emergent dynamics
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.database import get_database
from concurrency.db_retry import db_retry
from core.logger import log_info


# Clamp bounds for affinity and trust (0-100 integer scale)
AFFINITY_MIN = 0
AFFINITY_MAX = 100
TRUST_MIN = 0
TRUST_MAX = 100

# Default starting values (neutral at 50)
DEFAULT_AFFINITY = 50  # Neutral
DEFAULT_TRUST = 50     # Neutral


@dataclass
class RelationshipState:
    """Current state of the relationship."""
    affinity: int        # 0 (distant) to 100 (close)
    trust: int           # 0 (none) to 100 (complete)
    interaction_count: int
    first_interaction: Optional[datetime]
    last_interaction: Optional[datetime]
    updated_at: datetime


class RelationshipSource(ContextSource):
    """
    Provides relationship context for prompt injection.

    Tracks:
    - Affinity: How close the relationship is (0 to 100)
    - Trust: How much the AI trusts/is trusted (0 to 100)

    Both start at 50 (neutral) and adjust based on conversation
    analysis by the local LLM. Maximum change per analysis is ±2.
    """

    @property
    def source_name(self) -> str:
        return "relationship"

    @property
    def priority(self) -> int:
        return SourcePriority.RELATIONSHIP

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get relationship context for prompt injection."""
        state = self.get_state()

        if state is None:
            # Initialize relationship on first interaction
            state = self._initialize_relationship()

        # Format relationship context
        affinity_desc = self._describe_affinity(state.affinity)
        trust_desc = self._describe_trust(state.trust)

        lines = ["<relationship_context>"]
        lines.append(f"  Affinity: {affinity_desc} ({state.affinity}/100)")
        lines.append(f"  Trust: {trust_desc} ({state.trust}/100)")

        if state.interaction_count > 0:
            lines.append(f"  Interactions: {state.interaction_count}")

        if state.first_interaction:
            days_known = (datetime.now() - state.first_interaction).days
            if days_known > 0:
                lines.append(f"  Known for: {days_known} days")

        lines.append("</relationship_context>")

        # Store state in session context for other sources
        session_context["relationship_state"] = state

        return ContextBlock(
            source_name=self.source_name,
            content="\n".join(lines),
            priority=self.priority,
            include_always=True,
            metadata={
                "affinity": state.affinity,
                "trust": state.trust,
                "interaction_count": state.interaction_count
            }
        )

    @db_retry()
    def get_state(self) -> Optional[RelationshipState]:
        """Get current relationship state from database."""
        db = get_database()
        result = db.execute(
            "SELECT * FROM relationships WHERE id = 1",
            fetch=True
        )

        if not result:
            return None

        row = result[0]
        return self._row_to_state(row)

    @db_retry()
    def update(
        self,
        affinity_delta: int = 0,
        trust_delta: int = 0
    ) -> RelationshipState:
        """
        Update relationship values with clamping.

        Args:
            affinity_delta: Change to affinity (clamped to ±2)
            trust_delta: Change to trust (clamped to ±2)

        Returns:
            Updated RelationshipState
        """
        db = get_database()
        now = datetime.now()

        # Get current state
        state = self.get_state()

        if state is None:
            state = self._initialize_relationship()

        # Calculate new values with clamping
        new_affinity = max(AFFINITY_MIN, min(AFFINITY_MAX,
            state.affinity + affinity_delta
        ))
        new_trust = max(TRUST_MIN, min(TRUST_MAX,
            state.trust + trust_delta
        ))

        # Update database
        db.execute(
            """
            UPDATE relationships
            SET affinity = ?,
                trust = ?,
                interaction_count = interaction_count + 1,
                last_interaction = ?,
                updated_at = ?
            WHERE id = 1
            """,
            (new_affinity, new_trust, now.isoformat(), now.isoformat())
        )

        log_info(
            f"Relationship updated: affinity {affinity_delta:+d} → {new_affinity}, "
            f"trust {trust_delta:+d} → {new_trust}",
            prefix="💕"
        )

        return RelationshipState(
            affinity=new_affinity,
            trust=new_trust,
            interaction_count=state.interaction_count + 1,
            first_interaction=state.first_interaction,
            last_interaction=now,
            updated_at=now
        )

    @db_retry()
    def _initialize_relationship(self) -> RelationshipState:
        """Create initial relationship record."""
        db = get_database()
        now = datetime.now()

        # Insert or update (upsert pattern)
        db.execute(
            """
            INSERT INTO relationships (id, affinity, trust, interaction_count,
                                       first_interaction, last_interaction, updated_at)
            VALUES (1, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at = ?
            """,
            (DEFAULT_AFFINITY, DEFAULT_TRUST, now.isoformat(),
             now.isoformat(), now.isoformat(), now.isoformat())
        )

        log_info("Relationship initialized", prefix="🌱")

        return RelationshipState(
            affinity=DEFAULT_AFFINITY,
            trust=DEFAULT_TRUST,
            interaction_count=0,
            first_interaction=now,
            last_interaction=now,
            updated_at=now
        )

    def _describe_affinity(self, affinity: int) -> str:
        """Convert affinity value (0-100) to description."""
        if affinity >= 90:
            return "very close"
        elif affinity >= 75:
            return "friendly"
        elif affinity >= 60:
            return "warm"
        elif affinity >= 40:
            return "neutral"
        elif affinity >= 25:
            return "cool"
        elif affinity >= 10:
            return "distant"
        else:
            return "cold"

    def _describe_trust(self, trust: int) -> str:
        """Convert trust value (0-100) to description."""
        if trust >= 90:
            return "complete"
        elif trust >= 70:
            return "high"
        elif trust >= 50:
            return "moderate"
        elif trust >= 30:
            return "cautious"
        elif trust >= 10:
            return "low"
        else:
            return "minimal"

    def _row_to_state(self, row) -> RelationshipState:
        """Convert database row to RelationshipState."""
        first_interaction = row["first_interaction"]
        if isinstance(first_interaction, str):
            first_interaction = datetime.fromisoformat(first_interaction)

        last_interaction = row["last_interaction"]
        if isinstance(last_interaction, str):
            last_interaction = datetime.fromisoformat(last_interaction)

        updated_at = row["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)

        return RelationshipState(
            affinity=row["affinity"],
            trust=row["trust"],
            interaction_count=row["interaction_count"],
            first_interaction=first_interaction,
            last_interaction=last_interaction,
            updated_at=updated_at
        )


# Global instance
_relationship_source: Optional[RelationshipSource] = None


def get_relationship_source() -> RelationshipSource:
    """Get the global relationship source instance."""
    global _relationship_source
    if _relationship_source is None:
        _relationship_source = RelationshipSource()
    return _relationship_source
