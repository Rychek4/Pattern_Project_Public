#!/usr/bin/env python3
"""
Pattern Project - Core Memory Audit & Cleanup Script
Lists all core memories and optionally removes non-original additions.

Usage:
    python scripts/audit_core_memories.py                # View all core memories
    python scripts/audit_core_memories.py --remove ID    # Remove a specific core memory by ID
    python scripts/audit_core_memories.py --remove-all-additions  # Remove all non-original memories
    python scripts/audit_core_memories.py --dry-run --remove-all-additions  # Preview removals

The original narrative (migrated from CORE_MEMORIES.md) is identified as the
earliest 'narrative' category entry. All other entries are considered additions.
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import DATABASE_PATH, DB_BUSY_TIMEOUT_MS, LOGS_DIR
from core.database import init_database, get_database
from core.logger import setup_logging

# Maximum content preview length for display
PREVIEW_LENGTH = 120


def get_all_core_memories() -> list:
    """Fetch all core memories from the database."""
    db = get_database()
    result = db.execute(
        "SELECT * FROM core_memories ORDER BY id ASC",
        fetch=True
    )
    return result if result else []


def get_original_narrative_id() -> int | None:
    """
    Identify the original narrative entry (lowest ID with category='narrative').
    This is the one migrated from CORE_MEMORIES.md.
    """
    db = get_database()
    result = db.execute(
        "SELECT id FROM core_memories WHERE category = 'narrative' ORDER BY id ASC LIMIT 1",
        fetch=True
    )
    return result[0]["id"] if result else None


def display_memories(memories: list, original_narrative_id: int | None):
    """Display all core memories in a readable format."""
    if not memories:
        print("\nNo core memories found in the database.")
        return

    print(f"\n{'='*80}")
    print(f"  CORE MEMORY AUDIT — {len(memories)} total entries")
    print(f"{'='*80}\n")

    originals = []
    additions = []

    for mem in memories:
        is_original = (mem["id"] == original_narrative_id)
        label = "ORIGINAL" if is_original else "ADDITION"

        if is_original:
            originals.append(mem)
        else:
            additions.append(mem)

        # Truncate content for preview
        content = mem["content"].replace("\n", " ").strip()
        if len(content) > PREVIEW_LENGTH:
            content = content[:PREVIEW_LENGTH] + "..."

        promoted = ""
        if mem["promoted_from_memory_id"]:
            promoted = f"  promoted_from: memory #{mem['promoted_from_memory_id']}"

        print(f"  [{label}] ID: {mem['id']}")
        print(f"    category:   {mem['category']}")
        print(f"    created_at: {mem['created_at']}")
        if promoted:
            print(f"   {promoted}")
        print(f"    content:    {content}")
        print()

    # Summary
    print(f"{'-'*80}")
    print(f"  Summary: {len(originals)} original, {len(additions)} additions")
    if additions:
        addition_ids = [str(m["id"]) for m in additions]
        print(f"  Addition IDs: {', '.join(addition_ids)}")
    print(f"{'-'*80}\n")


def remove_memory(memory_id: int, dry_run: bool = False) -> bool:
    """Remove a single core memory by ID."""
    db = get_database()

    # Verify it exists first
    result = db.execute(
        "SELECT id, category, content FROM core_memories WHERE id = ?",
        (memory_id,),
        fetch=True
    )
    if not result:
        print(f"  No core memory found with ID {memory_id}")
        return False

    mem = result[0]
    content_preview = mem["content"].replace("\n", " ").strip()[:80]

    if dry_run:
        print(f"  [DRY RUN] Would remove ID {memory_id} [{mem['category']}]: {content_preview}...")
        return True

    db.execute("DELETE FROM core_memories WHERE id = ?", (memory_id,))
    print(f"  Removed ID {memory_id} [{mem['category']}]: {content_preview}...")
    return True


def remove_all_additions(original_narrative_id: int | None, dry_run: bool = False) -> int:
    """Remove all core memories that aren't the original narrative."""
    memories = get_all_core_memories()
    removed = 0

    for mem in memories:
        if mem["id"] == original_narrative_id:
            continue
        if remove_memory(mem["id"], dry_run=dry_run):
            removed += 1

    return removed


def main():
    parser = argparse.ArgumentParser(
        description="Audit and clean up core memories"
    )
    parser.add_argument(
        "--remove",
        type=int,
        metavar="ID",
        help="Remove a specific core memory by ID"
    )
    parser.add_argument(
        "--remove-all-additions",
        action="store_true",
        help="Remove all core memories except the original narrative"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be removed without actually deleting"
    )
    args = parser.parse_args()

    # Setup
    setup_logging(LOGS_DIR / "audit.log")
    init_database(DATABASE_PATH, DB_BUSY_TIMEOUT_MS)

    original_id = get_original_narrative_id()

    # Always display current state first
    memories = get_all_core_memories()
    display_memories(memories, original_id)

    # Handle removal operations
    if args.remove is not None:
        if args.remove == original_id:
            print("  WARNING: That ID is the original narrative. Skipping.")
            print("  Use --remove with a different ID, or manually delete if you're sure.")
            return 1

        print("Removing core memory...\n")
        if remove_memory(args.remove, dry_run=args.dry_run):
            action = "Would remove" if args.dry_run else "Removed"
            print(f"\n  {action} 1 core memory.")
        return 0

    if args.remove_all_additions:
        additions = [m for m in memories if m["id"] != original_id]
        if not additions:
            print("  No additions to remove. Only the original narrative exists.")
            return 0

        print(f"Removing {len(additions)} addition(s)...\n")
        removed = remove_all_additions(original_id, dry_run=args.dry_run)
        action = "Would remove" if args.dry_run else "Removed"
        print(f"\n  {action} {removed} core memory addition(s).")
        return 0

    # Default: display-only mode (already printed above)
    if not memories:
        return 0

    additions = [m for m in memories if m["id"] != original_id]
    if additions:
        print("  To remove all additions:")
        print("    python scripts/audit_core_memories.py --remove-all-additions")
        print()
        print("  To preview removals first:")
        print("    python scripts/audit_core_memories.py --dry-run --remove-all-additions")
        print()
        print("  To remove a specific entry:")
        print("    python scripts/audit_core_memories.py --remove <ID>")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
