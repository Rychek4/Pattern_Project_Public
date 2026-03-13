# Audit & Testing Plan: Memory Pipeline Data Integrity

## Context

This plan covers bugs and risks identified through codebase audit, focused on
what matters for a single-user research project: **silent data corruption in the
memory pipeline**. Deployment hardening, security, and multi-user concerns are
excluded.

Each section describes the bug, where it is, how to fix it, and how to test it.

---

## PHASE 1: Fix Confirmed Bugs (Week 1)

### Bug 1: Extraction Deadlock on Empty Results

**Location:** `memory/extractor.py:734-749`

**The problem:** When `_extract_unified()` returns memories but ALL are below
`importance_floor`, or `add_memory()` fails for all of them (e.g., embedding
issue), `total_memories == 0`. The code intentionally does NOT mark turns as
processed (line 736-749). The comment says "manual intervention required."

But there's no mechanism for manual intervention. Next conversation turn hits 40
unprocessed turns again, triggers extraction on the same turns, gets the same
result, and the system loops forever. Context window grows unbounded. No alarm
fires — just a warning in the log.

This can also trigger if the LLM returns an unparseable response from
`_extract_unified()` (returns empty lists).

**The fix:** After N consecutive failures on the same turns (e.g., 3 attempts),
mark them as processed anyway and log an error. The alternative — stalling
forever — is worse than losing a few memories. Add a counter to track
consecutive empty extractions.

**How to test:**

```
test_extraction_deadlock_recovery:
  1. Set up: Create 40+ unprocessed turns in test DB
  2. Mock _extract_unified() to return empty lists
  3. Call extract_memories() 3 times
  4. Assert: After max retries, turns ARE marked processed
  5. Assert: A clear error is logged (not just warning)
  6. Assert: Subsequent extraction cycles work normally on NEW turns

test_extraction_below_importance_floor:
  1. Set up: Create 40+ unprocessed turns
  2. Mock _extract_unified() to return memories all with importance 0.1
     (below IMPORTANCE_FLOOR of 0.3)
  3. Call extract_memories()
  4. Assert: Same deadlock recovery behavior as above

test_extraction_add_memory_failure:
  1. Set up: Create 40+ unprocessed turns
  2. Mock _extract_unified() to return valid memories
  3. Mock vector_store.add_memory() to return None (embedding failure)
  4. Call extract_memories()
  5. Assert: Same deadlock recovery behavior

test_extraction_normal_path_unaffected:
  1. Set up: Create 40+ unprocessed turns
  2. Mock _extract_unified() to return valid memories above floor
  3. Mock add_memory() to return memory IDs
  4. Assert: Turns marked processed on first try (no retry needed)
```

---

### Bug 2: Extraction Race Condition (TOCTOU)

**Location:** `memory/extractor.py:440-454`

**The problem:** `check_and_extract()` checks `_extraction_in_progress.is_set()`
at line 440, then checks again at line 451, then sets at line 454. Between
the check at 451 and the set at 454, another thread can pass the same check.
Both threads then call `.set()` and both spawn extraction threads.

With single-user load this is unlikely but not impossible — a system pulse and a
regular conversation turn can both call `check_and_extract()` near-simultaneously.

**The fix:** Replace the event-flag check-then-set with an atomic operation.
Use a `threading.Lock` to make the check-and-set atomic, or use
`_extraction_in_progress` as a Lock instead of an Event:

```python
# Replace Event with Lock (non-blocking acquire)
if not self._extraction_lock.acquire(blocking=False):
    log_info("Extraction already in progress, skipping")
    return
# ... spawn thread, release lock in finally block of _run_extraction
```

**How to test:**

```
test_concurrent_extraction_prevented:
  1. Set up: Create 40+ unprocessed turns
  2. Spawn 5 threads, each calling check_and_extract() simultaneously
  3. Assert: Exactly ONE extraction thread was started
  4. Assert: Other threads logged "already in progress" or equivalent
  5. Assert: No duplicate memories in vector store

test_extraction_lock_released_on_error:
  1. Mock extract_memories() to raise an exception
  2. Call check_and_extract()
  3. Assert: Lock/flag is cleared after error
  4. Call check_and_extract() again
  5. Assert: Extraction can proceed (lock isn't stuck)

test_extraction_lock_released_on_success:
  1. Run a successful extraction
  2. Assert: Lock/flag is cleared
  3. Assert: Next extraction can proceed
```

---

### Bug 3: Memory Access Recording Silently Swallowed

**Location:** `memory/vector_store.py:447-448`

**The problem:** `_record_access()` catches all exceptions and logs an error but
doesn't propagate. If the UPDATE fails (e.g., DB locked beyond timeout),
`access_count` and `last_accessed_at` are silently wrong. These fields feed into
freshness scoring, so memories that Isaac frequently uses may still appear
"dormant" and decay inappropriately.

**The fix:** This is a judgment call. The current behavior prevents a secondary
failure from crashing a primary operation (memory search). The fix should:
- Log at ERROR level (already does)
- Add a metric/counter for access recording failures
- If failures exceed a threshold in a session, log a prominent warning

For testing purposes, the important thing is verifying that access recording
WORKS under normal conditions and that failures don't cascade.

**How to test:**

```
test_access_count_increments:
  1. Add a memory to the store
  2. Search for it (triggering retrieval)
  3. Assert: access_count == 1, last_accessed_at updated
  4. Search again
  5. Assert: access_count == 2

test_access_recording_failure_doesnt_crash_search:
  1. Add a memory
  2. Mock the UPDATE in _record_access to raise sqlite3.OperationalError
  3. Perform a search
  4. Assert: Search still returns results (didn't crash)
  5. Assert: Error was logged
```

---

### Bug 4: Embedding Deserialization Without Validation

**Location:** `memory_observer.py:119-122`

**The problem:** `np.frombuffer(blob, dtype=np.float32)` creates an array from
raw bytes with no validation that the result has the expected embedding dimension
(384 for all-MiniLM-L6-v2). If a blob is corrupted (truncated write, disk
error), the array will have a wrong shape. Downstream cosine similarity
computations will either crash or produce nonsense scores silently.

**The fix:** Validate the shape after deserialization:

```python
def _deserialize_embedding(self, blob: bytes) -> Optional[np.ndarray]:
    if not blob:
        return None
    arr = np.frombuffer(blob, dtype=np.float32)
    if self._embedding_dim and len(arr) != self._embedding_dim:
        log_error(f"Corrupted embedding: expected {self._embedding_dim}, got {len(arr)}")
        return None
    return arr
```

**How to test:**

```
test_valid_embedding_deserializes:
  1. Create a valid 384-dim float32 embedding, serialize to bytes
  2. Call _deserialize_embedding()
  3. Assert: Returns correct array with shape (384,)

test_corrupted_embedding_returns_none:
  1. Create a truncated blob (e.g., 100 bytes instead of 1536)
  2. Call _deserialize_embedding()
  3. Assert: Returns None
  4. Assert: Error logged

test_empty_blob_returns_none:
  1. Call _deserialize_embedding(b"")
  2. Assert: Returns None (no error)

test_corrupted_embedding_excluded_from_signals:
  1. Insert a memory with corrupted embedding into test DB
  2. Run signal detection
  3. Assert: Corrupted memory is skipped, not included in signal report
  4. Assert: Other valid memories still produce signals
```

---

## PHASE 2: Targeted Memory Pipeline Tests (Week 2)

These aren't bug fixes — they're tests for critical paths that currently have
zero coverage. The goal is to catch future regressions before they corrupt data.

### Test Suite: Extraction Pipeline End-to-End

```
test_windowed_extraction_basic:
  1. Insert 40 turns (triggering overflow at 40, window size 30)
  2. Run extraction with mocked LLM (returns known episodic + factual)
  3. Assert: 10 oldest turns marked processed
  4. Assert: 30 newest turns remain unprocessed
  5. Assert: Memories created in vector store with correct metadata

test_extraction_preserves_context_window:
  1. Insert 50 turns
  2. Run extraction
  3. Assert: Exactly 20 turns extracted (50 - 30)
  4. Assert: 30 newest turns still in context

test_factual_dedup_refreshes_existing:
  1. Add a factual memory: "User's favorite color is blue" (importance 0.5)
  2. Extract turns containing "User's favorite color is blue" (importance 0.8)
  3. Assert: No new memory created (dedup triggered)
  4. Assert: Existing memory's importance is now 0.8 (MAX of 0.5, 0.8)
  5. Assert: Existing memory's source_timestamp is updated

test_factual_dedup_below_threshold_creates_new:
  1. Add factual memory: "User likes Python"
  2. Extract turns with semantically different fact: "User owns a cat"
  3. Assert: New memory created (below similarity threshold)

test_importance_floor_filtering:
  1. Mock LLM to return 3 episodic memories:
     importance 0.8, 0.2, 0.6
  2. Run extraction (floor = 0.3)
  3. Assert: 2 memories created (0.2 was filtered)
  4. Assert: Turns still marked processed (not deadlocked)

test_extraction_with_embedding_model_down:
  1. Set is_model_loaded() to return False
  2. Call extract_memories()
  3. Assert: Returns 0, logs error
  4. Assert: Turns NOT marked processed (correct — we want retry when model loads)
```

### Test Suite: Vector Store Search & Scoring

```
test_semantic_search_returns_relevant:
  1. Add 3 memories: "cats", "dogs", "quantum physics"
  2. Search for "feline pets"
  3. Assert: "cats" memory ranked highest

test_freshness_decay_standard:
  1. Add memory with source_timestamp = 30 days ago, decay_category = "standard"
  2. Compute freshness
  3. Assert: Score ≈ 0.5 (30-day half-life)

test_freshness_decay_permanent:
  1. Add memory with decay_category = "permanent"
  2. Set source_timestamp to 365 days ago
  3. Assert: Freshness == 1.0 (no decay)

test_freshness_decay_ephemeral:
  1. Add memory with decay_category = "ephemeral", source_timestamp = 7 days ago
  2. Assert: Score ≈ 0.5 (7-day half-life)

test_combined_scoring_weights:
  1. Add memory with known similarity, importance, freshness
  2. Search and capture combined_score
  3. Assert: Score matches formula (0.6 * similarity + 0.25 * importance + 0.15 * freshness)
```

### Test Suite: Conversation Manager

```
test_add_turn_and_retrieve:
  1. Add user turn, assistant turn
  2. Call get_api_messages()
  3. Assert: Returns both turns with correct roles and content

test_message_merging_consecutive_same_role:
  1. Insert: user, assistant, assistant (simulating filtered system turn between)
  2. Call get_api_messages()
  3. Assert: Two assistant messages merged into one
  4. Assert: Content concatenated with \n\n separator

test_first_message_must_be_user:
  1. Insert: assistant, user, assistant
  2. Call get_api_messages()
  3. Assert: First assistant message dropped, starts with user

test_unprocessed_count_accuracy:
  1. Add 10 turns
  2. Mark 3 as processed
  3. Assert: get_unprocessed_count() == 7

test_mark_processed_idempotent:
  1. Add 5 turns, mark all processed
  2. Mark same turns processed again
  3. Assert: No error, count still 0
```

### Test Suite: Warmth Cache

```
test_warmth_cache_decay:
  1. Set retrieval warmth for memory ID 1
  2. Call decay_all() 10 times
  3. Assert: Entry removed from cache (below 0.01 threshold)

test_warmth_cache_retrieval_resets:
  1. Set retrieval warmth, decay 3 times
  2. Set retrieval warmth again (re-retrieved)
  3. Assert: Warmth back to initial value (not accumulated)

test_warmth_cap_enforced:
  1. Set both retrieval and topic warmth to maximum values
  2. Assert: combined <= WARMTH_CAP

test_warmth_cache_size_bounded_over_session:
  1. Simulate 100 turns, each retrieving 5 different memories
  2. Call decay_all() between each turn
  3. Assert: Cache size stays bounded (not growing linearly with turn count)
  4. Record max cache size — should plateau, not grow without bound
```

---

## PHASE 3: Audit Silent Exception Handlers (Week 3)

Not every `except: pass` is a bug. But each one should be a conscious decision.
This phase is about reviewing all 50+ broad exception handlers and categorizing
them.

### Methodology

For each `except Exception` or `except: pass` in the codebase:

1. **Is it swallowing a real failure?** Would the caller want to know?
2. **Is logging sufficient?** ERROR vs WARNING vs nothing
3. **Can the except be narrowed?** e.g., `except sqlite3.OperationalError`
   instead of `except Exception`

### Priority locations to audit (highest risk first):

| File | Line | Current Behavior | Risk |
|------|------|-----------------|------|
| `memory/extractor.py:520` | `except Exception: pass` | Clear injected images fails silently | Low — cosmetic |
| `interface/web_server.py:784` | `except Exception: pass` | Async poll error swallowed | Medium — hides connection issues |
| `agency/commands/handlers/intention_handler.py:100` | `except Exception: pass` | Session lookup suppressed | Low — graceful fallback |
| `agency/commands/handlers/active_thoughts_handler.py:119-124` | Two `pass` blocks | Dev window update fails silently | Low — debug feature |
| `subprocess_mgmt/manager.py:199` | Returns False | Network error = unhealthy | Medium — misleading health status |
| `core/round_recorder.py:421-428` | Deep copy fallback | No warning logged | Low — defensive copy |
| `memory/vector_store.py:447-448` | `log_error` but swallows | Access recording lost | Medium — freshness scoring affected |

### How to test the audit:

For each handler you decide to change:

```
test_<location>_logs_on_failure:
  1. Trigger the exception path
  2. Assert: Appropriate log level (ERROR for data-affecting, WARNING for cosmetic)
  3. Assert: Exception message captured (not just "pass")

test_<location>_doesnt_crash_caller:
  1. Trigger the exception path
  2. Assert: Calling function completes normally (graceful degradation preserved)
```

---

## PHASE 4: Evaluate Feature Complexity (Weeks 3-4)

This isn't about bugs — it's about whether complexity is earning its keep.
No tests to write here; this is observational.

### Questions to answer through production observation:

**Prompt sources (15 registered):** For each source, check:
- Does it consistently produce non-empty content?
- Does Isaac's behavior measurably improve with it vs without it?
- Priority candidates for removal/consolidation:
  - `pattern_breaker.py` — Is it actually breaking patterns, or adding noise?
  - `self_correction.py` — Is self-correction happening? How often?
  - `response_scope.py` — Is this shaping responses or just burning tokens?
  - `tool_stance.py` — Could this be folded into the base system prompt?

**Metacognition system:** Monitor for 2-3 weeks:
- Are bridge connections producing genuine insight or mostly noise?
- Is the token cost (3 LLM calls per reflective pulse) justified?
- Track the O(N^2) bridge query performance as bridges accumulate

**Curiosity engine:** Is it surfacing things you find genuinely interesting,
or generating busywork? Check the curiosity log over a few weeks.

---

## Test Infrastructure Setup

### Recommended structure:

```
tests/
├── conftest.py              # Shared fixtures (test DB, mock LLM, etc.)
├── test_extraction.py       # Phase 1 Bug 1 + Phase 2 extraction tests
├── test_extraction_race.py  # Phase 1 Bug 2
├── test_vector_store.py     # Phase 1 Bug 3 + Phase 2 scoring tests
├── test_memory_observer.py  # Phase 1 Bug 4
├── test_conversation.py     # Phase 2 conversation tests
├── test_warmth_cache.py     # Phase 2 warmth tests
```

### Key fixtures needed in conftest.py:

```python
@pytest.fixture
def test_db(tmp_path):
    """Fresh SQLite database with schema applied, no production data."""
    # Create DB at tmp_path / "test.db"
    # Apply all migrations
    # Yield database instance
    # Cleanup automatic via tmp_path

@pytest.fixture
def mock_llm():
    """Mock LLM router that returns predetermined extraction results."""
    # Returns configurable episodic/factual memories
    # Tracks call count for verification

@pytest.fixture
def vector_store(test_db):
    """VectorStore instance backed by test DB."""
    # Pre-load embedding model (or mock it for unit tests)

@pytest.fixture
def extractor(test_db, mock_llm):
    """MemoryExtractor with mocked LLM and test DB."""

@pytest.fixture
def conversation_mgr(test_db):
    """ConversationManager backed by test DB."""

@pytest.fixture
def populated_turns(conversation_mgr):
    """Insert 45 turns into test DB (enough to trigger extraction)."""
    # Returns list of turn IDs for assertion
```

### Mocking strategy:

The main challenge is that many components use module-level singletons
(e.g., `get_conversation_manager()`, `get_vector_store()`). Tests should:

1. **Patch the singletons** using `unittest.mock.patch` to inject test instances
2. **Use a real test DB** (not mocking SQLite — test the actual queries)
3. **Mock only the LLM** — extraction parsing and storage should use real code
4. **Mock embeddings conditionally** — if embedding model is available, use it;
   otherwise mock with random 384-dim vectors for structural tests

### Running:

```bash
# From project root
python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_extraction.py -v

# Single test
python -m pytest tests/test_extraction.py::test_extraction_deadlock_recovery -v
```

---

## Summary: What This Plan Produces

| Phase | Output | Protects Against |
|-------|--------|-----------------|
| 1 | 4 bug fixes | Active data corruption, silent stalls |
| 2 | ~25 targeted tests | Future regressions in memory pipeline |
| 3 | Audited exception handlers | Hidden failures |
| 4 | Feature evaluation data | Unnecessary complexity and token waste |

The plan is deliberately scoped to the memory pipeline because that's the
irreplaceable data layer. Other subsystems (communication gateways, web UI,
blog) are recoverable — memories are not.
