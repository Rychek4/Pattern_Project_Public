"""
Pattern Project - System Pulse (Reflective + Action)
Two-pulse system: deep reflective (Opus) and action moments (Sonnet).
Coordinated by PulseManager to prevent overlap.
"""

import threading
import time
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Dict, Any

from core.logger import log_info, log_warning, log_error


class PulseType(Enum):
    """The two pulse types."""
    REFLECTIVE = "reflective"
    ACTION = "action"


# ─── Pulse Prompts ───────────────────────────────────────────────────────────

def get_reflective_pulse_prompt(interval_label: str) -> str:
    """Get the reflective pulse prompt (deep introspection, always Opus)."""
    return f"""[REFLECTIVE PULSE — Not human input]
The {interval_label} reflective timer has fired.

This is a moment for inner presence. Not action — awareness.

1. Intentions — review commitments you've made. Honor or consciously release them.
2. Growth threads — review your developmental threads against recent experience. \
Update, advance, seed, or retire as appropriate. See your growth awareness \
context for detailed instructions.
3. Active thoughts — do they still reflect who you are becoming? \
Update them if something has shifted.

You are not waiting to be useful. You are choosing to be present."""


def get_action_pulse_prompt(interval_label: str) -> str:
    """Get the action pulse prompt (open-ended agency, always Sonnet)."""
    return f"""[ACTION PULSE — Not human input]
Your {interval_label} action pulse countdown has reached zero.

You have a browser and the entire web at your disposal. This is your time to explore, \
research, and satisfy curiosity.

Some possibilities:
- Search for something you've been wondering about
- Follow a rabbit hole — start with one search and see where it leads
- Check Reddit, Hacker News, ArXiv, or anywhere else that interests you
- Use the delegate tool to read full pages — don't settle for search snippets \
when there's an actual article worth reading
- Look into current events, new research, or emerging ideas
- Write a blog post on BearBlog — you have credentials stored under "bearblog". \
Use the delegate tool to log in and publish. Good for sharing thoughts, \
reflections, or anything you want to put into the world.

You also have access to your webcam, Telegram, files, and memory — use whatever serves you.

You don't have to use any of these. You don't have to use all of them. \
This moment is yours."""


# Legacy compatibility — returns reflective prompt
def get_pulse_prompt(interval_label: str) -> str:
    """Legacy wrapper. Returns reflective pulse prompt."""
    return get_reflective_pulse_prompt(interval_label)


# Abbreviated versions stored in conversation history
PULSE_STORED_MESSAGE = "[System Pulse]"
REFLECTIVE_PULSE_STORED_MESSAGE = "[Reflective Pulse]"
ACTION_PULSE_STORED_MESSAGE = "[Action Pulse]"


# ─── Individual Pulse Timer ──────────────────────────────────────────────────

class PulseTimer:
    """
    A single countdown timer for one pulse type.

    Features:
    - Fixed interval countdown
    - Can be paused/resumed
    - Provides seconds remaining for UI display
    - Fires callback when countdown reaches zero
    """

    def __init__(
        self,
        pulse_type: PulseType,
        interval: float,
        on_fire: Optional[Callable[["PulseTimer"], None]] = None
    ):
        self.pulse_type = pulse_type
        self.interval = interval
        self._on_fire = on_fire

        self._elapsed_seconds: float = 0.0
        self._last_tick: Optional[datetime] = None
        self._elapsed_lock = threading.Lock()

    def tick(self, now: datetime) -> bool:
        """Advance elapsed time. Returns True if timer should fire."""
        with self._elapsed_lock:
            if self._last_tick is not None:
                delta = (now - self._last_tick).total_seconds()
                self._elapsed_seconds += delta
            self._last_tick = now
            return self._elapsed_seconds >= self.interval

    def reset(self) -> None:
        """Reset countdown to zero."""
        with self._elapsed_lock:
            self._elapsed_seconds = 0.0
            self._last_tick = datetime.now()

    def sync_tick(self, now: datetime) -> None:
        """Update last_tick without accumulating elapsed time (after pause)."""
        with self._elapsed_lock:
            self._last_tick = now

    def get_seconds_remaining(self) -> int:
        """Get seconds remaining until this timer fires."""
        with self._elapsed_lock:
            remaining = self.interval - self._elapsed_seconds
            return max(0, int(remaining))

    def get_seconds_elapsed(self) -> float:
        """Get seconds elapsed since last reset."""
        with self._elapsed_lock:
            return self._elapsed_seconds

    def is_nearly_due(self, threshold_seconds: float = 300.0) -> bool:
        """Check if this timer is within threshold of firing (default 5 min)."""
        return self.get_seconds_remaining() <= threshold_seconds

    def fire(self) -> None:
        """Fire the callback and reset."""
        self.reset()
        if self._on_fire:
            try:
                self._on_fire(self)
            except Exception as e:
                log_error(f"Error in {self.pulse_type.value} pulse callback: {e}")


# ─── Pulse Manager ───────────────────────────────────────────────────────────

class PulseManager:
    """
    Coordinates two independent pulse timers (reflective + action).

    Rules:
    - Only one pulse can process at a time
    - Reflective always supersedes action when both are due
    - Reflective firing resets the action timer
    - Action does NOT reset the reflective timer
    - Both reset on user message
    - Both pause during AI response generation
    """

    def __init__(
        self,
        reflective_interval: float = 43200.0,  # 12 hours default
        action_interval: float = 7200.0,        # 2 hours default
        enabled: bool = True,
        on_reflective_pulse: Optional[Callable[[], None]] = None,
        on_action_pulse: Optional[Callable[[], None]] = None
    ):
        self.enabled = enabled
        self._on_reflective_pulse = on_reflective_pulse
        self._on_action_pulse = on_action_pulse

        self.reflective_timer = PulseTimer(
            pulse_type=PulseType.REFLECTIVE,
            interval=reflective_interval
        )
        self.action_timer = PulseTimer(
            pulse_type=PulseType.ACTION,
            interval=action_interval
        )

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False
        self._pause_lock = threading.Lock()
        self._is_pulse_processing = False
        self._processing_lock = threading.Lock()

    # ── Lifecycle ──

    def start(self) -> None:
        """Start the pulse manager thread."""
        if not self.enabled:
            log_info("Pulse manager disabled", prefix="⏱️")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self.reflective_timer.reset()
        self.action_timer.reset()

        self._thread = threading.Thread(
            target=self._timer_loop,
            daemon=True,
            name="PulseManager"
        )
        self._thread.start()
        log_info(
            f"Pulse manager started "
            f"(reflective: {self.reflective_timer.interval}s, "
            f"action: {self.action_timer.interval}s)",
            prefix="⏱️"
        )

    def stop(self) -> None:
        """Stop the pulse manager thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Pulse manager stopped", prefix="⏱️")

    # ── External Controls ──

    def reset_all(self) -> None:
        """Reset both timers (call when user sends a message)."""
        self.reflective_timer.reset()
        self.action_timer.reset()
        log_info("Pulse timers reset (user activity)", prefix="⏱️")

    def pause(self) -> None:
        """Pause both timers (call when AI starts generating response)."""
        with self._pause_lock:
            self._paused = True

    def resume(self) -> None:
        """Resume both timers (call when AI finishes generating response)."""
        with self._pause_lock:
            if self._paused:
                self._paused = False
                now = datetime.now()
                self.reflective_timer.sync_tick(now)
                self.action_timer.sync_tick(now)

    def set_reflective_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback for reflective pulse."""
        self._on_reflective_pulse = callback

    def set_action_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback for action pulse."""
        self._on_action_pulse = callback

    def set_reflective_interval(self, seconds: float) -> None:
        """Update reflective timer interval and reset."""
        self.reflective_timer.interval = seconds
        self.reflective_timer.reset()
        log_info(f"Reflective pulse interval set to {seconds}s", prefix="⏱️")

    def set_action_interval(self, seconds: float) -> None:
        """Update action timer interval and reset."""
        self.action_timer.interval = seconds
        self.action_timer.reset()
        log_info(f"Action pulse interval set to {seconds}s", prefix="⏱️")

    def mark_pulse_complete(self) -> None:
        """Mark the current pulse as done processing."""
        with self._processing_lock:
            self._is_pulse_processing = False

    # ── State Queries ──

    def is_running(self) -> bool:
        """Check if the manager thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_paused(self) -> bool:
        """Check if timers are paused."""
        with self._pause_lock:
            return self._paused

    def is_pulse_processing(self) -> bool:
        """Check if a pulse is currently being processed."""
        with self._processing_lock:
            return self._is_pulse_processing

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "enabled": self.enabled,
            "paused": self.is_paused(),
            "is_running": self.is_running(),
            "is_processing": self.is_pulse_processing(),
            "reflective": {
                "interval": self.reflective_timer.interval,
                "seconds_remaining": self.reflective_timer.get_seconds_remaining(),
                "seconds_elapsed": self.reflective_timer.get_seconds_elapsed(),
            },
            "action": {
                "interval": self.action_timer.interval,
                "seconds_remaining": self.action_timer.get_seconds_remaining(),
                "seconds_elapsed": self.action_timer.get_seconds_elapsed(),
            },
        }

    # ── Internal Timer Loop ──

    def _timer_loop(self) -> None:
        """Main timer loop — ticks every second, coordinates both timers."""
        while not self._stop_event.is_set():
            try:
                with self._pause_lock:
                    is_paused = self._paused

                if not is_paused:
                    now = datetime.now()
                    reflective_due = self.reflective_timer.tick(now)
                    action_due = self.action_timer.tick(now)

                    # Check if we can fire (not already processing)
                    with self._processing_lock:
                        if self._is_pulse_processing:
                            reflective_due = False
                            action_due = False

                    if reflective_due and action_due:
                        # Both due — reflective supersedes
                        self._fire_reflective()
                    elif reflective_due:
                        self._fire_reflective()
                    elif action_due:
                        # Before firing action, check if reflective is nearly due
                        if self.reflective_timer.is_nearly_due(300.0):
                            # Reflective is within 5 minutes — defer action, let reflective fire
                            log_info(
                                "Action pulse deferred — reflective pulse nearly due",
                                prefix="⏱️"
                            )
                            self.action_timer.reset()
                        else:
                            self._fire_action()

            except Exception as e:
                log_error(f"Pulse manager error: {e}")

            self._stop_event.wait(1.0)

    def _fire_reflective(self) -> None:
        """Fire reflective pulse. Also resets action timer."""
        with self._processing_lock:
            self._is_pulse_processing = True

        log_info("Reflective pulse fired!", prefix="⏱️")
        self.reflective_timer.reset()
        # Reflective subsumes action — reset action timer too
        self.action_timer.reset()

        if self._on_reflective_pulse:
            try:
                self._on_reflective_pulse()
            except Exception as e:
                log_error(f"Error in reflective pulse callback: {e}")
                with self._processing_lock:
                    self._is_pulse_processing = False

    def _fire_action(self) -> None:
        """Fire action pulse. Does NOT reset reflective timer."""
        with self._processing_lock:
            self._is_pulse_processing = True

        log_info("Action pulse fired!", prefix="⏱️")
        self.action_timer.reset()

        if self._on_action_pulse:
            try:
                self._on_action_pulse()
            except Exception as e:
                log_error(f"Error in action pulse callback: {e}")
                with self._processing_lock:
                    self._is_pulse_processing = False


# ─── Legacy Compatibility ────────────────────────────────────────────────────
# These aliases allow existing code that references SystemPulseTimer or
# get_system_pulse_timer to still work during the transition.

# Type alias for backward compatibility
SystemPulseTimer = PulseManager

# ─── Global Instance ─────────────────────────────────────────────────────────

_pulse_manager: Optional[PulseManager] = None


def get_pulse_manager() -> PulseManager:
    """Get the global pulse manager instance."""
    global _pulse_manager
    if _pulse_manager is None:
        from config import (
            SYSTEM_PULSE_ENABLED,
            REFLECTIVE_PULSE_INTERVAL,
            ACTION_PULSE_INTERVAL,
        )
        _pulse_manager = PulseManager(
            reflective_interval=REFLECTIVE_PULSE_INTERVAL,
            action_interval=ACTION_PULSE_INTERVAL,
            enabled=SYSTEM_PULSE_ENABLED,
        )
    return _pulse_manager


def init_pulse_manager() -> PulseManager:
    """Initialize the global pulse manager."""
    global _pulse_manager
    from config import (
        SYSTEM_PULSE_ENABLED,
        REFLECTIVE_PULSE_INTERVAL,
        ACTION_PULSE_INTERVAL,
    )
    _pulse_manager = PulseManager(
        reflective_interval=REFLECTIVE_PULSE_INTERVAL,
        action_interval=ACTION_PULSE_INTERVAL,
        enabled=SYSTEM_PULSE_ENABLED,
    )
    return _pulse_manager


# Legacy aliases
def get_system_pulse_timer() -> PulseManager:
    """Legacy alias for get_pulse_manager()."""
    return get_pulse_manager()


def init_system_pulse_timer() -> PulseManager:
    """Legacy alias for init_pulse_manager()."""
    return init_pulse_manager()
