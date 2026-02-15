# Changelog

All notable changes to Pattern Project will be documented in this file.

## [0.1.0] — 2026-02-15

Initial public release.

### Features

- **Persistent Memory System** — Dual-track extraction (episodic + factual), vector embeddings (all-MiniLM-L6-v2), composite scoring, warmth cache, and decay categories
- **Ephemeral Context Window** — Each prompt assembled fresh from 16 pluggable context sources
- **AI Agency** — System pulse timer, natural-language reminders, curiosity engine, active thoughts, growth threads
- **Native Tool System** — Memory search, file operations, reminders, clipboard, visual capture, communication, and web tools via Claude's tool use API
- **Communication Gateways** — Telegram (bidirectional), email (Gmail SMTP), Reddit, Moltbook — all with rate limiting
- **Visual Capture** — Screenshot and webcam integration with auto/on-demand/disabled modes
- **Text-to-Speech** — ElevenLabs streaming integration
- **Multiple Interfaces** — PyQt5 GUI, Rich terminal CLI, Flask HTTP API
- **LLM Routing** — Anthropic Claude (primary) with KoboldCpp local fallback
- **Browser Automation** — Playwright-based delegation with credential management
