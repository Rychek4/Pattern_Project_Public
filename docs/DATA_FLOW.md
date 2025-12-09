# Pattern Project - Data Flow & Context Memory Architecture

> **Quick Reference for Future Instances**
> This document explains how data flows through Pattern Project, with special focus on the "one-off" context window approach.

---

## The Core Concept: Ephemeral Context Windows

The key architectural decision in Pattern is that **each prompt is assembled fresh from scratch**. The context window is disposable - we don't build state in it.

```
Traditional Chatbot:                    Pattern Project:
┌────────────────────────┐             ┌────────────────────────┐
│ Context Window         │             │ Context Window         │
│ (accumulates)          │             │ (rebuilt each request) │
│ ┌────────────────────┐ │             │ ┌────────────────────┐ │
│ │ Turn 1             │ │             │ │ Core Memories      │ │
│ │ Turn 2             │ │             │ │ Semantic Recall    │ │
│ │ Turn 3             │ │             │ │ Last 15 exchanges  │ │
│ │ ...                │ │             │ │ Temporal Context   │ │
│ │ Turn N (truncate?) │ │             │ │ (always ~1-3K tok) │ │
│ └────────────────────┘ │             │ └────────────────────┘ │
└────────────────────────┘             └────────────────────────┘
     Grows until full                       Self-contained lens
```

**Why this matters:**
- **No accumulation** - Context doesn't grow over sessions
- **Consistent size** - Always ~1-3K tokens regardless of history length
- **Semantic relevance** - Old memories resurface when relevant
- **Graceful forgetting** - Freshness decay ages out memories naturally

The "memory" lives in the **database and vector store**, not the conversation thread. The context window is just a **disposable lens** onto that persistent memory.

---

## High-Level Data Flow

```
USER INPUT
    │
    ├─→ [Database] Store conversation turn
    │        │
    │        └─→ [Background] Memory extraction → embeddings
    │
    ├─→ [Prompt Builder] Assemble fresh context from sources
    │        │
    │        ├─→ Core Memories (permanent facts)
    │        ├─→ Temporal Context (time awareness)
    │        ├─→ Visual Context (screenshots - optional)
    │        ├─→ Semantic Memories (vector search recall)
    │        └─→ Conversation History (last 15 exchanges)
    │
    ├─→ [LLM Router] Select provider → API call
    │
    └─→ [Response] Display + Store (also awaits extraction)
```

---

## Phase 1: Input Storage

Every user message is immediately stored to SQLite:

```sql
INSERT INTO conversations (session_id, role, content, input_type,
                          created_at, processed_for_memory)
VALUES (?, 'user', ?, 'text', NOW(), FALSE)
```

Key fields:
- `processed_for_memory = FALSE` - Awaits background extraction
- `time_since_last_turn_seconds` - Temporal metadata for decay

---

## Phase 2: Context Assembly (The "One-Off")

The Prompt Builder queries **multiple independent sources** and assembles a fresh context:

| Priority | Source | Always? | What It Provides |
|----------|--------|---------|------------------|
| 10 | **Core Memory** | YES | Permanent identity/facts from `core_memories` table |
| 25 | **System Pulse** | NO | AI agency timer state |
| 30 | **Temporal** | YES | Time awareness, session duration, turn count |
| 40 | **Visual** | NO | Current screenshot/webcam description |
| 50 | **Semantic Memory** | NO | Top 10 relevant memories via vector search |
| 60 | **Conversation** | NO | Last 15 exchanges (30 turns) |

### Assembled Prompt Structure

```xml
<core_knowledge>
  <identity>Name, role, foundational facts</identity>
</core_knowledge>

<temporal_context>
  Current time: December 7, 2025 at 3:45 PM
  Session duration: 23 minutes
  Exchange count: 8
</temporal_context>

<recalled_memories>
  📌 [high] User prefers technical explanations
  💜 [medium] Discussed machine learning last week
</recalled_memories>

<recent_conversation>
  User: Previous message
  Assistant: Previous response
  ...last 15 exchanges...
</recent_conversation>

---
[System prompt / persona]
---

User: [Current input]
```

---

## Phase 3: Memory Recall (Vector Search)

When user input arrives, the Semantic Memory source:

1. **Generates embedding** for user input (sentence-transformers, 384 dimensions)
2. **Searches all memories** using cosine similarity
3. **Scores each memory** with combined formula:

```
score = 0.6 × semantic_similarity +
        0.3 × freshness_decay +
        0.1 × access_recency

Where:
  semantic_similarity = cosine(query_embedding, memory_embedding)
  freshness_decay = exp(-age_days / 30)
  access_recency = exp(-hours_since_accessed / 24)
```

4. **Filters** memories with score ≥ 0.3
5. **Returns top 10** sorted by combined score
6. **Updates access times** for returned memories

### Example Recall

```
Query: "What do you think about consciousness?"

Memory A: "User enjoys philosophical discussions"
  semantic: 0.87  freshness: 0.92  access: 0.61
  combined: 0.522 + 0.276 + 0.061 = 0.859 ✓ INCLUDED

Memory B: "User's birthday is December 15"
  semantic: 0.12  freshness: 0.95  access: 0.50
  combined: 0.072 + 0.285 + 0.050 = 0.407 ✗ LOW RELEVANCE
```

---

## Phase 4: LLM Routing

```
Task Type → Provider Selection

CONVERSATION  →  Anthropic Claude (quality)
EXTRACTION    →  KoboldCpp (local, cost-free)
SIMPLE        →  KoboldCpp (quick tasks)

If primary fails & fallback enabled:
  → Retry with secondary provider
```

---

## Phase 5: Background Extraction

Extraction is triggered when unprocessed turns reach a threshold (default: 10):

```
IF unprocessed_turns >= 10:
    │
    ├─ Phase 1: Topic Segmentation (multi-pass LLM)
    │   ├─ Pass 1: Identify topics (natural language)
    │   └─ Pass 2: Assign turns to topics (simple JSON)
    │
    ├─ Phase 2: Memory Synthesis (multi-pass LLM per topic)
    │   ├─ Pass 1: Write 1-2 sentence summary
    │   ├─ Pass 2: Rate importance (0-10)
    │   └─ Pass 3: Classify type (single word)
    │
    ├─ Infer decay_category from type + importance (no LLM needed):
    │   - High-importance facts/preferences → 'permanent'
    │   - Low-importance observations → 'ephemeral'
    │   - Everything else → 'standard'
    │
    ├─ Generate embedding for each memory
    ├─ Store in `memories` table with decay_category
    └─ Mark source turns as processed
```

**Decay categories** control how quickly memories fade from relevance:
- `permanent`: Never decays (core identity, lasting preferences)
- `standard`: 30-day half-life (events, discussions, insights)
- `ephemeral`: 7-day half-life (situational observations)

This is how conversations become **searchable memories** without bloating the context window.

---

## Database Schema Summary

```
sessions        → Session metadata (start, end, duration)
conversations   → All turns with temporal data
memories        → Extracted memories + 384-dim embeddings
core_memories   → Permanent foundational knowledge
state           → Key-value runtime state
```

---

## Threading Model

```
Main Thread        → CLI/GUI input loop
Memory Extractor   → Every 60s, extracts & embeds
System Pulse       → Configurable interval, AI-initiated speaking
Proactive Agent    → Every 300s, checks for AI-initiated triggers
Visual Capture     → Every 30s, screenshots to Gemini (optional)
HTTP Server        → Flask REST API (optional)
```

All daemon threads - stop automatically on main exit.

---

## Why This Architecture Works

1. **Infinite history without token cost** - Only relevant memories enter context
2. **Consistent performance** - Context size bounded regardless of conversation length
3. **Emergent recall** - Old memories resurface when semantically relevant
4. **Graceful degradation** - Freshness decay naturally ages out stale info
5. **Emergent relationships** - Relationship context emerges from memories naturally
6. **Separation of concerns** - Storage, recall, and context are independent systems

The context window is a **query result**, not a **state container**.

---

## Quick Reference: Key Files

| File | Purpose |
|------|---------|
| `prompt_builder/builder.py` | Orchestrates context assembly |
| `prompt_builder/sources/*.py` | 6 pluggable context sources |
| `memory/vector_store.py` | Semantic search with scoring |
| `memory/extractor.py` | Background extraction thread |
| `memory/conversation.py` | Turn storage/retrieval |
| `core/embeddings.py` | Sentence-transformers wrapper |
| `core/database.py` | SQLite with WAL mode |
| `llm/router.py` | Provider routing + fallback |
| `agency/system_pulse.py` | AI-initiated speaking timer |

---

## Configuration Defaults

```python
MEMORY_EXTRACTION_THRESHOLD = 10      # Turns before extraction
MEMORY_FRESHNESS_HALF_LIFE_DAYS = 30  # Decay rate
MEMORY_MAX_PER_QUERY = 10             # Max recalled memories
MEMORY_SEMANTIC_WEIGHT = 0.6          # Scoring weights
MEMORY_FRESHNESS_WEIGHT = 0.3
MEMORY_ACCESS_WEIGHT = 0.1
CONVERSATION_EXCHANGE_LIMIT = 15      # History in context
```
