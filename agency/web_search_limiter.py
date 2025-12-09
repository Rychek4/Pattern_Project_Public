"""
Pattern Project - Web Search Rate Limiter
Tracks daily web search usage with midnight reset
"""

from datetime import datetime, date
from typing import Tuple

from core.database import get_database
from core.logger import log_info, log_warning
import config


# State keys for persistence
STATE_KEY_DAILY_COUNT = "web_search_daily_count"
STATE_KEY_LAST_RESET_DATE = "web_search_last_reset_date"


class WebSearchLimiter:
    """
    Manages daily web search budget.

    Uses the state table for persistence across restarts.
    Resets count at midnight (based on local date).
    """

    def __init__(self):
        self._db = None

    def _get_db(self):
        """Lazy-load database."""
        if self._db is None:
            self._db = get_database()
        return self._db

    def _check_reset(self) -> None:
        """Reset counter if we've crossed midnight."""
        db = self._get_db()
        today = date.today().isoformat()
        last_reset = db.get_state(STATE_KEY_LAST_RESET_DATE)

        if last_reset != today:
            # New day - reset counter
            db.set_state(STATE_KEY_DAILY_COUNT, 0)
            db.set_state(STATE_KEY_LAST_RESET_DATE, today)
            log_info(f"Web search daily limit reset for {today}", prefix="🔄")

    def get_remaining(self) -> int:
        """
        Get remaining searches for today.

        Returns:
            Number of searches remaining in daily budget
        """
        self._check_reset()
        db = self._get_db()
        used = db.get_state(STATE_KEY_DAILY_COUNT, 0)
        remaining = max(0, config.WEB_SEARCH_TOTAL_ALLOWED_PER_DAY - used)
        return remaining

    def get_usage(self) -> Tuple[int, int]:
        """
        Get current usage stats.

        Returns:
            Tuple of (used_today, daily_limit)
        """
        self._check_reset()
        db = self._get_db()
        used = db.get_state(STATE_KEY_DAILY_COUNT, 0)
        return (used, config.WEB_SEARCH_TOTAL_ALLOWED_PER_DAY)

    def is_available(self) -> bool:
        """
        Check if web search is available (enabled and within budget).

        Returns:
            True if web search can be used
        """
        if not config.WEB_SEARCH_ENABLED:
            return False
        return self.get_remaining() > 0

    def record_usage(self, count: int = 1) -> int:
        """
        Record web search usage.

        Args:
            count: Number of searches to record

        Returns:
            New total used today
        """
        self._check_reset()
        db = self._get_db()
        current = db.get_state(STATE_KEY_DAILY_COUNT, 0)
        new_total = current + count
        db.set_state(STATE_KEY_DAILY_COUNT, new_total)

        remaining = config.WEB_SEARCH_TOTAL_ALLOWED_PER_DAY - new_total
        log_info(
            f"Web search used: {count} (today: {new_total}/{config.WEB_SEARCH_TOTAL_ALLOWED_PER_DAY}, remaining: {remaining})",
            prefix="🔍"
        )

        if remaining <= 5 and remaining > 0:
            log_warning(f"Web search daily limit nearly exhausted: {remaining} remaining")
        elif remaining <= 0:
            log_warning("Web search daily limit exhausted")

        return new_total

    def get_max_for_request(self) -> int:
        """
        Get the max searches allowed for a single request.

        Considers both the per-request limit and remaining daily budget.

        Returns:
            Maximum searches Claude should use in this request
        """
        remaining = self.get_remaining()
        per_request = config.WEB_SEARCH_MAX_USES_PER_REQUEST
        return min(remaining, per_request)


# Global instance
_limiter: WebSearchLimiter = None


def get_web_search_limiter() -> WebSearchLimiter:
    """Get the global web search limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = WebSearchLimiter()
    return _limiter
