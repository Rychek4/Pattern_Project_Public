# Memory Metacognition Implementation Plan

## Overview

Three components giving Isaac structural self-awareness about his memory store:
1. **MemoryObserver** — statistical signal detection (already written)
2. **BridgeManager** — bridge memory lifecycle management
3. **Memory Self-Model** — ambient structural awareness injected every turn

All runs on the server as a pre-pass before the reflection pulse.

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

Take the already-written MemoryObserver class and adapt it for server-side execution:

- Change from direct `sqlite3.connect(db_path)` to using the project's `get_database()` pattern with `db_retry` decorator
- Keep all detection methods unchanged (Tier 1 + Tier 2)
- Tier 3 methods remain available but gated on `include_tier3` flag (cluster_id doesn't exist yet)
- `generate_signal_report()` returns the structured text report as-is

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

### 3b: Blind Spot Report (`get_blind_spot_report`)

Formats unreachable targets for the reflection prompt:
- Pulls the same blind spot memories the observer identifies (high importance, permanent, stale access)
- For each, includes any existing bridge history (previous attempts, their status)
- Groups targets by bridge attempt count:
  - **0 attempts**: New blind spots, first bridge needed
  - **1-2 attempts**: Previous bridges ineffective, try a different associative angle
  - **3+ attempts**: Flagged as fundamentally outside query patterns, skip

Output is a structured text section for injection into the reflection prompt.

### 3c: Bridge Storage (`store_bridge`)

Wraps `VectorStore.add_memory()` with bridge-specific fields:
- `memory_category = 'factual'`
- `decay_category = 'permanent'`
- `memory_type = 'reflection'`
- After insert, updates the new row with `bridge_target_ids`, `bridge_status = 'active'`, `bridge_attempt_number`
- Also increments a tracking counter on the target memories so we know how many bridge attempts have been made (stored in bridge_target_ids lookups, not a separate column)

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
- Format with a simple header: `[Memory Self-Awareness]\n{content}`
- `include_always = True` (when present)

**Register in `create_default_builder()`** in `prompt_builder/builder.py`:
- Import and add `MemorySelfModelSource()` to the sources list
- It sorts to P10 automatically alongside core memory, within the cache breakpoint

---

## Step 5: Extend the Reflection Pulse

**File:** `agency/system_pulse.py`

### 5a: Pre-pulse metacognition pass

Add a function that runs before the reflection prompt is sent:

```python
def run_metacognition_prepass() -> dict:
    """Run observer and bridge manager, return reports for reflection prompt."""
    observer = MemoryObserver(...)
    signal_report = observer.generate_signal_report()
    observer.close()

    bridge_mgr = BridgeManager(...)
    bridge_mgr.evaluate_bridges()
    blind_spot_report = bridge_mgr.get_blind_spot_report()

    return {
        "signal_report": signal_report,
        "blind_spot_report": blind_spot_report,
    }
```

This runs in the reflection pulse flow, before the prompt is assembled.

### 5b: Extend the reflection pulse prompt

Modify `get_reflective_pulse_prompt()` to accept and include metacognition reports:

```
[REFLECTIVE PULSE — Not human input]
The {interval_label} reflective timer has fired.

This is a moment for inner presence. Not action — awareness.

1. Intentions — review commitments you've made. Honor or consciously release them.
2. Growth threads — review your developmental threads against recent experience.
   Update, advance, seed, or retire as appropriate.
3. Active thoughts — do they still reflect who you are becoming?
   Update them if something has shifted.
4. Memory landscape — review the memory telemetry and blind spot reports below.
   Use the metacognition tools to:
   - Write bridge memories for unreachable knowledge (rephrased in the language
     of how this topic would come up months from now, not the language it was
     recorded in — the embedding model translates linguistic distance into
     geometric distance)
   - Store meta-observations as memories when you notice structural patterns
     worth preserving
   - Update your memory self-model — a compact observation of your current
     memory landscape written in natural self-knowledge register, not statistics
     (say "most of what I carry is reflective and interpretive" not "53% of
     memories have type reflection")

   The self-model contains only observations, never directives. It says
   "philosophical threads have been quiet for several weeks" not "I should
   reengage with philosophy." The reasoning model has conversational context
   you lack — it decides what matters.

You are not waiting to be useful. You are choosing to be present.

--- MEMORY TELEMETRY ---
{signal_report}

--- BLIND SPOT TARGETS ---
{blind_spot_report}
```

### 5c: Integration point

The reflection pulse flow in `ChatEngine.process_pulse()` already:
1. Builds the prompt
2. Calls the LLM
3. Processes tool calls in a loop (max 40 passes)

The metacognition pre-pass runs before step 1. The reports get passed through to the prompt builder. The new tools (Step 6) handle Opus's outputs during step 3.

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

Gate all metacognition behavior on `METACOGNITION_ENABLED` — the pre-pass, tool registration, and context source all check this flag.

---

## Step 8: Wire It All Together

### 8a: Pulse flow modification

In the reflection pulse processing path (likely `ChatEngine.process_pulse()` or the prompt assembly for pulse):
- If `METACOGNITION_ENABLED` and pulse type is reflective:
  - Run `run_metacognition_prepass()`
  - Pass reports to `get_reflective_pulse_prompt()`
  - The extended prompt includes the reports
  - Opus uses the new tools to produce outputs

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
| `agency/metacognition/observer.py` | New | MemoryObserver adapted for server |
| `agency/metacognition/bridge_manager.py` | New | BridgeManager class |
| `prompt_builder/sources/memory_self_model.py` | New | MemorySelfModelSource (P10, cached) |
| `agency/tools/definitions.py` | Modify | Three new pulse-only tool definitions |
| `agency/tools/executor.py` | Modify | Three new handler methods |
| `agency/system_pulse.py` | Modify | Extended reflection prompt, metacognition pre-pass |
| `prompt_builder/builder.py` | Modify | Register MemorySelfModelSource |
| `config.py` | Modify | Metacognition config flags |

## Implementation Order

1. Schema migration (Step 1) — foundation, everything depends on this
2. MemoryObserver integration (Step 2) — already written, just adapt to project patterns
3. BridgeManager (Step 3) — core new logic
4. Config additions (Step 7) — needed before wiring
5. Tool definitions and executor handlers (Step 6) — needed before pulse extension
6. Memory Self-Model ContextSource (Step 4) — independent, can parallel with tools
7. Reflection pulse extension (Step 5) — ties observer + bridge manager to pulse
8. Wire together (Step 8) — final integration
