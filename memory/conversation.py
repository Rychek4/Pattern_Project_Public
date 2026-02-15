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

        # Prefixes that AI may echo from prompt metadata but shouldn't persist
        # These become stale and conflict with real semantic timestamps
        self._temporal_prefixes_to_strip = [
            "(Just now) ",
        ]

    def _sanitize_assistant_content(self, content: str) -> str:
        """
        Remove AI-generated temporal markers that shouldn't persist.

        The AI sometimes echoes prompt metadata like "(Just now)" at the start
        of responses. These become stale and create contradictory timestamps
        when combined with the real semantic timestamps added at retrieval time.

        Args:
            content: The assistant's response content

        Returns:
            Sanitized content with temporal prefixes removed
        """
        for prefix in self._temporal_prefixes_to_strip:
            if content.startswith(prefix):
                from core.logger import log_info
                log_info(
                    f"Sanitized '{prefix.strip()}' prefix from assistant response",
                    prefix="🧹"
                )
                return content[len(prefix):]
        return content

    @db_retry()
    def add_turn(
        self,
        role: str,
        content: str,
        input_type: str = "text",
        session_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Add a conversation turn.

        After storing the turn, checks if the memory extraction threshold
        has been reached and triggers extraction asynchronously if so.

        Args:
            role: 'user', 'assistant', or 'system'
            content: The message content
            input_type: 'text', 'voice', or 'image'
            session_id: Session ID (uses current if None)

        Returns:
            The new turn's ID, or None if the turn was skipped (e.g., empty assistant message)
        """
        # Validate content - reject empty assistant messages
        # Empty assistant messages cause API errors: "messages must have non-empty content"
        # This can happen when AI responds with only tool calls and no text
        if role == "assistant" and (content is None or content.strip() == ""):
            from core.logger import log_warning
            log_warning(
                "Skipping empty assistant message - would cause API errors in future calls",
                prefix="⚠️"
            )
            return None

        # Sanitize assistant responses to remove echoed temporal markers
        if role == "assistant":
            content = self._sanitize_assistant_content(content)

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

            turn_id = result[0]["id"]

        # Check if memory extraction threshold reached (outside the lock)
        # Import here to avoid circular imports
        from memory.extractor import get_memory_extractor
        from core.logger import log_info
        import time

        log_info(f"Turn {turn_id} stored, checking for memory extraction...", prefix="📜")
        extraction_start = time.time()

        extractor = get_memory_extractor()
        extractor.check_and_extract()

        extraction_duration = (time.time() - extraction_start) * 1000
        if extraction_duration > 100:  # Only log if it took more than 100ms
            log_info(f"Memory extraction check took {extraction_duration:.0f}ms", prefix="📜")

        return turn_id

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

        Filters out empty messages to prevent API errors. The Anthropic API
        rejects requests where non-final messages have empty content.

        Args:
            limit: Maximum turns to return
            session_id: Session ID (uses current if None)

        Returns:
            List of {"role": ..., "content": ...} dicts with non-empty content
        """
        turns = self.get_session_history(session_id=session_id, limit=limit)
        return [
            {"role": turn.role, "content": turn.content}
            for turn in turns
            if turn.role in ("user", "assistant") and turn.content and turn.content.strip()
        ]

    def get_api_messages(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get conversation history formatted for LLM API with semantic timestamps.

        This is the PRIMARY method for getting conversation context for API calls.
        It replaces the old dual-system (recent_conversation + raw messages).

        KEY BEHAVIORS:
        - Spans all sessions (cross-session continuity)
        - Excludes processed turns (coordinates with memory extraction)
        - Adds timestamps at format-time (NOT stored in database)
        - Loads ALL unprocessed turns (context grows naturally from 30→40)

        The timestamps are computed from the stored created_at field, ensuring
        the database remains clean and memory extraction receives raw content.

        DYNAMIC CONTEXT WINDOW:
        The context window grows naturally as turns accumulate. When
        unprocessed turns reach CONTEXT_OVERFLOW_TRIGGER (40), extraction
        fires and consolidates the oldest turns into long-term memory,
        snapping the window back to CONTEXT_WINDOW_SIZE (30). The agent
        experiences this growth as increasing context density before
        consolidation relieves it.

        A safety cap of CONTEXT_OVERFLOW_TRIGGER + CONTEXT_EXTRACTION_BATCH
        prevents pathological growth if extraction stalls.

        Args:
            limit: Maximum turns to return. If None, loads all unprocessed
                   turns up to the safety cap.

        Returns:
            List of {"role": ..., "content": "(timestamp) message"} dicts
        """
        from core.temporal import format_fuzzy_relative_time
        from core.logger import log_info
        from config import CONTEXT_WINDOW_SIZE, CONTEXT_OVERFLOW_TRIGGER, CONTEXT_EXTRACTION_BATCH

        # DIAGNOSTIC: Log entry
        log_info("=== get_api_messages START ===", prefix="📜")

        # Determine the limit to use
        if limit is None:
            # Load ALL unprocessed turns - let the context window grow naturally
            # from CONTEXT_WINDOW_SIZE (30) toward CONTEXT_OVERFLOW_TRIGGER (40).
            # Extraction fires at the trigger and snaps back to window size.
            # Safety cap prevents pathological growth if extraction stalls.
            actual_count = self.get_unprocessed_count()
            safety_cap = CONTEXT_OVERFLOW_TRIGGER + CONTEXT_EXTRACTION_BATCH
            limit = min(actual_count, safety_cap)
            log_info(f"Unprocessed turns: {actual_count}, safety cap: {safety_cap}, limit: {limit}", prefix="📜")
        else:
            log_info(f"Using provided limit: {limit}", prefix="📜")

        # Use get_context_window for cross-session, excludes-processed behavior
        log_info(f"Fetching context window (limit={limit})...", prefix="📜")
        turns = self.get_context_window(limit=limit)
        log_info(f"Got {len(turns)} raw turns from context window", prefix="📜")

        # Format and filter
        result = [
            {
                "role": turn.role,
                "content": f"({format_fuzzy_relative_time(turn.created_at)}) {turn.content}"
            }
            for turn in turns
            if turn.role in ("user", "assistant") and turn.content and turn.content.strip()
        ]

        log_info(f"Formatted {len(result)} messages for API (after filtering)", prefix="📜")

        # Log role distribution
        user_count = sum(1 for m in result if m["role"] == "user")
        assistant_count = sum(1 for m in result if m["role"] == "assistant")
        log_info(f"Role distribution: {user_count} user, {assistant_count} assistant", prefix="📜")

        log_info("=== get_api_messages END ===", prefix="📜")
        return result

    @db_retry()
    def get_context_window(
        self,
        limit: int = 30,
        exclude_processed: bool = True
    ) -> List[ConversationTurn]:
        """
        Get turns for the active context window.

        This method supports the windowed extraction system where:
        - Context spans across sessions (for AI continuity)
        - Processed turns are excluded (coordinated with extraction)
        - Turns flow: Context → Extraction → Memory → Gone from context

        Unlike get_session_history(), this method is NOT session-scoped.
        It returns the most recent unprocessed turns regardless of which
        session they belong to, providing continuity across sessions.

        Args:
            limit: Maximum turns to return (default: CONTEXT_WINDOW_SIZE)
            exclude_processed: If True, exclude already-extracted turns

        Returns:
            List of ConversationTurn in chronological order (oldest first)
        """
        with self._lock_manager.acquire("conversation"):
            db = get_database()

            if exclude_processed:
                # Get most recent UNPROCESSED turns (spans all sessions)
                result = db.execute(
                    """
                    SELECT * FROM conversations
                    WHERE processed_for_memory = FALSE
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                    fetch=True
                )
            else:
                # Get most recent turns regardless of processed status
                result = db.execute(
                    """
                    SELECT * FROM conversations
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                    fetch=True
                )

            # Reverse to chronological order (oldest first)
            turns = [self._row_to_turn(row) for row in result]
            turns.reverse()

            return turns

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

    @db_retry()
    def cleanup_empty_messages(self) -> int:
        """
        Remove empty assistant messages from the database.

        Empty assistant messages can cause API errors when retrieved for context.
        This method cleans up any historical empty messages that may have been
        saved before validation was added.

        Returns:
            Number of messages deleted
        """
        from core.logger import log_info, log_warning

        with self._lock_manager.acquire("conversation"):
            db = get_database()

            # First, count how many empty messages exist
            count_result = db.execute(
                """
                SELECT COUNT(*) as count FROM conversations
                WHERE role = 'assistant'
                AND (content IS NULL OR TRIM(content) = '')
                """,
                fetch=True
            )
            count = count_result[0]["count"] if count_result else 0

            if count == 0:
                log_info("No empty assistant messages found", prefix="✅")
                return 0

            # Delete empty assistant messages
            db.execute(
                """
                DELETE FROM conversations
                WHERE role = 'assistant'
                AND (content IS NULL OR TRIM(content) = '')
                """
            )

            log_warning(f"Cleaned up {count} empty assistant message(s)", prefix="🧹")
            return count

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
