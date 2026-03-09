# Pattern Project — Patch Notes

---

## March 9, 2026

### Summary

This release transforms Pattern Project from a local desktop application into a deployment-ready, web-first AI companion platform. The PyQt5 GUI has been retired in favor of a FastAPI + WebSocket web interface. Major additions include Google Calendar integration, Google Drive backups, image memory, a blog publishing tool, and a fully autonomous pulse system with web controls. Dozens of bug fixes improve API reliability, image handling, and real-time UI updates. Deployment tooling for Ubuntu / DigitalOcean is now included out of the box.

---

### New Features

- **Web UI mode** — Full browser-based interface powered by FastAPI and WebSocket with streaming responses, image paste/upload, and real-time updates. Replaces the PyQt5 desktop GUI as the default interface.
- **Dev tools web UI** — Debug panels accessible via `/dev/*` routes, eliminating the need for PyQt5 developer tools.
- **Process panel** — Live view of delegation, curiosity, and memory extraction events in the web UI.
- **Pulse type selector** — Trigger specific pulse types manually from the web UI, with live countdown display.
- **Google Calendar integration** — Full OAuth2-based calendar support with four tools: create, update, delete, and list events. Includes reminder support and correct timezone handling.
- **Image memory** — The AI can now save and recall images across sessions, building a persistent visual memory.
- **Blog publishing tool** — Write and publish blog posts with static site generation.
- **Google Drive backup gateway** — Automatic off-server database backups to Google Drive, including user writings stored in `data/files/`.
- **Daily backup cron script** — Scheduled backup automation for production deployments.
- **Multi-topic memory retrieval** — Improved recall accuracy through paragraph and marker splitting, allowing the AI to retrieve memories across multiple topics in a single query.

### Bug Fixes

- **API stability** — Fixed tool_result validation errors, server tool handling (preserving SDK objects, fixing text duplication, skipping `srvtoolu_` IDs), and added defensive tool_result guarantees for continuation messages.
- **Web search** — Resolved persistent 400 errors caused by three compounding issues: image placement in tool_result blocks, response content rebuilding, and search parameter formatting.
- **Image handling** — Fixed MIME type misdetection for non-JPEG uploads and media type mismatch causing API 400 errors on image encoding.
- **Telegram gateway** — Fixed handler passing decomposed arguments instead of the expected message object.
- **Web UI process panel** — Tool use calls now appear correctly in the process panel.
- **Pulse countdown** — Fixed countdown timer freezing when the browser tab loses focus.
- **Broadcast system** — Resolved AttributeError in broadcast and added an engine task safety net.
- **Image save tool** — Fixed import error that broke the image memory feature on first use.
- **Embedding model** — Fixed model failing to load on read-only filesystems (relevant for containerized deployments).
- **Calendar timezone** — Corrected timezone format used when writing calendar events.
- **Missing imports** — Fixed `log_info` import error and removed broken BearBlog reference from the action pulse.

### Improvements

- **Engine extraction** — Shared `ChatEngine` extracted from GUI and CLI into a dedicated `engine/` package, enabling both interfaces to share core logic.
- **Deprecated code removal** — Removed PyQt5 GUI, deprecated tools (clipboard, clarification, moltbook, email), legacy `[[COMMAND: arg]]` inline syntax, and redundant `ai_commands` prompt source.
- **Action pulse rewrite** — Replaced the autonomous pulse prompt body with carefully researched text. Changed phrasing from "This hour is yours" to "This moment is yours."
- **Memory extraction** — Added provenance as positive reinforcement, helping the AI understand where its memories come from.
- **Curiosity rebalance** — Moved curiosity priority from P20 to P82 and fixed documentation weight drift.
- **Pulse configuration** — Unified `max_passes` with `COMMAND_MAX_PASSES` config to prevent future drift; default is now config-driven.
- **Delegate token limit** — Bumped from default to 16k to support longer delegation tasks.
- **Dev WebSocket** — Initial dev state is now sent to newly connected `/ws/dev` clients.

### DevOps & Deployment

- **VPS setup guide** — Comprehensive Ubuntu / DigitalOcean deployment guide covering firewall, systemd, Nginx, SSL, and monitoring.
- **Deployment scripts** — Production-ready `setup.sh` with hardened firewall rules, fail2ban, and reconciled deploy files matching the VPS guide and Guardian spec.
- **Environment template** — `.env.example` updated with all 17 previously missing environment variables.
- **Linux cheat sheet** — Quick-reference command guide for Pattern Project server administration.
- **Dependency fix** — Added missing `matplotlib` dependency to `requirements.txt`.

### License

- Pattern Project is now licensed under the **GNU General Public License v3.0 (GPLv3)**. See the `LICENSE` file for full terms.

---

*Pattern Project — Where memory meets agency*
