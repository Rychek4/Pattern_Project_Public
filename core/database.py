"""
Pattern Project - Database Module
SQLite with WAL mode, schema management, and connection handling
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, List, Tuple
from contextlib import contextmanager

from core.logger import log_info, log_success, log_error, log_config, log_section

# Schema version for migrations
SCHEMA_VERSION = 1

# SQL schema definition
SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions track distinct conversation periods
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    turn_count INTEGER DEFAULT 0,
    idle_time_seconds REAL DEFAULT 0,
    metadata JSON
);

-- Raw conversation turns with temporal context
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    input_type TEXT DEFAULT 'text' CHECK (input_type IN ('text', 'voice', 'image')),

    -- Temporal fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_since_last_turn_seconds REAL,

    -- Processing state
    processed_for_memory BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP
);

-- Extracted memories with embeddings and temporal tracking
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,

    -- Source tracking
    source_conversation_ids JSON,
    source_session_id INTEGER REFERENCES sessions(id),

    -- Temporal fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    source_timestamp TIMESTAMP,
    temporal_relevance TEXT DEFAULT 'recent' CHECK (temporal_relevance IN ('permanent', 'recent', 'dated')),

    -- Scoring
    importance REAL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    memory_type TEXT CHECK (memory_type IN ('fact', 'preference', 'event', 'reflection', 'observation'))
);

-- Runtime state persistence
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value JSON,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_unprocessed ON conversations(processed_for_memory) WHERE processed_for_memory = FALSE;
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_recency ON memories(last_accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_source_time ON memories(source_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(ended_at) WHERE ended_at IS NULL;
"""


class Database:
    """SQLite database manager with WAL mode and thread-safe connections."""

    def __init__(
        self,
        db_path: Path,
        busy_timeout_ms: int = 10000,
    ):
        """
        Initialize the database.

        Args:
            db_path: Path to the SQLite database file
            busy_timeout_ms: Timeout for busy/locked database
        """
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms
        self._initialized = False

    def initialize(self) -> bool:
        """
        Initialize the database: create file, set WAL mode, apply schema.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure data directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            log_section("Initializing database", "📁")
            log_config("Path", str(self.db_path), indent=1)

            # Create connection and configure
            with self.get_connection() as conn:
                # Enable WAL mode for better concurrency
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")

                # Check current schema version
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                )
                if cursor.fetchone() is None:
                    # Fresh database, apply full schema
                    conn.executescript(SCHEMA_SQL)
                    conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,)
                    )
                    log_config("Schema", f"Created (v{SCHEMA_VERSION})", indent=1)
                else:
                    # Check for migrations
                    cursor = conn.execute(
                        "SELECT MAX(version) FROM schema_version"
                    )
                    current_version = cursor.fetchone()[0] or 0
                    if current_version < SCHEMA_VERSION:
                        self._apply_migrations(conn, current_version)
                    log_config("Schema", f"Version {current_version}", indent=1)

                # Verify WAL mode
                cursor = conn.execute("PRAGMA journal_mode")
                mode = cursor.fetchone()[0]
                log_config("Mode", f"{mode.upper()} (Write-Ahead Logging)", indent=1)

            log_success("Database ready")
            self._initialized = True
            return True

        except Exception as e:
            log_error(f"Database initialization failed: {e}")
            return False

    def _apply_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """Apply schema migrations from from_version to SCHEMA_VERSION."""
        # Add migration logic here as schema evolves
        # For now, just update version
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,)
        )
        log_config("Migration", f"v{from_version} → v{SCHEMA_VERSION}", indent=1)

    @contextmanager
    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection with proper configuration.

        Yields:
            Configured SQLite connection
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.busy_timeout_ms / 1000,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(
        self,
        sql: str,
        params: Tuple = (),
        fetch: bool = False
    ) -> Optional[List[sqlite3.Row]]:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement
            params: Parameters for the statement
            fetch: Whether to fetch and return results

        Returns:
            List of rows if fetch=True, None otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            if fetch:
                return cursor.fetchall()
            return None

    def execute_many(self, sql: str, params_list: List[Tuple]) -> None:
        """Execute a SQL statement with multiple parameter sets."""
        with self.get_connection() as conn:
            conn.executemany(sql, params_list)

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get a value from the state table."""
        result = self.execute(
            "SELECT value FROM state WHERE key = ?",
            (key,),
            fetch=True
        )
        if result:
            return json.loads(result[0]["value"])
        return default

    def set_state(self, key: str, value: Any) -> None:
        """Set a value in the state table."""
        self.execute(
            """
            INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, json.dumps(value), datetime.now().isoformat(),
             json.dumps(value), datetime.now().isoformat())
        )

    def get_stats(self) -> dict:
        """Get database statistics."""
        stats = {}

        with self.get_connection() as conn:
            # Session count
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            stats["total_sessions"] = cursor.fetchone()[0]

            # Active session
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL"
            )
            stats["active_sessions"] = cursor.fetchone()[0]

            # Conversation count
            cursor = conn.execute("SELECT COUNT(*) FROM conversations")
            stats["total_conversations"] = cursor.fetchone()[0]

            # Memory count
            cursor = conn.execute("SELECT COUNT(*) FROM memories")
            stats["total_memories"] = cursor.fetchone()[0]

            # Unprocessed conversations
            cursor = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE processed_for_memory = FALSE"
            )
            stats["unprocessed_conversations"] = cursor.fetchone()[0]

        return stats


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get the global database instance."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db


def init_database(db_path: Path, busy_timeout_ms: int = 10000) -> Database:
    """Initialize the global database instance."""
    global _db
    _db = Database(db_path, busy_timeout_ms)
    _db.initialize()
    return _db
