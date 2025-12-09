#!/usr/bin/env python3
"""
Pattern Project - Database Sample Inspector

Usage:
    python db_sample.py                    # Sample all data (most recent 3 rows per table)
    python db_sample.py --session last     # Sample only the most recent session
    python db_sample.py --session today    # Sample only today's session(s)
    python db_sample.py --session 5        # Sample data from session ID 5
    python db_sample.py --rows 10          # Show 10 rows per table instead of 3
    python db_sample.py --table memories   # Show only the memories table
    python db_sample.py --stats            # Show database statistics only
"""

import sqlite3
import json
import argparse
from datetime import datetime, date
from pathlib import Path
from config import DATABASE_PATH


# All tables in the database with their descriptions
# Format: (table_name, description, timestamp_column, session_filter_column)
TABLES = [
    ("sessions", "Conversation sessions", "started_at", None),
    ("conversations", "Chat message history", "created_at", "session_id"),
    ("memories", "Extracted memories with embeddings", "created_at", "source_session_id"),
    ("core_memories", "Permanent foundational memories", "created_at", None),
    ("state", "Runtime state persistence", "updated_at", None),
    ("schema_version", "Database schema version tracking", "applied_at", None),
]


def get_connection():
    """Get a database connection."""
    if not DATABASE_PATH.exists():
        print(f"Database not found at: {DATABASE_PATH}")
        print("Run the application first to create the database.")
        return None

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def format_value(value, column_name: str, max_length: int = 60) -> str:
    """Format a value for display."""
    if value is None:
        return "[NULL]"

    # Handle embedding blobs - just show dimensions
    if column_name == "embedding" and isinstance(value, bytes):
        try:
            import numpy as np
            arr = np.frombuffer(value, dtype=np.float32)
            return f"[{len(arr)} dim embedding]"
        except Exception:
            return f"[{len(value)} bytes]"

    # Handle JSON fields
    if column_name in ("metadata", "source_conversation_ids", "value"):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass

    # Convert to string and truncate if needed
    str_value = str(value)
    if len(str_value) > max_length:
        return str_value[:max_length - 3] + "..."
    return str_value


def format_timestamp(ts_str: str) -> str:
    """Format a timestamp for display."""
    if not ts_str:
        return "[NULL]"
    try:
        # Handle various timestamp formats
        if "T" in ts_str:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts_str)


def print_table_header(table_name: str, description: str, count: int):
    """Print a table header."""
    print()
    print("=" * 80)
    print(f"TABLE: {table_name}")
    print(f"Description: {description}")
    print(f"Total rows: {count}")
    print("=" * 80)


def get_session_filter(session_arg: str, conn: sqlite3.Connection) -> list:
    """
    Get session IDs based on the session argument.

    Returns:
        List of session IDs to filter by, or empty list for no filter
    """
    if session_arg is None:
        return []

    cursor = conn.cursor()

    if session_arg == "last":
        cursor.execute("SELECT MAX(id) FROM sessions")
        result = cursor.fetchone()
        return [result[0]] if result[0] else []

    elif session_arg == "today":
        today = date.today().isoformat()
        cursor.execute(
            "SELECT id FROM sessions WHERE date(started_at) = ?",
            (today,)
        )
        return [row[0] for row in cursor.fetchall()]

    else:
        try:
            return [int(session_arg)]
        except ValueError:
            print(f"Invalid session argument: {session_arg}")
            return []


def sample_table(
    conn: sqlite3.Connection,
    table_name: str,
    description: str,
    timestamp_col: str,
    session_col: str,
    session_ids: list,
    num_rows: int
):
    """Sample and display rows from a table."""
    cursor = conn.cursor()

    # Get total count
    try:
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        total_count = cursor.fetchone()[0]
    except sqlite3.OperationalError as e:
        print(f"\nTable {table_name}: Error - {e}")
        return

    print_table_header(table_name, description, total_count)

    if total_count == 0:
        print("(empty table)")
        return

    # Build query with optional session filter
    where_clause = ""
    params = []

    if session_ids and session_col:
        placeholders = ",".join("?" * len(session_ids))
        where_clause = f"WHERE {session_col} IN ({placeholders})"
        params = session_ids

    # Get column names
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]

    # Query with ordering by timestamp if available
    order_clause = f"ORDER BY {timestamp_col} DESC" if timestamp_col else "ORDER BY rowid DESC"
    query = f"SELECT * FROM {table_name} {where_clause} {order_clause} LIMIT ?"
    params.append(num_rows)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    if not rows:
        if session_ids:
            print(f"(no rows for session(s): {session_ids})")
        else:
            print("(no rows)")
        return

    # Print rows
    for i, row in enumerate(rows):
        print(f"\n--- Row {i + 1} ---")
        for col in columns:
            value = row[col]
            formatted = format_value(value, col)

            # Special formatting for certain columns
            if col.endswith("_at") or col == "timestamp":
                formatted = format_timestamp(str(value)) if value else "[NULL]"

            # Multi-line display for content
            if col == "content" and value and len(str(value)) > 60:
                print(f"  {col}:")
                for line in str(value)[:500].split("\n"):
                    print(f"    {line}")
                if len(str(value)) > 500:
                    print(f"    ... ({len(str(value))} chars total)")
            else:
                print(f"  {col}: {formatted}")


def print_stats(conn: sqlite3.Connection):
    """Print database statistics."""
    cursor = conn.cursor()

    print()
    print("=" * 80)
    print("DATABASE STATISTICS")
    print("=" * 80)

    # File size
    db_size = DATABASE_PATH.stat().st_size
    print(f"\nDatabase file: {DATABASE_PATH}")
    print(f"File size: {db_size / 1024:.1f} KB")

    # Table counts
    print("\nTable row counts:")
    for table_name, description, _, _ in TABLES:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"  {table_name}: {count}")
        except sqlite3.OperationalError:
            print(f"  {table_name}: (table not found)")

    # Session summary
    print("\nSession summary:")
    cursor.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN ended_at IS NULL THEN 1 ELSE 0 END) as active,
            SUM(turn_count) as total_turns,
            AVG(duration_seconds) as avg_duration
        FROM sessions
    """)
    row = cursor.fetchone()
    if row and row[0] > 0:
        print(f"  Total sessions: {row[0]}")
        print(f"  Active sessions: {row[1]}")
        print(f"  Total turns: {row[2] or 0}")
        if row[3]:
            print(f"  Avg duration: {row[3]:.0f}s")

    # Memory summary
    print("\nMemory summary:")
    cursor.execute("""
        SELECT
            memory_type,
            COUNT(*) as count,
            AVG(importance) as avg_importance
        FROM memories
        GROUP BY memory_type
    """)
    rows = cursor.fetchall()
    if rows:
        for row in rows:
            mem_type = row[0] or "unknown"
            print(f"  {mem_type}: {row[1]} (avg importance: {row[2]:.2f})")
    else:
        print("  (no memories)")

    # Schema version
    cursor.execute("SELECT MAX(version) FROM schema_version")
    version = cursor.fetchone()[0]
    print(f"\nSchema version: {version}")


def main():
    parser = argparse.ArgumentParser(
        description="Sample and inspect Pattern Project database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--session", "-s",
        help="Filter by session: 'last', 'today', or session ID"
    )
    parser.add_argument(
        "--rows", "-r",
        type=int,
        default=3,
        help="Number of rows to show per table (default: 3)"
    )
    parser.add_argument(
        "--table", "-t",
        help="Show only a specific table"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show database statistics only"
    )

    args = parser.parse_args()

    # Connect to database
    conn = get_connection()
    if conn is None:
        return 1

    try:
        # Stats only mode
        if args.stats:
            print_stats(conn)
            return 0

        # Get session filter
        session_ids = get_session_filter(args.session, conn)
        if args.session and not session_ids:
            print(f"No sessions found for filter: {args.session}")
            return 1

        if session_ids:
            print(f"Filtering by session ID(s): {session_ids}")

        # Sample tables
        tables_to_show = TABLES
        if args.table:
            tables_to_show = [t for t in TABLES if t[0] == args.table]
            if not tables_to_show:
                print(f"Unknown table: {args.table}")
                print(f"Available tables: {', '.join(t[0] for t in TABLES)}")
                return 1

        for table_name, description, timestamp_col, session_col in tables_to_show:
            sample_table(
                conn,
                table_name,
                description,
                timestamp_col,
                session_col,
                session_ids,
                args.rows
            )

        # Always show stats at the end
        print_stats(conn)

        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    exit(main())
