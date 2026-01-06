# Pattern Project — Feature Catalog

A comprehensive reference of all features, their configuration, and current status.

---

## 1. Memory System

### 1.1 Conversation Memory
- **Storage**: SQLite with WAL mode for concurrency
- **Turn Data**: Role, content, timestamps, input type (text/voice/image)
- **Temporal Metadata**: Time gaps between messages (`time_since_last_turn_seconds`)
- **Processing Flag**: `processed_for_memory` tracks extraction status

### 1.2 Semantic Memory Search
- **Embedding Model**: all-MiniLM-L6-v2 (384 dimensions)
- **Combined Scoring Algorithm**:
  | Weight | Factor | Description |
  |--------|--------|-------------|
  | 65% | Semantic Similarity | Cosine similarity between query and memory embeddings |
  | 25% | Importance Score | AI-rated significance (0.0–1.0) |
  | 10% | Freshness | Decay based on memory age |
  | 0% | Access Recency | *Deprecated* — Now handled by Warmth Cache |

- **Dual-Track Retrieval**:
  - **Episodic**: Narrative memories ("We discussed machine learning")
  - **Factual**: Concrete facts ("Brian is 45 years old")
  - Queries both categories separately for balanced results

- **Relevance Floor**: 0.35 minimum combined score to include
- **Max Results**: 5 episodic + 5 factual per query

### 1.3 Memory Warmth Cache
Session-scoped memory boosting for conversational continuity:

| Type | Initial Boost | Decay/Turn | Purpose |
|------|---------------|------------|---------|
| Retrieval Warmth | 0.15 | 0.6x | Recently discussed topics stay accessible |
| Topic Warmth | 0.10 | 0.5x | Associated memories pre-warmed |
| Combined Cap | 0.20 | — | Maximum warmth boost |

**Example**: Discussing "game awards" → memory stays warm even if next query doesn't mention "awards"

### 1.4 Windowed Memory Extraction
Context flows through a bounded window instead of accumulating:

```
Context Window (30 turns) → Overflow (40 turns) → Extract oldest 10 → Back to 30
```

- **Unified Extraction**: Single API call extracts both episodic and factual memories
- **Max Per Extraction**: 6 episodic + 8 factual
- **Importance Floor**: Memories rated below 0.3 are not stored

### 1.5 Memory Decay Categories
| Category | Half-Life | Use Case |
|----------|-----------|----------|
| Permanent | Never | Core identity, lasting preferences, key biographical facts |
| Standard | 30 days | Events, discussions, insights |
| Ephemeral | 7 days | Situational observations, temporary states |

Decay category is inferred from memory type and importance automatically.

### 1.6 Core Memories
- **Purpose**: Permanent foundational knowledge that never decays
- **Categories**: identity, relationship, preference, fact, narrative
- **Management**:
  - Manual via `/addcore` command
  - Auto-promotion when regular memory scores > 0.85 relevance
- **Always Included**: Core memories appear in every prompt

### 1.7 Deduplication
- **Enabled by default**: Prevents the same fact from consuming multiple retrieval slots
- **Similarity Threshold**: 0.85 embedding similarity = duplicate
- **Behavior**: Highest-scored duplicate is kept, others collapsed

---

## 2. LLM Integration

### 2.1 Multi-Provider Routing
| Provider | Role | Model |
|----------|------|-------|
| Anthropic Claude | Primary (conversation) | claude-sonnet-4-5-20250929 |
| Anthropic Claude | Extraction | claude-sonnet-4-5-20250929 |
| KoboldCpp (Local) | Fallback only | Llama-3 compatible |

- **Task-Based Routing**: CONVERSATION, EXTRACTION, SIMPLE
- **Fallback**: Automatic retry with secondary provider on failure
- **Concurrent Limit**: Max 3 simultaneous LLM requests

### 2.2 Web Search Integration
- **Capability**: Native Anthropic web search (server-side)
- **Daily Budget**: 30 searches/day
- **Per-Request Limit**: 3 searches per API call
- **Citations**: Automatic tracking with title, URL, cited text
- **Pricing**: $10 per 1,000 searches + token costs

### 2.3 Streaming Support
- **Response Streaming**: Real-time token display
- **Tool Call Handling**: Proper streaming with tool use
- **TTS Integration**: Sentence-by-sentence audio streaming

---

## 3. AI Agency & Autonomy

### 3.1 System Pulse Timer
Sends periodic prompts during idle periods to encourage autonomous thinking.

| Setting | Default | Description |
|---------|---------|-------------|
| `SYSTEM_PULSE_ENABLED` | true | Master toggle |
| `SYSTEM_PULSE_INTERVAL` | 600s | 10 minutes between pulses |

- **Adjustable Intervals**: 3m, 10m, 30m, 1h, 6h via `set_pulse_interval` tool
- **Reset**: Timer resets on user message
- **CLI Control**: `/pause` and `/resume` commands

### 3.2 Reminder/Intention System
AI-created reminders with natural language time parsing.

**Time Formats Supported**:
- Relative: "in 30 minutes", "in 2 hours", "in 3 days"
- Named: "tomorrow", "tomorrow morning", "tomorrow evening", "tonight"
- Session-based: "next session" (triggers when user returns)

**Intention Lifecycle**:
```
pending → triggered → completed/dismissed
```

| Setting | Default | Description |
|---------|---------|-------------|
| `INTENTION_ENABLED` | true | Master toggle |
| `INTENTION_MAX_PENDING_DISPLAY` | 3 | Max shown in context |
| Scheduler interval | 30s | Background check frequency |

### 3.3 Active Thoughts
AI's private working memory for priorities and ongoing deliberations.

- **Max Items**: 10 ranked thoughts (1 = most salient)
- **Structure**: rank, slug, topic, elaboration (~50-75 words each)
- **Persistence**: Session-scoped, decays as session progresses
- **Purpose**: Identity anchors, unresolved questions, long-term goals

### 3.4 Curiosity Engine
AI-driven topic exploration from dormant and fresh memories.

**Discovery Types**:
| Type | Criteria | Description |
|------|----------|-------------|
| Dormant | >7 days without access | Resurface forgotten topics |
| Fresh | <48 hours old, importance ≥0.5 | Explore new information |

**Cooldown Periods** (after exploration):
| Outcome | Cooldown | Trigger |
|---------|----------|---------|
| Explored (shallow) | ~20 hours | 2 interactions |
| Explored (deep) | ~48 hours | 5+ interactions |
| Deferred | 2 hours | "Not now" |
| Declined | 72 hours | User rejected |

---

## 4. Native Tool System

Pattern uses Claude's native tool use API. Tools are conditionally registered based on config.

### 4.1 Core Tools (Always Available)

| Tool | Purpose |
|------|---------|
| `search_memories` | Semantic memory search with natural language queries |
| `set_active_thoughts` | Update AI's working memory (max 10 ranked items) |

### 4.2 Intention Tools (if `INTENTION_ENABLED`)

| Tool | Purpose |
|------|---------|
| `create_reminder` | Schedule reminders with NLP time parsing |
| `complete_reminder` | Mark reminder done with optional outcome |
| `dismiss_reminder` | Cancel a reminder |
| `list_reminders` | View all active reminders |

### 4.3 File Tools

| Tool | Purpose |
|------|---------|
| `read_file` | Read from sandboxed storage |
| `write_file` | Create/overwrite file |
| `append_file` | Add to existing file |
| `list_files` | List available files |

**File Storage**:
- **Directory**: `data/files/` (sandboxed)
- **Extensions**: .txt, .md, .json, .csv
- **Max Size**: 30MB
- **Security**: No path traversal, filename sanitization

### 4.4 Communication Tools (Conditional)

| Tool | Condition | Purpose |
|------|-----------|---------|
| `send_telegram` | `TELEGRAM_ENABLED` | Send Telegram message |
| `send_email` | `EMAIL_GATEWAY_ENABLED` | Send email to whitelisted recipient |

### 4.5 Visual Tools (Conditional)

| Tool | Condition | Purpose |
|------|-----------|---------|
| `capture_screenshot` | `VISUAL_SCREENSHOT_MODE == "on_demand"` | Capture current screen |
| `capture_webcam` | `VISUAL_WEBCAM_MODE == "on_demand"` | Capture webcam image |

### 4.6 System Tools

| Tool | Condition | Purpose |
|------|-----------|---------|
| `set_pulse_interval` | `SYSTEM_PULSE_ENABLED` | Adjust idle timer (3m/10m/30m/1h/6h) |
| `advance_curiosity` | `CURIOSITY_ENABLED` | Progress/resolve curiosity topic |

### 4.7 Utility Tools

| Tool | Condition | Purpose |
|------|-----------|---------|
| `get_clipboard` | `CLIPBOARD_ENABLED` | Read system clipboard |
| `set_clipboard` | `CLIPBOARD_ENABLED` | Copy to clipboard |
| `request_clarification` | `CLARIFICATION_ENABLED` | Ask user for input |

---

## 5. Communication Gateways

### 5.1 Telegram Bot
- **Integration**: Bidirectional messaging via Telegram Bot API
- **Listener**: Background thread for incoming messages
- **Auto-Detection**: Chat ID detected on first message
- **Rate Limit**: 30 messages/hour
- **Status**: Configurable (`TELEGRAM_ENABLED`)

### 5.2 Email Gateway
- **Provider**: Gmail SMTP with app password
- **Security**: Recipient whitelist required
- **Rate Limit**: 20 emails/hour
- **Status**: Disabled by default (`EMAIL_GATEWAY_ENABLED`)

### 5.3 Rate Limiting
| Gateway | Limit | Window |
|---------|-------|--------|
| Telegram | 30 | per hour |
| Email | 20 | per hour |

---

## 6. Visual Capture System

### 6.1 Capture Sources
| Source | Capture Mode | Description |
|--------|--------------|-------------|
| Screenshot | auto/on_demand/disabled | Screen capture via Pillow |
| Webcam | auto/on_demand/disabled | Camera capture via OpenCV |

### 6.2 Capture Modes
| Mode | Behavior |
|------|----------|
| `auto` | Capture on every prompt (user input or pulse) |
| `on_demand` | Only when AI uses capture tool |
| `disabled` | Never capture |

### 6.3 Processing
- **Method**: Direct Claude multimodal (images attached to messages)
- **No External API**: Uses Claude's native vision capabilities
- **Caching**: Freshness checks to avoid redundant captures

---

## 7. User Interfaces

### 7.1 CLI Interface (Rich Terminal)

| Command | Purpose |
|---------|---------|
| `/help` | Show help |
| `/quit`, `/exit` | Exit application |
| `/new` | Start new session |
| `/end` | End session (triggers extraction) |
| `/stats` | System statistics |
| `/memories` | List recent memories |
| `/search <query>` | Semantic memory search |
| `/extract` | Force memory extraction |
| `/pause` | Pause pulse timer |
| `/resume` | Resume pulse timer |
| `/core` | Show core memories |
| `/addcore <text>` | Add core memory |
| `/pulse` | View pulse status |

### 7.2 HTTP REST API (Flask)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/chat` | POST | Send message |
| `/memories/search` | POST | Search memories |
| `/stats` | GET | System statistics |
| `/session/new` | POST | Start new session |
| `/session/end` | POST | End session |
| `/extract` | POST | Trigger extraction |

**Configuration**:
- `HTTP_ENABLED`: true/false
- `HTTP_HOST`: 127.0.0.1
- `HTTP_PORT`: 5000

### 7.3 GUI Interface (PyQt5)
- **Features**: Rich chat display, streaming, overlays
- **TTS Integration**: ElevenLabs voice output
- **Dependency**: Requires PyQt5 installation

### 7.4 Dev Window
Debug interface showing internal operations:
- Prompt assembly and context blocks
- Tool execution and results
- Memory recall scores
- Token counts and timing

**Launch**: `python main.py --dev`

---

## 8. Context & Prompt Building

### 8.1 Pluggable Context Sources (12+)

| Priority | Source | Always | Purpose |
|----------|--------|--------|---------|
| 5 | DevModeSource | No | Debug information |
| 10 | CoreMemorySource | Yes | Permanent identity/facts |
| 18 | ActiveThoughtsSource | No | AI's working memory |
| 22 | IntentionSource | No | Pending/triggered reminders |
| 25 | SystemPulseSource | No | Pulse timer state |
| 26 | AICommandsSource | Yes | Tool documentation |
| 30 | TemporalSource | Yes | Time/session awareness |
| 40 | VisualSource | No | Screenshot/webcam descriptions |
| 50 | SemanticMemorySource | No | Vector-searched memories |
| 60 | ConversationSource | Yes | Last 30 turns |
| 70 | ToolStanceSource | No | Tool usage guidance |
| 75 | CuriositySource | No | Current curiosity topic |

### 8.2 Context Assembly
Each prompt is built fresh from registered sources, sorted by priority, producing a self-contained context window.

---

## 9. Text-to-Speech

### 9.1 ElevenLabs Integration
| Setting | Value |
|---------|-------|
| Model | eleven_turbo_v2_5 |
| Default Voice | MKHH3pSZhHPPzypDhMoU |
| Audio Port | 5003 |

### 9.2 Features
- **Streaming**: Sentence-by-sentence audio delivery
- **Sequence Preservation**: Reorder buffer ensures correct playback order
- **User Preferences**: Voice selection stored in `user_settings.json`

---

## 10. Infrastructure

### 10.1 Database
- **Engine**: SQLite with WAL mode
- **Schema Version**: v9+
- **Busy Timeout**: 10 seconds
- **Retry Logic**: Exponential backoff (0.1s → 3.2s, max 5 retries)

**Tables**:
| Table | Purpose |
|-------|---------|
| `sessions` | Session metadata (start, end, duration) |
| `conversations` | All turns with temporal data |
| `memories` | Extracted memories with 384-dim embeddings |
| `core_memories` | Permanent foundational knowledge |
| `state` | Key-value runtime state |
| `schema_version` | Migration tracking |

### 10.2 Concurrency
- **Lock Manager**: Named RLocks with contention statistics
- **LLM Semaphore**: Max 3 concurrent requests
- **DB Retry**: Exponential backoff with graceful degradation

### 10.3 Background Services

| Service | Interval | Purpose |
|---------|----------|---------|
| Memory Extractor | On overflow | Extract memories from conversations |
| System Pulse | 10 min (configurable) | Autonomous AI prompts |
| Reminder Scheduler | 30 seconds | Fire triggered reminders |
| Telegram Listener | 2 seconds | Poll for incoming messages |
| Health Monitor | 30 seconds | System health checks |

### 10.4 Logging
- **Console**: Rich formatting
- **File**: `logs/diagnostic.log`
- **API Prompts**: `logs/api_prompts.jsonl`

---

## Quick Reference: Feature Status

| Feature | Status | Configuration |
|---------|--------|---------------|
| Memory extraction | ✅ Enabled | Automatic on overflow |
| Dual-track retrieval | ✅ Enabled | Episodic + Factual |
| Warmth cache | ✅ Enabled | Session-scoped |
| Core memories | ✅ Enabled | Manual + auto-promotion |
| System pulse | ✅ Enabled | `SYSTEM_PULSE_ENABLED` |
| Reminders | ✅ Enabled | `INTENTION_ENABLED` |
| Curiosity engine | ✅ Enabled | `CURIOSITY_ENABLED` |
| Active thoughts | ✅ Enabled | Core tool |
| Web search | ✅ Enabled | 30/day budget |
| Native tools | ✅ Enabled | Always (no legacy commands) |
| Telegram | ⚙️ Configurable | `TELEGRAM_ENABLED` |
| Email | ❌ Disabled | `EMAIL_GATEWAY_ENABLED` |
| Visual capture | ⚙️ Configurable | `VISUAL_ENABLED` |
| TTS | ⚙️ Configurable | Requires ElevenLabs key |
| Clipboard | ✅ Enabled | `CLIPBOARD_ENABLED` |
| Clarification | ✅ Enabled | `CLARIFICATION_ENABLED` |
| GUI | ⚠️ Optional | Requires PyQt5 |
| HTTP API | ⚙️ Configurable | `HTTP_ENABLED` |

---

## Configuration Reference

### Memory Settings
```python
CONTEXT_WINDOW_SIZE = 30              # Target turns in context
CONTEXT_OVERFLOW_TRIGGER = 40         # Extract when reached
CONTEXT_EXTRACTION_BATCH = 10         # Turns to extract per overflow

MEMORY_SEMANTIC_WEIGHT = 0.65         # Similarity importance
MEMORY_IMPORTANCE_WEIGHT = 0.25       # Rating importance
MEMORY_FRESHNESS_WEIGHT = 0.10        # Recency importance

MEMORY_MAX_EPISODIC_PER_QUERY = 5     # Episodic retrieval limit
MEMORY_MAX_FACTUAL_PER_QUERY = 5      # Factual retrieval limit
MEMORY_RELEVANCE_FLOOR = 0.35         # Minimum score threshold
MEMORY_IMPORTANCE_FLOOR = 0.3         # Don't store below this

DECAY_HALF_LIFE_STANDARD = 30.0       # Days for standard decay
DECAY_HALF_LIFE_EPHEMERAL = 7.0       # Days for ephemeral decay
```

### Warmth Cache Settings
```python
WARMTH_RETRIEVAL_INITIAL = 0.15       # Boost for retrieved memories
WARMTH_RETRIEVAL_DECAY = 0.6          # Per-turn decay
WARMTH_TOPIC_INITIAL = 0.10           # Boost for associated memories
WARMTH_TOPIC_DECAY = 0.5              # Per-turn decay
WARMTH_CAP = 0.20                     # Maximum combined boost
```

### Agency Settings
```python
SYSTEM_PULSE_ENABLED = True
SYSTEM_PULSE_INTERVAL = 600           # 10 minutes

INTENTION_ENABLED = True
INTENTION_MAX_PENDING_DISPLAY = 3

CURIOSITY_ENABLED = True
CURIOSITY_DORMANT_DAYS = 7
CURIOSITY_FRESH_HOURS = 48
```

### Communication Settings
```python
TELEGRAM_ENABLED = True               # Set to False to disable
TELEGRAM_MAX_PER_HOUR = 30

EMAIL_GATEWAY_ENABLED = False         # Disabled by default
EMAIL_MAX_PER_HOUR = 20
```

### Visual Settings
```python
VISUAL_ENABLED = True
VISUAL_SCREENSHOT_MODE = "auto"       # "auto", "on_demand", "disabled"
VISUAL_WEBCAM_MODE = "on_demand"      # "auto", "on_demand", "disabled"
```

---

## Architecture Notes

### Why Ephemeral Context Windows?
1. **No accumulation** — Context doesn't grow over sessions
2. **Consistent size** — Always bounded (~2K tokens) regardless of history
3. **Semantic relevance** — Old memories resurface when relevant
4. **Graceful forgetting** — Freshness decay ages out stale info naturally

### Why Native Tools vs Text Commands?
1. **Type safety** — Structured schemas prevent parsing errors
2. **Reliability** — Claude's native tool use is more reliable than regex
3. **Simplicity** — No multi-pass command extraction needed
4. **Future-proof** — Aligned with Anthropic's recommended patterns

### Why Dual-Track Memory?
1. **Balanced recall** — Both narrative context and specific facts
2. **Different decay** — Facts often permanent, episodes fade
3. **Better coverage** — Neither category dominates retrieval slots
