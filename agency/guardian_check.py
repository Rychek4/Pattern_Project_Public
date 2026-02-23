"""
Pattern Project - Guardian Health Check
Periodically verifies Guardian watchdog is alive and respawns it if needed.

Guardian is an external watchdog process that monitors Pattern's health
and restarts it on failure. Pattern reciprocally checks that Guardian
is alive, creating a mutual supervision loop.

The check is simple and lightweight:
1. Read the heartbeat file Guardian writes
2. Verify Guardian's PID is a running process
3. Verify the heartbeat timestamp is recent
4. If Guardian is missing, spawn it
"""

import os
import json
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from core.logger import log_info, log_warning, log_error, log_success


class GuardianChecker:
    """
    Monitors Guardian's liveness and respawns it if needed.

    Guardian writes a heartbeat file at a regular interval. This checker
    reads that file and verifies the PID is alive and the timestamp is
    recent. If Guardian is not running, this spawns it as a detached
    process that survives Pattern's own death.
    """

    def __init__(
        self,
        heartbeat_path: Path,
        guardian_executable: str,
        guardian_config: str,
        check_interval: float = 300.0,
        max_heartbeat_age_seconds: float = 120.0,
        enabled: bool = True
    ):
        self.heartbeat_path = heartbeat_path
        self.guardian_executable = guardian_executable
        self.guardian_config = guardian_config
        self.check_interval = check_interval
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds
        self.enabled = enabled

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_check_result: Optional[Dict[str, Any]] = None

    # ── Lifecycle ──

    def start(self) -> None:
        """Start the periodic guardian check thread."""
        if not self.enabled:
            log_info("Guardian checker disabled", prefix="🛡️")
            return

        if not self.guardian_executable:
            log_warning(
                "Guardian checker enabled but GUARDIAN_EXECUTABLE_PATH not configured. "
                "Guardian cannot be spawned automatically."
            )
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._check_loop,
            daemon=True,
            name="GuardianChecker"
        )
        self._thread.start()
        log_info(
            f"Guardian checker started (interval: {self.check_interval}s)",
            prefix="🛡️"
        )

    def stop(self) -> None:
        """Stop the periodic guardian check thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Guardian checker stopped", prefix="🛡️")

    # ── One-shot check (called on startup and periodically) ──

    def check_guardian(self) -> bool:
        """
        Check if Guardian is alive. Returns True if healthy, False if not.

        This is the main check method, usable both for the startup check
        and for periodic background checks.
        """
        if not self.enabled:
            return True  # Not our concern if disabled

        result = {
            "timestamp": datetime.now().isoformat(),
            "heartbeat_exists": False,
            "pid_alive": False,
            "heartbeat_fresh": False,
            "guardian_healthy": False,
            "action_taken": None
        }

        try:
            # Step 1: Read heartbeat file
            if not self.heartbeat_path.exists():
                result["action_taken"] = "no_heartbeat_file"
                log_warning(
                    "Guardian heartbeat file not found. "
                    "Guardian may not be running.",
                    prefix="🛡️"
                )
                self._last_check_result = result
                self._try_spawn_guardian(reason="heartbeat file missing")
                return False

            result["heartbeat_exists"] = True

            # Step 2: Parse heartbeat
            heartbeat = self._read_heartbeat()
            if heartbeat is None:
                result["action_taken"] = "heartbeat_unreadable"
                self._last_check_result = result
                self._try_spawn_guardian(reason="heartbeat file unreadable")
                return False

            guardian_pid = heartbeat.get("guardian_pid")
            last_heartbeat_str = heartbeat.get("last_heartbeat")

            # Step 3: Check PID is alive
            if guardian_pid and self._is_process_alive(guardian_pid):
                result["pid_alive"] = True
            else:
                result["action_taken"] = "pid_dead"
                log_warning(
                    f"Guardian PID {guardian_pid} is not running.",
                    prefix="🛡️"
                )
                self._last_check_result = result
                self._try_spawn_guardian(reason=f"PID {guardian_pid} not found")
                return False

            # Step 4: Check heartbeat freshness
            if last_heartbeat_str:
                try:
                    last_heartbeat = datetime.fromisoformat(last_heartbeat_str)
                    age = (datetime.now() - last_heartbeat).total_seconds()

                    if age <= self.max_heartbeat_age_seconds:
                        result["heartbeat_fresh"] = True
                        result["guardian_healthy"] = True
                    else:
                        result["action_taken"] = "heartbeat_stale"
                        log_warning(
                            f"Guardian heartbeat is {age:.0f}s old "
                            f"(max: {self.max_heartbeat_age_seconds}s). "
                            f"Guardian may be hung.",
                            prefix="🛡️"
                        )
                        # PID alive but heartbeat stale — Guardian may be hung.
                        # Don't kill it immediately; just log. If the PID dies
                        # on its own, next check will respawn.
                        self._last_check_result = result
                        return False

                except (ValueError, TypeError):
                    result["action_taken"] = "heartbeat_parse_error"
                    log_warning(
                        f"Could not parse Guardian heartbeat timestamp: "
                        f"{last_heartbeat_str}",
                        prefix="🛡️"
                    )

            self._last_check_result = result

            if result["guardian_healthy"]:
                log_info("Guardian is healthy", prefix="🛡️")

            return result["guardian_healthy"]

        except Exception as e:
            log_error(f"Error checking Guardian health: {e}")
            result["action_taken"] = f"error: {e}"
            self._last_check_result = result
            return False

    # ── Internal helpers ──

    def _read_heartbeat(self) -> Optional[Dict[str, Any]]:
        """Read and parse the Guardian heartbeat file."""
        try:
            with open(self.heartbeat_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log_warning(f"Could not read Guardian heartbeat: {e}")
            return None

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with the given PID exists."""
        try:
            # Signal 0 doesn't actually send a signal — it just checks
            # if the process exists and we have permission to signal it.
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we can't signal it (different user).
            # This shouldn't happen in normal operation but means
            # the PID is alive.
            return True
        except OSError:
            return False

    def _try_spawn_guardian(self, reason: str) -> None:
        """
        Attempt to spawn Guardian as a detached process.

        Uses start_new_session=True to ensure Guardian survives
        if Pattern crashes or is restarted.
        """
        if not self.guardian_executable:
            log_warning(
                f"Cannot spawn Guardian ({reason}): "
                f"GUARDIAN_EXECUTABLE_PATH not configured",
                prefix="🛡️"
            )
            return

        executable_path = Path(self.guardian_executable)
        if not executable_path.exists():
            log_error(
                f"Cannot spawn Guardian: executable not found at "
                f"{self.guardian_executable}",
                prefix="🛡️"
            )
            return

        try:
            cmd = ["python", str(executable_path)]
            if self.guardian_config:
                cmd.extend(["--config", str(self.guardian_config)])

            log_info(
                f"Spawning Guardian ({reason}): {' '.join(cmd)}",
                prefix="🛡️"
            )

            # start_new_session=True creates a new process group.
            # This is critical: if Pattern dies, Guardian must survive.
            process = subprocess.Popen(
                cmd,
                cwd=str(executable_path.parent),
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            log_success(
                f"Guardian spawned (PID: {process.pid})",
                prefix="🛡️"
            )

        except Exception as e:
            log_error(f"Failed to spawn Guardian: {e}", prefix="🛡️")

    def _check_loop(self) -> None:
        """Background loop that checks Guardian periodically."""
        # Wait a bit on first run to let Guardian start if it was
        # launched alongside Pattern
        self._stop_event.wait(30.0)

        while not self._stop_event.is_set():
            try:
                self.check_guardian()
            except Exception as e:
                log_error(f"Guardian check loop error: {e}")

            self._stop_event.wait(self.check_interval)

    # ── Status ──

    def get_status(self) -> Dict[str, Any]:
        """Get the last check result for display/logging."""
        return {
            "enabled": self.enabled,
            "guardian_executable": self.guardian_executable,
            "heartbeat_path": str(self.heartbeat_path),
            "check_interval": self.check_interval,
            "last_check": self._last_check_result
        }


# ── Global instance ─────────────────────────────────────────────────────────

_guardian_checker: Optional[GuardianChecker] = None


def get_guardian_checker() -> GuardianChecker:
    """Get the global guardian checker instance."""
    global _guardian_checker
    if _guardian_checker is None:
        _guardian_checker = _create_guardian_checker()
    return _guardian_checker


def init_guardian_checker() -> GuardianChecker:
    """Initialize the global guardian checker."""
    global _guardian_checker
    _guardian_checker = _create_guardian_checker()
    return _guardian_checker


def _create_guardian_checker() -> GuardianChecker:
    """Create a GuardianChecker from config values."""
    import config

    heartbeat_path = getattr(config, "GUARDIAN_HEARTBEAT_PATH", config.DATA_DIR / "guardian_heartbeat.json")
    executable = getattr(config, "GUARDIAN_EXECUTABLE_PATH", "")
    config_path = getattr(config, "GUARDIAN_CONFIG_PATH", "")
    check_interval = getattr(config, "GUARDIAN_CHECK_INTERVAL", 300.0)
    enabled = getattr(config, "GUARDIAN_ENABLED", True)

    return GuardianChecker(
        heartbeat_path=heartbeat_path,
        guardian_executable=executable,
        guardian_config=config_path,
        check_interval=check_interval,
        enabled=enabled
    )
