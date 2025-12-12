#!/usr/bin/env python3
"""
Wipe memories from before a specified date.
Only affects the memories table - leaves core_memories and other tables untouched.
"""

import sqlite3
from pathlib import Path

# Default database path
project_root = Path(__file__).parent.parent
DEFAULT_DB_PATH = project_root / "data" / "pattern.db"


def wipe_old_memories(cutoff_date: str, db_path: Path, dry_run: bool = True):
    """
    Delete memories created before the cutoff date.

    Args:
        cutoff_date: ISO format date string (YYYY-MM-DD)
        db_path: Path to the SQLite database
        dry_run: If True, only show what would be deleted
    """
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Count memories to be deleted
    cursor.execute("""
        SELECT COUNT(*) FROM memories
        WHERE date(created_at) < date(?)
    """, (cutoff_date,))
    count = cursor.fetchone()[0]

    # Count total memories
    cursor.execute("SELECT COUNT(*) FROM memories")
    total = cursor.fetchone()[0]

    # Show some samples of what will be deleted
    cursor.execute("""
        SELECT id, substr(content, 1, 80), created_at
        FROM memories
        WHERE date(created_at) < date(?)
        ORDER BY created_at DESC
        LIMIT 5
    """, (cutoff_date,))
    samples = cursor.fetchall()

    print(f"\n{'='*60}")
    print(f"Memory Wipe - Cutoff Date: {cutoff_date}")
    print(f"{'='*60}")
    print(f"Memories to delete: {count}")
    print(f"Memories to keep:   {total - count}")
    print(f"Total memories:     {total}")

    if samples:
        print(f"\nSample memories to be deleted:")
        for id_, content, created in samples:
            print(f"  [{created}] {content}...")

    if dry_run:
        print(f"\n*** DRY RUN - No changes made ***")
        print(f"Run with --execute to actually delete")
    else:
        confirm = input(f"\nDelete {count} memories? (type 'yes' to confirm): ")
        if confirm.lower() == 'yes':
            cursor.execute("""
                DELETE FROM memories
                WHERE date(created_at) < date(?)
            """, (cutoff_date,))
            conn.commit()
            print(f"\nDeleted {cursor.rowcount} memories.")
        else:
            print("\nAborted.")

    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Wipe memories before a cutoff date")
    parser.add_argument(
        "--cutoff",
        default="2025-12-11",
        help="Delete memories before this date (YYYY-MM-DD). Default: 2025-12-11"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to database file. Default: {DEFAULT_DB_PATH}"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the deletion (default is dry-run)"
    )

    args = parser.parse_args()

    wipe_old_memories(args.cutoff, args.db, dry_run=not args.execute)
