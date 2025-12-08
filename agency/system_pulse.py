"""
Pattern Project - System Pulse Timer
Sends periodic prompts to the AI to encourage autonomous agency
"""

import threading
import time
from datetime import datetime
from typing import Optional, Callable, Dict, Any

from core.logger import log_info, log_warning, log_error


# The pulse message sent to the AI (full version for LLM context)
PULSE_PROMPT = """System Pulse: 3-minute timer. There is no new user message. Instead of responding, utilize your agency. Review the conversation history: is there a loose end you want to tie up? Is there a new idea you want to introduce? Speak your mind freely."""

# Abbreviated version stored in conversation history
PULSE_STORED_MESSAGE = "[System Pulse]"


class SystemPulseTimer:
    """
    Timer that sends periodic system pulse prompts to the AI.

    Features:
    - Fixed interval countdown (default 3 minutes)
    - Resets when user sends a message
    - Pauses during AI response generation
    - Provides countdown for UI display
    """

    def __init__(
        self,
        pulse_interval: float = 180.0,
        enabled: bool = True,
        on_pulse: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the system pulse timer.

        Args:
            pulse_interval: Seconds between pulses (default 180 = 3 minutes)
            enabled: Whether the pulse timer is active
            on_pulse: Callback function when pulse fires
        """
        self.pulse_interval = pulse_interval
        self.enabled = enabled
        self._on_pulse = on_pulse

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False
        self._pause_lock = threading.Lock()

        # Elapsed time tracking (in seconds)
        self._elapsed_seconds: float = 0.0
        self._last_tick: Optional[datetime] = None
        self._elapsed_lock = threading.Lock()

    def start(self) -> None:
        """Start the pulse timer thread."""
        if not self.enabled:
            log_info("System pulse timer disabled", prefix="⏱️")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._reset_elapsed()

        self._thread = threading.Thread(
            target=self._timer_loop,
            daemon=True,
            name="SystemPulseTimer"
        )
        self._thread.start()
        log_info(f"System pulse timer started ({self.pulse_interval}s interval)", prefix="⏱️")

    def stop(self) -> None:
        """Stop the pulse timer thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("System pulse timer stopped", prefix="⏱️")

    def reset(self) -> None:
        """Reset the timer countdown (call when user sends a message)."""
        self._reset_elapsed()
        log_info("System pulse timer reset", prefix="⏱️")

    def pause(self) -> None:
        """Pause the timer (call when AI starts generating response)."""
        with self._pause_lock:
            self._paused = True

    def resume(self) -> None:
        """Resume the timer (call when AI finishes generating response)."""
        with self._pause_lock:
            if self._paused:
                self._paused = False
                # Reset the tick timestamp so we don't count paused time
                with self._elapsed_lock:
                    self._last_tick = datetime.now()

    def set_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback function for when pulse fires."""
        self._on_pulse = callback

    def get_seconds_remaining(self) -> int:
        """Get seconds remaining until next pulse."""
        with self._elapsed_lock:
            remaining = self.pulse_interval - self._elapsed_seconds
            return max(0, int(remaining))

    def get_seconds_elapsed(self) -> float:
        """Get seconds elapsed since last reset."""
        with self._elapsed_lock:
            return self._elapsed_seconds

    def is_running(self) -> bool:
        """Check if the timer thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_paused(self) -> bool:
        """Check if the timer is currently paused."""
        with self._pause_lock:
            return self._paused

    def _reset_elapsed(self) -> None:
        """Reset elapsed time to zero."""
        with self._elapsed_lock:
            self._elapsed_seconds = 0.0
            self._last_tick = datetime.now()

    def _timer_loop(self) -> None:
        """Main timer loop - ticks every second."""
        while not self._stop_event.is_set():
            try:
                # Check if paused
                with self._pause_lock:
                    is_paused = self._paused

                if not is_paused:
                    self._tick()

                    # Check if it's time to fire
                    with self._elapsed_lock:
                        if self._elapsed_seconds >= self.pulse_interval:
                            self._fire_pulse()

            except Exception as e:
                log_error(f"System pulse timer error: {e}")

            # Wait 1 second before next tick
            self._stop_event.wait(1.0)

    def _tick(self) -> None:
        """Increment elapsed time by actual time passed."""
        with self._elapsed_lock:
            now = datetime.now()
            if self._last_tick is not None:
                delta = (now - self._last_tick).total_seconds()
                self._elapsed_seconds += delta
            self._last_tick = now

    def _fire_pulse(self) -> None:
        """Fire the pulse and reset timer."""
        log_info("System pulse fired!", prefix="⏱️")

        # Reset timer immediately (so countdown restarts)
        self._reset_elapsed()

        # Call the callback if set
        if self._on_pulse:
            try:
                self._on_pulse()
            except Exception as e:
                log_error(f"Error in pulse callback: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get timer statistics."""
        return {
            "enabled": self.enabled,
            "paused": self.is_paused(),
            "is_running": self.is_running(),
            "pulse_interval": self.pulse_interval,
            "seconds_elapsed": self.get_seconds_elapsed(),
            "seconds_remaining": self.get_seconds_remaining()
        }


# Global system pulse timer instance
_system_pulse_timer: Optional[SystemPulseTimer] = None


def get_system_pulse_timer() -> SystemPulseTimer:
    """Get the global system pulse timer instance."""
    global _system_pulse_timer
    if _system_pulse_timer is None:
        from config import SYSTEM_PULSE_ENABLED, SYSTEM_PULSE_INTERVAL
        _system_pulse_timer = SystemPulseTimer(
            pulse_interval=SYSTEM_PULSE_INTERVAL,
            enabled=SYSTEM_PULSE_ENABLED
        )
    return _system_pulse_timer


def init_system_pulse_timer() -> SystemPulseTimer:
    """Initialize the global system pulse timer."""
    global _system_pulse_timer
    from config import SYSTEM_PULSE_ENABLED, SYSTEM_PULSE_INTERVAL
    _system_pulse_timer = SystemPulseTimer(
        pulse_interval=SYSTEM_PULSE_INTERVAL,
        enabled=SYSTEM_PULSE_ENABLED
    )
    return _system_pulse_timer
