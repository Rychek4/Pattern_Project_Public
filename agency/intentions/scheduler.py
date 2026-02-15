"""
Pattern Project - Reminder Scheduler
Background thread that monitors intentions and fires pulse prompts when reminders become due.
"""

import threading
from datetime import datetime
from typing import Optional, Callable, List

from core.logger import log_info, log_error, log_warning
from agency.intentions.trigger_engine import get_trigger_engine, TriggerEngine
from agency.intentions.manager import Intention


# Default check interval: 30 seconds
DEFAULT_CHECK_INTERVAL = 30.0


def get_reminder_pulse_prompt(triggered_intentions: List[Intention]) -> str:
    """
    Generate a pulse prompt specifically for triggered reminders.

    Args:
        triggered_intentions: List of intentions that just triggered

    Returns:
        Formatted pulse prompt with reminder context
    """
    # Format the reminders
    reminder_lines = []
    for intention in triggered_intentions:
        context_note = f' (Context: "{intention.context}")' if intention.context else ""
        reminder_lines.append(f"  - [I-{intention.id}] {intention.content}{context_note}")

    reminders_text = "\n".join(reminder_lines)

    return f"""[AUTOMATED REMINDER PULSE - Not human input]
A scheduled reminder has triggered. You set this reminder for yourself.

TRIGGERED REMINDER{"S" if len(triggered_intentions) > 1 else ""}:
{reminders_text}

This pulse was fired by the reminder scheduler because the reminder time has arrived.
Address this reminder naturally in your response. When done, use the complete_reminder
tool (params: reminder_id, outcome). Or dismiss if no longer relevant using the
dismiss_reminder tool (params: reminder_id)."""


class ReminderScheduler:
    """
    Background scheduler that monitors intentions and fires pulses when reminders become due.

    Unlike the idle-based SystemPulseTimer, this scheduler actively watches for
    time-based intentions and fires a pulse prompt exactly when they trigger,
    ensuring reminders are delivered even if the user hasn't messaged.

    Features:
    - Runs as daemon thread, checking every 30 seconds
    - Fires reminder-specific pulse prompts when intentions trigger
    - Reads from database, so survives app restarts
    - Integrates with existing pulse infrastructure
    """

    def __init__(
        self,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        enabled: bool = True,
        on_reminder_pulse: Optional[Callable[[List[Intention]], None]] = None
    ):
        """
        Initialize the reminder scheduler.

        Args:
            check_interval: Seconds between checks (default 30)
            enabled: Whether the scheduler is active
            on_reminder_pulse: Callback when reminders trigger (receives list of triggered intentions)
        """
        self.check_interval = check_interval
        self.enabled = enabled
        self._on_reminder_pulse = on_reminder_pulse

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._trigger_engine: Optional[TriggerEngine] = None

    def start(self) -> None:
        """Start the reminder scheduler thread."""
        if not self.enabled:
            log_info("Reminder scheduler disabled", prefix="⏰")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._trigger_engine = get_trigger_engine()

        self._thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="ReminderScheduler"
        )
        self._thread.start()
        log_info(f"Reminder scheduler started (checking every {self.check_interval}s)", prefix="⏰")

    def stop(self) -> None:
        """Stop the reminder scheduler thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Reminder scheduler stopped", prefix="⏰")

    def set_callback(self, callback: Callable[[List[Intention]], None]) -> None:
        """Set the callback function for when reminders trigger."""
        self._on_reminder_pulse = callback

    def is_running(self) -> bool:
        """Check if the scheduler thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def _scheduler_loop(self) -> None:
        """Main scheduler loop - checks for due intentions periodically."""
        while not self._stop_event.is_set():
            try:
                self._check_reminders()
            except Exception as e:
                log_error(f"Reminder scheduler error: {e}")

            # Wait for next check interval (or until stop is requested)
            self._stop_event.wait(self.check_interval)

    def _check_reminders(self) -> None:
        """Check for triggered reminders and fire pulse if any are due."""
        if self._trigger_engine is None:
            return

        now = datetime.now()

        # Check and trigger any due intentions
        newly_triggered = self._trigger_engine.check_and_trigger(now, is_session_start=False)

        if newly_triggered:
            log_info(
                f"Reminder scheduler: {len(newly_triggered)} reminder(s) triggered",
                prefix="⏰"
            )

            # Fire the callback with triggered intentions
            if self._on_reminder_pulse:
                try:
                    self._on_reminder_pulse(newly_triggered)
                except Exception as e:
                    log_error(f"Error in reminder pulse callback: {e}")


# Global scheduler instance
_reminder_scheduler: Optional[ReminderScheduler] = None


def get_reminder_scheduler() -> ReminderScheduler:
    """Get the global reminder scheduler instance."""
    global _reminder_scheduler
    if _reminder_scheduler is None:
        _reminder_scheduler = ReminderScheduler()
    return _reminder_scheduler


def init_reminder_scheduler(
    check_interval: float = DEFAULT_CHECK_INTERVAL,
    enabled: bool = True,
    on_reminder_pulse: Optional[Callable[[List[Intention]], None]] = None
) -> ReminderScheduler:
    """
    Initialize the global reminder scheduler.

    Args:
        check_interval: Seconds between checks
        enabled: Whether scheduler is active
        on_reminder_pulse: Callback when reminders trigger

    Returns:
        The initialized ReminderScheduler instance
    """
    global _reminder_scheduler
    _reminder_scheduler = ReminderScheduler(
        check_interval=check_interval,
        enabled=enabled,
        on_reminder_pulse=on_reminder_pulse
    )
    return _reminder_scheduler
