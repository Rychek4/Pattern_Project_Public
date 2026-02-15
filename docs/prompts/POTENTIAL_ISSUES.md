# Potential Issues & Process Analysis

This document analyzes the prompt building system for bugs, design issues, and areas that may need review. Since prompt formation is the most critical part of the project (given the ephemeral context window design), this analysis focuses on what could cause malformed, confusing, or suboptimal prompts.

---

## Critical Issues

### 1. System Prompt Has No Base Context

**Location**: `interface/cli.py:127-129`, `prompt_builder/builder.py:96-132`

**Issue**: The system prompt is built with `system_prompt=""` (empty string). The AI receives no foundational instructions about:
- Its identity or name
- How to behave
- What the XML tags mean
- That it should maintain conversation coherence

**Current Behavior**:
```python
assembled = prompt_builder.build(
    user_input=user_input,
    system_prompt=""  # EMPTY - no base instructions
)
```

**Impact**:
- The AI must infer everything from context blocks
- New conversations with no core memories have zero identity guidance
- The AI might not understand the XML tag structure

**Recommendation**: Consider adding minimal foundational context, or ensure core memories always contain essential guidance.

---

### 2. Pulse Prompt Stored vs. Sent Mismatch

**Location**: `interface/cli.py:254-272`

**Issue**: What's stored in conversation history differs from what's sent to the LLM:

```python
# Stored in database (abbreviated)
conversation_mgr.add_turn(
    role="user",
    content=PULSE_STORED_MESSAGE,  # "[System Pulse]"
    input_type="system_pulse"
)

# Sent to LLM (full prompt)
history.append({"role": "user", "content": PULSE_PROMPT})
```

**Impact**:
- When history is replayed from database, AI sees `"[System Pulse]"` instead of full context
- Semantic memory search on pulse responses may be confusing
- History reconstruction differs from original prompt

**Recommendation**: Either store the full prompt, or ensure `[System Pulse]` is sufficient context when replayed.

---

### 3. Conversation Source Uses Hardcoded Names

**Location**: `prompt_builder/sources/conversation.py:64-68`

**Issue**: User and assistant names are hardcoded:

```python
for turn in turns:
    name = "Isaac" if turn.role == "assistant" else "Brian"
    timestamp = format_fuzzy_relative_time(turn.created_at)
    lines.append(f"  {name}: {turn.content} ({timestamp})")
```

**Impact**:
- "Brian" is hardcoded as the user's name
- "Isaac" may not match the intended persona
- No configuration for different users

**Recommendation**: Make names configurable or derive from core memories.

---

### 4. No Validation of Context Block Content

**Location**: `prompt_builder/builder.py:118-125`

**Issue**: Context sources can return any string content without validation:

```python
for source in self._sources:
    try:
        block = source.get_context(user_input, session_context)
        if block and block.content:
            blocks.append(block)
    except Exception as e:
        log_error(f"Error getting context from {source.source_name}: {e}")
```

**Impact**:
- Malformed XML could confuse the AI
- Empty tags `<tag></tag>` waste tokens
- Unclosed tags could break parsing
- No length limits on individual blocks

**Recommendation**: Add content validation/sanitization layer.

---

## Moderate Issues

### 5. Command Instructions Always Included

**Location**: `prompt_builder/sources/ai_commands.py:46-48`

**Issue**: All command instructions are included in every prompt, even when irrelevant:

```python
if not processor.has_handlers():
    return None

instructions = processor.get_all_instructions()
```

**Impact**:
- ~200 tokens of command instructions in every prompt
- Instructions for reminders shown even in casual conversations
- Could encourage unnecessary command use

**Recommendation**: Consider context-aware instruction inclusion (e.g., only show search when user asks about past).

---

### 6. Intention Context Privacy Claim May Be Inaccurate

**Location**: `prompt_builder/sources/intention_source.py:99, 116`

**Issue**: The prompt claims intentions are "private":

```
"These are your private intentions — the user cannot see them."
```

But intentions appear in the system prompt which:
- Is logged to `logs/api_prompts.jsonl`
- Could be visible in debugging
- Stored in API provider logs

**Impact**: The privacy claim creates a false mental model for the AI.

**Recommendation**: Clarify the nature of "private" or implement actual privacy measures.

---

### 7. Semantic Memory Could Return Duplicates

**Location**: `prompt_builder/sources/semantic_memory.py:61-65`

**Issue**: Vector search doesn't explicitly deduplicate:

```python
results = vector_store.search(
    query=user_input,
    limit=self.max_memories,
    min_score=self.min_score
)
```

**Impact**: Similar memories could appear multiple times, wasting context.

**Recommendation**: Add deduplication logic in vector store or semantic memory source.

---

### 8. Continuation Prompt Doesn't Include Original Context

**Location**: `interface/cli.py:160-171`

**Issue**: Pass 2 reuses the same system prompt but doesn't acknowledge the two-pass nature:

```python
continuation = router.chat(
    messages=continuation_history,
    system_prompt=assembled.full_system_prompt,  # Same as Pass 1
    task_type=TaskType.CONVERSATION,
)
```

**Impact**:
- AI might not understand it already gave a partial response
- Context about command results is only in messages, not system prompt
- Could lead to repetition or confusion

**Recommendation**: Consider adding Pass 2 context to system prompt.

---

### 9. Memory Extraction Importance Scoring is Coarse

**Location**: `memory/extractor.py:120-130`

**Issue**: The importance prompt uses a 0-10 scale that's then converted to 0.0-1.0:

```python
def _parse_importance_response(self, response_text: str) -> float:
    # ...
    if value > 1.0:
        value = value / 10.0
```

But the scoring guide is imprecise:
- "8-10: Major decisions, strong preferences"
- Local LLMs may not score consistently

**Impact**: Memory importance may be unreliable, affecting recall priority.

**Recommendation**: Consider simplifying to high/medium/low or using examples.

---

### 10. Visual Context Cache Could Be Stale

**Location**: `prompt_builder/sources/visual.py` (general)

**Issue**: 30-second cache means visual context could be 30 seconds old:

```python
VISUAL_CAPTURE_INTERVAL = int(os.getenv("VISUAL_CAPTURE_INTERVAL", "30"))
```

**Impact**:
- User could be looking at something different
- Fast context switches won't be captured
- Descriptions might not match current state

**Recommendation**: Consider shorter intervals or on-demand capture.

---

## Minor Issues

### 11. XML Tag Inconsistency

**Issue**: Some context uses XML tags, some doesn't:

```
Core Memory: No wrapping tag (just content)
Intentions: <your_intentions>
Commands: <ai_commands>
Temporal: <temporal_context>
Semantic: <recalled_context>
Conversation: <recent_conversation>
```

**Impact**: Inconsistent structure could confuse the AI about what's what.

**Recommendation**: Either wrap all in tags or none, consistently.

---

### 12. Time Expression Parsing May Fail Silently

**Location**: `agency/intentions/parser.py` (via `parse_time_expression`)

**Issue**: If time parsing fails, the handler returns an error but the AI isn't informed consistently:

```python
trigger_at, trigger_type = parse_time_expression(when_str)

if trigger_type == 'time' and trigger_at is None:
    return CommandResult(
        # ...
        error=f"Could not parse time: '{when_str}'"
    )
```

**Impact**:
- User might see "Reminder set" message but with wrong time
- AI might not realize the reminder failed

**Recommendation**: Ensure error feedback reaches the AI.

---

### 13. Session Context Not Thread-Safe

**Location**: `prompt_builder/builder.py:113`

**Issue**: `session_context` is a shared dict passed between sources:

```python
session_context: Dict[str, Any] = additional_context.copy() if additional_context else {}
```

But sources modify it in-place:
```python
session_context["temporal_context"] = context  # From TemporalSource
session_context["pulse_interval_seconds"] = current_interval  # From SystemPulseSource
```

**Impact**: In concurrent scenarios, context could be corrupted.

**Recommendation**: Consider immutable patterns or explicit locks.

---

### 14. Turn Assignment JSON Parsing is Fragile

**Location**: `memory/extractor.py:683-762`

**Issue**: The LLM is asked to output JSON, but parsing is basic:

```python
# Handle markdown code blocks
if "```json" in text:
    text = text.split("```json")[1].split("```")[0]
elif "```" in text:
    text = text.split("```")[1].split("```")[0]
```

**Impact**:
- Local LLMs might output malformed JSON
- Extraction could fail silently

**Recommendation**: Add more robust JSON extraction or retry logic.

---

### 15. Core Memory Categories Limited Without Explanation

**Location**: `interface/cli.py:582-587`

**Issue**: Valid categories are hardcoded without explanation to the AI:

```python
valid_categories = ["identity", "relationship", "preference", "fact"]
if category not in valid_categories:
    self.console.print(f"[yellow]Invalid category. Use: {', '.join(valid_categories)}[/yellow]")
```

But the AI receives core memories formatted as:
```
- [identity] ...
- [relationship] ...
```

**Impact**:
- AI doesn't know what categories mean
- "narrative" category exists but isn't in valid list

**Recommendation**: Document categories in system or include in core memory context.

---

## Design Questions for Review

### A. Is No System Prompt Intentional?

The design document should clarify if the empty system prompt is a feature or oversight. Currently:
- Pros: Emergent personality, flexible
- Cons: No guardrails, no clear identity

### B. Should Commands Be Context-Aware?

Currently all commands are always available. Consider:
- Only showing `[[SEARCH:]]` when user asks about the past
- Only showing `[[REMIND:]]` when follow-up is relevant

### C. Is 30-Turn History Sufficient?

With `CONVERSATION_EXCHANGE_LIMIT = 15` (30 turns), older context is lost. Consider:
- Is this enough for complex discussions?
- Should important turns be preserved longer?

### D. Should Memories Be Validated Before Injection?

Currently, extracted memories go directly to vector store. Consider:
- Quality thresholds
- Duplicate detection
- Content validation

### E. How Should Multi-User Be Handled?

Currently "Brian" is hardcoded. Consider:
- User profiles in database
- Per-session user identification
- Multi-user conversation support

---

## Testing Recommendations

### Prompt Integrity Tests

1. **Empty State Test**: Start with empty database, verify prompts are valid
2. **Overflow Test**: Fill all context sources to max, verify no truncation
3. **Malformed Data Test**: Inject edge-case data, verify graceful handling
4. **Two-Pass Test**: Verify Pass 2 has correct context from Pass 1

### Regression Tests

1. **No Base Prompt**: Ensure empty system_prompt is intentional
2. **Tag Closure**: Verify all XML tags are properly closed
3. **Name Consistency**: Check "Brian"/"Isaac" usage
4. **Privacy Claims**: Audit what's actually visible

### Integration Tests

1. **Full Flow**: User message → AI response → Memory extraction
2. **Pulse Flow**: Timer fires → AI speaks → Commands work
3. **Command Chain**: Search → Results → Continuation

---

## Summary Priority Matrix

| Issue | Severity | Effort | Priority |
|-------|----------|--------|----------|
| #1 No Base System Prompt | High | Medium | P1 |
| #2 Pulse Storage Mismatch | Medium | Low | P2 |
| #3 Hardcoded Names | Low | Low | P3 |
| #4 No Content Validation | Medium | Medium | P2 |
| #5 Always-On Commands | Low | Medium | P4 |
| #6 Privacy Claim | Low | Low | P3 |
| #7 Duplicate Memories | Low | Medium | P4 |
| #8 Pass 2 Context | Medium | Medium | P2 |
| #9 Importance Scoring | Low | Medium | P4 |
| #10 Visual Cache Staleness | Low | Low | P4 |

---

## Related Documents

- [PROMPT_SYSTEM_OVERVIEW.md](PROMPT_SYSTEM_OVERVIEW.md) - Architecture overview
- [PROMPT_TYPES.md](PROMPT_TYPES.md) - Prompt type documentation
- [INJECTION_POINTS.md](INJECTION_POINTS.md) - Dynamic content injection
- [HARDCODED_PROMPTS.md](HARDCODED_PROMPTS.md) - Static prompt text
