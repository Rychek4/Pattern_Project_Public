# Pattern Project — Cloud Readiness Audit (VPS / Digital Ocean)

**Date:** 2026-02-27
**Scope:** Full audit of Pattern Project for deployment to a cloud VPS (Digital Ocean droplet)
**Verdict:** **READY with caveats** — strong deployment infrastructure exists; a focused hardening pass will close the remaining gaps.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [What's Already In Place (Strengths)](#whats-already-in-place)
3. [Gaps & Risks](#gaps--risks)
4. [Category-by-Category Breakdown](#category-breakdown)
5. [Recommended VPS Spec](#recommended-vps-spec)
6. [Pre-Deployment Checklist](#pre-deployment-checklist)
7. [Post-Deployment Checklist](#post-deployment-checklist)

---

## Executive Summary

Pattern Project has **production-grade deployment infrastructure** already built:

- `deploy/setup.sh` — automated Ubuntu 22.04+ VPS provisioning
- `deploy/pattern.service` — systemd unit with security hardening
- `deploy/nginx.conf` — reverse proxy with SSL/TLS, WebSocket support, rate limiting
- Guardian watchdog — external process health monitoring
- Health endpoints (`/health`, `/stats`) for uptime monitoring
- Graceful shutdown with signal handling (SIGINT/SIGTERM)
- SQLite WAL mode with automatic schema migrations (v20)

The project is **architecturally ready** for a single-instance VPS deployment. The gaps below are hardening items, not blockers.

---

## What's Already In Place

### Deployment Infrastructure (STRONG)

| Component | File | Status |
|-----------|------|--------|
| VPS setup automation | `deploy/setup.sh` | Complete — installs packages, creates user, configures services |
| systemd service | `deploy/pattern.service` | Complete — restart policies, security hardening, resource limits |
| nginx reverse proxy | `deploy/nginx.conf` | Complete — HTTPS, WebSocket, rate limiting on `/auth/login` |
| SSL/TLS | certbot (Let's Encrypt) | Integrated into setup script |
| Environment config | `.env.example` | 60+ variables documented |
| Dependencies | `requirements.txt` | 28 packages, pinned minimums |

### Security Infrastructure (GOOD)

| Component | Status | Notes |
|-----------|--------|-------|
| Guardian watchdog | Implemented | External process supervision, heartbeat, auto-restart |
| Web authentication | Implemented | Cookie-based sessions, `secrets.token_urlsafe(32)` |
| File upload sandboxing | Excellent | Path traversal prevention, extension whitelist, size limits |
| Rate limiting (comms) | Implemented | Email 20/hr, Telegram 30/hr, rolling window |
| SQL injection prevention | Good | Parameterized queries throughout |
| Input validation | Good | File handler has multi-layer validation |
| API keys via env vars | Good | Not hardcoded in source |
| nginx security headers | Present | X-Frame-Options, X-Content-Type-Options, X-XSS-Protection |
| systemd hardening | Present | NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp |

### Operational Readiness (GOOD)

| Component | Status | Notes |
|-----------|--------|-------|
| Health check endpoint | `/health` returns `{"status": "healthy"}` | Usable by DO uptime monitoring |
| Stats endpoint | `/stats` returns DB/session/extractor metrics | Operational visibility |
| Structured logging | `logs/diagnostic.log` | Configurable level (INFO default) |
| Graceful shutdown | SIGINT/SIGTERM handled | Waits for extraction, closes connections |
| Auto-restart | systemd `Restart=on-failure` | 5s delay, max 5 restarts per 5 min |
| Background scheduling | All internal | System pulse, reminders, health checks — no external cron needed |
| Database migrations | Automatic on startup | Schema v20, idempotent |

---

## Gaps & Risks

### CRITICAL (Fix before going live)

| # | Issue | Risk | Recommendation |
|---|-------|------|----------------|
| C1 | **No HTTPS enforcement at app level** | If nginx misconfigured, traffic is plaintext | App relies entirely on nginx for TLS — verify nginx config is airtight |
| C2 | **Web auth password not hashed** | Password compared in plaintext via env var | Hash with `bcrypt` or `argon2`; compare hashes, not raw strings |
| C3 | **Session cookies lack flags** | Session hijacking, CSRF | Set `HttpOnly`, `Secure`, `SameSite=Lax` on `pattern_session` cookie |
| C4 | **Sessions are in-memory only** | All sessions lost on restart; users must re-login | Acceptable for single-user, but document this behavior |
| C5 | **No backup strategy for database** | Single point of data loss — all memories, conversations | Set up automated daily backup (cron + `sqlite3 .backup` → object storage) |

### HIGH (Address in first hardening pass)

| # | Issue | Risk | Recommendation |
|---|-------|------|----------------|
| H1 | **HTTP API (Flask, port 5000) has no auth** | `/chat`, `/stats`, `/extract` accessible to anyone on localhost | Bind to `127.0.0.1` only (current default) and do NOT expose via nginx |
| H2 | **No HTTP security headers from FastAPI** | XSS, clickjacking, MIME sniffing | Add `Starlette` middleware for CSP, HSTS, etc. (nginx covers some, app should too) |
| H3 | **No fail2ban or SSH hardening documented** | Brute-force SSH attacks on VPS | Add fail2ban config for SSH + nginx auth |
| H4 | **No firewall rules (ufw) in setup script** | All ports open by default on fresh droplet | Add `ufw allow 22,80,443/tcp` and `ufw enable` to `setup.sh` |
| H5 | **WEB_HOST defaults to 0.0.0.0** | App directly exposed if nginx is down | Fine behind nginx, but add a note: never expose port 8080 via firewall |
| H6 | **credentials.toml is plaintext** | File read = credential theft | Restrict file permissions (`chmod 600`) in setup script |
| H7 | **No log rotation configured** | Disk fills up over weeks/months | Add `/etc/logrotate.d/pattern` config |

### MODERATE (Nice-to-have for production)

| # | Issue | Notes |
|---|-------|-------|
| M1 | No Docker/containerization | Not needed for single VPS — systemd works well |
| M2 | No Prometheus/Grafana metrics | Stats API exists; could add `prometheus-client` later |
| M3 | No CI/CD pipeline | Manual deploy is fine for a single instance |
| M4 | No CORS middleware | Not needed when all access goes through nginx on same domain |
| M5 | Limited test coverage | Risk is low for single-user system; add tests over time |
| M6 | No rate limiting on web API endpoints | nginx rate-limits `/auth/login`; other endpoints could be limited |
| M7 | 7-day session expiry is long | Consider 24h or 48h for a cloud-exposed system |

---

## Category Breakdown

### 1. Compute & Process Management

**Current state:** Single-process Python app managed by systemd.

- Entry point: `python main.py --web` (FastAPI + Uvicorn)
- Background threads: system pulse, reminder scheduler, Telegram listener, subprocess monitor, Guardian checker
- No multi-worker / multi-process configuration (Uvicorn runs single-worker by default)
- File descriptor limit: 65,535

**Cloud assessment:** Sufficient for single-user companion system. If concurrent users needed later, would need Uvicorn workers or Gunicorn.

### 2. Database

**Current state:** SQLite3 with WAL mode.

- Schema version 20 with automatic migrations
- Busy timeout: 10 seconds, max 5 retries with exponential backoff
- Tables: sessions, conversations, memories, core_memories, state, intentions, communication_log, active_thoughts, curiosity_goals, growth_threads, reading_sessions
- Embeddings stored as 384-dim BLOBs in `memories` table

**Cloud assessment:** SQLite is appropriate for a single-instance, single-user system. If scaling beyond one instance, would need to migrate to PostgreSQL with pgvector. No action needed now.

**Backup concern:** SQLite is a single file. A corrupted write = data loss. Daily `.backup` to DO Spaces or S3 is essential.

### 3. Networking

**Current state:**

| Service | Bind Address | Port | Notes |
|---------|-------------|------|-------|
| FastAPI (web UI) | 0.0.0.0 | 8080 | Behind nginx |
| Flask (HTTP API) | 127.0.0.1 | 5000 | Localhost only |
| nginx | 0.0.0.0 | 80, 443 | Public-facing |

**Cloud assessment:** Architecture is correct — nginx terminates TLS and proxies to localhost app. Need to ensure:
- Port 8080 is NOT in the firewall allow-list (only 80, 443, 22)
- Port 5000 stays bound to localhost

### 4. Authentication & Sessions

**Current state:**
- Single shared password (`WEB_AUTH_PASSWORD` env var)
- Cookie: `pattern_session` with 7-day TTL
- Token: `secrets.token_urlsafe(32)` — cryptographically secure
- Sessions: in-memory dictionary (lost on restart)

**Cloud assessment:** Functional for single-user. Critical fixes:
- Add `HttpOnly`, `Secure`, `SameSite=Lax` to cookie
- Consider hashing the password
- Document that restart = re-login required

### 5. Secrets Management

**Current state:** All secrets in `.env` file, loaded via `python-dotenv`.

| Secret | Source |
|--------|--------|
| ANTHROPIC_API_KEY | .env |
| OPENAI_API_KEY | .env |
| WEB_AUTH_PASSWORD | .env |
| telegram_bot | .env |
| APP_EMAIL_PASS | .env |
| REDDIT_CLIENT_SECRET | .env |
| MOLTBOOK_API_KEY | .env |
| Service passwords | credentials.toml |

**Cloud assessment:** Acceptable for a single VPS. The `.env` file must have restrictive permissions (`chmod 600`, owned by `pattern` user). For higher security, could use DO's encrypted environment variables or a vault service later.

### 6. Guardian Watchdog

**Current state:** External watchdog process (separate repo) that monitors Pattern via:
- HTTP health endpoint checks (`/health`, `/stats`)
- Heartbeat file (`data/guardian_heartbeat.json`)
- Escalating restart strategy (SIGTERM → SIGKILL → DB recovery)
- Mutual supervision (Pattern also checks Guardian liveness)

**Cloud assessment:** Excellent addition for VPS reliability. Complements systemd restart. State machine: STARTING → HEALTHY → DEGRADED → RESTARTING → FAILED.

### 7. File Operations Security

**Current state:** Comprehensive sandboxing in `agency/commands/handlers/file_handler.py`:
- Path traversal prevention (rejects `..`, `/`, `\`, null bytes, hidden files)
- Extension whitelist: `.txt`, `.md`, `.json`, `.csv`
- Size limit: 30 MB
- All operations confined to `data/files/`
- Multi-layer validation: sanitize → validate segments → validate extension → resolve safe path

**Cloud assessment:** Production-ready. No changes needed.

### 8. Communication Channels

**Current state:**
- Email: Gmail SMTP with app password, whitelist-based recipients, 20/hr rate limit
- Telegram: Bot API with 30/hr rate limit, 2s polling
- Moltbook: API integration, 100 req/min limit
- Reddit: PRAW with 30 req/min limit

**Cloud assessment:** All communication goes outbound via API calls — no inbound ports needed beyond web. Rate limits prevent abuse. Telegram polling is lightweight.

### 9. Logging & Observability

**Current state:**
- File logging: `logs/diagnostic.log` (INFO level, configurable)
- Console logging: Rich-formatted output (captured by systemd journal)
- Stats API: Database, session, and extractor metrics
- No structured JSON logging
- No external monitoring integration (Prometheus, Datadog, etc.)

**Cloud assessment:** Sufficient for launch. Add logrotate to prevent disk fill. Consider structured JSON logging and DO monitoring integration later.

### 10. Data Persistence

**What must survive reboots/redeploys:**

| Path | Contents | Criticality |
|------|----------|-------------|
| `data/pattern.db` | All memories, conversations, sessions | CRITICAL |
| `data/files/` | User documents, novels | HIGH |
| `data/credentials.toml` | Service credentials | HIGH |
| `.env` | API keys, config | HIGH |
| `data/browser_sessions/` | Cookie jars | LOW (regenerable) |
| `data/user_settings.json` | Voice preferences | LOW (regenerable) |
| `data/guardian_heartbeat.json` | Supervision state | EPHEMERAL |
| `logs/` | Diagnostic logs | LOW (archivable) |

**Cloud assessment:** All persistent data lives under `data/`. Use a DO volume or block storage for `/opt/pattern/data/` to survive droplet rebuilds.

---

## Recommended VPS Spec

### Digital Ocean Droplet

| Resource | Minimum | Recommended | Notes |
|----------|---------|-------------|-------|
| **CPU** | 1 vCPU | 2 vCPU | Embedding model loading + concurrent requests |
| **RAM** | 2 GB | 4 GB | Embedding model (~150 MB) + STT model (~500 MB) + runtime |
| **Disk** | 25 GB SSD | 50 GB SSD | SQLite DB growth + logs + novels + browser sessions |
| **OS** | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS | setup.sh targets Ubuntu 22.04+ |
| **Region** | Any | Closest to user | Reduces WebSocket latency |

### Estimated Monthly Cost (Digital Ocean)

| Tier | Spec | Price | Suitable For |
|------|------|-------|-------------|
| Basic | 2 vCPU, 2 GB RAM, 50 GB | ~$18/mo | Without STT/TTS (text-only) |
| **Standard** | **2 vCPU, 4 GB RAM, 80 GB** | **~$24/mo** | **Full feature set including voice** |
| Performance | 4 vCPU, 8 GB RAM, 100 GB | ~$48/mo | Heavy usage, fast embedding loads |

**Add-ons to consider:**
- DO Spaces ($5/mo): Automated database backups
- DO Monitoring (free): Basic CPU/RAM/disk alerts
- DO Firewall (free): Cloud-level firewall rules
- Reserved IP ($5/mo): Static IP for DNS

---

## Pre-Deployment Checklist

### Before running `setup.sh`:

- [ ] **Choose and purchase a domain** (for SSL certificate)
- [ ] **Create Digital Ocean account** and provision droplet
- [ ] **Point DNS A record** to droplet IP
- [ ] **Prepare `.env` values:**
  - `ANTHROPIC_API_KEY` (required)
  - `WEB_AUTH_PASSWORD` (strong, unique password)
  - `OPENAI_API_KEY` (if using TTS)
  - `telegram_bot` + `TELEGRAM_CHAT_ID` (if using Telegram)
  - `APP_EMAIL_ADDRESS` + `APP_EMAIL_PASS` (if using email)
- [ ] **Disable unneeded features** in `.env` to reduce attack surface:
  - `CLIPBOARD_ENABLED=false` (no clipboard on VPS)
  - `VISUAL_ENABLED=false` (no screen/webcam on VPS)
  - `VISUAL_SCREENSHOT_MODE=disabled`
  - `VISUAL_WEBCAM_MODE=disabled`

### Security hardening (add to `setup.sh` or do manually):

- [ ] **Enable UFW firewall:**
  ```bash
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow 22/tcp    # SSH
  sudo ufw allow 80/tcp    # HTTP (certbot + redirect)
  sudo ufw allow 443/tcp   # HTTPS
  sudo ufw enable
  ```
- [ ] **Install fail2ban:**
  ```bash
  sudo apt install fail2ban
  sudo systemctl enable fail2ban
  ```
- [ ] **Restrict `.env` and credentials:**
  ```bash
  chmod 600 /opt/pattern/.env
  chmod 600 /opt/pattern/data/credentials.toml
  chown pattern:pattern /opt/pattern/.env
  ```
- [ ] **Set up SSH key auth** and disable password login
- [ ] **Create non-root user** for SSH access (separate from `pattern` service user)

---

## Post-Deployment Checklist

### Immediately after deployment:

- [ ] **Verify HTTPS:** `curl -I https://YOUR_DOMAIN` — should see 200 + security headers
- [ ] **Verify health:** `curl https://YOUR_DOMAIN/health` — should return `{"status": "healthy"}`
- [ ] **Verify WebSocket:** Open browser, log in, send a message
- [ ] **Verify certbot renewal:** `sudo certbot renew --dry-run`
- [ ] **Check systemd status:** `sudo systemctl status pattern`
- [ ] **Check logs:** `sudo journalctl -u pattern -n 50`

### Set up automated backups:

```bash
# /etc/cron.d/pattern-backup (example)
0 3 * * * pattern sqlite3 /opt/pattern/data/pattern.db ".backup /opt/pattern/data/backups/pattern-$(date +\%Y\%m\%d).db"
0 4 * * * pattern find /opt/pattern/data/backups/ -name "*.db" -mtime +7 -delete
```

Or use DO Spaces with `s3cmd` / `rclone` for off-server backups.

### Set up log rotation:

```bash
# /etc/logrotate.d/pattern
/opt/pattern/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 pattern pattern
    missingok
}
```

### Set up DO monitoring:

- Enable **droplet metrics** in DO dashboard (free)
- Set alerts for: CPU > 80%, Disk > 85%, RAM > 90%
- Add uptime check: `GET https://YOUR_DOMAIN/health` every 5 min

---

## Final Verdict

**Pattern is ready for cloud deployment.** The `deploy/` directory provides a complete, well-thought-out VPS deployment pipeline. The Guardian watchdog adds a reliability layer beyond what systemd alone provides. The critical items (C1-C5) are hardening tasks that can be addressed in a focused session before or shortly after going live — none are architectural blockers.

The recommended path:

1. Address **C3** (cookie flags) and **C5** (backup strategy) — highest-impact, lowest-effort
2. Add **H3** (fail2ban) and **H4** (ufw) during VPS setup
3. Add **H7** (logrotate) during VPS setup
4. Deploy with `setup.sh`
5. Address remaining items (C2, H1, H2, H5, H6) in the first maintenance pass
