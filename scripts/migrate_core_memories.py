#!/usr/bin/env python3
"""
Pattern Project - Core Memories Migration Script
Migrates CORE_MEMORIES.md content to the database as a narrative entry.

Usage:
    python scripts/migrate_core_memories.py           # Insert new narrative
    python scripts/migrate_core_memories.py --update  # Update existing narrative

This script:
1. Reads the CORE_MEMORIES.md file
2. Checks if a narrative entry already exists
3. Inserts or updates the content as a single 'narrative' category entry
4. Preserves the original file as a historical artifact
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import DATABASE_PATH, DB_BUSY_TIMEOUT_MS, LOGS_DIR
from core.database import init_database, get_database
from core.logger import log_info, log_success, log_error, log_warning, setup_logging

# Path to the core memories markdown file
CORE_MEMORIES_FILE = PROJECT_ROOT / "CORE_MEMORIES.md"


def check_existing_narrative() -> bool:
    """Check if a narrative entry already exists in the database."""
    db = get_database()
    result = db.execute(
        "SELECT COUNT(*) as count FROM core_memories WHERE category = 'narrative'",
        fetch=True
    )
    return result[0]["count"] > 0 if result else False


def read_markdown_content() -> str:
    """Read the CORE_MEMORIES.md file content."""
    if not CORE_MEMORIES_FILE.exists():
        raise FileNotFoundError(f"Core memories file not found: {CORE_MEMORIES_FILE}")

    with open(CORE_MEMORIES_FILE, "r", encoding="utf-8") as f:
        return f.read()


def insert_narrative(content: str) -> int:
    """Insert the narrative content into the database."""
    db = get_database()

    db.execute(
        """
        INSERT INTO core_memories (content, category)
        VALUES (?, 'narrative')
        """,
        (content,)
    )

    # Get the inserted ID
    result = db.execute(
        "SELECT id FROM core_memories WHERE category = 'narrative' ORDER BY id DESC LIMIT 1",
        fetch=True
    )

    return result[0]["id"] if result else 0


def update_narrative(content: str) -> int:
    """Update the existing narrative content in the database."""
    db = get_database()

    # Get the existing narrative ID
    result = db.execute(
        "SELECT id FROM core_memories WHERE category = 'narrative' ORDER BY id ASC LIMIT 1",
        fetch=True
    )

    if not result:
        return 0

    memory_id = result[0]["id"]

    db.execute(
        """
        UPDATE core_memories
        SET content = ?
        WHERE id = ?
        """,
        (content, memory_id)
    )

    return memory_id


def main():
    """Run the migration."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Migrate CORE_MEMORIES.md to the database"
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update existing narrative instead of inserting new"
    )
    args = parser.parse_args()

    # Setup logging
    setup_logging(LOGS_DIR / "migration.log")

    log_info("Starting Core Memories migration...")

    # Initialize database (this will apply any pending migrations including v3)
    log_info("Initializing database...")
    init_database(DATABASE_PATH, DB_BUSY_TIMEOUT_MS)

    # Check if narrative already exists
    narrative_exists = check_existing_narrative()

    if narrative_exists and not args.update:
        log_warning("A narrative entry already exists in the database.")
        log_warning("Use --update flag to update the existing narrative.")
        print("\nExisting narrative found. Migration skipped.")
        print("To update the existing narrative, run:")
        print("  python scripts/migrate_core_memories.py --update")
        return 1

    if args.update and not narrative_exists:
        log_warning("No existing narrative found. Will insert new entry instead.")

    # Read the markdown content
    try:
        log_info(f"Reading {CORE_MEMORIES_FILE}...")
        content = read_markdown_content()
        log_success(f"Read {len(content)} characters from CORE_MEMORIES.md")
    except FileNotFoundError as e:
        log_error(str(e))
        print(f"\nError: {e}")
        return 1

    # Insert or update database
    if narrative_exists and args.update:
        log_info("Updating existing narrative in database...")
        memory_id = update_narrative(content)
        action = "updated"
    else:
        log_info("Inserting narrative into database...")
        memory_id = insert_narrative(content)
        action = "inserted"

    if memory_id:
        log_success(f"Successfully {action} narrative as core memory #{memory_id}")
        print(f"\nMigration successful!")
        print(f"  - Narrative {action} with ID: {memory_id}")
        print(f"  - Content length: {len(content)} characters")
        print(f"  - Original file preserved at: {CORE_MEMORIES_FILE}")
        return 0
    else:
        log_error(f"Failed to {action} narrative")
        print(f"\nError: Failed to {action} narrative in database")
        return 1


if __name__ == "__main__":
    sys.exit(main())
