"""
Pattern Project - Web Fetch Rate Limiter
Tracks daily web fetch usage with midnight reset
"""

from datetime import datetime, date
from typing import Tuple

from core.database import get_database
from core.logger import log_info, log_warning, log_error
import config


# State keys for persistence
STATE_KEY_DAILY_COUNT = "web_fetch_daily_count"
STATE_KEY_LAST_RESET_DATE = "web_fetch_last_reset_date"


class WebFetchLimiter:
    """
    Manages daily web fetch budget.

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
            log_info(f"Web fetch daily limit reset for {today}", prefix="🔄")

    def get_remaining(self) -> int:
        """
        Get remaining fetches for today.

        Returns:
            Number of fetches remaining in daily budget (0 on error)
        """
        try:
            self._check_reset()
            db = self._get_db()
            used = db.get_state(STATE_KEY_DAILY_COUNT, 0)
            # Ensure used is an int (defensive against type issues)
            if not isinstance(used, int):
                used = int(used) if used is not None else 0
            remaining = max(0, config.WEB_FETCH_TOTAL_ALLOWED_PER_DAY - used)
            return remaining
        except Exception as e:
            log_error(f"Error getting web fetch remaining count: {e}")
            return 0  # Fail safe: report no fetches available

    def get_usage(self) -> Tuple[int, int]:
        """
        Get current usage stats.

        Returns:
            Tuple of (used_today, daily_limit), or (0, limit) on error
        """
        try:
            self._check_reset()
            db = self._get_db()
            used = db.get_state(STATE_KEY_DAILY_COUNT, 0)
            # Ensure used is an int (defensive against type issues)
            if not isinstance(used, int):
                used = int(used) if used is not None else 0
            return (used, config.WEB_FETCH_TOTAL_ALLOWED_PER_DAY)
        except Exception as e:
            log_error(f"Error getting web fetch usage: {e}")
            return (0, config.WEB_FETCH_TOTAL_ALLOWED_PER_DAY)

    def is_available(self) -> bool:
        """
        Check if web fetch is available (enabled and within budget).

        Returns:
            True if web fetch can be used, False on error
        """
        try:
            if not config.WEB_FETCH_ENABLED:
                return False
            return self.get_remaining() > 0
        except Exception as e:
            log_error(f"Error checking web fetch availability: {e}")
            return False  # Fail safe: report unavailable

    def record_usage(self, count: int = 1) -> int:
        """
        Record web fetch usage.

        Args:
            count: Number of fetches to record

        Returns:
            New total used today, or 0 on error
        """
        try:
            self._check_reset()
            db = self._get_db()
            current = db.get_state(STATE_KEY_DAILY_COUNT, 0)
            # Ensure current is an int (defensive against type issues)
            if not isinstance(current, int):
                current = int(current) if current is not None else 0
            new_total = current + count
            db.set_state(STATE_KEY_DAILY_COUNT, new_total)

            remaining = config.WEB_FETCH_TOTAL_ALLOWED_PER_DAY - new_total
            log_info(
                f"Web fetch used: {count} (today: {new_total}/{config.WEB_FETCH_TOTAL_ALLOWED_PER_DAY}, remaining: {remaining})",
                prefix="🌐"
            )

            if remaining <= 5 and remaining > 0:
                log_warning(f"Web fetch daily limit nearly exhausted: {remaining} remaining")
            elif remaining <= 0:
                log_warning("Web fetch daily limit exhausted")

            return new_total
        except Exception as e:
            log_error(f"Error recording web fetch usage: {e}")
            return 0

    def get_max_for_request(self) -> int:
        """
        Get the max fetches allowed for a single request.

        Considers both the per-request limit and remaining daily budget.

        Returns:
            Maximum fetches Claude should use in this request, or 0 on error
        """
        try:
            remaining = self.get_remaining()
            per_request = config.WEB_FETCH_MAX_USES_PER_REQUEST
            return min(remaining, per_request)
        except Exception as e:
            log_error(f"Error getting max fetches for request: {e}")
            return 0


# Global instance
_limiter: WebFetchLimiter = None


def get_web_fetch_limiter() -> WebFetchLimiter:
    """Get the global web fetch limiter instance."""
    global _limiter
    if _limiter is None:
        _limiter = WebFetchLimiter()
    return _limiter
