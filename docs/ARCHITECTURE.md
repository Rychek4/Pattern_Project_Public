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
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │Memories │ │   Web   │ │ Visuals │ │Relation-│ │  Core   │  │
│  │         │ │ Sources │ │         │ │  ships  │ │Memories │  │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘  │
│       │           │           │           │           │        │
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
│  │Relation-│ │  Core   │ │Temporal │            │
│  │  ships  │ │Memories │ │ Context │            │
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

## Prompt Builder (Planned)

### Context Sources

| Source | Status | Description |
|--------|--------|-------------|
| Conversation History | ✅ Built | Recent turns from current session |
| Semantic Memories | ✅ Built | Relevant memories via vector search |
| Temporal Context | ✅ Built | Time awareness, session duration |
| Core Memories | 🔜 Planned | Permanent, foundational knowledge |
| Relationship Data | 🔜 Planned | Affinity, history, dynamics |
| Web Sources | 🔜 Planned | External data injection |
| Visual Input | 🔜 Planned | Screenshots, images |

### Assembly Process
1. **Persona/System Prompt** - Character, tone, guidelines
2. **Core Memories** - Immutable foundational context
3. **Relationship Context** - Who is the user, history
4. **Temporal Context** - Time of day, session duration
5. **Relevant Memories** - Semantically retrieved
6. **Visual Context** - Any images being referenced
7. **Web Context** - External data if applicable
8. **Conversation History** - Recent turns
9. **User Input** - Current message

### Token Budget Management
- Total budget based on model context window
- Each source has priority and max allocation
- Lower priority sources trimmed first
- Always preserve: user input, system prompt

---

## Configuration

### Environment Variables
```bash
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514
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
├── [Daemon] HTTPServer - Flask
└── [Daemon] SubprocessManager - health checks
```

All daemon threads stop automatically when main exits.

---

## Database Schema

```sql
sessions        -- Session metadata
conversations   -- All turns with temporal data
memories        -- Extracted memories with embeddings
state           -- Key-value runtime state
schema_version  -- Migration tracking
```

---

## Next Steps

1. **Prompt Builder** - Modular context assembly
2. **Core Memories** - Distinguished from regular memories
3. **Relationship Data** - User affinity and dynamics
4. **Web Sources** - External data integration
5. **Visual Input** - Image processing pipeline
6. **Richer Triggers** - Beyond idle detection
