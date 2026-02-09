# Pattern Project Architecture

## Vision

Pattern is an AI companion system that doesn't just respond—it understands, remembers, and initiates. The system assembles rich contextual prompts from multiple data sources and can act autonomously based on triggers.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     USER INTERFACES                             │
│  ┌──────────────────┬──────────────────┬──────────────────────┐ │
│  │   GUI / CLI      │   HTTP API       │   Telegram           │ │
│  │  (Rich Terminal) │  (Flask REST)    │   (Bot listener)     │ │
│  └──────────────────┴──────────────────┴──────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      PROMPT BUILDER                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│  │Memories │ │   Web   │ │ Visuals │ │  Core   │            │
│  │         │ │ Sources │ │         │ │Memories │            │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘            │
│       │           │           │           │                  │
│  ┌────┴───────────┴───────────┴───────────┴───────────┴────┐  │
│  │              CONTEXT ASSEMBLY ENGINE                     │  │
│  │    • Token budgeting   • Source prioritization          │  │
│  │    • Temporal context  • Persona injection              │  │
│  └─────────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼───────────────────────────────────┘
                             │
                             ▼
                    [Assembled Prompt]
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLM ROUTER                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Anthropic Claude (Primary)                               │  │
│  │  • Conversation, extraction, analysis, native tools       │  │
│  │  • Web search & fetch (built-in tools)                    │  │
│  │  • Visual understanding (native multimodal)               │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  KoboldCpp (Optional local fallback, non-conversation)    │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                             │
                             ▼
                       AI Response
                             │
              ┌──────────────┴──────────────┐
              ▼                              ▼
       Display to User              Store in Memory
```

---

## Core Components

### 1. Interfaces
- **GUI** (`interface/gui.py`): Rich terminal with slash commands (primary interface)
- **CLI** (`interface/cli.py`): Lightweight Rich terminal alternative
- **HTTP API** (`interface/http_api.py`): REST endpoints for external integration
- **Telegram** (`interface/telegram_listener.py`): Bot-based messaging interface

### 2. LLM Layer
- **Router** (`llm/router.py`): Task-based routing (Claude primary, KoboldCpp optional fallback for non-conversation tasks)
- **Anthropic Client** (`llm/anthropic_client.py`): Claude API with native tool use, web search, web fetch, and multimodal vision
- **Kobold Client** (`llm/kobold_client.py`): Optional local LLM fallback

### 3. Memory System
- **Conversation Manager** (`memory/conversation.py`): Turn storage with temporal data and windowed context
- **Vector Store** (`memory/vector_store.py`): Semantic search with freshness decay
- **Memory Extractor** (`memory/extractor.py`): Windowed extraction triggered by context overflow

### 4. Core Infrastructure
- **Database** (`core/database.py`): SQLite + WAL + migrations (schema v18)
- **Embeddings** (`core/embeddings.py`): Lazy-loaded sentence-transformers
- **Temporal Tracker** (`core/temporal.py`): Session and timing management
- **Logger** (`core/logger.py`): Rich console + file logging

### 5. Concurrency
- **Lock Manager** (`concurrency/locks.py`): Named RLocks with statistics
- **DB Retry** (`concurrency/db_retry.py`): Exponential backoff

---

## Data Flow

### User-Initiated Flow

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────┐
│              PROMPT BUILDER                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐            │
│  │ Memories│ │  Web    │ │ Visuals │            │
│  └────┬────┘ └────┬────┘ └────┬────┘            │
│       │           │           │                  │
│  ┌────┴────┐ ┌────┴────┐ ┌────┴────┐            │
│  │  Core   │ │Temporal │ │ Semantic│            │
│  │Memories │ │ Context │ │ Recall  │            │
│  └────┬────┘ └────┬────┘ └────┬────┘            │
│       └───────────┼───────────┘                  │
│                   ▼                              │
│         [Assembled Prompt]                       │
└─────────────────────────────────────────────────┘
                    │
                    ▼
              LLM API Call
                    │
                    ▼
              AI Response
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   Display to User      Store in Memory
```

### AI-Initiated Flow (System Pulse)

```
System Pulse Timer
├── Idle timer fires (configurable: 3m to 6h)
├── AI evaluates whether to speak
└── Can adjust its own timer interval
        │
        ▼
   [Same Prompt Builder] → LLM → Output
```

---

## Memory System

### Memory Categories
| Category | Description |
|----------|-------------|
| `episodic` | Narrative memories about what happened (first-person) |
| `factual` | Concrete facts about the user (third-person assertions) |

### Memory Types
| Type | Description | Example |
|------|-------------|---------|
| `fact` | Objective information | "User works as a software engineer" |
| `preference` | Likes/dislikes | "Prefers detailed explanations" |
| `event` | Something that happened | "Discussed machine learning project" |
| `reflection` | AI insight | "User seems interested in architecture" |
| `observation` | Pattern noticed | "Asks implementation questions often" |

### Decay Categories
| Value | Description |
|-------|-------------|
| `permanent` | Never decays (core facts, high-importance preferences) |
| `standard` | 30-day half-life (events, reflections, moderate items) |
| `ephemeral` | 7-day half-life (low-importance observations) |

### Windowed Extraction
```
Context Window (30 turns)
    │
    │  When unprocessed turns reach 40:
    │  Extract oldest 10 (40 - 30 = 10) via single Claude API call
    │
    ▼
┌───────────────────────────────────────────┐
│  Unified Extraction (1 API call)          │
│  → 1-3 episodic memories (first-person)   │
│  → 0-6 factual memories (third-person)    │
│  → Mark extracted turns as processed      │
└───────────────────────────────────────────┘
```

### Scoring Algorithm
```
combined_score = (
    SEMANTIC_WEIGHT × cosine_similarity(query, memory) +
    IMPORTANCE_WEIGHT × normalized_importance +
    FRESHNESS_WEIGHT × 2^(-age_days / HALF_LIFE)
)

Defaults:
  SEMANTIC_WEIGHT = 0.65
  IMPORTANCE_WEIGHT = 0.25
  FRESHNESS_WEIGHT = 0.10
  HALF_LIFE = 30 days (standard), 7 days (ephemeral)
```

---

## Prompt Builder

### Context Sources

| Source | Status | Description |
|--------|--------|-------------|
| Core Memories | Built | Permanent, foundational knowledge (always included) |
| Temporal Context | Built | Time awareness, session duration |
| Visual Input | Built | Screenshots/webcam via Claude native multimodal |
| Semantic Memories | Built | Relevant memories via vector search |
| Conversation History | Built | Windowed context (30 turns) |
| Web Search | Built | Claude built-in web search tool |
| Web Fetch | Built | Claude built-in page fetcher |
| Active Thoughts | Built | AI's working memory / stream of consciousness |
| Intentions | Built | Reminders and goals the AI tracks |
| Curiosity | Built | Topics the AI is exploring |
| Growth Threads | Built | Long-term developmental aspirations |

### Assembly Process (Priority Order)
1. **Core Memories** (priority 10) - Always included, foundational facts
2. **System Pulse** (priority 25) - AI agency timer control
3. **Temporal Context** (priority 30) - Time of day, session duration
4. **Visual Context** (priority 40) - Screenshot/webcam via native multimodal
5. **Semantic Memories** (priority 50) - Relevance-scored memories
6. **Conversation History** (priority 60) - Windowed context
7. **User Input** - Current message

### Pluggable Source Architecture
```python
class ContextSource(ABC):
    @property
    def source_name(self) -> str: ...
    @property
    def priority(self) -> int: ...
    def get_context(self, user_input, session_context) -> ContextBlock: ...
```

New sources can be added without modifying PromptBuilder.

---

## Configuration

### Environment Variables
```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-6
LLM_PRIMARY_PROVIDER=anthropic
LOG_LEVEL=INFO
```

### Key Settings (config.py)
| Setting | Default | Description |
|---------|---------|-------------|
| `CONTEXT_WINDOW_SIZE` | 30 | Turns kept in active context |
| `CONTEXT_OVERFLOW_TRIGGER` | 40 | Turns before extraction fires |
| `CONTEXT_EXTRACTION_BATCH` | 10 | Turns extracted per cycle |
| `MEMORY_FRESHNESS_HALF_LIFE_DAYS` | 30 | Standard memory decay rate |
| `AGENCY_IDLE_TRIGGER_SECONDS` | 900 | 15 min idle trigger |
| `AGENCY_CHECK_INTERVAL` | 300 | 5 min check interval |
| `MAX_CONCURRENT_LLM_REQUESTS` | 3 | LLM call limit |

---

## Threading Model

```
Main Process
├── [Main Thread] GUI/CLI input loop
├── [Threshold] MemoryExtractor - triggered by context overflow (40 turns)
├── [Daemon] SystemPulseTimer - configurable interval (default 10 min)
├── [Daemon] ReminderScheduler - intention due-date checking
├── [Daemon] SubprocessMonitor - health checks
├── [Daemon] HTTPServer - Flask (if enabled)
└── [Daemon] TelegramListener - bot polling (if enabled)
```

All daemon threads stop automatically when main exits.

---

## Database Schema (v18)

```sql
sessions              -- Session metadata
conversations         -- All turns with temporal data
memories              -- Extracted memories with embeddings
core_memories         -- Permanent foundational knowledge
state                 -- Key-value runtime state
schema_version        -- Migration tracking
intentions            -- AI reminders, goals, and plans
communication_log     -- Email/Telegram message tracking
active_thoughts       -- AI working memory / stream of consciousness
curiosity_goals       -- Curiosity-driven exploration topics
active_thoughts_history -- Longitudinal thought state archive
growth_threads        -- Long-term developmental aspirations
```

---

## Visual System

### Pipeline
1. Screenshot/webcam captured per configured mode (`auto` or `on_demand`)
2. Image attached directly to Claude API call as multimodal content
3. Claude interprets the image natively (no intermediary model)

### Capture Modes
| Mode | Behavior |
|------|----------|
| `auto` | Captures automatically every prompt, no tool added |
| `on_demand` | AI requests capture via tool when needed |
| `disabled` | Source never used |

### Configuration
```bash
VISUAL_ENABLED=true
VISUAL_SCREENSHOT_MODE=auto
VISUAL_WEBCAM_MODE=on_demand
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/quit` or `/exit` | Exit program |
| `/new` | Start new session |
| `/end` | End session |
| `/stats` | System statistics |
| `/memories` | Show recent memories |
| `/search <query>` | Semantic memory search |
| `/extract` | Force memory extraction |
| `/core` | Show core memories |
| `/addcore <cat> <content>` | Add core memory |
| `/pulse` | Show system pulse timer status |
| `/pause` | Pause background processes |
| `/resume` | Resume background processes |
