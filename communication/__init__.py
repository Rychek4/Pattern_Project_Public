"""
Pattern Project - Communication Module
Telegram and Google Calendar gateway functionality for AI-initiated messaging.
"""

from typing import Optional

from communication.telegram_gateway import TelegramGateway, get_telegram_gateway, init_telegram_gateway
from communication.telegram_listener import TelegramListener, get_telegram_listener, init_telegram_listener
from communication.rate_limiter import RateLimiter, get_rate_limiter
from communication.calendar_gateway import CalendarGateway, get_calendar_gateway, init_calendar_gateway
from communication.drive_backup_gateway import DriveBackupGateway, get_drive_backup_gateway, init_drive_backup_gateway, run_drive_backup


__all__ = [
    # Telegram
    'TelegramGateway',
    'get_telegram_gateway',
    'init_telegram_gateway',
    'TelegramListener',
    'get_telegram_listener',
    'init_telegram_listener',
    # Google Calendar
    'CalendarGateway',
    'get_calendar_gateway',
    'init_calendar_gateway',
    # Google Drive Backup
    'DriveBackupGateway',
    'get_drive_backup_gateway',
    'init_drive_backup_gateway',
    'run_drive_backup',
    # Rate Limiting
    'RateLimiter',
    'get_rate_limiter',
]
