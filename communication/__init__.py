"""
Pattern Project - Communication Module
Email and Telegram gateway functionality for AI-initiated messaging.
"""

from typing import Optional

from communication.email_gateway import EmailGateway, get_email_gateway, init_email_gateway
from communication.telegram_gateway import TelegramGateway, get_telegram_gateway, init_telegram_gateway
from communication.telegram_listener import TelegramListener, get_telegram_listener, init_telegram_listener
from communication.rate_limiter import RateLimiter, get_rate_limiter


__all__ = [
    # Email
    'EmailGateway',
    'get_email_gateway',
    'init_email_gateway',
    # Telegram
    'TelegramGateway',
    'get_telegram_gateway',
    'init_telegram_gateway',
    'TelegramListener',
    'get_telegram_listener',
    'init_telegram_listener',
    # Rate Limiting
    'RateLimiter',
    'get_rate_limiter',
]
