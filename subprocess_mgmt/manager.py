"""
Pattern Project - Subprocess Manager
Lifecycle management for child processes (audio, overlay, etc.)
"""

import subprocess
import threading
import time
import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from core.logger import log_info, log_warning, log_error, log_success


class ProcessState(Enum):
    """State of a managed process."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    RESTARTING = "restarting"


@dataclass
class ProcessConfig:
    """Configuration for a managed process."""
    name: str
    command: List[str]
    working_dir: Optional[Path] = None
    health_url: Optional[str] = None
    health_timeout: float = 5.0
    startup_timeout: float = 30.0
    max_restart_attempts: int = 3
    restart_delay: float = 2.0
    enabled: bool = True


@dataclass
class ProcessInfo:
    """Runtime information about a managed process."""
    config: ProcessConfig
    state: ProcessState = ProcessState.STOPPED
    process: Optional[subprocess.Popen] = None
    pid: Optional[int] = None
    restart_count: int = 0
    last_health_check: Optional[float] = None
    last_error: Optional[str] = None


class SubprocessManager:
    """
    Manages lifecycle of child processes.

    Features:
    - Start/stop processes
    - Health monitoring
    - Automatic restart on failure
    - Graceful shutdown
    """

    def __init__(
        self,
        health_check_interval: float = 30.0
    ):
        """
        Initialize the subprocess manager.

        Args:
            health_check_interval: Seconds between health checks
        """
        self.health_check_interval = health_check_interval
        self._processes: Dict[str, ProcessInfo] = {}
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def register(self, config: ProcessConfig) -> None:
        """
        Register a process configuration.

        Args:
            config: Process configuration
        """
        with self._lock:
            self._processes[config.name] = ProcessInfo(config=config)
            log_info(f"Registered subprocess: {config.name}", prefix="📦")

    def start(self, name: str) -> bool:
        """
        Start a registered process.

        Args:
            name: Process name

        Returns:
            True if started successfully
        """
        with self._lock:
            if name not in self._processes:
                log_error(f"Unknown process: {name}")
                return False

            info = self._processes[name]

            if not info.config.enabled:
                log_info(f"{name}: DISABLED (not configured)", prefix="⏸️")
                return False

            if info.state == ProcessState.RUNNING:
                log_warning(f"{name} is already running")
                return True

            return self._start_process(info)

    def _start_process(self, info: ProcessInfo) -> bool:
        """Internal method to start a process."""
        config = info.config
        info.state = ProcessState.STARTING

        log_info(f"Starting {config.name}...", prefix="🚀")

        try:
            # Start the process
            info.process = subprocess.Popen(
                config.command,
                cwd=config.working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            info.pid = info.process.pid

            log_success(f"{config.name} started (PID: {info.pid})")

            # Wait for health check if configured
            if config.health_url:
                if self._wait_for_health(info):
                    info.state = ProcessState.RUNNING
                    log_success(f"{config.name} is healthy and ready!")
                    return True
                else:
                    info.state = ProcessState.FAILED
                    info.last_error = "Health check failed during startup"
                    log_error(f"{config.name} failed health check")
                    return False
            else:
                info.state = ProcessState.RUNNING
                return True

        except Exception as e:
            info.state = ProcessState.FAILED
            info.last_error = str(e)
            log_error(f"Failed to start {config.name}: {e}")
            return False

    def _wait_for_health(self, info: ProcessInfo, timeout: Optional[float] = None) -> bool:
        """Wait for a process to become healthy."""
        config = info.config
        timeout = timeout or config.startup_timeout
        start_time = time.time()
        attempt = 1

        while time.time() - start_time < timeout:
            if self._check_health(info):
                return True

            log_info(
                f"Attempt {attempt} - not ready yet, retrying in 1s...",
                prefix="   "
            )
            attempt += 1
            time.sleep(1.0)

        return False

    def _check_health(self, info: ProcessInfo) -> bool:
        """Check if a process is healthy."""
        config = info.config

        # Check if process is still running
        if info.process is None:
            return False

        if info.process.poll() is not None:
            return False

        # Check health endpoint if configured
        if config.health_url:
            try:
                response = requests.get(
                    config.health_url,
                    timeout=config.health_timeout
                )
                info.last_health_check = time.time()
                return response.status_code == 200
            except Exception:
                return False

        return True

    def stop(self, name: str, timeout: float = 10.0) -> bool:
        """
        Stop a running process.

        Args:
            name: Process name
            timeout: Seconds to wait for graceful shutdown

        Returns:
            True if stopped successfully
        """
        with self._lock:
            if name not in self._processes:
                log_error(f"Unknown process: {name}")
                return False

            info = self._processes[name]

            if info.state != ProcessState.RUNNING or info.process is None:
                return True

            log_info(f"Stopping {name}...", prefix="🛑")

            try:
                # Try graceful termination
                info.process.terminate()

                try:
                    info.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    # Force kill
                    log_warning(f"{name} did not stop gracefully, killing...")
                    info.process.kill()
                    info.process.wait()

                info.state = ProcessState.STOPPED
                info.process = None
                info.pid = None

                log_success(f"{name} stopped")
                return True

            except Exception as e:
                log_error(f"Error stopping {name}: {e}")
                return False

    def stop_all(self) -> None:
        """Stop all managed processes."""
        log_info("Stopping all subprocesses...", prefix="🛑")

        for name in list(self._processes.keys()):
            self.stop(name)

    def start_monitor(self) -> None:
        """Start the health monitoring thread."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="SubprocessMonitor"
        )
        self._monitor_thread.start()
        log_info("Process monitor thread started", prefix="👁️")

    def stop_monitor(self) -> None:
        """Stop the health monitoring thread."""
        self._stop_event.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None

    def _monitor_loop(self) -> None:
        """Health monitoring loop."""
        while not self._stop_event.is_set():
            try:
                self._check_all_health()
            except Exception as e:
                log_error(f"Monitor error: {e}")

            self._stop_event.wait(self.health_check_interval)

    def _check_all_health(self) -> None:
        """Check health of all running processes."""
        with self._lock:
            for name, info in self._processes.items():
                if info.state != ProcessState.RUNNING:
                    continue

                if not self._check_health(info):
                    log_warning(f"{name} health check failed")

                    # Attempt restart
                    if info.restart_count < info.config.max_restart_attempts:
                        info.state = ProcessState.RESTARTING
                        info.restart_count += 1

                        log_info(
                            f"Restarting {name} (attempt {info.restart_count}/"
                            f"{info.config.max_restart_attempts})...",
                            prefix="🔄"
                        )

                        time.sleep(info.config.restart_delay)
                        self._start_process(info)
                    else:
                        info.state = ProcessState.FAILED
                        info.last_error = "Max restart attempts exceeded"
                        log_error(f"{name} failed after max restart attempts")

    def get_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Get status of a process."""
        with self._lock:
            if name not in self._processes:
                return None

            info = self._processes[name]
            return {
                "name": name,
                "state": info.state.value,
                "pid": info.pid,
                "enabled": info.config.enabled,
                "restart_count": info.restart_count,
                "last_error": info.last_error
            }

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all processes."""
        with self._lock:
            return {
                name: self.get_status(name)
                for name in self._processes
            }


# Global subprocess manager instance
_subprocess_manager: Optional[SubprocessManager] = None


def get_subprocess_manager() -> SubprocessManager:
    """Get the global subprocess manager instance."""
    global _subprocess_manager
    if _subprocess_manager is None:
        from config import SUBPROCESS_HEALTH_CHECK_INTERVAL
        _subprocess_manager = SubprocessManager(
            health_check_interval=SUBPROCESS_HEALTH_CHECK_INTERVAL
        )
    return _subprocess_manager


def init_subprocess_manager() -> SubprocessManager:
    """Initialize the global subprocess manager."""
    global _subprocess_manager
    from config import SUBPROCESS_HEALTH_CHECK_INTERVAL
    _subprocess_manager = SubprocessManager(
        health_check_interval=SUBPROCESS_HEALTH_CHECK_INTERVAL
    )
    return _subprocess_manager
