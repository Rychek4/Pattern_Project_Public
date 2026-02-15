# Prompt Types

This document details the four distinct prompt types used in the Pattern Project, their structure, and when each is used.

## Overview

The system produces four distinct prompt configurations:

| Type | Trigger | User Content | Continuation | Code Path |
|------|---------|--------------|--------------|-----------|
| First Pass Response | User message | User's text | Maybe | `cli.py:126-144` |
| First Pass Pulse | System pulse timer | Pulse prompt | Maybe | `cli.py:261-281` |
| Second Pass Response | Command needs results | Command results | No | `cli.py:156-176` |
| Second Pass Pulse | Pulse + command | Command results | No | `cli.py:294-312` |

---

## 1. First Pass Response (User-Initiated)

**Trigger**: User sends a message in the chat interface

**Code Location**: `interface/cli.py:126-144`

### Flow

```
User types message
    │
    ├─ Reset pulse timer
    ├─ Store user turn in database
    │
    ▼
prompt_builder.build(user_input="<user message>", system_prompt="")
    │
    ▼
router.chat(
    messages=conversation_history + [{"role": "user", "content": user_input}],
    system_prompt=assembled.full_system_prompt,
    task_type=TaskType.CONVERSATION
)
```

### System Prompt Structure

```
<core memories from database>

<your_intentions>
  <intention context>
</your_intentions>

<system_pulse_control>
  <pulse timer instructions>
</system_pulse_control>

<ai_commands>
  <available command instructions>
</ai_commands>

<temporal_context>
  <current time, session duration, turn count>
</temporal_context>

<visual_context>        (if VISUAL_ENABLED)
  <screenshot/webcam descriptions>
</visual_context>

<recalled_context>      (if semantic search has results)
  <semantically relevant memories>
</recalled_context>

<recent_conversation>   (if conversation history exists)
  <last 15 exchanges with timestamps>
</recent_conversation>
```

### Messages Array

```json
[
  {"role": "user", "content": "<historical user message 1>"},
  {"role": "assistant", "content": "<historical assistant response 1>"},
  ...
  {"role": "user", "content": "<current user input>"}
]
```

---

## 2. First Pass Pulse (System-Initiated)

**Trigger**: System pulse timer fires after N seconds of idle time

**Code Location**: `interface/cli.py:237-281`

### Key Difference from User-Initiated

The "user message" is actually the automated pulse prompt, and a different abbreviated message is stored in the database.

### Flow

```
Pulse timer fires
    │
    ├─ Pause pulse timer
    ├─ Store ABBREVIATED message in database: "[System Pulse]"
    │
    ▼
prompt_builder.build(user_input=PULSE_PROMPT, system_prompt="")
    │
    ▼
router.chat(
    messages=conversation_history + [{"role": "user", "content": PULSE_PROMPT}],
    system_prompt=assembled.full_system_prompt,
    task_type=TaskType.CONVERSATION
)
```

### The Pulse Prompt

From `agency/system_pulse.py:17-29`:

```python
def get_pulse_prompt(interval_label: str = "10 minutes") -> str:
    return f"""[AUTOMATED SYSTEM PULSE - Not human input]
The {interval_label} idle timer has fired. No new human message has been received.
This is your opportunity to utilize agency: review the conversation for loose ends,
introduce new ideas, or speak freely. Respond as you would naturally."""
```

### Database Storage

What's stored in conversation history: `"[System Pulse]"` (abbreviated)
What's sent to LLM: Full pulse prompt (seen in messages array)

### System Prompt Structure

Identical to First Pass Response - all context sources still inject their content.

---

## 3. Second Pass Response (Continuation)

**Trigger**: First Pass Response contained a command that requires results (e.g., `[[SEARCH: query]]`)

**Code Location**: `interface/cli.py:156-176`

### Condition

Only triggered when `processor.process(response.text).needs_continuation == True`

### Flow

```
Pass 1 response contains [[SEARCH: query]]
    │
    ├─ CommandProcessor detects command
    ├─ Handler executes search
    ├─ Handler returns needs_continuation=True
    │
    ▼
Build continuation_history:
    original_history + [
        {"role": "assistant", "content": "<pass 1 response>"},
        {"role": "user", "content": "<continuation prompt with results>"}
    ]
    │
    ▼
router.chat(
    messages=continuation_history,
    system_prompt=assembled.full_system_prompt,  # SAME as Pass 1
    task_type=TaskType.CONVERSATION
)
```

### Continuation Prompt Format

From `agency/commands/processor.py:143-174`:

```
[Command Results]

Your [[SEARCH: query]] returned:
  - [fact] User mentioned they love hiking (2 days ago) [relevance: 0.87]
  - [preference] User prefers morning walks (5 days ago) [relevance: 0.72]

Continue your response naturally, incorporating this information.
```

### Messages Array

```json
[
  {"role": "user", "content": "<historical message>"},
  {"role": "assistant", "content": "<historical response>"},
  ...
  {"role": "user", "content": "<original user input>"},
  {"role": "assistant", "content": "<Pass 1 response with [[SEARCH:...]]>"},
  {"role": "user", "content": "[Command Results]\n\nYour [[SEARCH:...]] returned:\n..."}
]
```

### System Prompt Structure

**Same as First Pass** - the system prompt is reused, not regenerated.

---

## 4. Second Pass Pulse (Pulse Continuation)

**Trigger**: First Pass Pulse response contained a command requiring results

**Code Location**: `interface/cli.py:294-312`

### Flow

```
Pass 1 pulse response contains [[LIST_INTENTIONS]]
    │
    ├─ CommandProcessor detects command
    ├─ Handler returns intentions list with needs_continuation=True
    │
    ▼
Build continuation_history:
    original_history + [
        {"role": "user", "content": PULSE_PROMPT},
        {"role": "assistant", "content": "<pass 1 pulse response>"},
        {"role": "user", "content": "<continuation prompt with results>"}
    ]
    │
    ▼
router.chat(
    messages=continuation_history,
    system_prompt=assembled.full_system_prompt,
    task_type=TaskType.CONVERSATION
)
```

### Key Difference

- The "user message" before the assistant response is the PULSE_PROMPT
- Otherwise identical structure to Second Pass Response

---

## Commands That Trigger Second Pass

| Command | Handler | needs_continuation | Result Format |
|---------|---------|-------------------|---------------|
| `[[SEARCH: query]]` | MemorySearchHandler | **True** | Memory list with scores |
| `[[REMIND: when \| what]]` | RemindHandler | False | Fire-and-forget |
| `[[COMPLETE: id \| note]]` | CompleteHandler | False | Fire-and-forget |
| `[[DISMISS: id]]` | DismissHandler | False | Fire-and-forget |
| `[[LIST_INTENTIONS]]` | ListIntentionsHandler | **True** | All intentions |
| `[[PULSE:Xm]]` | (inline processing) | False | Timer adjustment |

---

## Prompt Size Analysis

### Typical Token Counts

Based on production usage:

| Component | Typical Tokens | Notes |
|-----------|---------------|-------|
| Core Memories | 200-500 | Depends on content amount |
| Intentions Block | 150-300 | With commands documentation |
| System Pulse Control | ~200 | Fixed template |
| AI Commands | ~200 | Fixed instruction text |
| Temporal Context | ~50 | Single line |
| Visual Context | 0-200 | Only if enabled |
| Semantic Memories | 100-300 | 3 memories default |
| Recent Conversation | 500-2000 | 15 exchanges |
| **Total System Prompt** | **1200-3500** | |
| Messages Array | 500-2500 | Conversation history |
| **Total Input** | **~2000-6000** | |

### Token Limit Considerations

- `ANTHROPIC_MAX_TOKENS = 4096` (output limit)
- Anthropic's context window is much larger (200K for Claude 3)
- Current prompts are well within limits
- Primary concern is response quality, not truncation

---

## Related Documents

- [PROMPT_SYSTEM_OVERVIEW.md](PROMPT_SYSTEM_OVERVIEW.md) - Architecture overview
- [INJECTION_POINTS.md](INJECTION_POINTS.md) - Where dynamic content enters
- [HARDCODED_PROMPTS.md](HARDCODED_PROMPTS.md) - Static prompt text
- [POTENTIAL_ISSUES.md](POTENTIAL_ISSUES.md) - Bug analysis
