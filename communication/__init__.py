"""
Pattern Project - Communication Module
Telegram and Google Calendar gateway functionality for AI-initiated messaging.
"""

from typing import Optional

from communication.telegram_gateway import TelegramGateway, get_telegram_gateway, init_telegram_gateway
from communication.telegram_listener import TelegramListener, get_telegram_listener, init_telegram_listener
from communication.rate_limiter import RateLimiter, get_rate_limiter
from communication.calendar_gateway import CalendarGateway, get_calendar_gateway, init_calendar_gateway


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
    # Rate Limiting
    'RateLimiter',
    'get_rate_limiter',
]
