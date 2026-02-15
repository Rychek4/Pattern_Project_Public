#!/usr/bin/env python3
"""
Pattern Project - Database Reset Utility

Provides commands to reset specific database tables:
- memories: Delete episodic memories only (core memories are preserved)
- conversations: Delete all conversation history
- reprocess: Reset processing flags only (allows re-extraction without deleting memories)

Usage:
    python scripts/reset_db.py memories
    python scripts/reset_db.py conversations
    python scripts/reset_db.py reprocess
    python scripts/reset_db.py --all
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config import DATABASE_PATH
from core.database import Database


def confirm_action(action: str) -> bool:
    """Prompt user to confirm destructive action."""
    print(f"\n{'='*60}")
    print(f"WARNING: You are about to {action}")
    print(f"{'='*60}")
    response = input("\nType 'yes' to confirm: ").strip().lower()
    return response == "yes"


def clear_memories(db: Database) -> None:
    """Delete all episodic memories and reset processing flags for re-extraction.

    Note: This only clears the 'memories' table (episodic memories).
    Core memories are preserved - use 'core_memories' command to clear those.
    """
    print("\n[Memories] Clearing episodic memories...")

    with db.get_connection() as conn:
        # Get count before deletion
        cursor = conn.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]

        # Delete all episodic memories (NOT core memories)
        conn.execute("DELETE FROM memories")

        # Reset processing flags so conversations can be re-extracted
        cursor = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE processed_for_memory = TRUE"
        )
        processed_count = cursor.fetchone()[0]

        conn.execute("""
            UPDATE conversations
            SET processed_for_memory = FALSE, processed_at = NULL
        """)

    print(f"[Memories] Cleared {count} episodic memories (core memories preserved)")
    print(f"[Memories] Reset {processed_count} conversations for re-extraction")


def clear_conversations(db: Database) -> None:
    """Delete all conversations from the database."""
    print("\n[Conversations] Clearing all conversations...")

    with db.get_connection() as conn:
        # Get count before deletion
        cursor = conn.execute("SELECT COUNT(*) FROM conversations")
        count = cursor.fetchone()[0]

        # Delete all conversations
        conn.execute("DELETE FROM conversations")

        # Also clear sessions
        cursor = conn.execute("SELECT COUNT(*) FROM sessions")
        session_count = cursor.fetchone()[0]
        conn.execute("DELETE FROM sessions")

    print(f"[Conversations] Cleared {count} conversation turns and {session_count} sessions")


def reset_processing_flags(db: Database) -> None:
    """Reset processing flags only, allowing conversations to be re-extracted.

    This is useful for testing prompt changes without deleting existing memories.
    Conversations will be re-processed on next extraction trigger.
    """
    print("\n[Reprocess] Resetting processing flags...")

    with db.get_connection() as conn:
        # Count conversations that will be reset
        cursor = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE processed_for_memory = TRUE"
        )
        processed_count = cursor.fetchone()[0]

        if processed_count == 0:
            print("[Reprocess] No processed conversations to reset")
            return

        # Reset processing flags
        conn.execute("""
            UPDATE conversations
            SET processed_for_memory = FALSE, processed_at = NULL
        """)

    print(f"[Reprocess] Reset {processed_count} conversations for re-extraction")
    print("[Reprocess] Note: Existing memories are preserved. New extraction will add more memories.")


def main():
    parser = argparse.ArgumentParser(
        description="Reset specific database tables in Pattern Project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/reset_db.py memories        Delete episodic memories (preserves core memories)
  python scripts/reset_db.py conversations   Delete all conversations
  python scripts/reset_db.py reprocess       Reset processing flags only (for re-extraction)
  python scripts/reset_db.py --all           Reset everything (except core memories)
        """
    )

    parser.add_argument(
        "table",
        nargs="?",
        choices=["memories", "conversations", "reprocess"],
        help="The table to reset (or 'reprocess' to reset processing flags only)"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Reset all tables (memories, conversations)"
    )

    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.table and not args.all:
        parser.print_help()
        sys.exit(1)

    # Check database exists
    if not DATABASE_PATH.exists():
        print(f"Error: Database not found at {DATABASE_PATH}")
        print("Run the main application first to create the database.")
        sys.exit(1)

    # Initialize database connection
    db = Database(DATABASE_PATH)

    # Determine what to reset
    tables_to_reset = []
    if args.all:
        tables_to_reset = ["memories", "conversations"]
        action_desc = "RESET ALL TABLES (memories, conversations)"
    else:
        tables_to_reset = [args.table]
        action_desc = f"reset the '{args.table}' table"

    # Confirm action
    if not args.yes:
        if not confirm_action(action_desc):
            print("\nOperation cancelled.")
            sys.exit(0)

    print(f"\nDatabase: {DATABASE_PATH}")

    # Execute resets
    for table in tables_to_reset:
        if table == "memories":
            clear_memories(db)
        elif table == "conversations":
            clear_conversations(db)
        elif table == "reprocess":
            reset_processing_flags(db)

    print("\n" + "="*60)
    print("Reset complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
