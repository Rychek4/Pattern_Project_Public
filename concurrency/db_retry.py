"""
Pattern Project - Database Retry Logic
Exponential backoff retry for database operations
"""

import time
import sqlite3
from typing import TypeVar, Callable, Optional
from functools import wraps

from core.logger import log_warning, log_error

T = TypeVar('T')


class DatabaseRetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""
    pass


def db_retry(
    max_retries: int = 5,
    initial_delay: float = 0.1,
    backoff_multiplier: float = 2.0,
    max_delay: float = 10.0,
    retryable_errors: tuple = ("locked", "busy", "database is locked")
):
    """
    Decorator for retrying database operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_multiplier: Multiplier for each retry
        max_delay: Maximum delay between retries
        retryable_errors: Error message substrings that trigger retry
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except sqlite3.OperationalError as e:
                    error_msg = str(e).lower()
                    is_retryable = any(err in error_msg for err in retryable_errors)

                    if not is_retryable or attempt >= max_retries:
                        if attempt > 0:
                            log_error(
                                f"Database operation failed after {attempt + 1} attempts: {e}"
                            )
                        raise

                    last_error = e
                    log_warning(
                        f"Database locked (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                    delay = min(delay * backoff_multiplier, max_delay)

            # Should not reach here, but just in case
            raise DatabaseRetryExhausted(
                f"Max retries ({max_retries}) exhausted. Last error: {last_error}"
            )

        return wrapper
    return decorator


def execute_with_retry(
    func: Callable[..., T],
    max_retries: int = 5,
    initial_delay: float = 0.1,
    backoff_multiplier: float = 2.0,
    max_delay: float = 10.0
) -> T:
    """
    Execute a database function with retry logic.

    Args:
        func: The function to execute (no arguments)
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        backoff_multiplier: Multiplier for each retry
        max_delay: Maximum delay between retries

    Returns:
        The result of the function

    Raises:
        DatabaseRetryExhausted: If all retries fail
    """
    delay = initial_delay
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return func()

        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()

            if "locked" not in error_msg and "busy" not in error_msg:
                raise

            if attempt >= max_retries:
                log_error(
                    f"Database operation failed after {attempt + 1} attempts: {e}"
                )
                raise DatabaseRetryExhausted(
                    f"Max retries ({max_retries}) exhausted. Last error: {e}"
                )

            last_error = e
            log_warning(
                f"Database locked (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying in {delay:.2f}s..."
            )
            time.sleep(delay)
            delay = min(delay * backoff_multiplier, max_delay)

    raise DatabaseRetryExhausted(
        f"Max retries ({max_retries}) exhausted. Last error: {last_error}"
    )


class RetryConfig:
    """Configuration for database retry behavior."""

    def __init__(
        self,
        max_retries: int = 5,
        initial_delay: float = 0.1,
        backoff_multiplier: float = 2.0,
        max_delay: float = 10.0
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_multiplier = backoff_multiplier
        self.max_delay = max_delay

    def to_dict(self) -> dict:
        """Convert to dictionary for logging."""
        return {
            "max_retries": self.max_retries,
            "initial_delay": f"{self.initial_delay}s",
            "backoff_multiplier": f"{self.backoff_multiplier}x",
            "max_delay": f"{self.max_delay}s"
        }


# Default retry configuration
DEFAULT_RETRY_CONFIG = RetryConfig()
