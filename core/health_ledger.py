"""
Pattern Project - Health Ledger
Rotating error log for system health monitoring.

Records errors/warnings/criticals from all subsystems to a JSONL file
with a configurable max-line ring buffer. The AI reads this file via
the health_check tool for situational infrastructure awareness.

Errors are also emitted to stderr so they appear in journalctl.
"""

import json
import logging
import os
import sys
import threading
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import config


# Severity levels
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITY_CRITICAL = "critical"
_VALID_SEVERITIES = {SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL}

# Stderr logger for journalctl visibility
_stderr_logger = logging.getLogger("pattern.health")
_stderr_logger.setLevel(logging.WARNING)
if not _stderr_logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.WARNING)
    _handler.setFormatter(logging.Formatter(
        "HEALTH %(levelname)s [%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _stderr_logger.addHandler(_handler)
    _stderr_logger.propagate = False

# Map severity to logging level
_SEVERITY_TO_LEVEL = {
    SEVERITY_WARNING: logging.WARNING,
    SEVERITY_ERROR: logging.ERROR,
    SEVERITY_CRITICAL: logging.CRITICAL,
}


class HealthLedger:
    """
    Singleton rotating error ledger.

    Writes JSON lines to a file. When the file exceeds max_lines,
    it trims to keep the most recent entries. Consecutive duplicate
    errors from the same system are coalesced with an incrementing count.
    """

    def __init__(self, file_path: Path, max_lines: int = 400):
        self._file_path = file_path
        self._max_lines = max_lines
        self._trim_threshold = int(max_lines * 1.25)  # Trim at 500 if max is 400
        self._lock = threading.Lock()
        self._last_entry: Optional[Dict[str, Any]] = None
        self._started_at = datetime.now().isoformat()

        # Ensure directory exists
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        system: str,
        severity: str,
        message: str,
    ) -> None:
        """
        Record a health event.

        Args:
            system: Subsystem name (e.g., "llm", "database", "telegram")
            severity: One of "warning", "error", "critical"
            message: Human-readable error description
        """
        if severity not in _VALID_SEVERITIES:
            severity = SEVERITY_ERROR

        timestamp = datetime.now().isoformat()

        # Emit to stderr for journalctl
        log_level = _SEVERITY_TO_LEVEL.get(severity, logging.ERROR)
        _stderr_logger.log(log_level, "[%s] %s", system, message)

        with self._lock:
            try:
                # Deduplication: coalesce consecutive identical errors
                if (self._last_entry
                        and self._last_entry["system"] == system
                        and self._last_entry["severity"] == severity
                        and self._last_entry["message"] == message):
                    self._last_entry["count"] += 1
                    self._last_entry["last_seen"] = timestamp
                    self._rewrite_last_entry()
                    return

                entry = {
                    "timestamp": timestamp,
                    "system": system,
                    "severity": severity,
                    "message": message,
                    "count": 1,
                }
                self._last_entry = entry

                # Append to file
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")

                # Trim if over threshold
                self._maybe_trim()

            except Exception:
                # The ledger must never break the caller
                pass

    def read_summary(self) -> str:
        """
        Read the ledger and return a structured summary for the AI.

        Returns a human-readable health report with per-system status,
        recent error counts, and the last N critical/error entries.
        """
        with self._lock:
            entries = self._read_all_entries()

        if not entries:
            return (
                f"SYSTEM HEALTH REPORT\n"
                f"Uptime since: {self._started_at}\n\n"
                f"Status: All systems healthy. No errors recorded."
            )

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        twenty_four_hours_ago = now - timedelta(hours=24)

        # Per-system aggregation
        systems: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            sys_name = entry.get("system", "unknown")
            if sys_name not in systems:
                systems[sys_name] = {
                    "last_1h": 0,
                    "last_24h": 0,
                    "total": 0,
                    "worst_severity": SEVERITY_WARNING,
                    "last_error": None,
                }
            info = systems[sys_name]
            count = entry.get("count", 1)
            info["total"] += count

            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= one_hour_ago:
                    info["last_1h"] += count
                if ts >= twenty_four_hours_ago:
                    info["last_24h"] += count
            except (ValueError, KeyError):
                pass

            # Track worst severity
            sev = entry.get("severity", SEVERITY_WARNING)
            if sev == SEVERITY_CRITICAL:
                info["worst_severity"] = SEVERITY_CRITICAL
            elif sev == SEVERITY_ERROR and info["worst_severity"] != SEVERITY_CRITICAL:
                info["worst_severity"] = SEVERITY_ERROR

            info["last_error"] = entry

        # Build report
        lines = [
            "SYSTEM HEALTH REPORT",
            f"Uptime since: {self._started_at}",
            f"Ledger entries: {len(entries)}",
            "",
            "--- PER-SYSTEM STATUS ---",
        ]

        severity_rank = {SEVERITY_WARNING: 0, SEVERITY_ERROR: 1, SEVERITY_CRITICAL: 2}
        sorted_systems = sorted(
            systems.items(),
            key=lambda x: severity_rank.get(x[1]["worst_severity"], 0),
            reverse=True,
        )

        for sys_name, info in sorted_systems:
            status = "HEALTHY"
            if info["worst_severity"] == SEVERITY_CRITICAL:
                status = "CRITICAL"
            elif info["worst_severity"] == SEVERITY_ERROR:
                if info["last_1h"] > 0:
                    status = "DEGRADED"
                else:
                    status = "RECOVERED"

            lines.append(
                f"  {sys_name}: {status} "
                f"(1h: {info['last_1h']}, 24h: {info['last_24h']}, total: {info['total']})"
            )

        # Recent critical/error entries (last 20)
        recent_important = [
            e for e in entries
            if e.get("severity") in (SEVERITY_ERROR, SEVERITY_CRITICAL)
        ][-20:]

        if recent_important:
            lines.append("")
            lines.append("--- RECENT ERRORS (newest last) ---")
            for entry in recent_important:
                count_str = f" (x{entry['count']})" if entry.get("count", 1) > 1 else ""
                lines.append(
                    f"  [{entry.get('timestamp', '?')}] "
                    f"{entry.get('severity', '?').upper()} "
                    f"[{entry.get('system', '?')}] "
                    f"{entry.get('message', '?')}{count_str}"
                )

        return "\n".join(lines)

    def _rewrite_last_entry(self) -> None:
        """Rewrite the last line of the file with the updated count."""
        try:
            all_lines = self._file_path.read_text(encoding="utf-8").splitlines()
            if all_lines:
                all_lines[-1] = json.dumps(self._last_entry)
                self._file_path.write_text(
                    "\n".join(all_lines) + "\n", encoding="utf-8"
                )
        except Exception:
            pass

    def _maybe_trim(self) -> None:
        """Trim the file to max_lines if it exceeds the threshold."""
        try:
            all_lines = self._file_path.read_text(encoding="utf-8").splitlines()
            if len(all_lines) > self._trim_threshold:
                trimmed = all_lines[-self._max_lines:]
                # Atomic write: temp file + os.replace
                dir_path = self._file_path.parent
                fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write("\n".join(trimmed) + "\n")
                    os.replace(tmp_path, self._file_path)
                except Exception:
                    # Clean up temp file on failure
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        except Exception:
            pass

    def _read_all_entries(self) -> List[Dict[str, Any]]:
        """Read and parse all JSONL entries from the ledger file."""
        entries = []
        try:
            if not self._file_path.exists():
                return entries
            for line in self._file_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return entries


# ─── Global Instance ────────────────────────────────────────────────────────

_ledger: Optional[HealthLedger] = None


def get_health_ledger() -> HealthLedger:
    """Get the global health ledger instance."""
    global _ledger
    if _ledger is None:
        file_path = getattr(config, 'HEALTH_LEDGER_PATH', config.LOGS_DIR / "health_ledger.jsonl")
        max_lines = getattr(config, 'HEALTH_LEDGER_MAX_LINES', 400)
        _ledger = HealthLedger(file_path=file_path, max_lines=max_lines)
    return _ledger


def record_health_event(system: str, severity: str, message: str) -> None:
    """Convenience function to record a health event."""
    get_health_ledger().record(system, severity, message)
