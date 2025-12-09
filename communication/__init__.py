"""
Pattern Project - Communication Module
Email and SMS gateway functionality for AI-initiated messaging.
"""

from typing import Optional

from communication.email_gateway import EmailGateway, get_email_gateway, init_email_gateway
from communication.sms_gateway import SMSGateway, get_sms_gateway, init_sms_gateway
from communication.rate_limiter import RateLimiter, get_rate_limiter


__all__ = [
    # Email
    'EmailGateway',
    'get_email_gateway',
    'init_email_gateway',
    # SMS
    'SMSGateway',
    'get_sms_gateway',
    'init_sms_gateway',
    # Rate Limiting
    'RateLimiter',
    'get_rate_limiter',
]
