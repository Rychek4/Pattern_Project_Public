#!/usr/bin/env python3
"""
Pattern Project - Database Reset Utility

Provides commands to reset specific database tables:
- relationships: Reset relationship state to defaults (affinity=50, trust=50)
- memories: Delete all memories from the vector store
- conversations: Delete all conversation history

Usage:
    python scripts/reset_db.py relationships
    python scripts/reset_db.py memories
    python scripts/reset_db.py conversations
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


def reset_relationships(db: Database) -> None:
    """Reset relationships table to default values."""
    print("\n[Relationships] Resetting to defaults...")

    with db.get_connection() as conn:
        # Delete existing relationship
        conn.execute("DELETE FROM relationships")

        # Insert fresh relationship with new defaults
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO relationships (id, affinity, trust, interaction_count,
                                       first_interaction, last_interaction, updated_at)
            VALUES (1, 50, 50, 0, ?, ?, ?)
            """,
            (now, now, now)
        )

    print("[Relationships] Reset complete:")
    print("  - Affinity: 50 (neutral)")
    print("  - Trust: 50 (neutral)")
    print("  - Interaction count: 0")


def clear_memories(db: Database) -> None:
    """Delete all memories from the database."""
    print("\n[Memories] Clearing all memories...")

    with db.get_connection() as conn:
        # Get count before deletion
        cursor = conn.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]

        # Delete all memories
        conn.execute("DELETE FROM memories")

        # Also clear core memories
        cursor = conn.execute("SELECT COUNT(*) FROM core_memories")
        core_count = cursor.fetchone()[0]
        conn.execute("DELETE FROM core_memories")

    print(f"[Memories] Cleared {count} memories and {core_count} core memories")


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


def main():
    parser = argparse.ArgumentParser(
        description="Reset specific database tables in Pattern Project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/reset_db.py relationships   Reset relationship state
  python scripts/reset_db.py memories        Delete all memories
  python scripts/reset_db.py conversations   Delete all conversations
  python scripts/reset_db.py --all           Reset everything
        """
    )

    parser.add_argument(
        "table",
        nargs="?",
        choices=["relationships", "memories", "conversations"],
        help="The table to reset"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Reset all tables (relationships, memories, conversations)"
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
        tables_to_reset = ["relationships", "memories", "conversations"]
        action_desc = "RESET ALL TABLES (relationships, memories, conversations)"
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
        if table == "relationships":
            reset_relationships(db)
        elif table == "memories":
            clear_memories(db)
        elif table == "conversations":
            clear_conversations(db)

    print("\n" + "="*60)
    print("Reset complete!")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
