# Pattern Project

**An AI Companion System with Persistent Memory and Autonomous Agency**

> "The Prompt is the thing" — Each conversation draws from multiple context sources to create a rich, coherent understanding without accumulating context bloat.

Pattern is an advanced AI companion system built around Claude that doesn't just respond—it **understands, remembers, and initiates**. The system maintains persistent memories across sessions, assembles contextual prompts from multiple data sources, and can act autonomously through triggers, reminders, and curiosity-driven exploration.

---

## Key Features

### 🧠 Persistent Memory System
- **Semantic Memory Search** — Vector embeddings (all-MiniLM-L6-v2) with combined scoring: 65% semantic similarity, 25% importance, 10% freshness
- **Dual-Track Extraction** — Episodic memories (narratives: "We discussed X") and Factual memories (concrete facts: "User prefers dark mode")
- **Warmth Cache** — Session-scoped memory boosting for conversational continuity
- **Core Memories** — Permanent foundational knowledge that never decays
- **Decay Categories** — Permanent, standard (30-day), and ephemeral (7-day) half-lives

### 🤖 AI Agency & Autonomy
- **System Pulse Timer** — Periodic prompts during idle periods encourage autonomous thinking
- **Reminder System** — Natural language time parsing ("in 2 hours", "tomorrow morning")
- **Curiosity Engine** — AI-driven topic exploration from dormant and fresh memories
- **Active Thoughts** — AI's private working memory for priorities and ongoing deliberations

### 💬 Communication Gateways
- **Telegram Bot** — Bidirectional messaging with background listener
- **Email Gateway** — Gmail SMTP with recipient whitelist
- Rate limiting on all channels to prevent abuse

### 👁️ Visual Capture
- **Screenshot Capture** — See what the user is looking at
- **Webcam Capture** — Visual context when appropriate
- **Modes** — Auto (every prompt), On-Demand (tool-triggered), or Disabled

### 🔧 Native Tool System
Pattern uses Claude's native tool use (no text-pattern parsing):

| Tool | Purpose |
|------|---------|
| `search_memories` | Semantic memory search |
| `set_active_thoughts` | AI's working memory |
| `create_reminder` | Schedule reminders |
| `complete/dismiss_reminder` | Manage reminders |
| `read/write/append_file` | Sandboxed file operations |
| `list_files` | View available files |
| `send_telegram` | Telegram messaging |
| `send_email` | Email sending |
| `capture_screenshot` | Screen capture |
| `capture_webcam` | Webcam capture |
| `set_pulse_interval` | Control pulse timing |
| `advance_curiosity` | Progress curiosity exploration |
| `get/set_clipboard` | Clipboard access |
| `request_clarification` | Ask user for input |

### 🌐 Web Search
- Native Anthropic web search capability
- Daily budget: 30 searches/day
- Automatic citation tracking

### 🔊 Text-to-Speech
- ElevenLabs integration (Turbo v2.5 model)
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

Context doesn't accumulate—it flows through a window:

```
Context Window (30 turns) → Overflow (40 turns) → Extract oldest 10 → Back to 30
```

Extracted conversations become searchable memories that resurface when semantically relevant.

### Pluggable Context Sources

12+ independent sources combine into rich prompts:

| Priority | Source | Purpose |
|----------|--------|---------|
| 5 | Dev Mode | Debug information |
| 10 | Core Memory | Permanent identity/facts |
| 18 | Active Thoughts | AI's working memory |
| 22 | Intentions | Pending reminders |
| 25 | System Pulse | Pulse timer state |
| 26 | AI Commands | Tool documentation |
| 30 | Temporal | Time/session awareness |
| 40 | Visual | Screenshot/webcam |
| 50 | Semantic Memory | Vector-searched memories |
| 60 | Conversation | Recent history |
| 70+ | Tool Stance, Curiosity | Behavioral guidance |

---

## Interfaces

### CLI (Rich Terminal)
```bash
python main.py        # Start CLI
python main.py --dev  # With debug window
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

### HTTP API (Flask)
- `/health` — Health check
- `/chat` — Send message
- `/memories/search` — Search memories
- `/stats` — System statistics
- `/session/new`, `/session/end` — Session control

### GUI (PyQt5)
Rich graphical interface with streaming, overlays, and TTS integration.

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Core dependencies:
- `anthropic>=0.18.0` — Claude API
- `sentence-transformers>=2.2.0` — Embeddings
- `rich>=13.0.0` — Terminal formatting
- `flask>=3.0.0` — HTTP API
- `python-dotenv>=1.0.0` — Environment loading

Optional:
- `PyQt5>=5.15.0` — GUI interface
- `elevenlabs>=1.0.0` — Text-to-speech
- `python-telegram-bot>=21.0` — Telegram integration
- `opencv-python` — Webcam capture
- `pillow` — Screenshot capture
- `pyperclip` — Clipboard access

### 2. Configure Environment

Create a `.env` file:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Optional
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
USER_NAME=YourName
AI_NAME=YourAIName

# Telegram (optional)
telegram_bot=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# TTS (optional)
Eleven_Labs_API=your_api_key

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
| `MEMORY_SEMANTIC_WEIGHT` | 0.65 | Similarity importance |
| `MEMORY_IMPORTANCE_WEIGHT` | 0.25 | Rating importance |
| `MEMORY_FRESHNESS_WEIGHT` | 0.10 | Recency importance |
| `SYSTEM_PULSE_INTERVAL` | 600 | Seconds between pulses |
| `WEB_SEARCH_TOTAL_ALLOWED_PER_DAY` | 30 | Daily search budget |

See `config.py` for all options.

---

## Project Structure

```
Pattern_Project/
├── main.py                 # Entry point
├── config.py               # Configuration (~500 settings)
├── memory/                 # Memory subsystem
│   ├── conversation.py     # Turn storage
│   ├── vector_store.py     # Semantic search
│   ├── extractor.py        # Background extraction
│   └── semantic_memory.py  # Dual-track + warmth cache
├── prompt_builder/         # Context assembly
│   ├── builder.py          # Orchestrator
│   └── sources/            # 12+ pluggable sources
├── llm/                    # LLM integration
│   ├── router.py           # Provider routing
│   └── anthropic_client.py # Claude API
├── agency/                 # AI autonomy
│   ├── tools/              # Native tool definitions
│   ├── intentions/         # Reminder system
│   ├── curiosity/          # Curiosity engine
│   └── system_pulse.py     # Pulse timer
├── communication/          # Gateways
│   ├── telegram_gateway.py
│   └── email_gateway.py
├── interface/              # User interfaces
│   ├── cli.py              # Rich terminal
│   └── http_api.py         # Flask REST
├── core/                   # Infrastructure
│   ├── database.py         # SQLite + WAL
│   └── embeddings.py       # Sentence-transformers
└── docs/                   # Documentation
```

---

## Database

SQLite with WAL mode for concurrency. Current schema version: **v9+**

**Tables:**
- `sessions` — Session metadata
- `conversations` — All turns with temporal data
- `memories` — Extracted memories with 384-dim embeddings
- `core_memories` — Permanent foundational knowledge
- `state` — Runtime key-value store

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

- [Feature Catalog](FEATURE_CATALOG.md) — Complete feature reference
- [Architecture](docs/ARCHITECTURE.md) — System design
- [Data Flow](docs/DATA_FLOW.md) — How context flows through the system
- [Prompt System](docs/prompts/PROMPT_SYSTEM_OVERVIEW.md) — Prompt assembly details

---

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).

---

*Pattern Project — Where memory meets agency*
