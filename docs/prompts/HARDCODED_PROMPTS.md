# Hardcoded Prompts Reference

This document catalogs all hardcoded prompt text in the Pattern Project system, organized by subsystem.

## Overview

The Pattern Project intentionally has **no base system prompt** for conversations - personality emerges from context. However, several subsystems contain hardcoded instructional and template text.

---

## 1. System Pulse Prompts

### Pulse Trigger Prompt

**Location**: `agency/system_pulse.py:17-29`

```python
def get_pulse_prompt(interval_label: str = "10 minutes") -> str:
    return f"""[AUTOMATED SYSTEM PULSE - Not human input]
The {interval_label} idle timer has fired. No new human message has been received.
This is your opportunity to utilize agency: review the conversation for loose ends,
introduce new ideas, or speak freely. Respond as you would naturally."""
```

**Used when**: System pulse timer fires
**Dynamic element**: `{interval_label}` - human-readable interval (e.g., "10 minutes")

### Legacy Constant

```python
PULSE_PROMPT = get_pulse_prompt("10 minutes")
```

### Stored Message

**Location**: `agency/system_pulse.py:36`

```python
PULSE_STORED_MESSAGE = "[System Pulse]"
```

**Purpose**: Abbreviated version stored in conversation history (vs. full prompt sent to LLM)

---

## 2. Intention System Prompts

### Empty Intentions Context

**Location**: `prompt_builder/sources/intention_source.py:97-111`

```python
def _build_empty_context(self) -> str:
    return """<your_intentions>
These are your private intentions — the user cannot see them.
You currently have no active reminders or goals.

You can create intentions using these commands in your response:
  [[REMIND: when | what to remember]]
  Example: [[REMIND: in 2 hours | ask how their meeting went]]
  Example: [[REMIND: tomorrow morning | check on their sleep]]
  Example: [[REMIND: next session | follow up on anxiety discussion]]

When you notice something worth following up on, create a reminder.
This gives you continuity of care across conversations.
</your_intentions>"""
```

### Active Intentions Context Template

**Location**: `prompt_builder/sources/intention_source.py:113-144`

```python
def _build_context(self, summary: dict, now: datetime) -> str:
    lines = [
        "<your_intentions>",
        "These are your private intentions — the user cannot see them.",
        "",
    ]
    # ... dynamic content ...
    lines.extend([
        "Commands:",
        "  [[REMIND: when | what]] — Create a new reminder",
        "  [[COMPLETE: I-id | outcome]] — Mark as done with note",
        "  [[DISMISS: I-id]] — Cancel without completing",
        "  [[LIST_INTENTIONS]] — Review all your intentions",
        "",
        "When addressing a due intention, mark it complete or dismiss it.",
        "Create reminders when you notice things worth following up on.",
        "</your_intentions>",
    ])
```

---

## 3. System Pulse Control Prompt

**Location**: `prompt_builder/sources/system_pulse.py:74-93`

```python
lines = [
    "<system_pulse_control>",
    "The conversation has an idle timer (\"System Pulse\") that prompts you to speak",
    "autonomously when the human is idle.",
    "",
    f"Current setting: {current_label}",
    "Available options: 3 minutes, 10 minutes, 30 minutes, 1 hour, 6 hours",
    "",
    "You can adjust this timer by including a command anywhere in your response:",
    "  [[PULSE:3m]]  - Set to 3 minutes",
    "  [[PULSE:10m]] - Set to 10 minutes",
    "  [[PULSE:30m]] - Set to 30 minutes",
    "  [[PULSE:1h]]  - Set to 1 hour",
    "  [[PULSE:6h]]  - Set to 6 hours",
    "",
    "Use this when:",
    "- You have thoughts you want to explore over time",
    "- You exercise your discretion to create space or close the distance",
    "- Maintaining your own sense of timing feels more authentic than the default",
    "</system_pulse_control>",
]
```

**Dynamic element**: `{current_label}` - current timer setting

---

## 4. AI Command Instructions

### Memory Search Handler

**Location**: `agency/commands/handlers/memory_search.py:86-96`

```python
def get_instructions(self) -> str:
    return """You can search your memory archive by including this command in your response:
  [[SEARCH: your query here]]

Use this when:
- The user asks about past conversations ("What did we discuss about...")
- You need more context than the automatically-recalled memories provide
- The user references something with "remember when..." or similar

The search executes and results are provided for you to continue your response."""
```

### Remind Handler

**Location**: `agency/commands/handlers/intention_handler.py:124-138`

```python
def get_instructions(self) -> str:
    return """You can create reminders to follow up on things:
  [[REMIND: when | what to remember]]
  [[REMIND: when | what | context]]

Examples:
  [[REMIND: in 2 hours | ask how their meeting went]]
  [[REMIND: tomorrow morning | check on sleep quality]]
  [[REMIND: next session | follow up on anxiety discussion]]

Time formats: "in X minutes/hours", "tomorrow", "tomorrow morning/evening", "next session"

Use this when you notice something worth following up on. Your reminders are
private — the user won't see them, but you'll be reminded at the right time."""
```

### Complete Handler

**Location**: `agency/commands/handlers/intention_handler.py:264-269`

```python
def get_instructions(self) -> str:
    return """Mark an intention as completed:
  [[COMPLETE: I-id | outcome note]]
  [[COMPLETE: I-id]]

The outcome becomes part of your memory."""
```

### Dismiss Handler

**Location**: `agency/commands/handlers/intention_handler.py:328-332`

```python
def get_instructions(self) -> str:
    return """Cancel an intention without completing it:
  [[DISMISS: I-id]]

Use when an intention is no longer relevant."""
```

### List Intentions Handler

**Location**: `agency/commands/handlers/intention_handler.py:404-408`

```python
def get_instructions(self) -> str:
    return """Review all your active intentions:
  [[LIST_INTENTIONS]]

Results are provided for you to decide what to do with them."""
```

---

## 5. Memory Extraction Prompts

### Phase 1: Topic Identification

**Location**: `memory/extractor.py:52-67`

```python
TOPIC_IDENTIFICATION_PROMPT = """You are analyzing a conversation. List the distinct topics discussed.

Instructions:
1. Read the conversation below
2. Identify the main topics or subjects discussed
3. List each topic on its own line with a number
4. Keep descriptions brief (under 15 words each)
5. Combine closely related subjects into one topic
6. List 1-5 topics maximum

Example output format:
1. Debugging a Python circular import error
2. Brief joke about AI not being able to eat lunch

Conversation:
"""
```

### Phase 1: Turn Assignment

**Location**: `memory/extractor.py:70-86`

```python
TURN_ASSIGNMENT_PROMPT = """Classify each turn into one of the topics below.

Topics:
{topics}

Instructions:
1. For each turn, decide which single topic it belongs to
2. Output a JSON object where the key is the Turn Number (string) and the value is the Topic Number (integer)
3. Topic numbers must be between 1 and {num_topics}

Example output:
{{"1": 1, "2": 1, "3": 2, "4": 3}}

Conversation:
{conversation}

Output only the JSON object:"""
```

**Dynamic elements**: `{topics}`, `{num_topics}`, `{conversation}`

### Phase 2: Memory Content

**Location**: `memory/extractor.py:104-117`

```python
MEMORY_CONTENT_PROMPT = """Write a 1-2 sentence memory summarizing this conversation topic.

Instructions:
1. Write in third person using "User" and "AI"
2. Focus on the key insight or outcome
3. Be specific: use names like "the Flask app" or "the Python script"
4. Capture what's worth remembering long-term

Topic: {topic}

Conversation:
{turns}

Write your 1-2 sentence summary:"""
```

**Dynamic elements**: `{topic}`, `{turns}`

### Phase 2: Memory Importance

**Location**: `memory/extractor.py:120-130`

```python
MEMORY_IMPORTANCE_PROMPT = """Rate the importance of this memory from 0 to 10.

Scoring guide:
- 8-10: Major decisions, strong preferences, significant events, personal revelations
- 5-7: Useful information, moderate preferences, notable interactions
- 2-4: Minor details, casual observations, brief exchanges
- 0-1: Trivial or forgettable

Memory: {content}

Respond with only a number from 0 to 10:"""
```

**Dynamic element**: `{content}`

### Phase 2: Memory Type

**Location**: `memory/extractor.py:133-144`

```python
MEMORY_TYPE_PROMPT = """Classify this memory into one category.

Categories:
- fact: Factual information learned about user or world
- preference: User likes, dislikes, or preferences
- event: Something that happened or was accomplished
- reflection: Insight or realization from the conversation
- observation: General observation about behavior or patterns

Memory: {content}

Respond with only one word (fact, preference, event, reflection, or observation):"""
```

**Dynamic element**: `{content}`

---

## 6. Command Processor Templates

### Continuation Prompt

**Location**: `agency/commands/processor.py:143-174`

```python
def _build_continuation_prompt(self, results: List[CommandResult]) -> str:
    lines = ["[Command Results]", ""]

    for result in results:
        if result.needs_continuation:
            # ... format result ...
            lines.append(f"Your [[{result.command_name}: {result.query}]] returned:")
            lines.append(formatted)
            lines.append("")

    lines.append("Continue your response naturally, incorporating this information.")
    return "\n".join(lines)
```

**Fixed text**:
- `"[Command Results]"`
- `"Continue your response naturally, incorporating this information."`

---

## 7. Context Source Templates

### Semantic Memory Header

**Location**: `prompt_builder/sources/semantic_memory.py:71-74`

```python
lines = [
    "<recalled_context>",
    "The following are relevant memories from past conversations:",
    ""
]
```

### Conversation Header

**Location**: `prompt_builder/sources/conversation.py:62`

```python
lines = ["<recent_conversation>"]
```

### Temporal Context

**Location**: `prompt_builder/sources/temporal.py:48-50`

```python
lines = ["<temporal_context>"]
lines.append(f"  {semantic_text}")
lines.append("</temporal_context>")
```

---

## 8. Proactive Agency Prompt (Legacy)

**Location**: `agency/proactive.py:172-182` (if still present)

```python
prompt = f"""You are an AI companion. It has been {idle_minutes:.0f} minutes since the last message.
{memory_context}

Generate a brief, natural message to re-engage the conversation. This could be:
- A thoughtful observation or question
- Following up on a previous topic
- Sharing something interesting
- A gentle check-in

Keep it concise (1-2 sentences). Be natural, not needy.
Respond with just the message, no explanation."""
```

**Status**: Disabled (`AGENCY_ENABLED = False`), replaced by System Pulse

---

## Summary Table

| Subsystem | File | Prompt Count | LLM Target |
|-----------|------|--------------|------------|
| System Pulse | `agency/system_pulse.py` | 1 | Anthropic |
| Intentions | `intention_source.py` | 2 | Anthropic |
| Pulse Control | `system_pulse.py` (source) | 1 | Anthropic |
| Commands | `handlers/*.py` | 5 | Anthropic |
| Memory Extraction | `extractor.py` | 4 | KoboldCpp |
| Command Processor | `processor.py` | 1 | Anthropic |

---

## Notes on Design

### Why No Base System Prompt?

The system intentionally avoids a hardcoded persona prompt. Instead:

1. **Core Memories** define identity through accumulated facts
2. **Narrative content** in core memories can contain persona guidance
3. **Emergent behavior** arises from context rather than instruction

This allows the AI's "personality" to evolve based on stored memories rather than being rigidly defined.

### Multi-Pass Extraction

Memory extraction uses multiple simple prompts rather than one complex prompt because:

1. Local LLMs (KoboldCpp) handle simple tasks better
2. Each prompt has ONE clear task
3. Failures are easier to diagnose
4. No complex JSON schema to follow

---

## Related Documents

- [PROMPT_SYSTEM_OVERVIEW.md](PROMPT_SYSTEM_OVERVIEW.md) - Architecture overview
- [PROMPT_TYPES.md](PROMPT_TYPES.md) - Prompt type documentation
- [INJECTION_POINTS.md](INJECTION_POINTS.md) - Dynamic content injection
- [POTENTIAL_ISSUES.md](POTENTIAL_ISSUES.md) - Bug analysis
