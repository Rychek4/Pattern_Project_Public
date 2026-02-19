# Server Tool Use Bug — History, Root Cause, and Fix

## Summary

Multi-turn conversations that use Anthropic's server-side tools (web_search,
web_fetch) would intermittently fail with **API 400 errors** complaining about
missing `tool_result` blocks. The root cause was that our code manually
re-serialized the SDK's response content blocks into hand-crafted dicts,
dropping critical fields and creating fragile type-handling code that the API
then rejected.

---

## Background: Server Tools vs Client Tools

The Anthropic API has two categories of tools:

| Aspect                 | Client Tools (`tool_use`)              | Server Tools (`server_tool_use`)              |
|------------------------|----------------------------------------|-----------------------------------------------|
| ID prefix              | `toolu_`                               | `srvtoolu_`                                   |
| Execution              | Client-side (our code)                 | Server-side (Anthropic's servers)             |
| Result block           | `tool_result` in next **user** message | `web_search_tool_result` / `web_fetch_tool_result` in same **assistant** message |
| Requires `tool_result`?| **Yes** — API rejects without it       | **No** — self-contained                       |
| `stop_reason`          | `tool_use`                             | `end_turn` or `pause_turn`                    |

**Key rule**: Server tool blocks (`server_tool_use` + `web_search_tool_result`)
live entirely within the same assistant message. You must **never** send a
`tool_result` for them. The `srvtoolu_` ID prefix distinguishes them from
client tools.

---

## The Bug

### What Happened

When building multi-turn continuation messages, our `anthropic_client.py`
converted `response.content` (a list of SDK Pydantic objects) into
**hand-crafted Python dicts** for `raw_content`. These dicts were then passed
back to the SDK in subsequent `messages.create()` calls.

This caused three distinct problems:

### Problem 1: Lost `encrypted_content` (Non-streaming + Streaming)

`web_search_tool_result` and `web_fetch_tool_result` blocks contain nested
`encrypted_content` fields that the API requires for citation continuity in
multi-turn conversations. Our hand-crafted dicts dropped these fields:

```python
# BEFORE (broken) — drops encrypted_content
state.raw_content.append({
    "type": current_block_type,
    "tool_use_id": getattr(result_block, "tool_use_id", ""),
    "content": block_content  # shallow reference, but wrapper dict is wrong
})
```

The Anthropic SDK knows how to serialize its own Pydantic objects, including
all nested fields. By constructing our own dict wrapper, we lost the ability
for the SDK to properly round-trip the response.

### Problem 2: Streaming text block accumulation bug

In the streaming path, when finalizing a text block in `content_block_stop`,
the code stored `state.text` (the *cumulative* text across all blocks) instead
of just the current block's text:

```python
# BEFORE (broken) — duplicates text from earlier blocks
elif current_block_type == "text":
    state.raw_content.append({
        "type": "text",
        "text": state.text  # ALL text, not just this block
    })
```

In a response like `[text, server_tool_use, web_search_tool_result, text]`,
the second text block would contain all text from the first block too,
causing duplicate content in continuation messages.

### Problem 3: Type confusion between `tool_use` and `server_tool_use`

The API can return server tool invocations as either `tool_use` or
`server_tool_use` blocks. When they arrive as `tool_use`, our code re-typed
them in `raw_content` — but as hand-crafted dicts, not SDK objects. If the
SDK's serialization path didn't handle `"type": "server_tool_use"` dicts
identically to `ServerToolUseBlockParam` Pydantic objects, the API would
see them as `tool_use` and demand `tool_result` blocks.

---

## Previous Fix Attempts

### PR #227 — Re-type to `server_tool_use`

Changed the `raw_content` dict's `type` field from `"tool_use"` to
`"server_tool_use"` for web_search/web_fetch blocks. This was directionally
correct but still used hand-crafted dicts, which:
- Dropped `encrypted_content` from result blocks
- Could be silently normalized back to `tool_use` by some SDK versions

### PR #228 — `ensure_tool_results` defensive function

Added a safety net that scans `raw_content` for `tool_use` blocks without
matching `tool_result` blocks, and adds synthetic `tool_result` entries.
This **worked against the API's design** — server tools should *never*
receive `tool_result` blocks. It also masked the real bug instead of fixing
it.

---

## The Fix

### Principle

**Store the SDK's original Pydantic objects in `raw_content` wherever
possible.** The SDK knows how to serialize its own objects when they are
passed back in `messages.create()`. This preserves all fields including
`encrypted_content`, `encrypted_index`, and thinking block signatures.

### Changes Made

#### `llm/anthropic_client.py` — Non-streaming path (`chat()`)

Replaced the manual dict-construction loop with logic that stores original
Pydantic objects for all block types *except* `tool_use` blocks for
web_search/web_fetch (which are re-typed to `server_tool_use` dicts since
the API may return them with the wrong type):

```python
for block in content_blocks:
    block_type = getattr(block, "type", None)
    if block_type == "tool_use":
        tool_name = getattr(block, "name", "")
        if tool_name in ("web_search", "web_fetch"):
            # Re-type to server_tool_use dict
            raw_content_list.append({
                "type": "server_tool_use",
                "id": getattr(block, "id", ""),
                "name": tool_name,
                "input": getattr(block, "input", {})
            })
        else:
            raw_content_list.append(block)  # Pydantic object
    else:
        raw_content_list.append(block)  # Pydantic object
```

#### `llm/anthropic_client.py` — Streaming path (`chat_stream()`)

Three fixes:

1. **Text block accumulation**: Added `_current_block_text` field to
   `StreamingState` that tracks text per-block (reset on each
   `content_block_start`, accumulated on each `text_delta`). The
   `content_block_stop` handler now uses `state._current_block_text`
   instead of the cumulative `state.text`.

2. **Server tool result preservation**: Changed
   `web_search_tool_result` / `web_fetch_tool_result` handling in
   `content_block_stop` to store the original Pydantic object from
   `content_block_start` instead of extracting fields into a dict.

3. **Server tool use blocks**: These were already handled correctly
   (built as dicts with `"type": "server_tool_use"`), and cannot be
   stored as Pydantic objects since their input is streamed via deltas.

#### `agency/tools/response_helper.py` — `ensure_tool_results()`

Updated to:
- Handle both plain dicts and SDK Pydantic objects in `raw_content`
- Skip `server_tool_use` typed blocks entirely
- Skip blocks with `srvtoolu_` ID prefixes (server tool IDs)
- Only create synthetic `tool_result` entries for orphaned *client*
  `tool_use` blocks (defensive safety net, should rarely trigger)

---

## How to Verify

If this bug resurfaces, check these things:

1. **API 400 about missing `tool_result`**: Look at the block IDs in the
   error. If they start with `srvtoolu_`, a server tool block is being
   treated as a client tool. Check that `raw_content` has `server_tool_use`
   type (not `tool_use`) for web_search/web_fetch blocks.

2. **Citations not working in multi-turn**: Check that
   `web_search_tool_result` blocks in `raw_content` contain
   `encrypted_content` fields. If they're plain dicts without those fields,
   the Pydantic object storage is not working.

3. **Duplicate text in continuations**: Enable prompt export
   (`RoundRecorder`) and check the continuation messages for duplicate text
   content across text blocks.

4. **`ensure_tool_results` firing warnings**: The log message
   "Adding synthetic tool_result for N orphaned client tool_use block(s)"
   should be rare. If it fires frequently, investigate why client tool
   results are being dropped by the processor.

---

## References

- [Anthropic Web Search Tool docs](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool)
- [Anthropic Web Fetch Tool docs](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-fetch-tool)
- [Anthropic Tool Use Overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)
- [LiteLLM Issue #17737](https://github.com/BerriAI/litellm/issues/17737) — same class of bug in LiteLLM middleware
