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

## Fix Attempt 3 (Commit 832c7e8) — Preserve Pydantic Objects

### Principle

Store the SDK's original Pydantic objects in `raw_content` wherever
possible.  The SDK knows how to serialize its own objects when they are
passed back in `messages.create()`.

### What It Fixed

- `encrypted_content` preservation (Problem 1)
- Streaming text duplication (Problem 2)
- `ensure_tool_results()` now skips server tools (Problem 3 partially)

### Why It Still Failed

The fix still **mixed types** in `raw_content`: re-typed `server_tool_use`
blocks were plain dicts while all other blocks (including the paired
`web_search_tool_result`) remained SDK Pydantic objects. When the SDK's
Pydantic v2 union discriminator encountered this mixed list during
serialization, it could silently drop the Pydantic `web_search_tool_result`
block — leaving `server_tool_use` without its matching result.

Additionally, `get_api_messages()` in `conversation.py` never enforced
user/assistant alternation. Pulse responses create system + assistant turns;
after filtering out system turns, consecutive assistant messages remained.
The API or SDK merges these, shifting block indices unpredictably (the error
index varied between runs: 20 → 22 → 21).

The non-streaming parsing code also only checked `block_type == "tool_use"`
for web_search/web_fetch — genuine `server_tool_use` blocks from the API
were invisible in logs, making the bug appear more mysterious than it was.

---

## Fix Attempt 4 — Homogeneous dicts via model_dump()

Converted ALL blocks to plain dicts using `model_dump()` to ensure
homogeneous types.  This also failed — the SDK's `ContentBlockParam`
union apparently does NOT include server-side block types as TypedDict
variants.  Dicts with `type: "server_tool_use"` or
`type: "web_search_tool_result"` don't match any TypedDict variant and
get silently dropped during serialization.  Same error, zero behavioral
change from 4 PRs.

---

## The Fix (Current)

### Principle

**Pass `response.content` VERBATIM.  Do not rebuild, convert, re-type,
or model_dump() ANY content blocks.**

The Anthropic docs explicitly state that `response.content` must be passed
back as-is in multi-turn conversations.  The SDK is designed to serialize
its own Pydantic response objects when they appear in message content.
Any modification (hand-crafted dicts, re-typing, model_dump) breaks this
round-trip because it changes the objects from SDK types to dict/TypedDict
types that may not match the `ContentBlockParam` union.

### Changes Made

#### `llm/anthropic_client.py` — Verbatim passthrough (non-streaming)

Replaced the block-by-block raw_content building loop with:
```python
raw_content_list = list(content_blocks)
```
No re-typing, no model_dump(), no dict conversion.  Just pass through
the original SDK Pydantic objects exactly as received from the API.

Added diagnostic logging of block types and count for debugging.

#### `llm/anthropic_client.py` — Pydantic preservation (streaming)

Reverted `web_search_tool_result` / `web_fetch_tool_result` handling in
`content_block_stop` to store the original Pydantic object from
`content_block_start`, not a model_dump() dict.

#### `llm/anthropic_client.py` — `server_tool_use` parsing

Added `elif block_type == "server_tool_use"` handling in the non-streaming
content block parsing loop.  Web search/fetch invocations that arrive as
`server_tool_use` (the correct type) are now properly logged, counted, and
added to `server_tool_details`.

#### `memory/conversation.py` — Message alternation

`get_api_messages()` now merges consecutive same-role messages after
filtering out system turns, and drops leading assistant messages.

#### `agency/tools/response_helper.py` — `ensure_tool_results()`

Added name-based skip for `web_search` and `web_fetch` tool_use blocks
(safety net in case the API sends them with a `toolu_` prefix).

---

## How to Verify

If this bug resurfaces, check these things:

1. **API 400 about missing `tool_result`**: Look at the block IDs in the
   error. If they start with `srvtoolu_`, a server tool block is being
   treated as a client tool. Check that `raw_content` has `server_tool_use`
   type (not `tool_use`) for web_search/web_fetch blocks.

2. **Mixed types in raw_content**: All items in `raw_content` should be
   plain `dict` instances. If any are Pydantic objects (`hasattr(block,
   'model_dump')`), the `_content_block_to_dict()` conversion is not being
   applied. Mixed types are the root cause of silent block drops.

3. **Non-alternating messages**: Check that `get_api_messages()` returns
   strictly alternating user/assistant messages starting with user. Log the
   role distribution; user count and assistant count should differ by at
   most 1.

4. **Citations not working in multi-turn**: Check that
   `web_search_tool_result` dicts in `raw_content` contain
   `encrypted_content` keys. If missing, `model_dump()` may not be
   preserving the field.

5. **Duplicate text in continuations**: Enable prompt export
   (`RoundRecorder`) and check the continuation messages for duplicate text
   content across text blocks.

6. **`ensure_tool_results` firing warnings**: The log message
   "Adding synthetic tool_result for N orphaned client tool_use block(s)"
   should be rare. If it fires frequently, investigate why client tool
   results are being dropped by the processor.

7. **Invisible web_search invocations**: Check logs for "Server web search
   invoked" messages. If web_search is being used but no log appears, the
   `server_tool_use` parsing handler may have regressed.

---

## References

- [Anthropic Web Search Tool docs](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool)
- [Anthropic Web Fetch Tool docs](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-fetch-tool)
- [Anthropic Tool Use Overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)
- [LiteLLM Issue #17737](https://github.com/BerriAI/litellm/issues/17737) — same class of bug in LiteLLM middleware
