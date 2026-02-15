"""
Pattern Project - Natural Language Time Parser
Parses relative time expressions into datetime objects
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple


# Patterns for parsing time expressions
TIME_PATTERNS = [
    # "in X minutes/hours/days"
    (r'in\s+(\d+)\s*(?:min(?:ute)?s?)', 'minutes'),
    (r'in\s+(\d+)\s*(?:h(?:ou)?rs?)', 'hours'),
    (r'in\s+(\d+)\s*(?:days?)', 'days'),

    # "Xm", "Xh" shorthand
    (r'^(\d+)\s*m$', 'minutes'),
    (r'^(\d+)\s*h$', 'hours'),

    # Relative day expressions
    (r'tomorrow\s*(?:morning)?', 'tomorrow_morning'),
    (r'tomorrow\s*(?:afternoon)?', 'tomorrow_afternoon'),
    (r'tomorrow\s*(?:evening)?', 'tomorrow_evening'),
    (r'tomorrow', 'tomorrow'),
    (r'later\s*(?:today)?', 'later_today'),
    (r'this\s*evening', 'this_evening'),
    (r'tonight', 'tonight'),

    # Session-based
    (r'next\s*(?:session|time)', 'next_session'),
]


def parse_time_expression(expression: str, now: Optional[datetime] = None) -> Tuple[Optional[datetime], str]:
    """
    Parse a natural language time expression into a datetime.

    Args:
        expression: Natural language time string (e.g., "in 2 hours", "tomorrow morning")
        now: Current datetime (defaults to datetime.now())

    Returns:
        Tuple of (datetime or None, trigger_type)
        - datetime: When the intention should trigger
        - trigger_type: 'time' for time-based, 'next_session' for session-based
    """
    if now is None:
        now = datetime.now()

    expression = expression.lower().strip()

    # Check for next session
    if re.match(r'next\s*(?:session|time)', expression):
        return None, 'next_session'

    # Try numeric patterns first
    for pattern, unit in TIME_PATTERNS:
        match = re.match(pattern, expression, re.IGNORECASE)
        if match:
            if unit == 'minutes':
                delta = timedelta(minutes=int(match.group(1)))
                return now + delta, 'time'
            elif unit == 'hours':
                delta = timedelta(hours=int(match.group(1)))
                return now + delta, 'time'
            elif unit == 'days':
                delta = timedelta(days=int(match.group(1)))
                return now + delta, 'time'
            elif unit == 'next_session':
                return None, 'next_session'
            elif unit == 'tomorrow':
                # Default to 9am tomorrow
                tomorrow = now + timedelta(days=1)
                return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0), 'time'
            elif unit == 'tomorrow_morning':
                tomorrow = now + timedelta(days=1)
                return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0), 'time'
            elif unit == 'tomorrow_afternoon':
                tomorrow = now + timedelta(days=1)
                return tomorrow.replace(hour=14, minute=0, second=0, microsecond=0), 'time'
            elif unit == 'tomorrow_evening':
                tomorrow = now + timedelta(days=1)
                return tomorrow.replace(hour=18, minute=0, second=0, microsecond=0), 'time'
            elif unit == 'later_today':
                # 2 hours from now, but at least 30 min
                return now + timedelta(hours=2), 'time'
            elif unit == 'this_evening':
                return now.replace(hour=18, minute=0, second=0, microsecond=0), 'time'
            elif unit == 'tonight':
                return now.replace(hour=20, minute=0, second=0, microsecond=0), 'time'

    # Try to parse as a simple number (assume hours)
    try:
        hours = float(expression)
        return now + timedelta(hours=hours), 'time'
    except ValueError:
        pass

    # Default: couldn't parse, return None
    return None, 'time'


def format_trigger_time(trigger_at: Optional[datetime], trigger_type: str, now: Optional[datetime] = None) -> str:
    """
    Format a trigger time for display.

    Args:
        trigger_at: The datetime when the intention triggers
        trigger_type: 'time' or 'next_session'
        now: Current datetime for relative formatting

    Returns:
        Human-readable string like "in 2 hours" or "next session"
    """
    if trigger_type == 'next_session':
        return "next session"

    if trigger_at is None:
        return "unknown"

    if now is None:
        now = datetime.now()

    delta = trigger_at - now

    if delta.total_seconds() < 0:
        return "overdue"

    if delta.total_seconds() < 60:
        return "in less than a minute"

    if delta.total_seconds() < 3600:
        minutes = int(delta.total_seconds() / 60)
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"

    if delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"in {hours} hour{'s' if hours != 1 else ''}"

    days = int(delta.total_seconds() / 86400)
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def format_relative_past(dt: datetime, now: Optional[datetime] = None) -> str:
    """
    Format a past datetime relative to now.

    Args:
        dt: The datetime to format
        now: Current datetime

    Returns:
        Human-readable string like "2 hours ago" or "yesterday"
    """
    if now is None:
        now = datetime.now()

    delta = now - dt

    if delta.total_seconds() < 60:
        return "just now"

    if delta.total_seconds() < 3600:
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"

    if delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = int(delta.total_seconds() / 86400)
    if days == 1:
        return "yesterday"
    return f"{days} days ago"
