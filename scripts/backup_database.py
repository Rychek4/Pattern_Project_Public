#!/usr/bin/env python3
"""
Pattern Project - Database Backup Script

Standalone script for backing up the database to Google Drive.
Can be run manually or via cron for automated daily backups.

Usage:
    # Manual run
    python scripts/backup_database.py

    # Or from the project root
    /opt/pattern/venv/bin/python scripts/backup_database.py

Cron setup (daily at 3 AM):
    crontab -e -u pattern
    0 3 * * * cd /opt/pattern && /opt/pattern/venv/bin/python scripts/backup_database.py >> /opt/pattern/logs/backup.log 2>&1
"""

import os
import sys

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def main():
    if not config.GOOGLE_DRIVE_BACKUP_ENABLED:
        print("ERROR: Google Drive backup is disabled. Set GOOGLE_DRIVE_BACKUP_ENABLED=true in .env")
        sys.exit(1)

    from communication.drive_backup_gateway import init_drive_backup_gateway, run_drive_backup

    print(f"[backup] Initializing Google Drive backup gateway...")
    init_drive_backup_gateway()

    print(f"[backup] Starting backup of {config.DATABASE_PATH}...")
    result = run_drive_backup()

    if result.success:
        print(f"[backup] SUCCESS: {result.message}")
    else:
        print(f"[backup] FAILED: {result.message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
