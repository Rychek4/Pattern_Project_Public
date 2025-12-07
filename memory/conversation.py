"""
Pattern Project - Conversation Memory
CRUD operations for conversation storage with temporal tracking
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from core.database import get_database
from core.temporal import get_temporal_tracker
from concurrency.locks import get_lock_manager
from concurrency.db_retry import db_retry


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""
    id: int
    session_id: int
    role: str
    content: str
    input_type: str
    created_at: datetime
    time_since_last_turn: Optional[float]
    processed_for_memory: bool


class ConversationManager:
    """
    Manages conversation storage and retrieval.

    Thread-safe CRUD operations for conversation data
    with temporal context tracking.
    """

    def __init__(self):
        self._lock_manager = get_lock_manager()

    @db_retry()
    def add_turn(
        self,
        role: str,
        content: str,
        input_type: str = "text",
        session_id: Optional[int] = None
    ) -> int:
        """
        Add a conversation turn.

        Args:
            role: 'user', 'assistant', or 'system'
            content: The message content
            input_type: 'text', 'voice', or 'image'
            session_id: Session ID (uses current if None)

        Returns:
            The new turn's ID
        """
        with self._lock_manager.acquire("conversation"):
            db = get_database()
            tracker = get_temporal_tracker()

            # Get session ID
            if session_id is None:
                session_id = tracker.current_session_id
                if session_id is None:
                    # Auto-start session if needed
                    session_id = tracker.start_session()

            # Record timing
            time_since_last = tracker.record_turn()

            # Insert turn
            db.execute(
                """
                INSERT INTO conversations
                (session_id, role, content, input_type, time_since_last_turn_seconds)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, input_type, time_since_last)
            )

            # Get the new ID
            result = db.execute(
                "SELECT id FROM conversations ORDER BY id DESC LIMIT 1",
                fetch=True
            )

            return result[0]["id"]

    @db_retry()
    def get_turn(self, turn_id: int) -> Optional[ConversationTurn]:
        """Get a specific turn by ID."""
        with self._lock_manager.acquire("conversation"):
            db = get_database()
            result = db.execute(
                "SELECT * FROM conversations WHERE id = ?",
                (turn_id,),
                fetch=True
            )

            if result:
                row = result[0]
                return self._row_to_turn(row)
            return None

    @db_retry()
    def get_session_history(
        self,
        session_id: Optional[int] = None,
        limit: Optional[int] = None
    ) -> List[ConversationTurn]:
        """
        Get conversation history for a session.

        Args:
            session_id: Session ID (uses current if None)
            limit: Maximum turns to return (most recent)

        Returns:
            List of ConversationTurn objects
        """
        with self._lock_manager.acquire("conversation"):
            db = get_database()
            tracker = get_temporal_tracker()

            if session_id is None:
                session_id = tracker.current_session_id

            if session_id is None:
                return []

            query = """
                SELECT * FROM conversations
                WHERE session_id = ?
                ORDER BY created_at DESC
            """
            params = [session_id]

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            result = db.execute(query, tuple(params), fetch=True)

            # Reverse to chronological order
            turns = [self._row_to_turn(row) for row in result]
            turns.reverse()

            return turns

    @db_retry()
    def get_recent_history(
        self,
        limit: int = 20,
        session_id: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        Get recent conversation history formatted for LLM context.

        Args:
            limit: Maximum turns to return
            session_id: Session ID (uses current if None)

        Returns:
            List of {"role": ..., "content": ...} dicts
        """
        turns = self.get_session_history(session_id=session_id, limit=limit)
        return [
            {"role": turn.role, "content": turn.content}
            for turn in turns
            if turn.role in ("user", "assistant")
        ]

    @db_retry()
    def get_unprocessed_turns(self, limit: int = 100) -> List[ConversationTurn]:
        """Get turns that haven't been processed for memory extraction."""
        with self._lock_manager.acquire("conversation"):
            db = get_database()

            result = db.execute(
                """
                SELECT * FROM conversations
                WHERE processed_for_memory = FALSE
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
                fetch=True
            )

            return [self._row_to_turn(row) for row in result]

    @db_retry()
    def mark_processed(self, turn_ids: List[int]) -> None:
        """Mark turns as processed for memory extraction."""
        if not turn_ids:
            return

        with self._lock_manager.acquire("conversation"):
            db = get_database()
            now = datetime.now().isoformat()

            placeholders = ",".join("?" * len(turn_ids))
            db.execute(
                f"""
                UPDATE conversations
                SET processed_for_memory = TRUE, processed_at = ?
                WHERE id IN ({placeholders})
                """,
                (now, *turn_ids)
            )

    @db_retry()
    def get_unprocessed_count(self) -> int:
        """Get count of unprocessed turns."""
        db = get_database()
        result = db.execute(
            "SELECT COUNT(*) as count FROM conversations WHERE processed_for_memory = FALSE",
            fetch=True
        )
        return result[0]["count"] if result else 0

    @db_retry()
    def get_session_summary(self, session_id: int) -> Dict[str, Any]:
        """Get summary statistics for a session."""
        with self._lock_manager.acquire("conversation"):
            db = get_database()

            result = db.execute(
                """
                SELECT
                    COUNT(*) as turn_count,
                    MIN(created_at) as first_turn,
                    MAX(created_at) as last_turn,
                    SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) as user_turns,
                    SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) as assistant_turns
                FROM conversations
                WHERE session_id = ?
                """,
                (session_id,),
                fetch=True
            )

            if result:
                row = result[0]
                return {
                    "session_id": session_id,
                    "turn_count": row["turn_count"],
                    "user_turns": row["user_turns"],
                    "assistant_turns": row["assistant_turns"],
                    "first_turn": row["first_turn"],
                    "last_turn": row["last_turn"]
                }

            return {}

    def _row_to_turn(self, row) -> ConversationTurn:
        """Convert a database row to ConversationTurn."""
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return ConversationTurn(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            input_type=row["input_type"],
            created_at=created_at,
            time_since_last_turn=row["time_since_last_turn_seconds"],
            processed_for_memory=bool(row["processed_for_memory"])
        )


# Global conversation manager instance
_conversation_manager: Optional[ConversationManager] = None


def get_conversation_manager() -> ConversationManager:
    """Get the global conversation manager instance."""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
    return _conversation_manager


def init_conversation_manager() -> ConversationManager:
    """Initialize the global conversation manager."""
    global _conversation_manager
    _conversation_manager = ConversationManager()
    return _conversation_manager
