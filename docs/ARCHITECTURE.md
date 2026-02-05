# Pattern Project Architecture

## Vision

Pattern is an AI companion system that doesn't just respond—it understands, remembers, and initiates. The system assembles rich contextual prompts from multiple data sources and can act autonomously based on triggers.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     USER INTERFACES                             │
│  ┌──────────────────┬──────────────────┬──────────────────────┐ │
│  │   CLI Interface  │   HTTP API       │  Proactive Agency    │ │
│  │  (Rich Terminal) │  (Flask REST)    │  (AI-initiated)      │ │
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
│  ┌──────────────────────┐    ┌──────────────────────┐         │
│  │  Anthropic Claude    │◄──►│  KoboldCpp (Local)   │         │
│  │  (Primary/Quality)   │    │  (Fallback/Extract)  │         │
│  └──────────────────────┘    └──────────────────────┘         │
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
- **CLI** (`interface/cli.py`): Rich terminal with slash commands
- **HTTP API** (`interface/http_api.py`): REST endpoints for external integration
- **Proactive Agency** (`agency/proactive.py`): AI-initiated conversations

### 2. LLM Layer
- **Router** (`llm/router.py`): Task-based routing with fallback
- **Anthropic Client** (`llm/anthropic_client.py`): Claude API
- **Kobold Client** (`llm/kobold_client.py`): Local Llama-3

### 3. Memory System
- **Conversation Manager** (`memory/conversation.py`): Turn storage with temporal data
- **Vector Store** (`memory/vector_store.py`): Semantic search with freshness decay
- **Memory Extractor** (`memory/extractor.py`): Background extraction thread

### 4. Core Infrastructure
- **Database** (`core/database.py`): SQLite + WAL + migrations
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

### AI-Initiated Flow (Proactive)

```
Timer Triggers
├── Idle (user hasn't responded)
├── Reflection (after memory extraction)
├── Curiosity (incomplete information)
├── Greeting (time-of-day)
└── Reminder (scheduled events)
        │
        ▼
   Evaluate: Should AI speak?
        │
        ▼
   [Same Prompt Builder] → LLM → Output
```

---

## Memory System

### Memory Types
| Type | Description | Example |
|------|-------------|---------|
| `fact` | Objective information | "User works as a software engineer" |
| `preference` | Likes/dislikes | "Prefers detailed explanations" |
| `event` | Something that happened | "Discussed machine learning project" |
| `reflection` | AI insight | "User seems interested in architecture" |
| `observation` | Pattern noticed | "Asks implementation questions often" |

### Temporal Relevance
| Value | Description |
|-------|-------------|
| `permanent` | Never decays (core facts) |
| `recent` | High relevance, normal decay |
| `dated` | Lower relevance, faster decay |

### Scoring Algorithm
```
combined_score = (
    SEMANTIC_WEIGHT × cosine_similarity(query, memory) +
    FRESHNESS_WEIGHT × exp(-age_days / HALF_LIFE) +
    ACCESS_WEIGHT × exp(-hours_since_access / 24)
)

Defaults:
  SEMANTIC_WEIGHT = 0.6
  FRESHNESS_WEIGHT = 0.3
  ACCESS_WEIGHT = 0.1
  HALF_LIFE = 30 days
```

---

## Prompt Builder

### Context Sources

| Source | Status | Description |
|--------|--------|-------------|
| Core Memories | ✅ Built | Permanent, foundational knowledge (always included) |
| Temporal Context | ✅ Built | Time awareness, session duration |
| Visual Input | ✅ Built | Screenshots/webcam via Gemini 2.5 Flash |
| Semantic Memories | ✅ Built | Relevant memories via vector search |
| Conversation History | ✅ Built | Last 15 exchanges |
| Web Sources | 🔜 Future | External data injection |

### Assembly Process (Priority Order)
1. **Core Memories** (priority 10) - Always included, foundational facts
2. **System Pulse** (priority 25) - AI agency timer control
3. **Temporal Context** (priority 30) - Time of day, session duration
4. **Visual Context** (priority 40) - Screenshot/webcam descriptions
5. **Semantic Memories** (priority 50) - Relevance-scored memories
6. **Conversation History** (priority 60) - Last 15 exchanges
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
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
KOBOLD_API_URL=http://127.0.0.1:5001
LLM_PRIMARY_PROVIDER=anthropic
LOG_LEVEL=INFO
```

### Key Settings (config.py)
| Setting | Default | Description |
|---------|---------|-------------|
| `MEMORY_EXTRACTION_THRESHOLD` | 10 | Turns before extraction |
| `MEMORY_FRESHNESS_HALF_LIFE_DAYS` | 30 | Memory decay rate |
| `AGENCY_IDLE_TRIGGER_SECONDS` | 900 | 15 min idle trigger |
| `AGENCY_CHECK_INTERVAL` | 300 | 5 min check interval |
| `MAX_CONCURRENT_LLM_REQUESTS` | 3 | LLM call limit |

---

## Threading Model

```
Main Process
├── [Main Thread] CLI input loop
├── [Daemon] MemoryExtractor - every 60s
├── [Daemon] ProactiveAgent - every 300s
├── [Daemon] SystemPulseTimer - configurable interval
├── [Daemon] VisualCapture - every 30s (if enabled)
├── [Daemon] HTTPServer - Flask
└── [Daemon] SubprocessManager - health checks
```

All daemon threads stop automatically when main exits.

---

## Database Schema (v7)

```sql
sessions        -- Session metadata
conversations   -- All turns with temporal data
memories        -- Extracted memories with embeddings
core_memories   -- Permanent foundational knowledge
state           -- Key-value runtime state
schema_version  -- Migration tracking
```

---

## Visual System

### Pipeline
1. Timer triggers capture (screenshot/webcam)
2. Image sent to Gemini 2.5 Flash
3. Text description cached
4. Description injected into prompts

### Configuration
```bash
VISUAL_ENABLED=true
VISUAL_CAPTURE_INTERVAL=30
GOOGLE_API_KEY=your_key
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/quit` | Exit program |
| `/new` | Start new session |
| `/end` | End session (triggers extraction) |
| `/stats` | System statistics |
| `/memories` | Show recent memories |
| `/search <query>` | Semantic memory search |
| `/extract` | Force memory extraction |
| `/core` | Show core memories |
| `/addcore <cat> <content>` | Add core memory |
| `/pulse` | Show system pulse timer status |
| `/pause` | Pause background processes |
| `/resume` | Resume background processes |

---

## Next Steps

1. **Web Sources** - External data integration (search, APIs)
2. **Richer Triggers** - Curiosity, time-of-day, events
3. **Memory Promotion** - Auto-promote high-scoring memories to core
4. **Multi-User Support** - Separate relationship tracking per user
