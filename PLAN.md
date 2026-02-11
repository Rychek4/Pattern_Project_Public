# Plan: Integrate Anthropic Prompt Caching

## Goal
Reduce API input token costs (~56%) and latency (~85% TTFT improvement) by adding `cache_control` breakpoints to the system prompt sent to Claude.

## Design Principle
**Contain the change.** The conversion from flat string to structured content blocks happens inside `anthropic_client.py` only. All upstream code (PromptBuilder, router, callers) continues to pass `system_prompt` as a plain string. This keeps the blast radius to 1 file.

---

## Files Changed

### 1. `config.py` — Add feature flag + settings

Add a new config section after the existing LLM configuration block (~line 80):

```python
# Prompt Caching
# Caches stable portions of the system prompt to reduce cost and latency.
# The system prompt is split at PROMPT_CACHE_BREAKPOINT (a delimiter string).
# Everything before (and including) the breakpoint is marked for caching.
PROMPT_CACHE_ENABLED = os.getenv("PROMPT_CACHE_ENABLED", "true").lower() == "true"
PROMPT_CACHE_BREAKPOINT = "<!-- cache-breakpoint -->"  # Delimiter inserted by PromptBuilder
```

- `PROMPT_CACHE_ENABLED`: Kill switch. When `False`, system prompt is sent as a plain string (current behavior). No API changes, no risk.
- `PROMPT_CACHE_BREAKPOINT`: A delimiter string that the PromptBuilder inserts between stable and dynamic content. The anthropic client looks for this to know where to split.

### 2. `prompt_builder/builder.py` — Insert breakpoint delimiter

Modify `AssembledPrompt.full_system_prompt` (lines 21-32) to insert the cache breakpoint delimiter between stable and dynamic context blocks.

The existing priority ordering already groups stable sources first:
- Priority ≤ 26 = stable (core memories, growth threads, AI commands, etc.)
- Priority > 26 = dynamic (temporal, semantic memory, conversation, etc.)

Change the `full_system_prompt` property to insert `config.PROMPT_CACHE_BREAKPOINT` between the last stable block and the first dynamic block. The threshold is priority 26 (AI Commands — the last stable source).

```python
@property
def full_system_prompt(self) -> str:
    """Get complete system prompt with all context."""
    import config
    parts = [self.system_prompt] if self.system_prompt else []

    sorted_blocks = sorted(self.context_blocks, key=lambda b: b.priority)

    breakpoint_inserted = False
    for block in sorted_blocks:
        if block.content:
            # Insert cache breakpoint between stable (≤26) and dynamic (>26) blocks
            if (not breakpoint_inserted
                    and block.priority > config.PROMPT_CACHE_STABLE_PRIORITY
                    and config.PROMPT_CACHE_ENABLED):
                parts.append(config.PROMPT_CACHE_BREAKPOINT)
                breakpoint_inserted = True
            parts.append(block.content)

    return "\n\n".join(parts)
```

Also add `PROMPT_CACHE_STABLE_PRIORITY = 26` to `config.py` so the threshold is configurable.

This is a non-breaking change: the breakpoint is just a text delimiter. If caching is disabled in the client, it's harmless extra text (and can be stripped).

### 3. `llm/anthropic_client.py` — Convert string to cached content blocks

Modify the two sites where `system_prompt` is assigned to `request_params["system"]` (lines 344-345 and 619-620).

Replace:
```python
if system_prompt:
    request_params["system"] = system_prompt
```

With:
```python
if system_prompt:
    request_params["system"] = self._apply_prompt_caching(system_prompt)
```

Add a new private method `_apply_prompt_caching()`:

```python
def _apply_prompt_caching(self, system_prompt: str):
    """
    Convert a flat system prompt string into structured content blocks
    with cache_control markers for Anthropic prompt caching.

    If caching is disabled or no breakpoint is found, returns the
    original string unchanged (the API accepts both formats).
    """
    import config

    if not getattr(config, 'PROMPT_CACHE_ENABLED', False):
        return system_prompt

    breakpoint = getattr(config, 'PROMPT_CACHE_BREAKPOINT', '')
    if not breakpoint or breakpoint not in system_prompt:
        return system_prompt

    # Split at the breakpoint delimiter
    stable_part, dynamic_part = system_prompt.split(breakpoint, 1)
    stable_part = stable_part.strip()
    dynamic_part = dynamic_part.strip()

    blocks = []
    if stable_part:
        blocks.append({
            "type": "text",
            "text": stable_part,
            "cache_control": {"type": "ephemeral"}
        })
    if dynamic_part:
        blocks.append({
            "type": "text",
            "text": dynamic_part
        })

    return blocks if blocks else system_prompt
```

Key details:
- If caching is disabled or the breakpoint isn't found, the method returns the original string. Zero behavior change.
- The API natively accepts either `str` or `list[dict]` for the `system` parameter, so no other request-building logic needs to change.
- The `"ephemeral"` cache type uses the 5-minute TTL, which is the default and most widely supported option.

### 4. `llm/anthropic_client.py` — Track cache metrics in response

Update the response parsing in both `chat()` and `chat_stream()` to capture cache-related token counts from the API response.

In `AnthropicResponse` dataclass (top of file), add two fields:

```python
cache_creation_input_tokens: int = 0
cache_read_input_tokens: int = 0
```

In `StreamingState` dataclass, add the same two fields, and update `to_response()` to copy them.

In `chat()` (~line 460), after parsing `response.usage`:
```python
usage = getattr(response, "usage", None)
if usage:
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
```

In `chat_stream()`, capture the same from the `message_delta` or final message usage.

These fields are purely additive — they default to 0 and existing code that reads `input_tokens` is unaffected.

### 5. `llm/anthropic_client.py` — Log cache hit/miss

Add a log line after each API call to surface cache behavior:

```python
if cache_read > 0:
    log_info(f"Prompt cache HIT: {cache_read} tokens read from cache", prefix="💾")
elif cache_creation > 0:
    log_info(f"Prompt cache WRITE: {cache_creation} tokens cached", prefix="💾")
```

This gives immediate visibility into whether caching is working without requiring any UI changes.

---

## Files NOT Changed

| File | Why |
|------|-----|
| `llm/router.py` | String concatenation at lines 255-258 (appending unavailable notices) works fine — it happens *before* the string reaches `anthropic_client.py`, so the breakpoint delimiter is already present in the concatenated string. The client splits on it later. |
| `prompt_builder/sources/*` | No source files change. The breakpoint is inserted by the builder, not by individual sources. |
| All 9 callers (gui, cli, http_api, etc.) | They pass `system_prompt` as a string. That contract doesn't change. |
| `llm/kobold_client.py` | KoboldCpp path never hits `_apply_prompt_caching()`. Unaffected. |
| `interface/gui.py` | Token display uses `input_tokens` which continues to work. Cache metrics are logged but not displayed in the UI (future enhancement). |

---

## Testing Strategy

1. **Feature-flag off**: Set `PROMPT_CACHE_ENABLED=false`. Verify all existing behavior is identical — system prompt sent as plain string, no structured blocks.

2. **Feature-flag on, verify structure**: Add a temporary log or breakpoint in `_apply_prompt_caching()` to confirm the system prompt splits correctly into 2 blocks with the delimiter removed.

3. **Verify cache hits**: Make two conversation requests within 5 minutes. Check logs for "Prompt cache WRITE" on the first call and "Prompt cache HIT" on the second. Confirm `cache_read_input_tokens > 0` in the response.

4. **Edge cases**:
   - System prompt with no breakpoint (e.g., extraction tasks that build their own prompt) — should pass through as plain string.
   - Empty system prompt — should pass through as-is.
   - Breakpoint at the very start or very end of the prompt — should produce a single block (no empty blocks).

5. **Router notice concatenation**: Exhaust web search daily budget, then send a message. Verify the unavailable notice is appended to the dynamic portion (after the breakpoint) and the cached portion is unaffected.

---

## Rollback

Set `PROMPT_CACHE_ENABLED=false` in config or `.env`. Instant revert, no code changes needed.

---

## Summary

| Aspect | Detail |
|--------|--------|
| Files modified | 3 (`config.py`, `prompt_builder/builder.py`, `llm/anthropic_client.py`) |
| New code | ~40 lines |
| Deleted code | 0 lines |
| Type signature changes | 0 (upstream contracts unchanged) |
| New dependencies | 0 |
| Risk level | Low (feature-flagged, contained in client, API accepts both formats) |
| Estimated savings | ~56% on input token costs, ~85% TTFT reduction on cache hits |
