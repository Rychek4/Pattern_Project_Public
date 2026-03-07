# Patch Notes — February 22 – March 7, 2026

Changes to the Pattern Project since February 22, organized by area.

---

## New Features

### Web UI (Feb 25–Mar 1)
- **Web UI mode** — FastAPI + WebSocket server with a browser frontend, replacing the PyQt5 GUI as the default interface
- **Shared ChatEngine** — Extracted from the GUI/CLI layers into `engine/` so all interfaces share one conversation core
- **Process panel** — Live delegation, curiosity, and memory-extraction events streamed to the browser
- **Dev tools panel** — Debug panels served at `/dev/*` routes; initial state sent to newly-connected `/ws/dev` clients
- **Pulse type selector** — Manual pulse triggering from the web UI
- **Reflective & action interval dropdowns** — Pulse timing now adjustable in the browser

### Google Calendar Integration (Mar 4)
- **Four calendar tools** — Create, update, delete, and list events via OAuth2
- **Reminder support** — Set reminders when creating or updating events
- **Event IDs** in list output for easy reference
- **Timezone fix** — Calendar writes now use the correct timezone format

### Image Memory (Mar 2–3)
- **Save & recall images** — AI can persist images to memory and retrieve them later
- **Import fix** — Resolved `save_image` tool import error that broke the feature on first deploy

### Google Drive Backup Gateway (Mar 6)
- **Off-server database backups** — Automated backups pushed to Google Drive
- **User writings protected** — `data/files/` directory included in backup scope

### Memory Retrieval Improvements (Mar 1)
- **Multi-topic retrieval** — Paragraph + marker splitting lets a single query surface memories across several topics

---

## Bug Fixes

- **Image MIME types** — Fixed misdetection causing API 400 errors for non-JPEG uploads (Feb 28) and a second media-type mismatch (Mar 4)
- **Telegram handler** — Web handler was passing decomposed args instead of the message object (Feb 28)
- **Tool-use panel** — Tool-use calls were missing from the web process panel (Feb 28)
- **Pulse countdown freeze** — Timer now keeps ticking when the browser tab loses focus (Feb 27)
- **Pulse countdown update** — Interval changes via web UI are reflected immediately (Feb 27)
- **Broadcast AttributeError** — Fixed crash and added engine task safety net (Feb 27)
- **Overdue reminders** — Now checked on webapp boot so nothing is silently skipped (Feb 28)

---

## Deployment & Infrastructure

- **VPS setup guide** — Comprehensive Ubuntu/DigitalOcean deployment documentation (Feb 27)
- **Windows-to-Ubuntu migration** section added to the guide (Feb 27)
- **Cloud readiness audit** — Pre-deployment checklist for VPS / Digital Ocean (Feb 27)
- **Guardian watchdog spec** — Layer 0 health-check specification and Pattern-side heartbeat (Feb 23)
- **Deployment configs** — `setup.sh`, systemd units, nginx config, and `.env.example` for Ubuntu (Mar 7)
- **Hardened firewall** — Skips re-application if already active; fail2ban added (Mar 7)
- **Setup script simplified** — Rewritten as a straight-line deploy script (Mar 7)

---

## Cleanup & Deprecations

- **PyQt5 GUI removed** — Web UI is now the sole interface (Mar 2)
- **Legacy code removed** — Dead command processor, proactive agent, Gemini system, chat overlay, and legacy fallback paths (−1,500+ lines) (Feb 22–28)
- **Deprecated tools removed** — Clipboard, clarification, moltbook, and email tools dropped (Mar 4)
- **Redundant prompt source removed** — `ai_commands` section eliminated; budget warnings relocated to the router (Mar 4)
- **Legacy syntax removed** — Old `[[COMMAND: arg]]` inline references cleaned out (Feb 22)
- **Stale references cleaned** — Deprecated config vars, dead aliases, and outdated docstrings removed (Feb 22)
- **Curiosity priority rebalanced** — Moved from P20 → P82; fixed doc weight drift (Feb 27)
- **Process panel simplified** — All remaining PyQt5/GUI code stripped (Feb 28)

---

*Generated from git log: `7a1f5d3..a874530` (55 commits)*
