"""
Pattern Project - Communication Rate Limiter
In-memory rate limiting for email and SMS sending.

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
        email_max_per_hour: int = 20,
        sms_max_per_hour: int = 10,
        window_seconds: int = 3600,
    ):
        """
        Initialize the rate limiter.

        Args:
            email_max_per_hour: Maximum emails allowed per window
            sms_max_per_hour: Maximum SMS messages allowed per window
            window_seconds: Time window in seconds (default: 1 hour)
        """
        self.email_max = email_max_per_hour
        self.sms_max = sms_max_per_hour
        self.window_seconds = window_seconds

        self._email_timestamps: List[datetime] = []
        self._sms_timestamps: List[datetime] = []
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

    def check_email(self) -> bool:
        """
        Check if an email can be sent within rate limits.

        Returns:
            True if under limit, False if rate limited
        """
        with self._lock:
            self._email_timestamps = self._clean_old_timestamps(self._email_timestamps)
            return len(self._email_timestamps) < self.email_max

    def check_sms(self) -> bool:
        """
        Check if an SMS can be sent within rate limits.

        Returns:
            True if under limit, False if rate limited
        """
        with self._lock:
            self._sms_timestamps = self._clean_old_timestamps(self._sms_timestamps)
            return len(self._sms_timestamps) < self.sms_max

    def record_email(self) -> None:
        """Record an email send timestamp."""
        with self._lock:
            self._email_timestamps.append(datetime.now())

    def record_sms(self) -> None:
        """Record an SMS send timestamp."""
        with self._lock:
            self._sms_timestamps.append(datetime.now())

    def get_email_remaining(self) -> int:
        """
        Get remaining email quota.

        Returns:
            Number of emails that can still be sent in current window
        """
        with self._lock:
            self._email_timestamps = self._clean_old_timestamps(self._email_timestamps)
            return max(0, self.email_max - len(self._email_timestamps))

    def get_sms_remaining(self) -> int:
        """
        Get remaining SMS quota.

        Returns:
            Number of SMS messages that can still be sent in current window
        """
        with self._lock:
            self._sms_timestamps = self._clean_old_timestamps(self._sms_timestamps)
            return max(0, self.sms_max - len(self._sms_timestamps))

    def get_email_reset_time(self) -> Optional[datetime]:
        """
        Get when the oldest email timestamp will expire.

        Returns:
            Datetime when quota will partially reset, or None if no emails sent
        """
        with self._lock:
            self._email_timestamps = self._clean_old_timestamps(self._email_timestamps)
            if not self._email_timestamps:
                return None
            oldest = min(self._email_timestamps)
            return oldest + timedelta(seconds=self.window_seconds)

    def get_sms_reset_time(self) -> Optional[datetime]:
        """
        Get when the oldest SMS timestamp will expire.

        Returns:
            Datetime when quota will partially reset, or None if no SMS sent
        """
        with self._lock:
            self._sms_timestamps = self._clean_old_timestamps(self._sms_timestamps)
            if not self._sms_timestamps:
                return None
            oldest = min(self._sms_timestamps)
            return oldest + timedelta(seconds=self.window_seconds)

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            Dict with current usage stats
        """
        with self._lock:
            self._email_timestamps = self._clean_old_timestamps(self._email_timestamps)
            self._sms_timestamps = self._clean_old_timestamps(self._sms_timestamps)

            return {
                "email_sent": len(self._email_timestamps),
                "email_limit": self.email_max,
                "email_remaining": self.email_max - len(self._email_timestamps),
                "sms_sent": len(self._sms_timestamps),
                "sms_limit": self.sms_max,
                "sms_remaining": self.sms_max - len(self._sms_timestamps),
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
    email_max_per_hour: Optional[int] = None,
    sms_max_per_hour: Optional[int] = None,
) -> RateLimiter:
    """
    Initialize the global rate limiter instance.

    Args:
        email_max_per_hour: Max emails per hour (defaults to config)
        sms_max_per_hour: Max SMS per hour (defaults to config)

    Returns:
        The initialized RateLimiter instance
    """
    global _limiter

    # Import config values as defaults
    from config import EMAIL_MAX_PER_HOUR, SMS_MAX_PER_HOUR

    _limiter = RateLimiter(
        email_max_per_hour=email_max_per_hour or EMAIL_MAX_PER_HOUR,
        sms_max_per_hour=sms_max_per_hour or SMS_MAX_PER_HOUR,
    )

    return _limiter
