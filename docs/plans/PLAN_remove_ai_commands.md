# Plan: Remove `ai_commands` Section from Prompt

## Rationale

The `ai_commands` section injects redundant capability announcements into every prompt. The AI already knows what tools are available via native tool schemas in the API call. The metadata (`native_tools_mode`, `web_search_enabled`, `web_fetch_enabled`) is written but **never read** by any code. The only non-redundant value — budget warnings when < 10 uses remain — can be handled by the router, which already has the limiter integration for unavailability notices.

## Steps

### Step 1: Relocate budget warnings into the router

**File:** `llm/router.py` (~lines 646-681, 689-739)

The router's `_check_web_search_availability()` and `_check_web_fetch_availability()` already check limiter state and inject unavailability messages when limits are exhausted. Extend these methods to also return a brief budget warning when remaining < 10 (but > 0). This preserves the one useful behavior from `ai_commands`.

For `_check_web_search_availability()`, after confirming available (~line 674):
```python
remaining = limiter.get_remaining()
budget_msg = None
if remaining < 10:
    used, total = limiter.get_usage()
    budget_msg = f"<web_search_notice>Web search budget low: {remaining} remaining ({used}/{total} used)</web_search_notice>"
return (True, max_uses, budget_msg)
```

Same pattern for `_check_web_fetch_availability()`.

The caller at ~line 226 already appends notice strings to the system prompt — adjust it to also handle non-None budget messages returned alongside the existing unavailable messages. The return signatures gain a budget notice field, or we can reuse the existing unavailable_msg field (since both are mutually exclusive — you're either unavailable OR low budget, never both).

**Simplest approach:** Reuse the existing `unavailable_msg` return slot. When budget is low, return the budget warning there instead. The caller already appends it to the system prompt. No signature change needed.

### Step 2: Delete the ai_commands source file

**File:** `prompt_builder/sources/ai_commands.py` — **DELETE** entire file (167 lines)

### Step 3: Remove registration from builder

**File:** `prompt_builder/builder.py`
- Remove import of `AICommandsSource` (~line 219)
- Remove `AICommandsSource()` from the sources list in `create_default_builder()` (~line 237)

### Step 4: Remove priority enum entry

**File:** `prompt_builder/sources/base.py`
- Remove `AI_COMMANDS = 26` from `SourcePriority` enum (~line 18-20)
- Leave the gap (25 → 30) — renumbering would be unnecessary churn

### Step 5: Update documentation (5 files)

1. **`FEATURE_CATALOG.md`** (~line 342) — Remove the AICommandsSource row from the source table
2. **`docs/prompts/PROMPT_SYSTEM_OVERVIEW.md`** (~lines 45, 140, 150-159) — Remove from priority diagram, source table, and key files section
3. **`docs/prompts/INJECTION_POINTS.md`** (~lines 188-253, 524) — Remove entire Section 4 "AI Commands Injection" and its row in the summary table
4. **`docs/prompts/PROMPT_TYPES.md`** (~lines 62-64) — Remove `<ai_commands>` from the example prompt structure
5. **`docs/prompts/POTENTIAL_ISSUES.md`** (~lines 118-137, 254) — Remove Section 5 "Command Instructions Always Included" and the tag reference

---

## What's preserved
- Budget warnings when running low (relocated to router, only shown when < 10 remaining)
- Unavailability notices when limits exhausted (already in router, unchanged)
- Tool availability (communicated via native tool schemas, unchanged)

## What's removed
- Redundant "Web search available" / "Web fetch available" every single request
- Dead metadata fields nobody reads
- "Combined research guidance" boilerplate (the AI doesn't need instructions to search then fetch)
- ~167 lines of source code + documentation references

## Risk
**Low.** No code reads the metadata. The router already handles availability. Native tool schemas already communicate tool presence. Budget warnings are relocated, not lost.
