# Injection Points Reference

This document catalogs every location where dynamic content is injected into prompts, what data flows through each point, and potential consequences of malformed data.

## Overview

The prompt system has **two injection phases**:

1. **System Prompt Assembly**: Context sources inject blocks into the system prompt
2. **Continuation Assembly**: Command results inject into user messages (Pass 2)

---

## Phase 1: System Prompt Injection Points

### 1. Core Memory Injection

**Source**: `prompt_builder/sources/core_memory.py:44-95`
**Priority**: 10 (first in system prompt)
**Always Included**: Yes (if memories exist)

#### Data Flow

```
Database: core_memories table
    │
    ▼
CoreMemorySource.get_all()
    │
    ├─ Query: "SELECT * FROM core_memories ORDER BY category, created_at"
    │
    ▼
Format by category:
    - Narrative content as plain text (no prefix)
    - Other categories as "- [category] content"
```

#### Output Format

```
<narrative content as plain prose>

- [identity] User's name is {USER_NAME}
- [relationship] AI maintains a supportive, engaged presence
- [preference] User prefers detailed technical explanations
- [fact] User works as a software engineer
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Prompt injection | User could add malicious instructions via /addcore | Categories limited to: identity, relationship, preference, fact |
| Empty content | Database could return empty strings | Conditional: returns None if no memories |
| SQL injection | Category/content from user input | Parameterized queries used |

---

### 2. Intention Injection

**Source**: `prompt_builder/sources/intention_source.py:37-95`
**Priority**: 22
**Always Included**: Yes

#### Data Flow

```
Database: intentions table
    │
    ▼
TriggerEngine.get_context_summary(now)
    │
    ├─ Check triggered intentions (due now)
    ├─ Check pending intentions (upcoming)
    │
    ▼
_build_context() or _build_empty_context()
```

#### Output Format (Empty)

```xml
<your_intentions>
These are your private intentions — the user cannot see them.
You currently have no active reminders or goals.

You can create intentions using these commands in your response:
  [[REMIND: when | what to remember]]
  Example: [[REMIND: in 2 hours | ask how their meeting went]]
  Example: [[REMIND: tomorrow morning | check on their sleep]]
  Example: [[REMIND: next session | follow up on anxiety discussion]]

When you notice something worth following up on, create a reminder.
This gives you continuity of care across conversations.
</your_intentions>
```

#### Output Format (With Intentions)

```xml
<your_intentions>
These are your private intentions — the user cannot see them.

<formatted intention list from TriggerEngine>

You have 3 active intentions.

Commands:
  [[REMIND: when | what]] — Create a new reminder
  [[COMPLETE: I-id | outcome]] — Mark as done with note
  [[DISMISS: I-id]] — Cancel without completing
  [[LIST_INTENTIONS]] — Review all your intentions

When addressing a due intention, mark it complete or dismiss it.
Create reminders when you notice things worth following up on.
</your_intentions>
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Intention hijacking | AI-created intentions contain malicious text | AI creates its own intentions; user cannot directly add |
| ID enumeration | Intention IDs are sequential | IDs are internal; user never sees them |
| Context overflow | Too many intentions | `INTENTION_MAX_PENDING_DISPLAY = 3` limits shown |

---

### 3. System Pulse Injection

**Source**: `prompt_builder/sources/system_pulse.py:55-109`
**Priority**: 25
**Always Included**: Conditional (`SYSTEM_PULSE_ENABLED`)

#### Data Flow

```
config.SYSTEM_PULSE_ENABLED
    │
    ├─ If False → return None
    │
    ▼
get_system_pulse_timer().pulse_interval
    │
    ▼
Build context with current interval
```

#### Output Format

```xml
<system_pulse_control>
The conversation has an idle timer ("System Pulse") that prompts you to speak
autonomously when the human is idle.

Current setting: 10 minutes
Available options: 3 minutes, 10 minutes, 30 minutes, 1 hour, 6 hours

You can adjust this timer by including a command anywhere in your response:
  [[PULSE:3m]]  - Set to 3 minutes
  [[PULSE:10m]] - Set to 10 minutes
  [[PULSE:30m]] - Set to 30 minutes
  [[PULSE:1h]]  - Set to 1 hour
  [[PULSE:6h]]  - Set to 6 hours

Use this when:
- You have thoughts you want to explore over time
- You exercise your discretion to create space or close the distance
- Maintaining your own sense of timing feels more authentic than the default
</system_pulse_control>
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Invalid interval | Timer set to non-standard value | `PULSE_INTERVAL_OPTIONS` whitelist |
| Timer disabled bypass | Context shows even when disabled | Explicit config check |

---

### 4. AI Commands Injection

**Source**: `prompt_builder/sources/ai_commands.py:27-67`
**Priority**: 26
**Always Included**: Yes (if handlers registered)

#### Data Flow

```
CommandProcessor._handlers
    │
    ▼
processor.get_all_instructions()
    │
    ├─ For each handler:
    │     handler.get_instructions()
    │
    ▼
Concatenate all instruction strings
```

#### Output Format

```xml
<ai_commands>
You can search your memory archive by including this command in your response:
  [[SEARCH: your query here]]

Use this when:
- The user asks about past conversations ("What did we discuss about...")
- You need more context than the automatically-recalled memories provide
- The user references something with "remember when..." or similar

The search executes and results are provided for you to continue your response.

You can create reminders to follow up on things:
  [[REMIND: when | what to remember]]
  [[REMIND: when | what | context]]

Examples:
  [[REMIND: in 2 hours | ask how their meeting went]]
  [[REMIND: tomorrow morning | check on sleep quality]]
  [[REMIND: next session | follow up on anxiety discussion]]

...additional handler instructions...
</ai_commands>
```

#### Registered Handlers

| Handler | Command | Instruction Source |
|---------|---------|-------------------|
| MemorySearchHandler | `[[SEARCH:]]` | `handlers/memory_search.py:86-96` |
| RemindHandler | `[[REMIND:]]` | `handlers/intention_handler.py:124-138` |
| CompleteHandler | `[[COMPLETE:]]` | `handlers/intention_handler.py:264-269` |
| DismissHandler | `[[DISMISS:]]` | `handlers/intention_handler.py:328-332` |
| ListIntentionsHandler | `[[LIST_INTENTIONS]]` | `handlers/intention_handler.py:404-408` |

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Instruction mismatch | Handler registered but no instructions | Returns empty string if no handlers |
| Handler conflict | Duplicate command patterns | Handlers keyed by command_name |

---

### 5. Temporal Injection

**Source**: `prompt_builder/sources/temporal.py:35-69`
**Priority**: 30
**Always Included**: Yes

#### Data Flow

```
TemporalTracker.get_context()
    │
    ├─ current_time: datetime.now()
    ├─ session_duration: timedelta
    ├─ turns_this_session: int
    ├─ total_sessions: int
    │
    ▼
temporal_context_to_semantic(context)
    │
    ▼
Human-readable description
```

#### Output Format

```xml
<temporal_context>
  It is Monday, December 9, 2025 at 2:34 PM. This session has been active for 12 minutes with 8 turns.
</temporal_context>
```

#### `temporal_context_to_semantic()` Function

Located in `core/temporal.py`. Converts raw temporal data to natural language:

```python
# Example outputs:
"It is Monday, December 9, 2025 at 2:34 PM."
"This is your first session."
"Your last session was 2 hours ago."
"This session has been active for 12 minutes with 8 turns."
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Clock manipulation | System time could be wrong | Uses system clock directly |
| Session state inconsistency | Tracker out of sync | Tracker is the single source of truth |

---

### 6. Visual Injection

**Source**: `prompt_builder/sources/visual.py`
**Priority**: 40
**Always Included**: Conditional (`VISUAL_ENABLED` and cache fresh)

#### Data Flow

```
Background thread captures screenshots/webcam
    │
    ├─ Google Vision API describes images
    │
    ▼
Cached descriptions (30-second refresh)
    │
    ▼
_build_context() formats descriptions
```

#### Output Format

```xml
<visual_context>
<screenshot>
The screen shows a code editor (VS Code) with a Python file open. The file
appears to be related to memory extraction. A terminal is visible at the bottom.
</screenshot>
<webcam>
A person is visible sitting at a desk. They appear to be focused on their
computer screen. Natural lighting from a window to their left.
</webcam>
</visual_context>
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Stale descriptions | Cache not refreshed | 30-second cache with expiration |
| Vision API failure | API returns error | Graceful degradation to None |
| Privacy leakage | Sensitive content captured | User must enable `VISUAL_ENABLED` |

---

### 7. Semantic Memory Injection

**Source**: `prompt_builder/sources/semantic_memory.py:52-111`
**Priority**: 50
**Always Included**: No (only if search returns results)

#### Data Flow

```
user_input
    │
    ▼
vector_store.search(query=user_input, limit=3, min_score=0.3)
    │
    ├─ Embed query → 384-dim vector
    ├─ Cosine similarity against stored memories
    ├─ Apply scoring weights:
    │     50% semantic + 35% freshness + 15% access
    │
    ▼
Top N results above min_score
    │
    ▼
Format with fuzzy timestamps
```

#### Output Format

```xml
<recalled_context>
The following are relevant memories from past conversations:

- User mentioned they're working on a Flask application (23 minutes ago)
- User prefers Python over JavaScript for backend development (2 days ago)
- User has a meeting with their team every Tuesday (1 week ago)

</recalled_context>
```

#### Scoring Configuration

From `config.py`:

```python
MEMORY_MAX_PER_QUERY = 3            # Max memories returned
MEMORY_SEMANTIC_WEIGHT = 0.50       # Similarity weight
MEMORY_FRESHNESS_WEIGHT = 0.35      # Recency weight
MEMORY_ACCESS_WEIGHT = 0.15         # Access frequency weight
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Irrelevant memories | Low-quality embeddings | `min_score=0.3` threshold |
| Memory injection | Malicious content in stored memories | Memories come from AI extraction |
| Timestamp manipulation | Fuzzy time could be misleading | Uses actual database timestamps |

---

### 8. Conversation Injection

**Source**: `prompt_builder/sources/conversation.py:44-87`
**Priority**: 60 (last in system prompt)
**Always Included**: No (only if history exists)

#### Data Flow

```
conversation_manager.get_session_history(limit=30)
    │
    ├─ Filter to user/assistant roles only
    │
    ▼
Format with names and fuzzy timestamps
```

#### Output Format

```xml
<recent_conversation>
  User: Hey, can you help me debug this Flask app? (23 minutes ago)
  AI: Of course! What kind of error are you seeing? (22 minutes ago)
  User: I'm getting a circular import error (21 minutes ago)
  AI: That's a common issue. Let me explain... (20 minutes ago)
  ...
</recent_conversation>
```

#### Configuration

```python
CONVERSATION_EXCHANGE_LIMIT = 15    # 15 exchanges = 30 turns
```

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| History manipulation | User could modify database | Database is local, trusted |
| Context overflow | Too much history | Fixed limit of 30 turns |
| Role confusion | Non-user/assistant roles | Explicit filter in code |

---

## Phase 2: Continuation Injection Points

### Command Results Injection

**Source**: `agency/commands/processor.py:143-174`
**Priority**: N/A (injected into messages array, not system prompt)

#### Data Flow

```
CommandResult objects from handlers
    │
    ▼
_build_continuation_prompt(results)
    │
    ├─ For each result where needs_continuation=True:
    │     handler.format_result(result)
    │
    ▼
"[Command Results]\n\n..."
```

#### Output Format

```
[Command Results]

Your [[SEARCH: book recommendations]] returned:
  - [preference] User enjoys science fiction novels (3 days ago) [relevance: 0.82]
  - [fact] User mentioned reading Dune recently (1 week ago) [relevance: 0.71]

Your [[LIST_INTENTIONS]] returned:
  Your active intentions:

  TRIGGERED (due now):
    [I-42] Ask how their meeting went (set 2 hours ago)

  PENDING:
    [I-43] Check on sleep quality (due tomorrow morning)

Continue your response naturally, incorporating this information.
```

#### Handler-Specific Formatting

| Handler | format_result() Location | Output Style |
|---------|-------------------------|--------------|
| MemorySearchHandler | `memory_search.py:98-131` | Memory list with types, scores |
| ListIntentionsHandler | `intention_handler.py:368-402` | Categorized intention list |

#### Injection Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| Result manipulation | Handler returns malicious data | Handlers are internal code |
| Empty results | No data found | Explicit "No results" message |
| Format errors | Handler returns invalid format | Try/except in processor |

---

## Injection Summary Table

| Injection Point | Source File | XML Tag | Dynamic Data Source | Risk Level |
|-----------------|-------------|---------|---------------------|------------|
| Core Memory | `core_memory.py` | (none) | `core_memories` table | Medium |
| Intentions | `intention_source.py` | `<your_intentions>` | `intentions` table | Low |
| System Pulse | `system_pulse.py` | `<system_pulse_control>` | Timer state | Low |
| AI Commands | `ai_commands.py` | `<ai_commands>` | Handler instructions | Low |
| Temporal | `temporal.py` | `<temporal_context>` | System clock/session | Low |
| Visual | `visual.py` | `<visual_context>` | Vision API | Medium |
| Semantic Memory | `semantic_memory.py` | `<recalled_context>` | Vector search | Medium |
| Conversation | `conversation.py` | `<recent_conversation>` | `conversations` table | Low |
| Command Results | `processor.py` | (messages array) | Handler execution | Low |

---

## Related Documents

- [PROMPT_SYSTEM_OVERVIEW.md](PROMPT_SYSTEM_OVERVIEW.md) - Architecture overview
- [PROMPT_TYPES.md](PROMPT_TYPES.md) - Prompt type documentation
- [HARDCODED_PROMPTS.md](HARDCODED_PROMPTS.md) - Static prompt text
- [POTENTIAL_ISSUES.md](POTENTIAL_ISSUES.md) - Bug analysis
