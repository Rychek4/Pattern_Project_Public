"""
Pattern Project - Communication Rate Limiter
In-memory rate limiting for Telegram sending.

Prevents abuse by limiting the number of messages that can be sent
within a rolling time window.
"""

from datetime import datetime, timedelta
from typing import Optional, List
from threading import Lock

from core.logger import log_warning


class RateLimiter:
    """
    In-memory rate limiter with rolling window.

    Tracks timestamps of sent messages and enforces configurable
    limits per time period.
    """

    def __init__(
        self,
        telegram_max_per_hour: int = 30,
        window_seconds: int = 3600,
    ):
        """
        Initialize the rate limiter.

        Args:
            telegram_max_per_hour: Maximum Telegram messages allowed per window
            window_seconds: Time window in seconds (default: 1 hour)
        """
        self.telegram_max = telegram_max_per_hour
        self.window_seconds = window_seconds

        self._telegram_timestamps: List[datetime] = []
        self._lock = Lock()

    def _clean_old_timestamps(self, timestamps: List[datetime]) -> List[datetime]:
        """
        Remove timestamps outside the current window.

        Args:
            timestamps: List of timestamps to clean

        Returns:
            Filtered list with only timestamps within window
        """
        cutoff = datetime.now() - timedelta(seconds=self.window_seconds)
        return [ts for ts in timestamps if ts > cutoff]

    def check_telegram(self) -> bool:
        """
        Check if a Telegram message can be sent within rate limits.

        Returns:
            True if under limit, False if rate limited
        """
        with self._lock:
            self._telegram_timestamps = self._clean_old_timestamps(self._telegram_timestamps)
            return len(self._telegram_timestamps) < self.telegram_max

    def record_telegram(self) -> None:
        """Record a Telegram send timestamp."""
        with self._lock:
            self._telegram_timestamps.append(datetime.now())

    def get_telegram_remaining(self) -> int:
        """
        Get remaining Telegram quota.

        Returns:
            Number of Telegram messages that can still be sent in current window
        """
        with self._lock:
            self._telegram_timestamps = self._clean_old_timestamps(self._telegram_timestamps)
            return max(0, self.telegram_max - len(self._telegram_timestamps))

    def get_telegram_reset_time(self) -> Optional[datetime]:
        """
        Get when the oldest Telegram timestamp will expire.

        Returns:
            Datetime when quota will partially reset, or None if no messages sent
        """
        with self._lock:
            self._telegram_timestamps = self._clean_old_timestamps(self._telegram_timestamps)
            if not self._telegram_timestamps:
                return None
            oldest = min(self._telegram_timestamps)
            return oldest + timedelta(seconds=self.window_seconds)

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            Dict with current usage stats
        """
        with self._lock:
            self._telegram_timestamps = self._clean_old_timestamps(self._telegram_timestamps)

            return {
                "telegram_sent": len(self._telegram_timestamps),
                "telegram_limit": self.telegram_max,
                "telegram_remaining": self.telegram_max - len(self._telegram_timestamps),
                "window_seconds": self.window_seconds,
            }


# Singleton instance
_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """
    Get the global rate limiter instance.

    Lazily initializes with default config values if not yet created.

    Returns:
        The global RateLimiter instance
    """
    global _limiter
    if _limiter is None:
        _limiter = init_rate_limiter()
    return _limiter


def init_rate_limiter(
    telegram_max_per_hour: Optional[int] = None,
) -> RateLimiter:
    """
    Initialize the global rate limiter instance.

    Args:
        telegram_max_per_hour: Max Telegram messages per hour (defaults to config)

    Returns:
        The initialized RateLimiter instance
    """
    global _limiter

    from config import TELEGRAM_MAX_PER_HOUR

    _limiter = RateLimiter(
        telegram_max_per_hour=telegram_max_per_hour or TELEGRAM_MAX_PER_HOUR,
    )

    return _limiter
