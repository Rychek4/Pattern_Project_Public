# Guardian: Process Watchdog for Pattern Project

## Specification for External Implementation

**Version:** 1.0
**Date:** 2026-02-23
**Context:** This document is written by a Claude Code instance with full access to Pattern Project's codebase. It provides everything needed to build Guardian as a standalone project in a separate repository. Guardian and Pattern are two halves of a self-sustaining system — neither should require human intervention to keep the other alive.

---

## 1. What Guardian Is

Guardian is a **minimal, independent watchdog process** that ensures Pattern Project stays running and healthy. It is the simplest possible program that can supervise a complex one.

**The contract:** If Pattern is running and healthy, Guardian does nothing. If Pattern is not running, Guardian starts it. If Pattern is running but unhealthy, Guardian restarts it. If Pattern's state is corrupted, Guardian repairs it before restarting.

**The constraint:** Guardian must be simple enough that it effectively cannot fail in interesting ways. If Guardian has bugs, they should be obvious, not subtle. No external dependencies. No API keys. No network calls. No database access (except SQLite integrity checks). No Python package requirements beyond the standard library.

---

## 2. What Guardian Is NOT

- **Not a feature of Pattern.** Guardian is a separate process, separate repository, separate codebase. It shares no imports, no modules, no runtime state with Pattern.
- **Not an orchestrator.** Guardian does not make decisions about Pattern's behavior. It does not configure Pattern, update Pattern, or interpret Pattern's output.
- **Not complex.** If you find yourself importing `requests`, `flask`, `anthropic`, or anything not in Python's standard library, you've gone wrong.

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Operating System                       │
│                                                           │
│  ┌──────────────┐              ┌──────────────────────┐  │
│  │   Guardian    │──watches───>│   Pattern Project    │  │
│  │              │              │                      │  │
│  │  - PID check │              │  main.py (Web/CLI)   │  │
│  │  - Heartbeat │              │  HTTP API :5000      │  │
│  │  - Resources │              │  SQLite DB           │  │
│  │  - DB safety │              │  Background threads  │  │
│  │              │              │                      │  │
│  └──────┬───────┘              └──────────┬───────────┘  │
│         │                                 │              │
│         │         Pattern checks          │              │
│         │<────Guardian PID alive?──────────│              │
│         │         (simple, rare)           │              │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

**Guardian watches Pattern (comprehensive, continuous).**
**Pattern watches Guardian (simple, occasional — just "is the process alive?").**

---

## 4. Pattern Project: What Guardian Needs to Know

### 4.1 How to Start Pattern

Pattern is a Python application launched from its project root:

```bash
# Web mode (default) — browser interface
cd /home/user/Pattern_Project
python main.py

# CLI mode — console interface
cd /home/user/Pattern_Project
python main.py --cli
```

**Important startup behavior:**
- Pattern uses `python main.py` (no virtualenv activation needed if system Python has dependencies)
- If a virtualenv exists, Guardian should activate it: `source /home/user/Pattern_Project/venv/bin/activate && python main.py`
- Pattern creates `data/` and `logs/` directories on first run
- Pattern requires `ANTHROPIC_API_KEY` in the environment (loaded from `.env` file via `python-dotenv`)
- Pattern's database is at `data/pattern.db` (SQLite with WAL mode)
- Pattern logs to `logs/diagnostic.log`

**Startup takes time.** Pattern loads an embedding model (`all-MiniLM-L6-v2`, ~80MB), initializes its database, and starts background threads. Expect 10-30 seconds before the health endpoint responds.

### 4.2 How to Know Pattern Is Alive

**Layer 1: Process alive (PID check)**

Pattern runs as a single Python process. Guardian should track its PID after launching it. Standard process liveness check: does the PID exist and is it a Python process?

**Layer 2: Application healthy (HTTP health endpoint)**

Pattern runs an HTTP API on `127.0.0.1:5000` (configurable via `HTTP_HOST` and `HTTP_PORT` environment variables, but defaults are fine).

Health endpoint:
```
GET http://127.0.0.1:5000/health
```

Response when healthy:
```json
{"status": "healthy", "service": "pattern-project"}
```

**The health endpoint is lightweight.** It does not touch the database or do any computation. A 200 response means Flask is running and the application initialized successfully.

**HTTP is enabled by default** (`HTTP_ENABLED = True` in config.py). If for some reason the HTTP server fails to start, Pattern still runs — it just won't have the health endpoint. Guardian should treat "process alive but no health response" differently from "process dead."

**Layer 3: Application functional (stats endpoint)**

For deeper health checking:
```
GET http://127.0.0.1:5000/stats
```

Response:
```json
{
  "database": {
    "total_sessions": 42,
    "active_sessions": 1,
    "total_conversations": 1500,
    "total_memories": 350,
    "core_memories": 25,
    "unprocessed_conversations": 15
  },
  "session": {
    "active": true,
    "session_id": 42,
    "turns_this_session": 5,
    "duration_seconds": 1200.0
  },
  "extractor": {
    "total_extractions": 100,
    "extraction_in_progress": false
  }
}
```

This hits the database and returns real statistics. If this endpoint returns valid JSON, Pattern is genuinely functional.

### 4.3 How to Know Pattern Needs Restarting

Guardian should consider Pattern unhealthy if:

1. **Process is dead** — PID no longer exists
2. **Health endpoint unreachable** — After the startup grace period (60 seconds), `GET /health` fails for N consecutive checks (recommend N=3 with 30-second intervals = 90 seconds of failure before action)
3. **Stats endpoint returns errors** — `GET /stats` returns 500 or invalid JSON repeatedly

Guardian should NOT restart Pattern for:
- Temporary API failures (Pattern handles its own LLM retry/failover internally)
- High memory usage alone (Pattern loads ML models that use significant RAM)
- Long response times on the stats endpoint (database operations can be slow under load)

### 4.4 Pattern's Database: What Guardian Must Protect

**Database path:** `/home/user/Pattern_Project/data/pattern.db`

**WAL mode:** Pattern uses SQLite WAL (Write-Ahead Logging). This means there are typically three files:
- `pattern.db` — Main database
- `pattern.db-wal` — Write-ahead log
- `pattern.db-shm` — Shared memory file

**CRITICAL: Never delete `-wal` or `-shm` files while Pattern is running.** These contain uncommitted data.

**Before restarting Pattern, Guardian must verify:**
1. Pattern's process is fully stopped (not just signaled — wait for exit)
2. The `-wal` file is either:
   - Absent (clean shutdown), OR
   - Present but Pattern's process is confirmed dead (WAL will be replayed on next open)
3. No other process has the database locked

**Database integrity check (run ONLY when Pattern is stopped):**
```bash
sqlite3 /home/user/Pattern_Project/data/pattern.db "PRAGMA integrity_check;"
```
Expected output: `ok`

If integrity check fails, Guardian should:
1. Log the failure
2. Copy the corrupted database to `pattern.db.corrupt.TIMESTAMP`
3. Attempt to recover: `sqlite3 pattern.db ".recover" | sqlite3 pattern_recovered.db`
4. If recovery succeeds, replace the original
5. If recovery fails, Pattern will need to start fresh (this is a catastrophic failure — log prominently)

### 4.5 Pattern's Log File

**Log path:** `/home/user/Pattern_Project/logs/diagnostic.log`

Pattern writes to this file continuously. Guardian can monitor it for:
- Fatal errors: lines containing `CRITICAL` or `Fatal error:`
- Database errors: lines containing `DatabaseRetryExhausted` or `Migration failed`
- Extraction stalls: lines containing `Extraction stalled - manual intervention required`

**Log rotation:** Pattern does not rotate its own logs. Guardian should implement simple log rotation:
- When `diagnostic.log` exceeds 50MB, rotate to `diagnostic.log.1` (keep only 1 backup)
- This prevents disk exhaustion on long-running deployments

### 4.6 Pattern's Process Model

Pattern runs everything in a single process with multiple daemon threads:

| Thread Name | Purpose | Failure Impact |
|---|---|---|
| `MainThread` | Web server or CLI input loop | Process dies |
| `MemoryExtraction` | Background memory extraction (triggered, not persistent) | Memories accumulate but don't extract |
| `PulseManager` | Reflective + action pulse timers | AI loses autonomous agency |
| `ReminderScheduler` | Checks for due intentions every 30s | Reminders don't fire |
| `SubprocessMonitor` | Health checks child processes every 30s | Child processes unmonitored |
| `HTTPServer` | Flask on :5000 | Health endpoint unreachable |
| `TelegramListener` | Optional: polls Telegram for messages | Telegram interface down |

**All background threads are daemon threads.** If the main thread exits, they all stop immediately. This means Pattern shuts down completely when the main process exits — there are no orphan threads to worry about.

### 4.7 Pattern's Shutdown

Pattern handles SIGINT and SIGTERM gracefully:

1. Waits for in-progress memory extraction to complete (5-second timeout)
2. Stops pulse manager
3. Stops reminder scheduler
4. Unloads STT model
5. Releases webcam
6. Stops subprocess manager
7. Stops Telegram listener
8. Logs final lock statistics

**Guardian should stop Pattern with SIGTERM first.** Wait 15 seconds for graceful shutdown. If the process is still alive, send SIGKILL.

```python
# Pseudocode for stopping Pattern
os.kill(pid, signal.SIGTERM)
wait_for_exit(pid, timeout=15)
if still_alive(pid):
    os.kill(pid, signal.SIGKILL)
    wait_for_exit(pid, timeout=5)
```

### 4.8 Environment Requirements

Pattern needs these environment variables (typically loaded from `.env`):

**Required:**
- `ANTHROPIC_API_KEY` — Claude API key

**Optional but common:**
- `OPENAI_API_KEY` — For TTS
- `TELEGRAM_ENABLED`, `telegram_bot`, `TELEGRAM_CHAT_ID` — Telegram bot
- `HTTP_HOST`, `HTTP_PORT` — HTTP API binding (defaults: 127.0.0.1:5000)

Guardian should preserve Pattern's environment. The simplest approach: launch Pattern from its project directory where `.env` lives, and let `python-dotenv` handle the rest.

---

## 5. Guardian's Design

### 5.1 Configuration

Guardian should use a single configuration file (`guardian.toml` or `guardian.json`):

```toml
[pattern]
# Path to Pattern Project root directory
project_dir = "/home/user/Pattern_Project"

# Command to launch Pattern
# Guardian will cd to project_dir before running this
launch_command = "python main.py --cli"

# If Pattern uses a virtualenv, specify the activate script path
# Leave empty if using system Python
virtualenv_activate = ""

# Health check endpoint
health_url = "http://127.0.0.1:5000/health"
stats_url = "http://127.0.0.1:5000/stats"

# How long to wait after starting Pattern before expecting health endpoint
startup_grace_seconds = 60

[guardian]
# How often to check Pattern's health (seconds)
check_interval = 30

# How many consecutive health failures before restarting
max_consecutive_failures = 3

# How long to wait for graceful shutdown (seconds)
shutdown_timeout = 15

# Log file path
log_file = "/home/user/Pattern_Project/logs/guardian.log"

# Maximum size of Pattern's diagnostic.log before rotation (bytes)
# 0 = disable log rotation
log_rotation_max_bytes = 52428800  # 50MB

[recovery]
# Escalation levels (tried in order)
# Level 1: Soft restart (SIGTERM + wait + start)
# Level 2: Hard restart (SIGKILL + start)
# Level 3: Database integrity check + restart
# Level 4: Database recovery + restart

# Cooldown between restart attempts (seconds)
# Prevents restart loops
restart_cooldown = 60

# Maximum restarts within a window before Guardian stops trying
max_restarts_per_hour = 5

# If Pattern fails this many times in a row, enter "failed" state
# In failed state, Guardian logs but does not restart
# Pattern must be manually restarted (or Guardian restarted) to exit this state
max_consecutive_restart_failures = 10
```

### 5.2 State Machine

Guardian should operate as a simple state machine:

```
                    ┌─────────┐
        ┌──────────>│ STARTING │
        │           └─────┬───┘
        │                 │ health OK
        │                 ▼
        │           ┌─────────┐
        │     ┌────>│ HEALTHY  │<────┐
        │     │     └─────┬───┘     │
        │     │           │ health  │ health
        │     │           │ failure │ recovery
        │     │           ▼         │
        │     │     ┌──────────┐    │
        │     │     │ DEGRADED │────┘
        │     │     └─────┬────┘
        │     │           │ N consecutive
        │     │           │ failures
        │     │           ▼
        │     │     ┌───────────┐
        │     └─────│ RESTARTING│
        │           └─────┬─────┘
        │                 │ restart
        │                 │ failed
        │                 ▼
        │           ┌──────────┐
        └───────────│  FAILED  │ (requires intervention
                    └──────────┘  or Guardian restart)
```

**States:**

| State | Meaning | Guardian Action |
|---|---|---|
| `STARTING` | Pattern was just launched, waiting for health | Wait up to `startup_grace_seconds`, then check health |
| `HEALTHY` | Pattern is running and health endpoint responds | Check every `check_interval` seconds |
| `DEGRADED` | Health check failed but under consecutive failure threshold | Continue checking, increment failure counter |
| `RESTARTING` | Pattern is being stopped and restarted | Execute restart sequence with escalation |
| `FAILED` | Too many consecutive restart failures | Log prominently, stop restarting, wait for manual intervention or Guardian restart |

### 5.3 Restart Escalation Sequence

When Guardian decides to restart Pattern, it should escalate through these levels:

**Level 1: Soft Restart**
1. Send SIGTERM to Pattern
2. Wait `shutdown_timeout` seconds
3. Verify process exited
4. Start Pattern
5. Wait for health

**Level 2: Hard Restart** (if Level 1 fails)
1. Send SIGKILL to Pattern
2. Wait 5 seconds
3. Verify process exited
4. Start Pattern
5. Wait for health

**Level 3: State Check + Restart** (if Level 2 fails or Pattern crashes repeatedly)
1. Kill Pattern (SIGKILL if needed)
2. Wait for full exit
3. Run `sqlite3 data/pattern.db "PRAGMA integrity_check;"`
4. If integrity OK → start Pattern
5. If integrity FAIL → proceed to Level 4

**Level 4: Database Recovery** (if integrity check fails)
1. Copy `data/pattern.db` to `data/pattern.db.corrupt.YYYYMMDD_HHMMSS`
2. Attempt recovery: `sqlite3 data/pattern.db ".recover" | sqlite3 data/pattern_recovered.db`
3. If recovery succeeds: `mv data/pattern_recovered.db data/pattern.db`
4. Delete leftover `-wal` and `-shm` files (they're from the corrupt database)
5. Start Pattern
6. If recovery fails: enter FAILED state

### 5.4 Resource Monitoring

Guardian should monitor basic system resources to pre-empt catastrophic failures:

**Disk space:**
- Check free space on Pattern's data directory
- If free space < 100MB, log a warning
- If free space < 20MB, enter a proactive shutdown: stop Pattern gracefully, rotate logs, then restart
- Pattern's database can grow large (hundreds of MB with many memories + embeddings)

**Memory (optional but recommended):**
- Monitor Pattern's RSS memory usage via `/proc/{pid}/status`
- Pattern typically uses 500MB-2GB (embedding model alone is ~200MB)
- If RSS exceeds a configurable threshold (default: 4GB), log a warning
- Do NOT restart based on memory alone — Pattern legitimately uses a lot of memory

### 5.5 Guardian's Own Logging

Guardian should log to its own file (`guardian.log`) in a simple, parseable format:

```
2026-02-23 14:30:00 [INFO] Guardian started, monitoring Pattern at /home/user/Pattern_Project
2026-02-23 14:30:00 [INFO] Pattern PID: 12345, state: STARTING
2026-02-23 14:30:30 [INFO] Health check OK (200), state: HEALTHY
2026-02-23 16:45:30 [WARN] Health check failed: ConnectionRefused, consecutive failures: 1
2026-02-23 16:46:00 [WARN] Health check failed: ConnectionRefused, consecutive failures: 2
2026-02-23 16:46:30 [WARN] Health check failed: ConnectionRefused, consecutive failures: 3
2026-02-23 16:46:30 [INFO] Entering RESTARTING state (Level 1: Soft Restart)
2026-02-23 16:46:30 [INFO] Sent SIGTERM to PID 12345
2026-02-23 16:46:35 [INFO] Pattern exited (code 0)
2026-02-23 16:46:35 [INFO] Starting Pattern...
2026-02-23 16:46:35 [INFO] Pattern PID: 12400, state: STARTING
2026-02-23 16:47:35 [INFO] Health check OK (200), state: HEALTHY
```

**Guardian should NOT use any external logging libraries.** Python's built-in `logging` module is sufficient.

### 5.6 Heartbeat File (Bidirectional Awareness)

Guardian should maintain a heartbeat file that Pattern can check:

**Guardian writes:** `/home/user/Pattern_Project/data/guardian_heartbeat.json`

```json
{
  "guardian_pid": 9999,
  "last_heartbeat": "2026-02-23T14:30:00",
  "pattern_pid": 12345,
  "pattern_state": "HEALTHY",
  "restarts_this_hour": 0,
  "guardian_uptime_seconds": 3600
}
```

Guardian updates this file every `check_interval` seconds. Pattern reads it to verify Guardian is alive (see Section 6).

**Important:** This file must be written atomically (write to temp file, then rename) to prevent Pattern from reading a partial write.

---

## 6. Pattern's Side: Guardian Health Check

Pattern needs a lightweight function that periodically checks if Guardian is alive. This is the **second deliverable** — built inside Pattern Project, not Guardian.

### 6.1 What Pattern Checks

1. Read `/home/user/Pattern_Project/data/guardian_heartbeat.json`
2. Parse `guardian_pid` and `last_heartbeat`
3. Verify `guardian_pid` is a running process
4. Verify `last_heartbeat` is within the last 2 minutes (allows for missed checks)
5. If Guardian is not running, spawn it

### 6.2 When Pattern Checks

- **On startup:** During `initialize_system()` in `main.py`, after database init but before background services
- **Periodically:** Every 5 minutes via a lightweight background check (can piggyback on the existing health check interval system)

### 6.3 How Pattern Spawns Guardian

If Pattern detects Guardian is not running:

```python
subprocess.Popen(
    ["python", "/path/to/guardian/guardian.py", "--config", "/path/to/guardian.toml"],
    cwd="/path/to/guardian/",
    start_new_session=True  # Detach from Pattern's process group
)
```

**Critical:** `start_new_session=True` ensures Guardian survives if Pattern crashes. If Guardian were a child process of Pattern without a new session, it would receive the same signals.

### 6.4 Integration Points in Pattern

The guardian check should be implemented as a new module: `agency/guardian_check.py`

It should integrate with Pattern at these points:

1. **`main.py:initialize_system()`** — Call `check_guardian()` after database init
2. **`main.py:start_background_services()`** — Start the periodic guardian check thread
3. **`config.py`** — Add configuration constants:
   - `GUARDIAN_ENABLED = True`
   - `GUARDIAN_CHECK_INTERVAL = 300` (5 minutes)
   - `GUARDIAN_HEARTBEAT_PATH = DATA_DIR / "guardian_heartbeat.json"`
   - `GUARDIAN_EXECUTABLE_PATH = ""` (path to guardian.py — must be configured)
   - `GUARDIAN_CONFIG_PATH = ""` (path to guardian.toml — must be configured)
4. **`main.py:stop_background_services()`** — Stop the guardian check thread (but do NOT stop Guardian itself — Guardian must outlive Pattern)

---

## 7. Filesystem Contract

These are the files that both Guardian and Pattern need to know about:

| File | Owner | Reader | Purpose |
|---|---|---|---|
| `data/pattern.db` | Pattern | Guardian (read-only, when Pattern is stopped) | Main database |
| `data/pattern.db-wal` | Pattern/SQLite | Guardian (existence check only) | WAL file |
| `data/pattern.db-shm` | Pattern/SQLite | Guardian (existence check only) | Shared memory |
| `data/guardian_heartbeat.json` | Guardian | Pattern | Guardian liveness proof |
| `logs/diagnostic.log` | Pattern | Guardian (for monitoring + rotation) | Pattern's application log |
| `logs/guardian.log` | Guardian | (Human reading) | Guardian's own log |

---

## 8. Implementation Checklist for Guardian

Guardian should be built as a standalone Python project:

```
guardian/
├── guardian.py          # Main entry point + state machine
├── config.py            # Configuration loader (TOML or JSON)
├── process.py           # Process management (start, stop, PID tracking)
├── health.py            # Health check logic (HTTP + process)
├── recovery.py          # Restart escalation + database checks
├── resources.py         # Disk space + memory monitoring
├── heartbeat.py         # Heartbeat file writer
├── log_rotation.py      # Pattern log rotation
├── guardian.toml         # Default configuration
└── README.md            # Setup instructions
```

**Requirements:**
- Python 3.8+ (standard library only)
- No pip dependencies
- Single-command launch: `python guardian.py`
- Optional: `python guardian.py --config /path/to/guardian.toml`

### 8.1 Standard Library Modules Guardian Should Use

| Module | Purpose |
|---|---|
| `subprocess` | Launch/manage Pattern process |
| `os` / `signal` | PID checks, sending signals |
| `time` / `datetime` | Timing, timestamps |
| `json` | Heartbeat file, config parsing |
| `pathlib` | File path handling |
| `logging` | Guardian's own logging |
| `sqlite3` | Database integrity checks (PRAGMA only) |
| `shutil` | File copy/move for database backup |
| `tomllib` (3.11+) or `json` | Configuration file parsing |
| `threading` | Background heartbeat writer |
| `http.client` | Health check HTTP requests (no `requests` library) |
| `stat` / `os.path` | File size checks for log rotation |

### 8.2 Key Implementation Notes

1. **HTTP health checks must use `http.client`, not `requests`.** No external dependencies.

2. **PID tracking:** After launching Pattern, write the PID to a pidfile (`data/pattern.pid`). On Guardian startup, check if a stale pidfile exists and whether that PID is actually Pattern.

3. **Atomic file writes:** Always write heartbeat/pidfiles to a temp file first, then `os.rename()` to the final path. This prevents partial reads.

4. **Signal handling:** Guardian should handle SIGTERM gracefully — write a final heartbeat with `pattern_state: "guardian_stopping"` so Pattern knows Guardian is going away intentionally (not crashed).

5. **No busy loops.** Use `time.sleep()` for the main check loop. The check interval should be 30 seconds by default — frequent enough to catch problems, infrequent enough to be invisible.

6. **SQLite integrity checks ONLY when Pattern is stopped.** Never open Pattern's database while Pattern is running. SQLite WAL mode handles concurrent reads, but Guardian has no reason to read the database during normal operation.

7. **Guardian should be its own process group leader** (`os.setsid()` equivalent). If launched by Pattern, it must survive Pattern's death.

---

## 9. Failure Scenarios and Expected Behavior

| Scenario | Guardian's Response |
|---|---|
| Pattern crashes (segfault, uncaught exception) | Detect via PID check → Level 1 restart |
| Pattern hangs (deadlock, infinite loop) | Health check fails → After N failures → Level 1 restart |
| Pattern's HTTP server crashes but process lives | Health check fails, PID alive → After N failures → Level 1 restart |
| Database corruption | Level 3 detects integrity failure → Level 4 recovery attempt |
| Disk full | Pre-emptive: rotate logs, warn. If Pattern crashes from this → restart after freeing space |
| Guardian crashes | Pattern detects missing heartbeat → Pattern respawns Guardian |
| Both crash simultaneously | OS restart required (systemd service recommended for Guardian) |
| Pattern refuses to start (missing API key, etc.) | Repeated restart failures → enters FAILED state after `max_consecutive_restart_failures` |
| Pattern starts but health never responds | Startup grace period expires → restart → if repeated, FAILED state |

---

## 10. Optional: systemd Integration

For maximum resilience, Guardian itself should be managed by systemd:

```ini
# /etc/systemd/system/pattern-guardian.service
[Unit]
Description=Pattern Project Guardian
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /path/to/guardian/guardian.py --config /path/to/guardian.toml
Restart=always
RestartSec=10
User=pattern_user
WorkingDirectory=/path/to/guardian/

[Install]
WantedBy=multi-user.target
```

This creates the complete chain:
- **systemd** restarts Guardian if it dies
- **Guardian** restarts Pattern if it dies
- **Pattern** respawns Guardian if it dies

Three layers of resilience with no human intervention.

---

## 11. Testing Guardian

Guardian should be testable without a running Pattern instance:

1. **Mock health endpoint:** A simple script that runs Flask on :5000 with /health returning 200. Test Guardian's detection, state transitions, and restart behavior.

2. **Simulated failures:** Scripts that:
   - Start a process and immediately kill it (test PID detection)
   - Start a health endpoint that returns 500 (test health failure detection)
   - Create a corrupt SQLite database (test integrity check + recovery)
   - Fill a temp directory to near-capacity (test disk space monitoring)

3. **State machine tests:** Unit tests for the state machine transitions independent of actual process management.

---

## 12. What This Spec Does NOT Cover

- **Remote monitoring / alerting** — Guardian is local only. External monitoring (Uptime Kuma, Grafana, etc.) is a separate concern.
- **Multi-instance Pattern** — Guardian supervises exactly one Pattern instance.
- **Pattern updates / deployment** — Guardian does not update Pattern's code. That's a separate process.
- **Guardian self-update** — Guardian is simple enough that it should rarely need updating.
- **Network-level health** — Guardian checks localhost only. External connectivity is Pattern's problem.

---

## Appendix A: Pattern's Existing HTTP Endpoints (Full Reference)

| Method | Path | Purpose | Response |
|---|---|---|---|
| GET | `/health` | Liveness check | `{"status": "healthy", "service": "pattern-project"}` |
| GET | `/stats` | Full system statistics | Database counts, session info, extractor stats |
| POST | `/chat` | Send a message | AI response with token counts |
| POST | `/memories/search` | Search memories | Scored memory results |
| POST | `/memories` | Add a memory directly | Memory ID |
| POST | `/session/new` | Start new session | Session ID |
| POST | `/session/end` | End current session | Session summary |
| POST | `/extract` | Force memory extraction | Memories extracted count |
| GET | `/voice/health` | Voice pipeline status | STT/TTS availability |
| POST | `/voice/stt` | Speech to text | Transcription |
| POST | `/voice/talk` | Full voice loop | Audio response |

**Guardian should only use `/health` and `/stats`.** The other endpoints are for Pattern's interfaces.

## Appendix B: Pattern's Directory Layout (Guardian-Relevant)

```
/home/user/Pattern_Project/
├── main.py                    # Entry point (what Guardian launches)
├── config.py                  # Configuration (Guardian reads paths from here conceptually)
├── .env                       # Environment variables (ANTHROPIC_API_KEY, etc.)
├── requirements.txt           # Python dependencies (not Guardian's concern)
├── data/
│   ├── pattern.db             # Main SQLite database
│   ├── pattern.db-wal         # WAL file (may or may not exist)
│   ├── pattern.db-shm         # Shared memory file (may or may not exist)
│   ├── guardian_heartbeat.json # Written by Guardian, read by Pattern
│   ├── pattern.pid            # Written by Guardian after launching Pattern
│   ├── files/                 # AI's file storage (sandboxed)
│   ├── browser_sessions/      # Browser cookies (if delegation enabled)
│   └── user_settings.json     # User preferences
├── logs/
│   ├── diagnostic.log         # Pattern's application log
│   ├── diagnostic.log.1       # Rotated log (managed by Guardian)
│   └── guardian.log           # Guardian's own log
├── agency/
│   └── guardian_check.py      # NEW: Pattern's Guardian liveness checker
└── docs/
    └── GUARDIAN_SPEC.md        # This document
```

## Appendix C: Pattern's config.py Constants (Guardian-Relevant)

```python
# From Pattern's config.py — these are the values Guardian should know about

# Paths
PROJECT_ROOT = Path(__file__).parent           # /home/user/Pattern_Project
DATA_DIR = PROJECT_ROOT / "data"               # /home/user/Pattern_Project/data
LOGS_DIR = PROJECT_ROOT / "logs"               # /home/user/Pattern_Project/logs
DATABASE_PATH = DATA_DIR / "pattern.db"        # /home/user/Pattern_Project/data/pattern.db
DIAGNOSTIC_LOG_PATH = LOGS_DIR / "diagnostic.log"

# HTTP API (health endpoint)
HTTP_ENABLED = True
HTTP_HOST = "127.0.0.1"
HTTP_PORT = 5000

# Database
DB_BUSY_TIMEOUT_MS = 10000                     # 10 second busy timeout

# Subprocess management
SUBPROCESS_HEALTH_CHECK_INTERVAL = 30          # Existing health check interval
HEALTH_CHECK_INTERVAL = 30                     # General health check interval
```
