# Hardcoded Prompts Reference

This document catalogs all hardcoded prompt text in the Pattern Project system, organized by subsystem.

## Overview

The Pattern Project intentionally has **no base system prompt** for conversations - personality emerges from context. However, several subsystems contain hardcoded instructional and template text.

---

## 1. System Pulse Prompts

### Pulse Trigger Prompt

**Location**: `agency/system_pulse.py` — `get_pulse_prompt()`

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

**Location**: `agency/system_pulse.py` — `PULSE_STORED_MESSAGE`

```python
PULSE_STORED_MESSAGE = "[System Pulse]"
```

**Purpose**: Abbreviated version stored in conversation history (vs. full prompt sent to LLM)

---

## 2. Intention System Prompts

### Empty Intentions Context

**Location**: `prompt_builder/sources/intention_source.py` — `_build_empty_context()`

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

**Location**: `prompt_builder/sources/intention_source.py` — `_build_context()`

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

**Location**: `prompt_builder/sources/system_pulse.py` — `get_context()`

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

**Location**: `agency/commands/handlers/memory_search.py` — `get_instructions()`

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

**Location**: `agency/commands/handlers/intention_handler.py` — `RemindHandler.get_instructions()`

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

**Location**: `agency/commands/handlers/intention_handler.py` — `CompleteHandler.get_instructions()`

```python
def get_instructions(self) -> str:
    return """Mark an intention as completed:
  [[COMPLETE: I-id | outcome note]]
  [[COMPLETE: I-id]]

The outcome becomes part of your memory."""
```

### Dismiss Handler

**Location**: `agency/commands/handlers/intention_handler.py` — `DismissHandler.get_instructions()`

```python
def get_instructions(self) -> str:
    return """Cancel an intention without completing it:
  [[DISMISS: I-id]]

Use when an intention is no longer relevant."""
```

### List Intentions Handler

**Location**: `agency/commands/handlers/intention_handler.py` — `ListIntentionsHandler.get_instructions()`

```python
def get_instructions(self) -> str:
    return """Review all your active intentions:
  [[LIST_INTENTIONS]]

Results are provided for you to decide what to do with them."""
```

---

## 5. Memory Extraction Prompt

### Unified Extraction (Single API Call)

**Location**: `memory/extractor.py` — `UNIFIED_EXTRACTION_PROMPT`

This prompt extracts both episodic and factual memories in a single Claude API call, replacing the previous multi-pass local LLM approach.

```python
UNIFIED_EXTRACTION_PROMPT = """<task>
Analyze this conversation and extract TWO types of memories:
1. EPISODIC: Narrative memories about what happened (written as the AI "I")
2. FACTUAL: Concrete facts about {user_name} that would be useful to remember
</task>

<episodic_instructions>
- Identify distinct topics/themes discussed
- Write 1-2 sentence memories in FIRST PERSON as the AI
- Focus on insights, shifts, moments of connection, or friction
- Create ONE memory per significant topic (3+ turns of discussion)
- Skip trivial small talk unless it reveals something meaningful
</episodic_instructions>

<factual_instructions>
- ONLY extract facts the user explicitly stated or confirmed
- AI suggestions are NOT facts unless user agreed
- Write as third-person assertions
</factual_instructions>

<source_credibility>
- User's own statements: Take at face value
- Claims from external sources: Attribute and note plausibility if dubious
- Discussions and ideas: Attribute but don't over-hedge
</source_credibility>

<importance_guide>
Rate importance on a 1-10 scale (only extract 3+)
</importance_guide>

<output_format>
===EPISODIC===
MEMORY: [content]
IMPORTANCE: [3-10]
TYPE: [fact/preference/event/reflection/observation]
TOPIC: [description]

===FACTUAL===
FACT: [content]
IMPORTANCE: [3-10]
TYPE: [fact/preference]
</output_format>
"""
```

**Dynamic elements**: `{user_name}`, `{conversation}`
**LLM target**: Anthropic Claude (single API call)
**Trigger**: Context window overflow (40 unprocessed turns)

---

## 6. Command Processor Templates

### Continuation Prompt

**Location**: `agency/commands/processor.py` — `_build_continuation_prompt()`

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

**Location**: `prompt_builder/sources/semantic_memory.py` — `get_context()`

```python
lines = [
    "<recalled_context>",
    "The following are relevant memories from past conversations:",
    ""
]
```

### Conversation Header

**Location**: `prompt_builder/sources/conversation.py` — `get_context()`

```python
lines = ["<recent_conversation>"]
```

### Temporal Context

**Location**: `prompt_builder/sources/temporal.py` — `get_context()`

```python
lines = ["<temporal_context>"]
lines.append(f"  {semantic_text}")
lines.append("</temporal_context>")
```

---

## 8. Proactive Agency Prompt (Legacy)

**Location**: `agency/proactive.py` — `_generate_proactive_message()`

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
| Memory Extraction | `extractor.py` | 1 (unified) | Anthropic |
| Command Processor | `processor.py` | 1 | Anthropic |

---

## Notes on Design

### Why No Base System Prompt?

The system intentionally avoids a hardcoded persona prompt. Instead:

1. **Core Memories** define identity through accumulated facts
2. **Narrative content** in core memories can contain persona guidance
3. **Emergent behavior** arises from context rather than instruction

This allows the AI's "personality" to evolve based on stored memories rather than being rigidly defined.

### Unified Extraction

Memory extraction uses a single comprehensive prompt to Claude rather than multiple simple prompts:

1. Claude handles topic identification, memory synthesis, and fact extraction in one pass
2. Produces both episodic (first-person narrative) and factual (third-person assertions) memories
3. Includes source credibility assessment for external claims
4. Importance-gated: only memories rated 3+ (on 1-10 scale) are extracted

---

## Related Documents

- [PROMPT_SYSTEM_OVERVIEW.md](PROMPT_SYSTEM_OVERVIEW.md) - Architecture overview
- [PROMPT_TYPES.md](PROMPT_TYPES.md) - Prompt type documentation
- [INJECTION_POINTS.md](INJECTION_POINTS.md) - Dynamic content injection
- [POTENTIAL_ISSUES.md](POTENTIAL_ISSUES.md) - Bug analysis
