"""
Pattern Project - Deferred Retry Manager
Schedules a single retry attempt when all API models are unavailable.

When both primary and failover models fail, this manager schedules one
retry attempt after a configurable delay (default 20 minutes). The retry
is automatically cancelled if the user sends a new message before it fires.

Usage:
    from llm.retry_manager import get_retry_manager

    manager = get_retry_manager()

    # Schedule a retry
    manager.schedule(callback=lambda: process_message(original_input), source="gui")

    # Cancel on new user activity
    manager.cancel()
"""

import threading
from typing import Optional, Callable

from core.logger import log_info, log_warning


class DeferredRetryManager:
    """
    Manages a single deferred retry attempt for API failures.

    Only one retry can be pending at a time. Scheduling a new retry
    cancels any existing one. The retry is also cancelled when the
    user sends a new message (call cancel() from message entry points).
    """

    def __init__(self, default_delay: float = 1200.0):
        """
        Initialize the retry manager.

        Args:
            default_delay: Default delay in seconds before retry (1200 = 20 minutes)
        """
        self.default_delay = default_delay
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._source: Optional[str] = None  # "gui", "telegram", etc.

    def schedule(
        self,
        callback: Callable[[], None],
        delay: Optional[float] = None,
        source: str = "unknown"
    ) -> None:
        """
        Schedule a deferred retry.

        Cancels any existing pending retry before scheduling.

        Args:
            callback: Function to call when the timer fires
            delay: Delay in seconds (uses default_delay if None)
            source: Label for the source interface (for logging)
        """
        with self._lock:
            # Cancel any existing timer
            self._cancel_locked()

            retry_delay = delay if delay is not None else self.default_delay
            self._source = source

            self._timer = threading.Timer(retry_delay, self._fire, args=[callback])
            self._timer.daemon = True
            self._timer.start()

            minutes = int(retry_delay // 60)
            log_info(
                f"Deferred retry scheduled: will retry in {minutes} minutes "
                f"(source={source})",
                prefix="🔄"
            )

    def cancel(self) -> bool:
        """
        Cancel any pending deferred retry.

        Returns:
            True if a retry was cancelled, False if none was pending.
        """
        with self._lock:
            return self._cancel_locked()

    def _cancel_locked(self) -> bool:
        """Cancel pending retry (must hold self._lock)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
            source = self._source or "unknown"
            self._source = None
            log_info(f"Deferred retry cancelled (was for source={source})", prefix="🔄")
            return True
        return False

    def has_pending(self) -> bool:
        """Check if a retry is currently scheduled."""
        with self._lock:
            return self._timer is not None

    def _fire(self, callback: Callable[[], None]) -> None:
        """Execute the deferred retry callback."""
        with self._lock:
            self._timer = None
            source = self._source or "unknown"
            self._source = None

        log_info(f"Deferred retry firing (source={source})", prefix="🔄")

        try:
            callback()
        except Exception as e:
            log_warning(f"Deferred retry callback failed: {e}")


# Global instance
_retry_manager: Optional[DeferredRetryManager] = None


def get_retry_manager() -> DeferredRetryManager:
    """Get the global deferred retry manager instance."""
    global _retry_manager
    if _retry_manager is None:
        import config
        delay = getattr(config, 'API_DEFERRED_RETRY_DELAY', 1200)
        _retry_manager = DeferredRetryManager(default_delay=delay)
    return _retry_manager
