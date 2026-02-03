# Prompt System Overview

This document provides a high-level overview of how prompts are built, assembled, and sent to the LLM in the Pattern Project.

## Core Architecture

The Pattern Project uses an **ephemeral context window** approach: each prompt is self-contained and freshly assembled from the database, rather than accumulating state in a growing context window.

### Key Design Decisions

1. **No Base System Prompt**: The AI has no hardcoded persona. Personality emerges from assembled context blocks.
2. **Pluggable Context Sources**: 8 independent sources inject context into every prompt, sorted by priority.
3. **Two-Pass Processing**: AI responses may contain commands that require a second LLM call to incorporate results.
4. **Database as Memory**: All persistent state lives in SQLite; vector search provides semantic recall.

## Prompt Flow Diagram

```
USER INPUT
    │
    ▼
┌─────────────────────────────────────────┐
│           PromptBuilder.build()          │
│  (prompt_builder/builder.py:95-132)      │
└─────────────────────────────────────────┘
    │
    │  For each registered source (sorted by priority):
    │    source.get_context(user_input, session_context)
    │
    ▼
┌─────────────────────────────────────────┐
│         Context Sources (8 total)        │
│                                          │
│  Priority 10: CoreMemorySource           │
│  Priority 22: IntentionSource            │
│  Priority 25: SystemPulseSource          │
│  Priority 26: AICommandsSource           │
│  Priority 30: TemporalSource             │
│  Priority 40: VisualSource               │
│  Priority 50: SemanticMemorySource       │
│  Priority 60: ConversationSource         │
└─────────────────────────────────────────┘
    │
    │  Each source returns a ContextBlock:
    │    - source_name: str
    │    - content: str (the actual prompt text)
    │    - priority: int
    │    - include_always: bool
    │    - metadata: Dict
    │
    ▼
┌─────────────────────────────────────────┐
│      AssembledPrompt Construction        │
│  (prompt_builder/builder.py:14-32)       │
│                                          │
│  full_system_prompt =                    │
│    base_prompt (EMPTY) +                 │
│    blocks sorted by priority +           │
│    joined with "\n\n"                    │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│           LLM Router                     │
│  (llm/router.py)                         │
│                                          │
│  chat(                                   │
│    messages=conversation_history,        │
│    system_prompt=assembled.full_system,  │
│    task_type=CONVERSATION                │
│  )                                       │
└─────────────────────────────────────────┘
    │
    │  API Call Structure:
    │    {
    │      "system": <full_system_prompt>,
    │      "messages": [
    │        {"role": "user", "content": "..."},
    │        {"role": "assistant", "content": "..."},
    │        ...
    │        {"role": "user", "content": <current_input>}
    │      ]
    │    }
    │
    ▼
┌─────────────────────────────────────────┐
│         LLM Response (Pass 1)            │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│       CommandProcessor.process()         │
│  (agency/commands/processor.py:81-141)   │
│                                          │
│  Scans for [[COMMAND: query]] patterns   │
│  Executes registered handlers            │
│  Returns ProcessedResponse               │
└─────────────────────────────────────────┘
    │
    │  If needs_continuation == True:
    │
    ▼
┌─────────────────────────────────────────┐
│         Continuation (Pass 2)            │
│                                          │
│  messages += [                           │
│    {role: "assistant", content: pass1},  │
│    {role: "user", content: results}      │
│  ]                                       │
│                                          │
│  Second LLM call with command results    │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│            Final Response                │
│                                          │
│  Stored in conversation database         │
│  Displayed to user                       │
└─────────────────────────────────────────┘
```

## Source Priority Order

Sources are assembled into the system prompt in priority order (lowest number first):

| Priority | Source | Always Included | Purpose |
|----------|--------|-----------------|---------|
| 10 | CoreMemorySource | Yes | Permanent foundational knowledge |
| 22 | IntentionSource | Yes | AI's reminders/goals (forward-looking) |
| 25 | SystemPulseSource | Conditional* | Pulse timer control instructions |
| 26 | AICommandsSource | Yes | Available command syntax |
| 30 | TemporalSource | Yes | Current time, session info |
| 40 | VisualSource | Conditional** | Screenshot/webcam descriptions |
| 50 | SemanticMemorySource | No | Vector-searched memories |
| 60 | ConversationSource | No | Recent conversation history |

*Only if `SYSTEM_PULSE_ENABLED=True`
**Only if `VISUAL_ENABLED=True` and cache is fresh

## Key Files

| File | Purpose |
|------|---------|
| `prompt_builder/builder.py` | Main orchestrator |
| `prompt_builder/sources/base.py` | ContextSource interface |
| `prompt_builder/sources/*.py` | Individual source implementations |
| `agency/commands/processor.py` | Two-pass command engine |
| `agency/commands/handlers/*.py` | Command handler implementations |
| `llm/router.py` | LLM provider routing |
| `interface/cli.py` | Entry point showing full flow |

## Configuration

Key configuration values in `config.py`:

```python
# Prompt Assembly
CONVERSATION_EXCHANGE_LIMIT = 15   # Exchanges in context (30 turns)
MEMORY_MAX_PER_QUERY = 3           # Semantic memories per prompt

# Multi-Pass Processing
COMMAND_MAX_PASSES = 15            # Max LLM calls per message (safety cap; typical queries use 1-3)
COMMAND_SEARCH_LIMIT = 10          # Memory search results
COMMAND_SEARCH_MIN_SCORE = 0.3     # Minimum relevance

# System Pulse
SYSTEM_PULSE_ENABLED = True
SYSTEM_PULSE_INTERVAL = 600        # 10 minutes default

# Intentions
INTENTION_ENABLED = True
INTENTION_MAX_PENDING_DISPLAY = 3
```

## Related Documents

- [PROMPT_TYPES.md](PROMPT_TYPES.md) - Detailed prompt type documentation
- [INJECTION_POINTS.md](INJECTION_POINTS.md) - All dynamic content injection points
- [HARDCODED_PROMPTS.md](HARDCODED_PROMPTS.md) - Static prompt text reference
- [POTENTIAL_ISSUES.md](POTENTIAL_ISSUES.md) - Bug and process analysis
