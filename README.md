# Pattern Project

**An AI Companion System with Persistent Memory and Autonomous Agency**

> "The Prompt is the thing" — Each conversation draws from multiple context sources to create a rich, coherent understanding without accumulating context bloat.

Pattern is an AI companion system built around Claude that doesn't just respond — it **understands, remembers, and initiates**. The system maintains persistent memories across sessions, assembles contextual prompts from multiple data sources, and acts autonomously through triggers, reminders, and curiosity-driven exploration.

---

## Key Features

### Persistent Memory System
- **Semantic Memory Search** — Vector embeddings (all-MiniLM-L6-v2) with combined scoring: 60% semantic similarity, 25% importance, 15% freshness
- **Dual-Track Extraction** — Episodic memories (narratives: "We discussed X") and Factual memories (concrete facts: "Brian is 45")
- **Warmth Cache** — Session-scoped memory boosting for conversational continuity
- **Core Memories** — Permanent foundational knowledge that never decays
- **Decay Categories** — Permanent, standard (30-day), and ephemeral (7-day) half-lives

### AI Agency & Autonomy
- **System Pulse Timer** — Dual-mode: reflective pulse (12h, Opus) for deep thinking and action pulse (2h, Sonnet) for open-ended agency
- **Reminder System** — Natural language time parsing ("in 2 hours", "tomorrow morning")
- **Curiosity Engine** — AI-driven topic exploration from dormant and fresh memories
- **Growth Threads** — Long-term intellectual pursuits with lifecycle stages (seed, growing, integrating, dormant)
- **Active Thoughts** — AI's private working memory for priorities and ongoing deliberations

### Communication Gateways
- **Telegram Bot** — Bidirectional messaging with background listener
- **Google Calendar** — List, create, update, and delete calendar events
- Rate limiting on all channels to prevent abuse

### Visual Capture
- **Screenshot Capture** — See what the user is looking at
- **Webcam Capture** — Visual context when appropriate
- **Modes** — Auto (every prompt), On-Demand (tool-triggered), or Disabled

### Native Tool System
Pattern uses Claude's native tool use (no text-pattern parsing). 42 tools across these categories:

| Category | Examples |
|----------|----------|
| Memory | `search_memories`, `store_bridge_memory`, `update_memory_self_model` |
| Reminders | `create_reminder`, `complete_reminder`, `dismiss_reminder`, `list_reminders` |
| Files | `read_file`, `write_file`, `append_file`, `list_files`, `create_directory`, `move_file` |
| Communication | `send_telegram` |
| Calendar | `list_calendar_events`, `create_calendar_event`, `update_calendar_event` |
| Visual | `capture_screenshot`, `capture_webcam`, `save_image` |
| Agency | `set_pulse_interval`, `set_active_thoughts`, `advance_curiosity`, `delegate_task` |
| Growth | `set_growth_thread`, `promote_growth_thread`, `remove_growth_thread` |
| Reading | `open_book`, `read_next_chapter`, `complete_reading`, `reading_progress` |
| Blog | `publish_blog_post`, `save_blog_draft`, `edit_blog_post`, `list_blog_posts` |
| Web | `manage_fetch_domains`, `list_fetch_domains` (plus native Anthropic web search) |
| Metacognition | `store_meta_observation` |

See `agency/tools/definitions.py` for the complete list.

### Web Search
- Native Anthropic web search capability
- Daily budget: 30 searches/day
- Automatic citation tracking

### Text-to-Speech
- OpenAI TTS integration (tts-1 / tts-1-hd models)
- Streaming audio with proper sequencing
- Voice selection and user preferences

---

## Architecture

### The Ephemeral Context Window

Pattern's key innovation is that **each prompt is assembled fresh from scratch**:

```
Traditional Chatbot:              Pattern Project:
┌──────────────────────┐         ┌──────────────────────┐
│ Context Window       │         │ Context Window       │
│ (accumulates)        │         │ (rebuilt each turn)  │
│ ┌──────────────────┐ │         │ ┌──────────────────┐ │
│ │ Turn 1           │ │         │ │ Core Memories    │ │
│ │ Turn 2           │ │         │ │ Semantic Recall  │ │
│ │ Turn 3           │ │         │ │ Active Thoughts  │ │
│ │ ...              │ │         │ │ Last 30 turns    │ │
│ │ Turn N (bloat)   │ │         │ │ (bounded ~2K)    │ │
│ └──────────────────┘ │         │ └──────────────────┘ │
└──────────────────────┘         └──────────────────────┘
     Grows until full                Self-contained lens
```

### Windowed Memory Extraction

Context doesn't accumulate — it flows through a window:

```
Context Window (30 turns) → Overflow (40 turns) → Extract oldest 10 → Back to 30
```

Extracted conversations become searchable memories that resurface when semantically relevant.

### Pluggable Context Sources

14 independent sources combine into rich prompts:

| Priority | Source | Purpose |
|----------|--------|---------|
| 5 | Dev Mode | Debug information |
| 10 | Core Memory | Permanent identity/facts |
| 10 | Memory Self-Model | Structural memory awareness |
| 15 | Tool Stance | Behavioral tool guidance |
| 18 | Active Thoughts | AI's working memory |
| 20 | Growth Threads | Long-term intellectual pursuits |
| 22 | Intentions | Pending reminders |
| 25 | System Pulse | Pulse timer state |
| 30 | Temporal | Time/session awareness |
| 50 | Semantic Memory | Vector-searched memories |
| 82 | Curiosity | Curiosity exploration state |
| 85 | Pattern Breaker | Response variety nudges |
| 87 | Self-Correction | Behavioral self-adjustment |
| 88 | Response Scope | Response length guidance |

---

## Interfaces

### Web UI (Default)
```bash
python main.py         # Start web interface on port 8080 (default)
```
Browser-based interface using FastAPI + WebSocket. Supports streaming,
image paste/upload, real-time process panel, pulse controls, and theme
switching. Recommended for VPS/cloud deployments and general use.

Set `WEB_AUTH_PASSWORD` in `.env` to require login (empty = no auth for local dev).

### CLI (Rich Terminal)
```bash
python main.py --cli   # Start CLI
python main.py --dev   # With dev mode debug tools
```

**Commands:**
| Command | Purpose |
|---------|---------|
| `/help` | Show help |
| `/quit`, `/exit` | Exit |
| `/new` | Start new session |
| `/end` | End session |
| `/stats` | System statistics |
| `/memories` | List recent memories |
| `/search <query>` | Search memories |
| `/extract` | Force extraction |
| `/pause` / `/resume` | Control pulse timer |
| `/core` | Show core memories |
| `/addcore <text>` | Add core memory |
| `/pulse` | View pulse status |

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Core dependencies:
- `anthropic>=0.78.0` — Claude API
- `sentence-transformers>=2.2.0` — Embeddings
- `rich>=13.0.0` — Terminal formatting
- `fastapi>=0.115.0` + `uvicorn>=0.32.0` — Web UI server
- `python-dotenv>=1.0.0` — Environment loading
- `numpy>=1.24.0` — Numerical operations

Optional:
- `python-telegram-bot>=21.0` — Telegram integration
- `playwright>=1.40.0` — Browser automation (delegate sub-agent)
- `google-api-python-client` — Google Calendar integration
- `pillow>=10.0.0` — Screenshot capture
- `opencv-python` — Webcam capture
- `openai>=1.0.0` — Text-to-speech
- `faster-whisper>=0.9.0` — Speech-to-text

### 2. Configure Environment

Create a `.env` file:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional
ANTHROPIC_MODEL=claude-sonnet-4-6
USER_NAME=YourName
AI_NAME=Isaac

# Telegram (optional)
telegram_bot=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# TTS (optional — uses OpenAI TTS)
OPENAI_API_KEY=your_openai_api_key

# Visual (optional)
VISUAL_ENABLED=true
VISUAL_SCREENSHOT_MODE=auto
VISUAL_WEBCAM_MODE=on_demand
```

### 3. Run

```bash
python main.py
```

---

## Configuration Highlights

| Setting | Default | Description |
|---------|---------|-------------|
| `CONTEXT_WINDOW_SIZE` | 30 | Target turns in context |
| `CONTEXT_OVERFLOW_TRIGGER` | 40 | Extract when reached |
| `MEMORY_SEMANTIC_WEIGHT` | 0.60 | Similarity importance |
| `MEMORY_IMPORTANCE_WEIGHT` | 0.25 | Rating importance |
| `MEMORY_FRESHNESS_WEIGHT` | 0.15 | Recency importance |
| `REFLECTIVE_PULSE_INTERVAL` | 43200 | Seconds between reflective pulses (12h) |
| `ACTION_PULSE_INTERVAL` | 7200 | Seconds between action pulses (2h) |
| `WEB_SEARCH_TOTAL_ALLOWED_PER_DAY` | 30 | Daily search budget |

See `config.py` for all options.

---

## Project Structure

```
Pattern_Project/
├── main.py                  # Entry point
├── config.py                # Configuration
├── CORE_MEMORIES.md         # AI identity document
├── engine/                  # Message processing
│   ├── chat_engine.py       # Core engine (prompt → LLM → tools → response)
│   └── events.py            # Event system for UI layers
├── memory/                  # Memory subsystem
│   ├── conversation.py      # Turn storage & windowing
│   ├── vector_store.py      # Semantic search (384-dim embeddings)
│   ├── extractor.py         # Background memory extraction
│   └── warmth_cache.py      # Session-scoped memory boosting
├── prompt_builder/          # Context assembly
│   ├── builder.py           # Orchestrator
│   └── sources/             # 14 pluggable context sources
├── llm/                     # LLM integration
│   ├── router.py            # Provider routing & task types
│   └── anthropic_client.py  # Claude API client
├── agency/                  # AI autonomy
│   ├── tools/               # Tool definitions & execution
│   ├── commands/handlers/   # Command handlers (modular)
│   ├── intentions/          # Reminder system
│   ├── curiosity/           # Curiosity engine
│   ├── growth_threads/      # Long-term pursuits
│   ├── active_thoughts/     # Working memory
│   ├── metacognition/       # Observer & bridge manager
│   ├── novel_reading/       # Book reading orchestrator
│   └── system_pulse.py      # Pulse timer (reflective + action)
├── communication/           # External gateways
│   ├── telegram_gateway.py  # Telegram messaging
│   ├── telegram_listener.py # Background message listener
│   ├── calendar_gateway.py  # Google Calendar
│   └── drive_backup_gateway.py  # Google Drive backup
├── interface/               # User interfaces
│   ├── cli.py               # Rich terminal UI
│   ├── web_server.py        # FastAPI + WebSocket server
│   └── web/                 # Static web assets
├── core/                    # Infrastructure
│   ├── database.py          # SQLite + WAL (schema v22)
│   ├── embeddings.py        # Sentence-transformers
│   ├── temporal.py          # Time & session tracking
│   └── user_settings.py     # Per-user preferences
├── concurrency/             # Thread safety
│   └── locks.py             # Lock manager
├── tts/                     # Text-to-speech (OpenAI)
├── stt/                     # Speech-to-text (Whisper)
├── voice/                   # Voice pipeline coordination
├── blog/                    # Blog publishing system
├── subprocess_mgmt/         # Sub-agent process management
├── deploy/                  # Deployment configs
├── scripts/                 # Utility & migration scripts
├── esp32/                   # ESP32 embedded client
└── docs/                    # Documentation (see below)
```

---

## Database

SQLite with WAL mode for concurrency. Schema version: **v22**

**Core tables:**
- `sessions` — Session metadata
- `conversations` — All turns with temporal data
- `memories` — Extracted memories with 384-dim embeddings
- `core_memories` — Permanent foundational knowledge
- `state` — Runtime key-value store
- `intentions` — Reminders and scheduled actions
- `active_thoughts` — AI's current working memory
- `curiosity_goals` — Curiosity exploration targets
- `growth_threads` — Long-term intellectual pursuits
- `reading_sessions` — Book reading progress
- `communication_log` — Telegram/external message history
- `relationships` — Entity relationship tracking
- `image_files` — Stored image metadata

See `core/database.py` for full schema.

---

## Design Philosophy

Pattern is built around these principles:

1. **Memory lives in the database, not the context** — The context window is a disposable lens onto persistent storage

2. **Semantic recall over chronological** — Old memories resurface when relevant, not because they're recent

3. **Graceful forgetting** — Freshness decay naturally ages out stale information

4. **AI agency with boundaries** — Autonomous actions (reminders, curiosity) within user-controlled limits

5. **Pluggable architecture** — New context sources, tools, and gateways can be added without core changes

---

## Documentation

All documentation lives in `docs/`, organized by category:

| Folder | Contents |
|--------|----------|
| [`docs/architecture/`](docs/architecture/) | System design, data flow, project overview |
| [`docs/deployment/`](docs/deployment/) | VPS setup guide, cloud readiness audit, operations cheatsheet |
| [`docs/guides/`](docs/guides/) | AI concepts guide & slides |
| [`docs/plans/`](docs/plans/) | Active development plans (metacognition, audit/testing, blog, cleanup) |
| [`docs/reference/`](docs/reference/) | Feature catalog, Guardian spec, streaming pipeline, bug history |
| [`docs/legacy/`](docs/legacy/) | Historical prompt system docs (pre-native tool use) |

---

## License

This project is for personal use.

---

*Pattern Project — Where memory meets agency*
