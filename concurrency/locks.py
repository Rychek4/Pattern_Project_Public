"""
Pattern Project - Lock Management
Named locks with acquisition tracking and statistics
"""

import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from contextlib import contextmanager
from collections import defaultdict

from core.logger import log_info, log_warning, log_section, log_subsection


@dataclass
class LockStats:
    """Statistics for a single lock."""
    acquisitions: int = 0
    contentions: int = 0  # Times lock was already held
    total_wait_time: float = 0.0
    total_hold_time: float = 0.0
    max_wait_time: float = 0.0
    max_hold_time: float = 0.0
    last_acquired: Optional[datetime] = None
    last_released: Optional[datetime] = None


class LockManager:
    """
    Manages named locks with monitoring and statistics.

    Provides thread-safe access to shared resources with
    detailed tracking for debugging and optimization.
    """

    def __init__(self):
        self._locks: Dict[str, threading.RLock] = {}
        self._semaphores: Dict[str, threading.Semaphore] = {}
        self._stats: Dict[str, LockStats] = defaultdict(LockStats)
        self._meta_lock = threading.Lock()  # Protects the dictionaries
        self._active_holders: Dict[str, Optional[int]] = {}  # lock_name -> thread_id
        self._acquisition_times: Dict[str, float] = {}  # lock_name -> time acquired

        # Pre-create common locks
        self._create_default_locks()

    def _create_default_locks(self) -> None:
        """Create the default set of locks."""
        # RLocks (reentrant) for general use
        self._locks["database"] = threading.RLock()
        self._locks["conversation"] = threading.RLock()
        self._locks["memory"] = threading.RLock()
        self._locks["memory_extraction"] = threading.RLock()
        self._locks["session"] = threading.RLock()
        self._locks["state"] = threading.RLock()

        # Semaphores for limiting concurrent operations
        self._semaphores["llm_requests"] = threading.Semaphore(3)

        # Initialize stats
        for name in self._locks:
            self._stats[name] = LockStats()
        for name in self._semaphores:
            self._stats[name] = LockStats()

    @contextmanager
    def acquire(self, lock_name: str, timeout: Optional[float] = None):
        """
        Acquire a named lock with optional timeout.

        Args:
            lock_name: Name of the lock to acquire
            timeout: Optional timeout in seconds

        Yields:
            None (just provides context management)

        Raises:
            TimeoutError: If timeout expires before lock acquired
            KeyError: If lock_name doesn't exist
        """
        with self._meta_lock:
            if lock_name in self._locks:
                lock = self._locks[lock_name]
                is_semaphore = False
            elif lock_name in self._semaphores:
                lock = self._semaphores[lock_name]
                is_semaphore = True
            else:
                raise KeyError(f"Unknown lock: {lock_name}")

        thread_id = threading.current_thread().ident
        start_wait = time.time()

        # Check if this would be a contention
        with self._meta_lock:
            current_holder = self._active_holders.get(lock_name)
            if current_holder is not None and current_holder != thread_id:
                self._stats[lock_name].contentions += 1

        # Acquire the lock
        if timeout is not None:
            acquired = lock.acquire(timeout=timeout)
            if not acquired:
                raise TimeoutError(f"Timeout waiting for lock: {lock_name}")
        else:
            lock.acquire()

        # Record acquisition
        wait_time = time.time() - start_wait
        acquire_time = time.time()

        with self._meta_lock:
            stats = self._stats[lock_name]
            stats.acquisitions += 1
            stats.total_wait_time += wait_time
            stats.max_wait_time = max(stats.max_wait_time, wait_time)
            stats.last_acquired = datetime.now()
            self._active_holders[lock_name] = thread_id
            self._acquisition_times[lock_name] = acquire_time

        try:
            yield
        finally:
            # Record release
            hold_time = time.time() - acquire_time

            with self._meta_lock:
                stats = self._stats[lock_name]
                stats.total_hold_time += hold_time
                stats.max_hold_time = max(stats.max_hold_time, hold_time)
                stats.last_released = datetime.now()
                self._active_holders[lock_name] = None
                self._acquisition_times.pop(lock_name, None)

            lock.release()

    def get_stats(self, lock_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics for locks.

        Args:
            lock_name: Specific lock name, or None for all locks

        Returns:
            Dict of lock statistics
        """
        with self._meta_lock:
            if lock_name:
                if lock_name in self._stats:
                    stats = self._stats[lock_name]
                    return {
                        "lock_name": lock_name,
                        "acquisitions": stats.acquisitions,
                        "contentions": stats.contentions,
                        "avg_wait_time": stats.total_wait_time / max(stats.acquisitions, 1),
                        "max_wait_time": stats.max_wait_time,
                        "avg_hold_time": stats.total_hold_time / max(stats.acquisitions, 1),
                        "max_hold_time": stats.max_hold_time,
                        "currently_held": self._active_holders.get(lock_name) is not None
                    }
                return {}

            # Return all stats
            all_stats = {}
            for name, stats in self._stats.items():
                all_stats[name] = {
                    "acquisitions": stats.acquisitions,
                    "contentions": stats.contentions,
                    "avg_wait_time": stats.total_wait_time / max(stats.acquisitions, 1),
                    "max_wait_time": stats.max_wait_time,
                    "avg_hold_time": stats.total_hold_time / max(stats.acquisitions, 1),
                    "max_hold_time": stats.max_hold_time,
                    "currently_held": self._active_holders.get(name) is not None
                }
            return all_stats

    def log_stats(self) -> None:
        """Log current lock statistics."""
        stats = self.get_stats()

        log_section("Lock Statistics", "🔒")

        for name, data in stats.items():
            if data["acquisitions"] > 0:
                log_subsection(
                    f"{name}: {data['acquisitions']} acq, "
                    f"{data['contentions']} contentions, "
                    f"avg wait {data['avg_wait_time']*1000:.1f}ms, "
                    f"avg hold {data['avg_hold_time']*1000:.1f}ms"
                )

    def create_lock(self, name: str, reentrant: bool = True) -> None:
        """Create a new named lock."""
        with self._meta_lock:
            if name not in self._locks:
                self._locks[name] = threading.RLock() if reentrant else threading.Lock()
                self._stats[name] = LockStats()

    def create_semaphore(self, name: str, value: int) -> None:
        """Create a new named semaphore."""
        with self._meta_lock:
            if name not in self._semaphores:
                self._semaphores[name] = threading.Semaphore(value)
                self._stats[name] = LockStats()


# Global lock manager instance
_lock_manager: Optional[LockManager] = None


def get_lock_manager() -> LockManager:
    """Get the global lock manager instance."""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


def init_lock_manager() -> LockManager:
    """Initialize the global lock manager."""
    global _lock_manager
    _lock_manager = LockManager()
    return _lock_manager
