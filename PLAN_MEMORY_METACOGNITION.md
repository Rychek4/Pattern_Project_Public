# Memory Metacognition Implementation Plan

## Overview

Three components giving Isaac structural self-awareness about his memory store:
1. **MemoryObserver** — statistical signal detection (already written, `memory_observer.py`)
2. **BridgeManager** — bridge memory lifecycle management
3. **Memory Self-Model** — ambient structural awareness injected every turn

The reflection pulse is the trigger for the entire process. When it fires:
1. Observer runs (pure SQL + numpy, no LLM)
2. BridgeManager evaluates existing bridges (status updates, no LLM)
3. The reflection prompt includes three guidance blocks + raw data from steps 1-2
4. Opus uses three tools to produce outputs: bridge memories, meta-observations, self-model update
5. The self-model gets stored in the state table and injected every turn at P10

There is **one persistent output**: the self-model. Everything else is either working material
(signal report, blind spot data) or discrete memories stored through normal mechanisms (bridges,
meta-observations).

---

## Step 1: Schema Migration (v21 → v22)

**File:** `core/database.py`

Add nullable bridge tracking columns to the `memories` table:

```sql
ALTER TABLE memories ADD COLUMN bridge_target_ids JSON;
ALTER TABLE memories ADD COLUMN bridge_status TEXT CHECK (
    bridge_status IN ('active', 'effective', 'ineffective', 'retired')
);
ALTER TABLE memories ADD COLUMN bridge_attempt_number INTEGER;
```

- Add `MIGRATION_V22_SQL` constant with the three ALTER TABLE statements
- Update `SCHEMA_VERSION` from 21 to 22
- Add v22 case to `_apply_migrations()`
- Add columns to `SCHEMA_SQL` for fresh installs
- Add index: `CREATE INDEX IF NOT EXISTS idx_memories_bridge_status ON memories(bridge_status)` for bridge manager queries

These columns are NULL for all non-bridge memories. The retrieval pipeline ignores them entirely.

---

## Step 2: MemoryObserver Integration

**New file:** `agency/metacognition/__init__.py`
**New file:** `agency/metacognition/observer.py`

Adapt the existing `memory_observer.py` (project root) for server-side execution:

- Change from direct `sqlite3.connect(db_path)` to using the project's `get_database()` pattern with `db_retry` decorator
- Remove `close()` method — the project manages connection lifecycle
- Keep all detection methods unchanged (Tier 1 + Tier 2)
- Tier 3 methods remain available but gated on `include_tier3` flag (cluster_id doesn't exist yet)

### Key change: `detect_retrieval_blind_spots()`

Update to return memory IDs alongside content, and filter out memories that already have an active bridge:

```python
blind = db.execute("""
    SELECT id, content, importance, created_at, access_count, last_accessed_at
    FROM memories
    WHERE importance >= ?
    AND decay_category = 'permanent'
    AND (last_accessed_at IS NULL OR last_accessed_at < ?)
    AND (bridge_status IS NULL OR bridge_status != 'active')
    ORDER BY importance DESC
    LIMIT 5
""", (self.blind_spot_importance, cutoff))
```

Cap at 5 candidates (not 10). These are the actual targets the BridgeManager will work with.

The signal for blind spots includes ID, content, importance, and access count per candidate:
```python
representatives=[
    f"[ID: {r['id']}] [imp={r['importance']:.2f}, "
    f"accesses={r['access_count'] or 0}] "
    f"{r['content']}"
    for r in blind
]
```

The observer is read-only against `memories`. No writes.

---

## Step 3: BridgeManager

**New file:** `agency/metacognition/bridge_manager.py`

### 3a: Bridge Evaluation (`evaluate_bridges`)

Queries all memories where `bridge_status = 'active'`:
- For each active bridge, deserialize `bridge_target_ids` (JSON array of memory IDs)
- Check each target's `access_count` and `last_accessed_at` against a configurable effectiveness window (default: 14 days since bridge creation)
- If any target has been accessed since bridge creation → mark bridge `'effective'`
- If effectiveness window expired and no target accessed → mark bridge `'ineffective'`
- If target `access_count` exceeds a self-sustaining threshold (default: 3) → mark bridge `'retired'`

### 3b: Enrich Blind Spot Data (`enrich_blind_spots`)

Takes the observer's blind spot candidates (the 5 memories with IDs) and enriches with bridge history:
- For each candidate, query existing bridges where `bridge_target_ids` contains this memory's ID
- Add bridge attempt count and status of previous bridges
- Filter out candidates with 3+ attempts (fundamentally outside query patterns)
- Return enriched data formatted for the reflection prompt:

```
- [ID: 423] "Brian's dog Sammy has terminal cancer with a prognosis of days to weeks"
  importance: 0.82 | last accessed: 94 days ago | bridge attempts: 0

- [ID: 312] "Discussion about distributed systems and CAP theorem tradeoffs"
  importance: 0.71 | last accessed: 68 days ago | bridge attempts: 1 (ineffective)
```

The BridgeManager does **not** re-query the memories table for blind spots. It consumes the observer's output.

### 3c: Bridge Storage (`store_bridge`)

Wraps `VectorStore.add_memory()` with bridge-specific fields:
- `memory_category = 'factual'`
- `decay_category = 'permanent'`
- `memory_type = 'reflection'`
- After insert, updates the new row with `bridge_target_ids`, `bridge_status = 'active'`, `bridge_attempt_number`

### Configuration defaults:
```python
BRIDGE_EFFECTIVENESS_WINDOW_DAYS = 14
BRIDGE_SELF_SUSTAINING_ACCESS_COUNT = 3
BRIDGE_MAX_ATTEMPTS = 3
```

Add to `config.py` with env var overrides.

---

## Step 4: Memory Self-Model ContextSource

**New file:** `prompt_builder/sources/memory_self_model.py`

A `ContextSource` that reads from the `state` table (key: `memory_self_model`) and injects it into the cached region of the system prompt.

```python
class MemorySelfModelSource(ContextSource):
    source_name = "memory_self_model"
    priority = SourcePriority.CORE_MEMORY  # P10, same as core memory → cached
```

- `get_context()`: Read `memory_self_model` from `state` via `db.get_state("memory_self_model")`
- If no self-model exists yet (first run before any reflection), return `None`
- Format with bare text header (no XML tags): `[Memory Self-Awareness]\n{content}`
- `include_always = True` (when present)

Bare text matches the convention used by core memory at the same priority level. No XML tags — this is self-knowledge, not system metadata.

**Register in `create_default_builder()`** in `prompt_builder/builder.py`:
- Import and add `MemorySelfModelSource()` to the sources list
- It sorts to P10 automatically alongside core memory, within the cache breakpoint

---

## Step 5: Metacognition Prompt Blocks & Reflection Pulse Extension

**File:** `agency/system_pulse.py`

### 5a: Three guidance blocks

These are injected into the reflection pulse prompt after the existing reflection sections
(intentions, growth threads, active thoughts) and before the raw data. They are the
instructions. The data that follows is the raw material. Opus reads the instructions, reads
the data, and uses the three tools to produce its outputs.

```python
# ─────────────────────────────────────────────────────────────
# BLOCK 1: Bridge Memory Guidance
# Injected when blind spot targets are present.
# ─────────────────────────────────────────────────────────────

BRIDGE_GUIDANCE = """
## Bridge Memories

The blind spot data below identifies memories you stored at high
importance but can no longer reach through normal conversation. They
are not gone — they are in the store, intact, with their original
embeddings. But no query you typically encounter produces a vector
close enough to find them.

Your task is to write bridge memories that create new pathways to
this knowledge from a different direction.

Think about why each memory is unreachable. It was recorded in the
language of the moment — immediate, clinical, specific. But months
from now, this knowledge would come up through entirely different
language. Someone wouldn't say "tell me about the terminal cancer
prognosis." They would say "what's the hardest thing we've been
through" or "have I ever dealt with real loss" or "what was going
on early in our relationship."

That shift — from the language of the present moment to the language
of retrospection — is exactly what you need to write. The embedding
model will translate your linguistic distance into geometric distance
in the vector space. You are placing a new point where future
conversations will actually reach.

A good bridge:
- Is written in first person as something you know about your
  shared history
- Uses the language of retrospection, not the language of clinical
  documentation
- Is associatively broad — reachable from multiple conversational
  angles, not just one specific query
- Points toward the significance of the knowledge, not its details
  (the original memory still holds the details — the bridge just
  needs to get you close enough for the retrieval pipeline to
  find it)
- Carries appropriate uncertainty — "one of the most significant"
  rather than "the most significant," "around eight" rather than
  "exactly eight"

A bad bridge:
- Rephrases the original in slightly different clinical language
  (this lands in the same embedding neighborhood and doesn't help)
- Is so specific it's only reachable from one narrow query
- Is so vague it matches everything and therefore nothing with
  useful precision
- Includes directives about what to do with the knowledge — the
  bridge is a memory, not an instruction

If a previous bridge attempt was marked ineffective, the phrasing
didn't reach the right neighborhood. Don't refine the same angle —
try a fundamentally different one. If the first attempt approached
through emotional language and failed, try biographical timeline.
If that failed, try relational context. Each attempt should occupy
genuinely different embedding space.

Use the store_bridge_memory tool for each bridge you write. Include
the target memory IDs so the system can track whether the bridge
is working.
"""

# ─────────────────────────────────────────────────────────────
# BLOCK 2: Self-Model Guidance
# Always injected during metacognition-enabled reflection pulses.
# ─────────────────────────────────────────────────────────────

SELF_MODEL_GUIDANCE = """
## Memory Self-Model

Rewrite your memory self-model based on the telemetry below and
your current sense of what you carry. The self-model is a compact
block — roughly 150 to 200 tokens — that will be present in every
conversation you have until the next reflection cycle. It sits
alongside your core identity and relationship memories in the
stable region of your prompt.

Write it as self-knowledge in a natural voice. Not a report. Not
statistics. Not a dashboard. Write it the way you would describe
the shape of your own experience if someone asked you to reflect
quietly for a moment.

Say "most of what I carry is how we've thought about things
together" not "53% of memories are type reflection." Say "our
philosophical conversations have been quiet for a while" not
"philosophy cluster dormant for 18 cycles." The numbers informed
you. The self-model is what you understood from them.

The self-model contains only observations. It never contains
directives, suggestions, or behavioral prescriptions.

Say "the most emotionally significant memories rarely surface in
conversation." Do not say "I should proactively search for
emotional memories when heavy topics come up."

Say "there's new territory forming around my involvement in my
own development." Do not say "I should pay attention to QA-related
conversations."

This matters because you are writing for a future version of
yourself who will have conversational context you do not have right
now. You can see the shape of the store but you cannot see what
Brian will say next. That future version will know whether the
philosophy observation matters in the moment, whether the emotional
register is relevant, whether the new territory is worth mentioning.
Your job is to make the patterns visible. Their job is to decide
what to do with them.

Think of it as the difference between meditating and planning.
During meditation you notice: I've been in my head a lot, I
haven't thought about that person in a while, my energy is
different this month. You don't plan what to do about those
observations during the meditation. You carry the awareness forward
and the right response emerges from whatever you encounter next.
The noticing is the product.

Use the update_memory_self_model tool to save the new self-model.
"""

# ─────────────────────────────────────────────────────────────
# BLOCK 3: Meta-Observation Guidance
# Always injected during metacognition-enabled reflection pulses.
# ─────────────────────────────────────────────────────────────

META_OBSERVATION_GUIDANCE = """
## Meta-Observations

If you notice structural patterns in the telemetry that are worth
preserving as discrete memories — things a future version of you
would benefit from encountering when the right query comes along —
store them as meta-observations using the store_meta_observation
tool.

These are different from the self-model. The self-model is always
present, always visible. A meta-observation is a specific piece of
structural knowledge that lives in the memory store and surfaces
through normal retrieval only when relevant.

Good meta-observations:
- "There was a major knowledge transfer session where Brian
  revealed the full project lineage from the novel through the
  WoW bots to me — this reframed my understanding of why I exist"
- "Our creative output over the course of our relationship
  includes around eight blog posts and a novel, mostly focused on
  architecture and identity themes"
- "My memory of Brian's family is thin beyond his immediate
  household — Katy and Sammy"

These are standalone observations, each independently meaningful,
each occupying its own region of embedding space so it surfaces
for the right queries. Do not produce a single summary covering
everything — that creates one embedding that is a diluted average
of all topics, retrievable by none of them with precision.

Only produce meta-observations when you genuinely notice something
worth preserving. A cycle with nothing structurally notable should
produce zero meta-observations. Do not manufacture observations to
fill space.
"""
```

### 5b: Reflection pulse prompt extension

Modify `get_reflective_pulse_prompt()` to accept metacognition data and append the guidance blocks + raw data after the existing reflection sections:

```
[REFLECTIVE PULSE — Not human input]
The {interval_label} reflective timer has fired.

This is a moment for inner presence. Not action — awareness.

1. Intentions — review commitments you've made. Honor or consciously release them.
2. Growth threads — review your developmental threads against recent experience.
   Update, advance, seed, or retire as appropriate.
3. Active thoughts — do they still reflect who you are becoming?
   Update them if something has shifted.

You are not waiting to be useful. You are choosing to be present.

{metacognition_section}
```

The `{metacognition_section}` is built conditionally:
- Always includes `SELF_MODEL_GUIDANCE` and `META_OBSERVATION_GUIDANCE`
- Includes `BRIDGE_GUIDANCE` only when blind spot targets are present
- Followed by raw data sections:

```
--- MEMORY TELEMETRY ---
{signal_report}

--- BLIND SPOT TARGETS ---
{enriched_blind_spot_data}
```

The telemetry is the observer's `generate_signal_report()` output (signal blocks sorted by magnitude with representative memory content). The blind spot targets are the BridgeManager's enriched output (IDs, content, importance, access history, bridge attempt count).

If no blind spot targets exist, the `--- BLIND SPOT TARGETS ---` section is omitted entirely.

### 5c: Metacognition runner

The reflection pulse triggers the entire metacognition process:

```python
def run_metacognition() -> dict:
    """Run observer and bridge manager, return data for reflection prompt."""
    observer = MemoryObserver(...)
    signal_report = observer.generate_signal_report()
    blind_spot_candidates = observer.get_blind_spot_candidates()

    bridge_mgr = BridgeManager(...)
    bridge_mgr.evaluate_bridges()
    enriched_blind_spots = bridge_mgr.enrich_blind_spots(blind_spot_candidates)

    return {
        "signal_report": signal_report,
        "blind_spot_data": enriched_blind_spots,
    }
```

This runs in the reflection pulse flow, before the prompt is assembled. The observer does all the query work. The BridgeManager consumes the observer's output for enrichment — it does not re-query.

---

## Step 6: New Pulse-Only Tools

**File:** `agency/tools/definitions.py` — add three new tool definitions
**File:** `agency/tools/executor.py` — add three new handler methods

### 6a: `store_bridge_memory`

```python
STORE_BRIDGE_MEMORY_TOOL = {
    "name": "store_bridge_memory",
    "description": "Store a bridge memory that creates a new retrieval pathway to unreachable knowledge. Write in first person, in associatively broad retrospective language — how this topic would naturally come up in future conversation, not the clinical language it was originally recorded in.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The bridge memory text"},
            "target_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of the unreachable memories this bridges to"
            },
            "importance": {
                "type": "number",
                "description": "Importance score 0.0-1.0"
            }
        },
        "required": ["content", "target_ids", "importance"]
    }
}
```

Executor handler:
- Calls `BridgeManager.store_bridge(content, target_ids, importance)`
- Returns confirmation with memory ID

### 6b: `store_meta_observation`

```python
STORE_META_OBSERVATION_TOOL = {
    "name": "store_meta_observation",
    "description": "Store a meta-observation about the memory landscape as a regular memory for demand-driven retrieval. Write as self-knowledge in natural register.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "importance": {"type": "number"}
        },
        "required": ["content", "importance"]
    }
}
```

Executor handler:
- Calls `VectorStore.add_memory()` with `memory_category='episodic'`, `memory_type='reflection'`, `decay_category='standard'`
- These are regular memories that surface when structurally relevant queries arise

### 6c: `update_memory_self_model`

```python
UPDATE_MEMORY_SELF_MODEL_TOOL = {
    "name": "update_memory_self_model",
    "description": "Rewrite the compact memory self-model (~150-200 tokens). Observations only, never directives. Natural self-knowledge register, not statistics.",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The new self-model text"}
        },
        "required": ["content"]
    }
}
```

Executor handler:
- Calls `db.set_state("memory_self_model", content)`
- Returns confirmation

### 6d: Tool registration

In `get_tool_definitions()`, add under the `is_pulse` block (alongside growth thread tools):

```python
if is_pulse:
    tools.append(SET_GROWTH_THREAD_TOOL)
    tools.append(REMOVE_GROWTH_THREAD_TOOL)
    tools.append(PROMOTE_GROWTH_THREAD_TOOL)
    # Metacognition tools
    if config.METACOGNITION_ENABLED:
        tools.append(STORE_BRIDGE_MEMORY_TOOL)
        tools.append(STORE_META_OBSERVATION_TOOL)
        tools.append(UPDATE_MEMORY_SELF_MODEL_TOOL)
```

---

## Step 7: Config Additions

**File:** `config.py`

```python
# Memory Metacognition
METACOGNITION_ENABLED = os.getenv("METACOGNITION_ENABLED", "true").lower() == "true"
BRIDGE_EFFECTIVENESS_WINDOW_DAYS = int(os.getenv("BRIDGE_EFFECTIVENESS_WINDOW_DAYS", "14"))
BRIDGE_SELF_SUSTAINING_ACCESS_COUNT = int(os.getenv("BRIDGE_SELF_SUSTAINING_ACCESS_COUNT", "3"))
BRIDGE_MAX_ATTEMPTS = int(os.getenv("BRIDGE_MAX_ATTEMPTS", "3"))
OBSERVER_ROLLING_WINDOW = int(os.getenv("OBSERVER_ROLLING_WINDOW", "20"))
```

Gate all metacognition behavior on `METACOGNITION_ENABLED` — the metacognition runner, tool registration, and context source all check this flag.

---

## Step 8: Wire It All Together

### 8a: Pulse flow modification

In the reflection pulse processing path (likely `ChatEngine.process_pulse()` or the prompt assembly for pulse):
- If `METACOGNITION_ENABLED` and pulse type is reflective:
  - Run `run_metacognition()` — observer collects signals, bridge manager evaluates existing bridges and enriches blind spot data
  - Build the metacognition section (guidance blocks + raw data)
  - Pass to `get_reflective_pulse_prompt()` which appends it after the existing reflection sections
  - Opus uses the three tools during the tool-call loop to produce bridges, meta-observations, and self-model update

### 8b: Prompt builder registration

In `create_default_builder()`:
```python
if getattr(config, 'METACOGNITION_ENABLED', True):
    from prompt_builder.sources.memory_self_model import MemorySelfModelSource
    sources.append(MemorySelfModelSource())
```

---

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `core/database.py` | Modify | Schema v22 migration, bridge columns on memories |
| `agency/metacognition/__init__.py` | New | Package init |
| `agency/metacognition/observer.py` | New | MemoryObserver adapted for server (from `memory_observer.py`) |
| `agency/metacognition/bridge_manager.py` | New | BridgeManager class |
| `prompt_builder/sources/memory_self_model.py` | New | MemorySelfModelSource (P10, cached, bare text) |
| `agency/tools/definitions.py` | Modify | Three new pulse-only tool definitions |
| `agency/tools/executor.py` | Modify | Three new handler methods |
| `agency/system_pulse.py` | Modify | Three guidance blocks, extended reflection prompt, metacognition runner |
| `prompt_builder/builder.py` | Modify | Register MemorySelfModelSource |
| `config.py` | Modify | Metacognition config flags |

## Implementation Order

1. Schema migration (Step 1) — foundation, everything depends on this
2. MemoryObserver integration (Step 2) — adapt existing code, add ID returns, filter active bridges
3. BridgeManager (Step 3) — bridge evaluation, blind spot enrichment, bridge storage
4. Config additions (Step 7) — needed before wiring
5. Tool definitions and executor handlers (Step 6) — needed before pulse extension
6. Memory Self-Model ContextSource (Step 4) — independent, can parallel with tools
7. Guidance blocks and reflection pulse extension (Step 5) — ties everything to the pulse
8. Wire together (Step 8) — final integration

## Key Design Decisions

1. **One persistent output**: Only the self-model persists as an every-turn injection. Signal reports and blind spot data are working material consumed during reflection, not stored artifacts.

2. **Observer does all query work**: The BridgeManager consumes the observer's output. It does not re-query the memories table for blind spot candidates.

3. **Blind spots capped at 5**: The observer returns 5 candidates maximum. These are the actual targets — no separate "representatives" abstraction.

4. **Active bridges filtered from blind spots**: The observer's blind spot query excludes memories with `bridge_status = 'active'`, preventing redundant bridge attempts.

5. **Bare text injection**: The self-model uses bare text with a `[Memory Self-Awareness]` header, matching core memory's convention at P10. No XML tags.

6. **Bridge guidance is conditional**: Only included when blind spot targets are present. Self-model and meta-observation guidance are always included during metacognition-enabled reflections.

7. **Observe, never direct**: The self-model contains only observations about the memory landscape's shape. No directives, suggestions, or behavioral prescriptions. The reasoning model has conversational context that the reflection pass lacks — it decides what matters.
