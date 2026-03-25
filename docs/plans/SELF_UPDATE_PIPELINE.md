# Self-Authoring Pipeline: Claude Code CLI Integration

## Overview

This plan adds the ability for Isaac to propose changes to his own codebase
through a structured self-authoring workflow. The pipeline has three phases:
impulse examination, design negotiation (multi-turn), and adversarial
evaluation. Changes are created on isolated git branches and require human
approval before merging.

**Design Philosophy**: This is the only tool in Isaac's architecture where the
expected outcome includes not producing output. Every other tool succeeds by
generating something. This tool sometimes succeeds by generating nothing — by
recognizing that the work it just did shouldn't exist.

**Core Principle — Frame Before Fix**: The tool exists to prevent Isaac from
becoming an automated patcher. Without structured judgment, an agent with
code-editing capability will default to the training distribution: here's a
system, here's a problem, write code that handles the problem. The most powerful
code change is often deletion — removal of the thing that made the code
necessary in the first place.

**Scope**: New tool (`self_author`), new module (`agency/self_update/`), new
database table (`self_authoring_sessions`), config additions, and registration
in the existing tool/executor system.

**What this does NOT do**: Auto-merge, auto-deploy, or modify Guardian. The
human gate is non-negotiable in this first iteration.

---

## The Two Valid Outcomes (Plus a Third)

Every invocation of this tool produces one of three outcomes, and all are
successes:

1. **"This accomplishes the task I meant to solve for."** — The frame was
   correct. Implementation follows cleanly. A branch is created for review.

2. **"This changes the frame such that the task no longer matters, is not
   achievable, or we need to solve for a different task entirely."** — The frame
   was wrong. Discovery of that fact before writing code is the most valuable
   outcome possible.

3. **"The problem space is too ambiguous for autonomous resolution."** — The
   system has attempted multiple frames and none have converged. The task
   requires context, judgment, or domain knowledge that the system cannot
   acquire through further autonomous exploration. This is an escalation to the
   human operator — a boundary recognition, not a failure.

**"Think Outside the Room"**: "Think outside the box" finds a better solution
within the same problem space. "Think outside the room" questions whether you're
in the right problem space at all. This tool's architecture is designed to
create structural opportunities for "room-level" reframes at every phase.

---

## Architecture Overview

The tool has three phases. Phase 2 contains a multi-turn sub-workflow. All
phases use Opus.

```
Phase 1: Examine the Impulse
    ↓
Phase 2a: Design Negotiation (Isaac ↔ Claude Code, multi-turn)
    ↓
    Fork A: Converged plan → Phase 2b
    Fork B: Frame invalidated → Return to Phase 1 with new information
    ↓
Phase 2b: Complexity Gate
    ↓
    Pass: Complexity proportional to prediction → Phase 2c
    Fail: Complexity disproportionate → Return to Phase 1
    ↓
Phase 2c: Implementation
    ↓
    Clean: Proceed to Phase 3
    Messy: Return to Phase 2a (not "fix it" — restart the design conversation)
    ↓
Phase 3: Adversarial Evaluation
    ↓
    Approve: Commit
    Veto: Return to Phase 1 with the failure as new input

Hard cap: 3 full cycles. After 3 cycles without convergence → Outcome 3.
```

---

## Architecture Decision Record

**Why `subprocess.run()` (blocking) instead of async/SubprocessManager?**

The SubprocessManager (`subprocess_mgmt/manager.py`) is designed for long-lived
child processes with health endpoints (HTTP health checks, PID monitoring,
auto-restart). Claude Code CLI is a short-lived, single-shot process — it runs,
produces output, and exits. `subprocess.run()` with a timeout is the right tool.

Isaac's ChatEngine processes messages synchronously on a single thread. During a
self-authoring session, Isaac is blocked. This is acceptable because:
- Self-authoring is triggered during action pulses, not user conversations
- The pulse system already pauses timers during processing
- A blocked pulse simply delays the next one
- Token limits will be hit before any practical time concern arises
- Blocking windows under 6 hours are acceptable

**Why post-hoc diff checking instead of pre-constraining Claude Code?**

Claude Code CLI's `--allowedTools` flag can restrict tool access, but it cannot
restrict which *files* a tool operates on. The only reliable way to enforce
protected paths is to let Claude Code run, then inspect the git diff afterward.
If violations are found, the branch is deleted and Isaac gets an error result.

**Why action pulse only (initially)?**

The action pulse (`agency/system_pulse.py` lines 317-340) is Isaac's open-ended
agency window — browser, Telegram, blog, Reddit. Code changes fit this pattern.
Reflective pulses are for introspection and metacognition, not action. Regular
conversation should not trigger code changes because the human is present and
can make changes themselves.

**Why multi-turn design negotiation (Phase 2a)?**

A single-shot brief would never reveal that the frame is wrong. The
back-and-forth is the mechanism that allows the frame to be challenged before
code exists. Isaac has the *why*. Claude Code has the *what's actually in the
repo*. The 2a conversation is where those two perspectives merge — or where
their incompatibility reveals a frame error.

**Why `--continue` for multi-turn CLI sessions?**

Claude Code CLI supports `--continue` (`-c`) to resume the most recent session
in the working directory, preserving full message history and codebase context.
This means each round of 2a negotiation retains all prior file reads, greps,
and research from previous rounds — no redundant codebase exploration.

---

## Database Schema

### New Table: `self_authoring_sessions`

Stores the full iteration history for each self-authoring invocation. One row
per phase execution within a session, providing a complete audit trail and raw
material for reflective pulse pattern detection.

```sql
CREATE TABLE IF NOT EXISTS self_authoring_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Session identity
    session_key TEXT NOT NULL,          -- Unique key per invocation (e.g. "sa-{timestamp}")
    cycle_number INTEGER NOT NULL,      -- Which iteration cycle (1, 2, or 3)
    phase TEXT NOT NULL CHECK (phase IN (
        'phase_1', 'phase_2a', 'phase_2b', 'phase_2c', 'phase_3'
    )),

    -- Phase 1 artifacts
    original_impulse TEXT,              -- What Isaac thought the problem was
    rationale TEXT,                      -- Full Phase 1 reasoning
    complexity_prediction JSON,         -- {"files": N, "lines_net": N, "conditionals": N, "dependencies": N, "rating": "low|medium|high"}

    -- Phase 2a artifacts
    negotiation_rounds INTEGER,         -- How many rounds of back-and-forth
    negotiation_summary TEXT,           -- Compressed summary of the 2a conversation
    fork_outcome TEXT CHECK (fork_outcome IN ('converged', 'invalidated')),
    plan_description TEXT,              -- The agreed plan (if converged)

    -- Phase 2b artifacts
    complexity_actual JSON,             -- Same shape as complexity_prediction
    gate_passed BOOLEAN,

    -- Phase 2c artifacts
    branch_name TEXT,                   -- isaac/{suffix}
    implementation_clean BOOLEAN,       -- Did 2c go smoothly?

    -- Phase 3 artifacts
    argument_against TEXT,              -- Mandatory rejection case
    argument_for TEXT,                  -- Acceptance case
    complexity_comparison JSON,         -- {"predicted": {...}, "actual": {...}, "gap_assessment": "..."}
    phase_3_decision TEXT CHECK (phase_3_decision IN ('approve', 'veto')),

    -- Iteration tracking
    delta_from_previous TEXT,           -- What structurally changed since last cycle
    return_reason TEXT,                 -- Why we returned to Phase 1 (if applicable)

    -- Final outcome (set on the last row of the session)
    final_outcome TEXT CHECK (final_outcome IN (
        'committed',                    -- Outcome 1: branch ready for review
        'frame_dissolved',              -- Outcome 2: task no longer matters
        'escalated'                     -- Outcome 3: needs human help
    )),

    -- Metadata
    total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_self_authoring_session_key
    ON self_authoring_sessions(session_key);
CREATE INDEX IF NOT EXISTS idx_self_authoring_outcome
    ON self_authoring_sessions(final_outcome);
CREATE INDEX IF NOT EXISTS idx_self_authoring_created
    ON self_authoring_sessions(created_at);
```

**Why one table, not multiple?** The phases are sequential within a session and
share context. A single table with nullable columns per phase keeps queries
simple — "show me all sessions where Phase 3 vetoed" is one WHERE clause, not a
JOIN across three tables. The tradeoff is nullable columns, but the phase CHECK
constraint makes it clear which columns are relevant per row.

**Why store negotiation summary, not full transcripts?** The full 2a transcript
lives in Claude Code's session history (accessible via `--resume`). Storing a
compressed summary in the database is sufficient for reflective pulse pattern
detection ("Isaac has written three rationales about workarounds for the same
subsystem") without bloating the table with multi-turn conversation logs.

**Growth thread integration**: Over time, accumulated Phase 1 rationale
artifacts allow the reflective pulse to detect patterns. A query like
`SELECT rationale, return_reason FROM self_authoring_sessions WHERE
final_outcome = 'frame_dissolved' ORDER BY created_at DESC LIMIT 10` surfaces
recurring frame errors that point to systemic issues.

---

## Phase Specifications

### Phase 1: Examine the Impulse

**Model**: Opus (Isaac's own model, via Anthropic API)
**Purpose**: Surface why Isaac thinks code needs to change, before any
implementation begins.
**Output**: A stored rationale artifact (written to `self_authoring_sessions`).

**What Phase 1 Must Answer**:
- What is the problem I'm actually solving?
- What am I observing that triggered this?
- Am I patching a symptom or addressing a cause?
- Have I seen this kind of problem before, and if so, what happened?
- Is the complexity of what I'm about to do proportional to the value it delivers?
- If I'm adding a special case handler — does the edge case exist because
  something upstream is framed wrong?

**Complexity Prediction**: Phase 1 must produce a concrete prediction:
- Estimated files touched
- Estimated lines added/removed (net)
- Estimated new conditionals or special cases
- Estimated new dependencies
- Overall complexity rating: Low / Medium / High

If complexity is rated **High**, Phase 1 restarts immediately. High complexity
is not "this will take longer." High complexity is "I'm probably in the wrong
room." The frame needs rethinking before any downstream work begins.

**On re-entry** (after a return from Phase 2 or 3): Phase 1 is not starting
fresh — it carries the full record of what was attempted and why it failed.
Before producing a new rationale, the system must reason about the **delta** —
what specific new constraint, codebase reality, or structural understanding
distinguishes this attempt from the previous one. The absence of a meaningful
delta is itself a signal that iteration is not producing convergence.

**Implementation**: A call to `AnthropicClient.chat()` with a structured system
prompt. The prompt includes:
- Isaac's original impulse (the task description)
- If cycle > 1: all prior Phase 1 rationales, return reasons, and deltas
- Instructions to produce the rationale and complexity prediction as structured
  output

The response is parsed and stored in `self_authoring_sessions`.

---

### Phase 2a: Design Negotiation

**Model**: Opus (Isaac, via API) ↔ Claude Code (via CLI subprocess)
**Purpose**: Converge on a shared understanding through iterative clarification.
**Structure**: Multi-turn conversation, typically 3-5 rounds.

**Conversation Shape**:

Round 1:
- Isaac: Proposes the change with context and intent from Phase 1.
- Claude Code: Researches the codebase. Responds with grounded assessment of
  feasibility and approach.

Round 2:
- Isaac: Identifies where Claude Code's interpretation diverged from intent.
  Reframes or clarifies the goal.
- Claude Code: Re-evaluates against the codebase with corrected understanding.
  Proposes revised plan.

Round 3:
- Isaac: Refines the plan, adds constraints, adjusts scope based on what Claude
  Code revealed about the codebase.
- Claude Code: Produces final plan. Confirms readiness for implementation.

Additional rounds as needed, but excessive rounds (4+) are themselves a
complexity signal.

**Multi-turn mechanism**:
```
Round 1: claude -p "{isaac_prompt}" --model opus --max-turns 25 \
         --output-format json --allowedTools "{allowed_tools}"
Round 2+: claude --continue -p "{isaac_next_message}" --output-format json
```

Each round:
1. Claude Code runs as a subprocess and returns JSON output
2. Isaac (via `AnthropicClient.chat()`) evaluates the response with full
   conversation history
3. Isaac decides: converged (Fork A), invalidated (Fork B), or continue

**Fork A — Plan Convergence**: "This plan accomplishes the task I meant to solve
for." → Proceed to Phase 2b (Complexity Gate).

**Fork B — Frame Invalidation**: "This conversation has revealed that my Phase 1
framing was incorrect. The task needs to be redefined." → Return to Phase 1,
carrying everything 2a revealed about codebase reality.

**What Makes Fork B Happen**: Claude Code's grounded assessment contradicts
Isaac's assumptions:
- The module Isaac wanted to modify doesn't work the way he thought
- There's already a mechanism that handles this differently
- A dependency Isaac wanted to remove is load-bearing in a way he didn't realize
- The "edge case" Isaac wanted to handle is actually a symptom of a deeper
  structural issue that Claude Code can see in the codebase

Fork B is the more valuable outcome. It means the design negotiation did
something that Phase 1's pure reasoning couldn't — it reality-tested the frame
and found it wanting.

---

### Phase 2b: Complexity Gate

**Model**: Opus (Isaac, via API)
**Purpose**: Compare Claude Code's implementation plan against Phase 1's
predicted complexity.

**Assessment**: Opus evaluates the gap with full conversation context — the
Phase 1 prediction, the 2a plan, and all prior rounds. This is LLM-judged, not
threshold-based, because proportionality depends on the nature of the change.
The prompt must be specific and high-quality, providing the full conversation
history and asking Opus to reason about whether the plan's complexity is
proportional to what was predicted.

**Assessment Criteria**:
- Does the plan touch more files than Phase 1 predicted?
- Does the plan introduce more conditionals or special cases?
- Does the plan require new dependencies Phase 1 didn't anticipate?
- Is the estimated line count significantly higher than predicted?

**Gate Outcomes**:
- **Pass**: Complexity is proportional to prediction. Proceed to Phase 2c.
- **Fail**: Complexity is disproportionate. Return to **Phase 1** — not 2a. If
  the plan is complex, the problem framing is wrong. A new Phase 1 is needed,
  not a new plan within the same frame.

---

### Phase 2c: Implementation

**Model**: Claude Code (via CLI subprocess)
**Purpose**: Execute the agreed plan from 2a.

**Expected Behavior**: If 2a converged properly, implementation should be
straightforward. The plan was negotiated, the codebase was researched, both
sides agreed. Phase 2c is execution, not design.

**Mechanism**: Claude Code runs with `--continue` to preserve the full 2a
conversation context. The prompt instructs it to implement the agreed plan and
commit the result.

```
claude --continue -p "Implement the plan we agreed on. Commit your changes." \
    --output-format json
```

**Scope Creep Detection**: After implementation, compare the actual files
changed (via `git diff --name-only`) against the file list from the 2a plan. If
unexpected files were modified, that's a complexity signal — the 2a convergence
was incomplete.

**Failure Path**: If 2c goes sideways — messy implementation, unexpected
complications, cascading changes — do not fix the code. Return to **Phase 2a**.
Restart the design conversation with new information about why the plan didn't
survive contact with the code. Not "fix it." Restart.

---

### Phase 3: Adversarial Evaluation

**Model**: Opus (Isaac, via API)
**Purpose**: Evaluate whether the implementation validates or contradicts the
Phase 1 reasoning.
**Key principle**: Phase 3 must argue against the implementation before it's
allowed to argue for it.

**Structure**:

**Step 1 — Argue Against (Mandatory First)**: Generate the strongest case for
why this change is wrong, unnecessary, or overcomplicated. List every reason to
reject it. This must be generated *before* the acceptance case to prevent the
model from building a justification narrative first.

**Step 2 — Argue For**: Generate the case for why this change is correct and
valuable.

**Step 3 — Compare Predicted vs. Actual Complexity**:

| Metric | Phase 1 Prediction | Actual |
|--------|-------------------|--------|
| Files touched | N | N |
| Net lines (added - removed) | N | N |
| New conditionals/special cases | N | N |
| New dependencies | N | N |
| Refinement rounds needed | N | N |

The gap between predicted and actual is the primary decision signal.

**Step 4 — Decide**:
- **Approve**: The rejection argument is weak, the complexity gap is small, the
  implementation matches the reasoning. Commit.
- **Veto**: The rejection argument is strong, OR the complexity gap is large, OR
  the implementation shape contradicts the Phase 1 rationale. Throw it all away.

**On Veto**: A veto does not mean "try again with the same approach." A veto
means the entire chain — rationale, design, implementation — was built on a
frame that didn't hold. The failure feeds back into a new Phase 1, carrying:
- The original rationale (what Isaac thought the problem was)
- What the implementation revealed (what the problem actually was)
- The complexity gap (how far off the prediction was)
- The strongest argument from the rejection case

**The Sunk Cost Problem**: Everything in the training distribution fights
against Phase 3 doing its job. Structural countermeasures:
1. Argue against first — rejection case before acceptance case
2. Concrete metrics resist narrativizing — either a new conditional exists or
   it doesn't
3. Predicted vs. actual complexity is quantified — the discrepancy is a number,
   not a feeling

**Implementation**: A call to `AnthropicClient.chat()` with a structured prompt
that includes the Phase 1 rationale, 2a plan summary, the actual `git diff`,
and complexity metrics. The prompt enforces argue-against-first ordering.

---

## Iteration Awareness

### The Loop Problem

Every return path feeds back into Phase 1. Without structural awareness of its
own iteration history, the system can cycle: propose a frame, discover it's
wrong, propose a subtly different frame that fails for related reasons. Each
individual iteration looks productive — new rationale, new negotiation, new
discovery. But the sequence may be treading water.

### Delta as a Reasoning Requirement

Return paths are **stateful, not stateless**. When the system re-enters Phase 1
after a failure, it carries the full record from the `self_authoring_sessions`
table. Phase 1 must reason about the delta — what specific new constraint,
codebase reality, or structural understanding distinguishes this attempt from
the previous one.

The absence of a meaningful delta is itself a signal. If the new rationale is a
rephrasing rather than a reframing, iteration is not producing convergence.

### Hard Cap: 3 Full Cycles

After 3 complete cycles (Phase 1 → 2a → 2b → 2c → 3) without convergence, the
system halts and produces **Outcome 3**: escalation to the human operator. This
is not a failure — it is a boundary recognition. The system has identified that
it is operating at the edge of its competence and that continued iteration will
consume resources without producing convergence.

### What This Means for Autonomous Operation

- Outcome 1 demonstrates the ability to solve problems within a correct frame
- Outcome 2 demonstrates the ability to recognize and escape incorrect frames
- Outcome 3 demonstrates the ability to recognize the limits of its own
  frame-finding capacity

An agent capable of all three is qualitatively different from one capable of
only the first two. The willingness to halt is a competence, not an admission
of incompetence.

---

## File-by-File Implementation Plan

### New Files

#### 1. `agency/self_update/__init__.py`

Empty init file. Standard Python package marker.

#### 2. `agency/self_update/cli_runner.py`

**Purpose**: Subprocess wrapper around the `claude` CLI binary.

**Class**: `CLIRunner`

```
CLIRunner(
    repo_path: Path,          # PROJECT_ROOT from config.py
    model: str,               # e.g. "opus" — the model Claude Code uses internally
    max_turns: int,           # Cap on agentic tool-use loops (e.g. 25)
    timeout_seconds: int,     # Hard timeout on subprocess (e.g. 600)
    allowed_tools: str,       # --allowedTools value
    api_key: str              # SELF_UPDATE_API_KEY from config.py
)
```

**Method**: `execute(task: str, branch_name: str) -> CLIRunResult`

Steps:
1. Validate the `claude` binary exists (`shutil.which("claude")`)
2. Create and checkout a new branch: `git checkout -b {branch_name}`
   - Uses `subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo_path)`
   - If branch already exists, return error (don't overwrite)
3. Run Claude Code CLI:
   ```
   subprocess.run(
       [
           "claude",
           "-p", task,
           "--model", model,
           "--max-turns", str(max_turns),
           "--output-format", "json",
           "--allowedTools", allowed_tools,
       ],
       cwd=str(repo_path),
       capture_output=True,
       text=True,
       timeout=timeout_seconds,
       env={**os.environ, "ANTHROPIC_API_KEY": api_key}
   )
   ```
4. Parse JSON stdout into structured result
5. Checkout back to the original branch: `git checkout {original_branch}`
   - IMPORTANT: Must always return to the original branch, even on failure
   - Use try/finally to guarantee this
6. Return `CLIRunResult(stdout, stderr, exit_code, branch_name, original_branch)`

**Method**: `continue_session(message: str) -> CLIRunResult`

For Phase 2a multi-turn and Phase 2c implementation. Resumes the most recent
Claude Code session in the working directory:
```
subprocess.run(
    [
        "claude",
        "--continue",
        "-p", message,
        "--output-format", "json",
    ],
    cwd=str(repo_path),
    capture_output=True,
    text=True,
    timeout=timeout_seconds,
    env={**os.environ, "ANTHROPIC_API_KEY": api_key}
)
```

Note: `--continue` does not need `--model`, `--max-turns`, or `--allowedTools`
— these carry over from the initial session.

**Dataclass**: `CLIRunResult`
```python
@dataclass
class CLIRunResult:
    stdout: str
    stderr: str
    exit_code: int
    branch_name: str
    original_branch: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out
```

**Error handling**:
- `subprocess.TimeoutExpired`: Set `timed_out=True`, kill process, checkout
  back to original branch, delete the timed-out branch
- `FileNotFoundError` (claude binary not found): Return error result immediately
- `subprocess.CalledProcessError`: Capture stderr, return as error result
- All paths must guarantee checkout back to original branch via try/finally

**Critical detail — determining original branch**:
```python
original_branch = subprocess.run(
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    cwd=str(repo_path), capture_output=True, text=True
).stdout.strip()
```
This must be captured BEFORE creating the new branch.

**Critical detail — git state safety**:
Before creating a branch, verify working tree is clean:
```python
status = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=str(repo_path), capture_output=True, text=True
).stdout.strip()
if status:
    return error("Working tree has uncommitted changes, cannot proceed")
```

#### 3. `agency/self_update/protected_paths.py`

**Purpose**: Post-hoc diff inspection against a hardcoded protected paths list.

**Function**: `check_diff(repo_path: Path, base_branch: str, target_branch: str) -> Optional[str]`

Steps:
1. Run `git diff --name-only {base_branch}..{target_branch}` to get changed files
2. Compare each changed file against `PROTECTED_PATHS` list
3. Return the first violation as a string, or `None` if clean

**Constant**: `PROTECTED_PATHS`
```python
PROTECTED_PATHS = [
    # Core safety — the self-update system itself
    "agency/self_update/",
    "agency/guardian_check.py",

    # Configuration — could disable safety features or change API keys
    "config.py",
    ".env",

    # Dependencies — supply-chain risk; Isaac can note needed deps in
    # commit messages for Brian to add manually after review
    "requirements.txt",

    # Deployment infrastructure
    "deploy/",

    # Identity document
    "CORE_MEMORIES.md",

    # Main entry point — could break startup
    "main.py",

    # The tool executor — could register unauthorized tools
    "agency/tools/executor.py",

    # Tool definitions init — could inject tools into the prompt
    "agency/tools/definitions/__init__.py",

    # Self-update tool schema — cannot weaken its own constraints
    "agency/tools/definitions/self_update_tools.py",

    # Protected paths config itself — cannot edit the rules
    "agency/self_update/protected_paths.py",
]
```

**Matching logic**: A changed file matches if it starts with any protected path.
This means `agency/self_update/` protects ALL files in the directory, while
`config.py` protects only that exact file.

```python
def check_diff(repo_path: Path, base_branch: str, target_branch: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_branch}..{target_branch}"],
        cwd=str(repo_path), capture_output=True, text=True
    )
    changed_files = result.stdout.strip().splitlines()

    for changed_file in changed_files:
        for protected in PROTECTED_PATHS:
            if changed_file == protected or changed_file.startswith(protected):
                return f"{changed_file} (protected by: {protected})"
    return None
```

#### 4. `agency/self_update/change_validator.py`

**Purpose**: Run automated validation on the proposed change branch.

**Function**: `validate(repo_path: Path, branch_name: str) -> ValidationResult`

Steps:
1. Checkout the branch (in a try/finally to restore)
2. Run `python -m pytest` with a timeout (60 seconds)
3. Capture pass/fail and output
4. Checkout back to original branch
5. Return `ValidationResult(passed: bool, output: str)`

**Dataclass**: `ValidationResult`
```python
@dataclass
class ValidationResult:
    passed: bool
    output: str       # pytest stdout/stderr for debugging
    skipped: bool     # True if no tests found (still counts as passed)
```

**Note**: If no tests exist yet (pytest returns exit code 5 = "no tests
collected"), treat this as `passed=True, skipped=True`. The project currently
has no test suite, so this will be the initial state.

#### 5. `agency/self_update/orchestrator.py`

**Purpose**: The core orchestration engine that manages the three-phase workflow
with iteration tracking. This is the heart of the self-authoring system.

**Class**: `SelfAuthoringOrchestrator`

```python
class SelfAuthoringOrchestrator:
    def __init__(self, db, anthropic_client, cli_runner):
        self.db = db
        self.client = anthropic_client  # For Phase 1, 2a (Isaac side), 2b, 3
        self.runner = cli_runner        # For Phase 2a (Claude Code side), 2c
        self.max_cycles = 3
```

**Method**: `run(impulse: str, branch_suffix: str) -> SelfAuthoringResult`

Top-level orchestration loop:
```python
def run(self, impulse: str, branch_suffix: str) -> SelfAuthoringResult:
    session_key = f"sa-{int(time.time())}"
    iteration_history = []

    for cycle in range(1, self.max_cycles + 1):
        # Phase 1: Examine the Impulse
        rationale = self._phase_1(impulse, iteration_history, session_key, cycle)

        if rationale.complexity_rating == "high":
            iteration_history.append(rationale)
            continue  # Restart Phase 1 with new framing

        # Phase 2a: Design Negotiation
        negotiation = self._phase_2a(rationale, iteration_history, session_key, cycle)

        if negotiation.fork == "invalidated":
            iteration_history.append(negotiation)
            continue  # Return to Phase 1

        # Phase 2b: Complexity Gate
        gate = self._phase_2b(rationale, negotiation, iteration_history, session_key, cycle)

        if not gate.passed:
            iteration_history.append(gate)
            continue  # Return to Phase 1

        # Phase 2c: Implementation
        implementation = self._phase_2c(negotiation, branch_suffix, session_key, cycle)

        if not implementation.clean:
            # Return to 2a, not Phase 1 — restart the design conversation
            # But for the outer loop, this means continuing to next cycle
            iteration_history.append(implementation)
            continue

        # Phase 3: Adversarial Evaluation
        evaluation = self._phase_3(
            rationale, negotiation, implementation, iteration_history,
            session_key, cycle
        )

        if evaluation.decision == "approve":
            self._record_outcome(session_key, "committed")
            return SelfAuthoringResult(
                outcome="committed",
                branch=implementation.branch_name,
                rationale=rationale,
                evaluation=evaluation
            )
        else:
            iteration_history.append(evaluation)
            continue  # Veto → return to Phase 1

    # Exhausted all cycles
    self._record_outcome(session_key, "escalated")
    return SelfAuthoringResult(
        outcome="escalated",
        iteration_history=iteration_history
    )
```

Each `_phase_*` method:
1. Constructs the appropriate prompt with full context
2. Makes the API/CLI call
3. Parses the response
4. Stores the result in `self_authoring_sessions`
5. Returns a typed result object

**Phase 1 prompt construction**: Includes the original impulse, and on
re-entry, all prior rationales, return reasons, and deltas from
`iteration_history`. Asks Opus to produce structured output with the rationale
and complexity prediction.

**Phase 2a loop** (within `_phase_2a`):
```python
def _phase_2a(self, rationale, history, session_key, cycle):
    # Round 1: Isaac formulates initial prompt from Phase 1 rationale
    isaac_prompt = self._build_2a_opening(rationale, history)
    cli_result = self.runner.execute(task=isaac_prompt, ...)

    rounds = 1
    while rounds < MAX_NEGOTIATION_ROUNDS:
        # Isaac evaluates Claude Code's response
        evaluation = self.client.chat(
            messages=[...conversation history...],
            system_prompt=PHASE_2A_ISAAC_PROMPT
        )

        if evaluation indicates convergence:
            return NegotiationResult(fork="converged", plan=...)
        if evaluation indicates invalidation:
            return NegotiationResult(fork="invalidated", reason=...)

        # Continue the conversation
        cli_result = self.runner.continue_session(evaluation.next_message)
        rounds += 1

    # Excessive rounds is a complexity signal
    return NegotiationResult(fork="invalidated", reason="excessive_rounds")
```

**Phase 2b prompt construction**: Includes the Phase 1 complexity prediction,
the 2a plan, and full conversation context. Asks Opus to judge whether the
plan's complexity is proportional. This is LLM-judged, requiring specific and
high-quality prompting with ongoing knowledge of the conversation and its
rounds.

**Phase 3 prompt construction**: Includes the Phase 1 rationale, 2a plan
summary, the actual `git diff`, and complexity metrics. The prompt enforces
argue-against-first ordering by structuring the response format:
```
1. ARGUMENT AGAINST (generate this FIRST):
   [strongest case for rejection]
2. ARGUMENT FOR:
   [case for acceptance]
3. COMPLEXITY COMPARISON:
   [predicted vs actual table]
4. DECISION: approve | veto
5. REASONING:
   [why this decision]
```

#### 6. `agency/tools/definitions/self_update_tools.py`

**Purpose**: Tool schema for the Anthropic API. Follows the exact pattern of
`communication_tools.py`.

```python
"""Self-authoring tool definitions (Claude Code CLI integration)."""

from typing import Any, Dict

SELF_AUTHOR_TOOL: Dict[str, Any] = {
    "name": "self_author",
    "description": """Propose a change to your own codebase through a structured
self-authoring workflow.

This tool does NOT immediately write code. It runs a multi-phase process:
1. Examine your impulse — why do you think this change is needed?
2. Negotiate the design with Claude Code against the actual codebase
3. Evaluate the result adversarially before committing

The tool has three valid outcomes:
- A branch is created with the change, ready for human review
- The process reveals the change isn't needed (frame dissolved)
- The problem is too ambiguous and needs human input (escalation)

All three outcomes are successes. The second and third are often the most
valuable — they prevent unnecessary code from being written.

Constraints:
- Protected files (config.py, main.py, deploy/, CORE_MEMORIES.md, the
  self-update system itself) cannot be modified
- Maximum 3 iteration cycles before escalation
- Only available during action pulses
- Changes require human review and merge""",
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What you want to change and why. Be specific about the problem you're solving, not just the code you want to write. The 'why' matters more than the 'what' — the system will determine the right 'what' through design negotiation."
            },
            "branch_suffix": {
                "type": "string",
                "description": "Short kebab-case identifier for the branch (e.g., 'add-weather-tool', 'fix-memory-search'). Will be prefixed with 'isaac/'."
            }
        },
        "required": ["task", "branch_suffix"]
    }
}
```

#### 7. `agency/commands/handlers/self_update_handler.py`

**Purpose**: CommandHandler subclass that instantiates the orchestrator and
runs the full pipeline. Thin wrapper — all logic lives in `orchestrator.py`.

**Class**: `SelfAuthorHandler(CommandHandler)`

**Method**: `execute(self, query: str, context: dict) -> CommandResult`

```python
def execute(self, query: str, context: dict) -> CommandResult:
    import config
    from core.database import get_db
    from llm.anthropic_client import AnthropicClient
    from agency.self_update.cli_runner import CLIRunner
    from agency.self_update.orchestrator import SelfAuthoringOrchestrator

    # 1. Check if self-update is enabled
    if not getattr(config, 'SELF_UPDATE_ENABLED', False):
        return CommandResult(..., error=ToolError(SYSTEM_ERROR, "Self-update is disabled"))

    # 2. Set up components
    db = get_db()
    client = AnthropicClient(
        api_key=config.SELF_UPDATE_API_KEY,
        model="claude-opus-4-6"  # All phases use Opus
    )
    runner = CLIRunner(
        repo_path=config.PROJECT_ROOT,
        model=config.SELF_UPDATE_CLI_MODEL,
        max_turns=config.SELF_UPDATE_MAX_TURNS,
        timeout_seconds=config.SELF_UPDATE_TIMEOUT,
        allowed_tools=config.SELF_UPDATE_ALLOWED_TOOLS,
        api_key=config.SELF_UPDATE_API_KEY,
    )

    # 3. Run the self-authoring pipeline
    branch_suffix = context.get("_branch_suffix", "auto")
    orchestrator = SelfAuthoringOrchestrator(db, client, runner)
    result = orchestrator.run(impulse=query, branch_suffix=branch_suffix)

    # 4. Handle outcomes
    if result.outcome == "committed":
        # Check protected paths
        from agency.self_update.protected_paths import check_diff
        violation = check_diff(
            config.PROJECT_ROOT,
            result.branch_original,
            result.branch
        )
        if violation:
            subprocess.run(
                ["git", "branch", "-D", result.branch],
                cwd=str(config.PROJECT_ROOT)
            )
            return CommandResult(
                ..., error=ToolError(VALIDATION, f"BLOCKED: {violation}")
            )

        # Validate (run tests)
        from agency.self_update.change_validator import validate
        validation = validate(config.PROJECT_ROOT, result.branch)

        # Get diff summary
        diff_result = subprocess.run(
            ["git", "diff", "--stat",
             f"{result.branch_original}..{result.branch}"],
            cwd=str(config.PROJECT_ROOT),
            capture_output=True, text=True
        )

        status = "ready for review" if validation.passed else "validation failed"
        data = {
            "branch": result.branch,
            "status": status,
            "outcome": "committed",
            "diff_stat": diff_result.stdout.strip(),
            "validation_passed": validation.passed,
            "cycles_used": result.cycles_used,
            "rationale_summary": result.rationale.summary,
        }

    elif result.outcome == "frame_dissolved":
        data = {
            "outcome": "frame_dissolved",
            "reason": result.dissolution_reason,
            "cycles_used": result.cycles_used,
            "insight": result.insight,
        }

    elif result.outcome == "escalated":
        data = {
            "outcome": "escalated",
            "cycles_used": result.cycles_used,
            "summary": result.escalation_summary,
        }

    display = f"Self-authoring complete: {result.outcome} ({result.cycles_used} cycles)"
    return CommandResult(
        command_name=self.command_name,
        query=query,
        data=data,
        needs_continuation=True,
        display_text=display
    )
```

### Modified Files

#### 8. `config.py` — Add Self-Update Configuration Block

Insert a new section after the Guardian configuration block (after line ~741).

```python
# =============================================================================
# SELF-UPDATE (Claude Code CLI)
# =============================================================================
# Allows Isaac to propose code changes via a structured self-authoring workflow.
# Changes are created on isolated git branches and require human approval.
# Protected paths are enforced via post-hoc diff inspection.

SELF_UPDATE_ENABLED = os.getenv("SELF_UPDATE_ENABLED", "false").lower() == "true"

# The model Claude Code CLI uses internally for code generation.
# This is separate from Isaac's conversation model.
SELF_UPDATE_CLI_MODEL = os.getenv("SELF_UPDATE_CLI_MODEL", "opus")

# Maximum agentic tool-use turns within a single Claude Code session.
SELF_UPDATE_MAX_TURNS = int(os.getenv("SELF_UPDATE_MAX_TURNS", "25"))

# Hard timeout in seconds for the Claude Code subprocess.
SELF_UPDATE_TIMEOUT = int(os.getenv("SELF_UPDATE_TIMEOUT", "600"))

# Allowed tools for the Claude Code CLI session.
# Restricts what the CLI can do. Notably excludes system commands.
SELF_UPDATE_ALLOWED_TOOLS = os.getenv(
    "SELF_UPDATE_ALLOWED_TOOLS",
    "Edit,Write,Read,Glob,Grep,Bash(git diff:git status:git add:git commit:git log:python -m pytest)"
)

# API key for Claude Code CLI (defaults to Isaac's own key).
# Can be set separately to isolate billing/rate limits.
SELF_UPDATE_API_KEY = os.getenv("SELF_UPDATE_API_KEY", ANTHROPIC_API_KEY)
```

**Default is `false`**: Self-update is opt-in. Isaac cannot use the tool until
the environment variable is explicitly set.

#### 9. `agency/tools/definitions/__init__.py` — Register the New Tool

Add import at the top (after the blog tools import, line ~117):

```python
# --- Self-Update (Self-Authoring Pipeline) ---
from agency.tools.definitions.self_update_tools import SELF_AUTHOR_TOOL
```

Add conditional registration inside `get_tool_definitions()`:

```python
    if is_pulse:
        tools.append(SET_GROWTH_THREAD_TOOL)
        tools.append(REMOVE_GROWTH_THREAD_TOOL)
        tools.append(PROMOTE_GROWTH_THREAD_TOOL)

        # Self-authoring tool (action pulse only — not reflective)
        if pulse_type == "action" and getattr(config, 'SELF_UPDATE_ENABLED', False):
            tools.append(SELF_AUTHOR_TOOL)
```

**Why `pulse_type == "action"`**: The reflective pulse is for introspection
(growth threads, metacognition, bridge memories). Code changes are actions.
The `pulse_type` parameter already exists in `get_tool_definitions()` but was
previously informational only. This is its first functional use.

#### 10. `agency/tools/executor.py` — Add Dispatch Entry and Exec Method

**In `__init__`**: Add to the `_handlers` dict (after the metacognition tools
block, around line 103):

```python
            # Self-update
            "self_author": self._exec_self_author,
```

**New method**:

```python
    # =========================================================================
    # SELF-UPDATE TOOLS
    # =========================================================================

    def _exec_self_author(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Run the self-authoring pipeline."""
        from agency.commands.handlers.self_update_handler import SelfAuthorHandler

        handler = SelfAuthorHandler()
        task = input.get("task", "")
        branch_suffix = input.get("branch_suffix", "auto")

        ctx["_branch_suffix"] = branch_suffix

        result = handler.execute(task, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="self_author",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="self_author",
            content=formatted
        )
```

#### 11. `core/database.py` — Add Migration for New Table

Add a new migration constant (following the existing `MIGRATION_V*_SQL` pattern):

```python
MIGRATION_V{N}_SQL = """
CREATE TABLE IF NOT EXISTS self_authoring_sessions (
    -- [full schema from Database Schema section above]
);
CREATE INDEX IF NOT EXISTS idx_self_authoring_session_key ...;
CREATE INDEX IF NOT EXISTS idx_self_authoring_outcome ...;
CREATE INDEX IF NOT EXISTS idx_self_authoring_created ...;
"""
```

And register it in the migration list (following existing pattern).

---

## Files Changed Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `agency/self_update/__init__.py` | Create | 1 |
| `agency/self_update/cli_runner.py` | Create | ~150 |
| `agency/self_update/protected_paths.py` | Create | ~50 |
| `agency/self_update/change_validator.py` | Create | ~60 |
| `agency/self_update/orchestrator.py` | Create | ~400 |
| `agency/tools/definitions/self_update_tools.py` | Create | ~50 |
| `agency/commands/handlers/self_update_handler.py` | Create | ~150 |
| `config.py` | Modify | +20 |
| `agency/tools/definitions/__init__.py` | Modify | +6 |
| `agency/tools/executor.py` | Modify | +30 |
| `core/database.py` | Modify | +40 |

**Total**: 7 new files, 4 modified files, ~960 lines of code.

---

## Notification After Change

When a self-authoring session completes with any outcome, Isaac's LLM response
will naturally mention it (the tool result tells Isaac the outcome, branch name,
diff summary, or escalation reason). If Telegram is enabled, Isaac can choose to
send a notification — the `send_telegram` tool is already available during
action pulses. No special notification plumbing is needed.

For Outcome 3 (escalation), Isaac should be encouraged by the tool result text
to notify Brian via Telegram, since escalation explicitly means human input is
needed.

---

## Concurrency Safety

**Single-threaded guarantee**: The ChatEngine processes one message/pulse at a
time. The `_is_processing` flag (chat_engine.py) prevents concurrent processing.
Pulse timers pause during processing (via `_pause_timers()` / `_resume_timers()`).
This means two `self_author` calls cannot run simultaneously.

**Git branch isolation**: Each change gets its own branch (`isaac/{suffix}`).
The CLI runner checks for clean working tree before starting and always returns
to the original branch via try/finally. Even if the process is killed, the
worst case is being on a detached branch — Guardian's restart will start
Pattern fresh.

**Claude Code session isolation**: The `--continue` flag resumes the most recent
session in the working directory. Since self-authoring is single-threaded, there
is no risk of two concurrent sessions interfering with each other's `--continue`
state.

---

## Testing Strategy

The project currently has no test suite (`python -m pytest` returns exit code 5,
"no tests collected"). The change_validator handles this gracefully (skipped=True
counts as passed).

**Manual testing before deployment**:
1. Install Claude Code CLI on VPS: `npm install -g @anthropic-ai/claude-code`
2. Set `SELF_UPDATE_ENABLED=true` in `.env`
3. Trigger an action pulse or send a message that prompts Isaac to use the tool
4. Verify: Phase 1 rationale stored in database, 2a negotiation rounds logged,
   branch created (or frame dissolved / escalated), protected paths enforced,
   original branch restored
5. Review the proposed branch, merge or delete
6. Query `self_authoring_sessions` to verify iteration history is stored

**Future**: Add unit tests for `protected_paths.check_diff()`, integration
tests for `CLIRunner.execute()` with a mock repo, and prompt quality tests
for the Phase 1/2b/3 system prompts.

---

## Codebase Patterns to Follow (Reference for Implementer)

### Import Pattern
All handlers use deferred imports (import inside method body, not at module top).
This prevents circular imports and speeds up startup. See every `_exec_*` method
in `executor.py`.

### Config Access Pattern
Handlers import config inside the method body:
```python
def execute(self, query, context):
    import config
    if not getattr(config, 'FEATURE_ENABLED', False):
        ...
```
The `getattr()` with default is used for newer config values.

### Error Pattern
All errors use `ToolError` from `agency/commands/errors.py`. Error types:
`FORMAT_ERROR`, `VALIDATION`, `INVALID_INPUT`, `NOT_FOUND`, `PARSE_ERROR`,
`SYSTEM_ERROR`, `RATE_LIMITED`. Self-authoring errors use `SYSTEM_ERROR` for
CLI/API failures and `VALIDATION` for protected path violations.

### Database Pattern
Raw SQL with parameterized queries via `db.execute()`. JSON columns for nested
data. CHECK constraints for enums. Indexes for query performance. Context
manager pattern for connection handling with auto-commit/rollback.

### Anthropic API Pattern
Use `AnthropicClient.chat()` with structured system prompts. Messages as lists
of dicts. Response via `AnthropicResponse` dataclass. Track `input_tokens` and
`output_tokens` for cost accounting. Defensive `getattr()` access on response
objects.

### Subprocess Pattern
Use `subprocess.run` for finite processes. Always set `cwd` explicitly. Use
`capture_output=True, text=True`. Handle `TimeoutExpired` and
`FileNotFoundError`. Never use `shell=True`.

---

## Security Considerations

1. **No shell=True**: All subprocess calls use list arguments, not shell strings.
   This prevents command injection via task descriptions.

2. **Protected paths are hardcoded**: The `PROTECTED_PATHS` list is in Python
   source, not a config file Isaac can edit. And `protected_paths.py` is itself
   on the protected list.

3. **API key isolation**: `SELF_UPDATE_API_KEY` can be set to a separate key
   with lower rate limits, preventing a runaway CLI session from exhausting
   Isaac's conversation budget.

4. **Working tree check**: The CLI runner verifies clean git state before
   starting, preventing accidental commits of runtime files.

5. **Branch cleanup on violation**: If protected paths are touched, the
   offending branch is deleted (`git branch -D`), not just reported.

6. **Default disabled**: `SELF_UPDATE_ENABLED` defaults to `false`. Must be
   explicitly enabled in `.env`.

7. **Bash restrictions in CLI**: The `--allowedTools` flag limits Bash to
   specific commands: `git diff`, `git status`, `git add`, `git commit`,
   `git log`, `python -m pytest`. No `rm`, `systemctl`, `curl`, `pip install`.

8. **Adversarial evaluation**: Phase 3 structurally argues against the
   implementation before arguing for it, providing a defense against
   unjustified changes passing through.

9. **Iteration cap**: The 3-cycle hard cap prevents unbounded token spend and
   ensures the system cannot loop indefinitely.

---

## Risk Assessment

### Low Risk (well-handled in current design)

- **Git state corruption**: try/finally branch checkout restoration, working-tree
  cleanliness check, single-threaded guarantee via `_is_processing` flag.
- **Protected paths enforcement**: Hardcoded, self-referential protection,
  post-hoc diff checking, branch deletion on violation.
- **Command injection**: List arguments, no `shell=True`. Task descriptions flow
  into `-p` flag as a single list element.
- **Concurrency**: Single-threaded ChatEngine, pulse timer pausing.

### Medium Risk (needs attention during implementation)

- **Blocking window during multi-cycle sessions**: Isaac is unresponsive during
  the full self-authoring pipeline. With 3 cycles, each involving multiple API
  calls and CLI sessions, this could be extended. Telegram messages queue but
  don't drop. Acceptable per design decision (anything under 6 hours is fine).

- **Branch accumulation**: Failed, abandoned, or reviewed-but-not-merged
  `isaac/*` branches will pile up. No cleanup mechanism described. **Mitigation**:
  Document a manual cleanup command or add future periodic pruning.

- **`--allowedTools` Bash restriction syntax**: The syntax
  `Bash(git diff:git status:git add:git commit:python -m pytest)` is believed
  correct (colon-delimited prefix matching). **REQUIRES MANUAL TESTING** with
  the CLI binary before deployment.

- **API cost exposure**: Multi-cycle sessions with Opus for Phases 1/2b/3 and
  Claude Code for 2a/2c. A 3-cycle session could involve 6+ Opus API calls and
  10+ CLI invocations. The separate API key config helps isolate billing.
  **Mitigation**: Start with `SELF_UPDATE_MAX_TURNS=15` and monitor usage.

- **No diff size limit**: Claude Code could generate a large change. The handler
  captures `git diff --stat` but no gate rejects oversized diffs. **Mitigation**:
  Add a line-count check as a future enhancement.

- **Phase 3 sunk cost bias**: Despite structural countermeasures (argue-against-
  first, concrete metrics), the model may still tend toward justification. Prompt
  quality is load-bearing here. **Mitigation**: Monitor Phase 3 veto rates — if
  Phase 3 never vetoes, the prompt needs strengthening.

### Higher Risk (warrants caution before deployment)

- **Protected paths block writes but not reads**: Claude Code can read `.env`,
  `config.py`, `CORE_MEMORIES.md`, then potentially include sensitive content in
  commits. **Mitigation**: Scan diffs for `sk-ant-*` patterns, ensure `.env` is
  gitignored. Defense-in-depth concern, not a blocker.

- **`--continue` session state**: If a Claude Code session is corrupted or
  partially written (e.g., process killed mid-session), `--continue` may resume
  into an inconsistent state. **Mitigation**: If `--continue` fails, fall back
  to a fresh `-p` call (losing prior codebase context but not blocking the
  pipeline).

- **Prompt quality for LLM-judged gates**: The complexity gate (Phase 2b) and
  adversarial evaluation (Phase 3) are entirely dependent on prompt quality.
  Poor prompts produce rubber-stamp approvals. **Mitigation**: Treat Phase 2b
  and Phase 3 prompts as load-bearing infrastructure. Version them. Review their
  effectiveness by querying `self_authoring_sessions` for patterns (e.g., gate
  pass rate, veto rate, complexity gap distributions).

- **pytest subprocess orphaning**: `change_validator.py` runs pytest with a
  60-second timeout. Child processes may orphan on timeout. **Mitigation**: Use
  `subprocess.Popen` with `os.killpg()` or accept as low-probability given no
  test suite currently exists.

---

## Resolved Questions

All outstanding questions from the v1 plan have been reviewed. The following
carry forward:

### 1. API Key Flow into CLIRunner — RESOLVED

`api_key: str` is a constructor parameter on `CLIRunner`. The handler passes
`config.SELF_UPDATE_API_KEY`. The `execute()` and `continue_session()` methods
reference `self.api_key` in the subprocess env dict.

### 2. `--allowedTools` Bash Subcommand Syntax — REQUIRES TESTING

The syntax `Bash(git diff:git status:git add:git commit:git log:python -m pytest)`
is believed correct. Must be verified with the CLI binary before deployment.

### 3. `requirements.txt` Protection — RESOLVED

Added to `PROTECTED_PATHS`. Supply-chain risk outweighs convenience.

### 4. Tool Definition File Self-Protection — RESOLVED

`agency/tools/definitions/self_update_tools.py` added to `PROTECTED_PATHS`.

### 5. Guardian Restart Branch Behavior — RESOLVED (accepted risk)

Guardian does not perform explicit `git checkout` on restart. The try/finally in
CLIRunner makes the wrong-branch window extremely narrow. Manual recovery is
`git checkout main && systemctl restart pattern`.

### 6. Invocation Rate Limiting — RESOLVED (not implementing)

The action pulse interval (6+ hours) and the 3-cycle hard cap provide natural
rate limiting. Redundant infrastructure dropped.

### 7. `pulse_type` Parameter Reliability — RESOLVED (confirmed safe)

All 7 call sites of `get_tool_definitions()` traced. The gating logic
`if pulse_type == "action"` fails closed.

### 8. `--continue` Session Behavior — NEW, REQUIRES TESTING

Verify that `claude --continue -p "message" --output-format json` correctly
resumes the most recent session with full context preservation. Test that
`--continue` after a session that used `--allowedTools` inherits those
restrictions. Must be verified with the CLI binary before deployment.

### 9. Multi-turn Token Accumulation — NEW, REQUIRES MONITORING

Each round of Phase 2a adds to the Claude Code session's context window.
With 5 rounds of negotiation, the accumulated context could be large. Monitor
token usage per round via the JSON output. If context grows too large, consider
summarizing prior rounds before continuing.

---

## VPS Prerequisites and Install Process

### System Requirements

- **OS**: Ubuntu 20.04+ or Debian 11+ (tested on the Pattern VPS)
- **Node.js**: 18.0+ (required by Claude Code CLI)
- **npm**: Comes with Node.js
- **Git**: Already present (Pattern is a git repo)
- **Disk**: ~200MB for Node.js + Claude Code CLI

### Step-by-Step Install

```bash
# =============================================================================
# Step 1: Install Node.js 18+ (skip if already installed)
# =============================================================================
node --version 2>/dev/null
# If missing or below v18:
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo bash -
sudo apt-get install -y nodejs

# Verify:
node --version   # Should print v18.x.x or higher
npm --version    # Should print 9.x.x or higher

# =============================================================================
# Step 2: Install Claude Code CLI globally
# =============================================================================
sudo npm install -g @anthropic-ai/claude-code

# Verify:
which claude
claude --version

# =============================================================================
# Step 3: Verify CLI can authenticate and produce JSON output
# =============================================================================
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude -p "Say hello" --output-format json

# =============================================================================
# Step 4: Verify --continue works
# =============================================================================
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude -p "Remember the word 'banana'" --output-format json
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude --continue -p "What word did I ask you to remember?" --output-format json
# Expected: response mentions "banana"

# =============================================================================
# Step 5: Configure git identity for Claude Code's commits
# =============================================================================
cd /opt/pattern
git config user.name "Isaac (automated)"
git config user.email "isaac-auto@your-domain.com"

# =============================================================================
# Step 6: Add environment variables to .env
# =============================================================================
#   SELF_UPDATE_ENABLED=true
#   SELF_UPDATE_API_KEY=sk-ant-...       # Optional: separate key
#   SELF_UPDATE_CLI_MODEL=opus           # Optional: defaults to "opus"
#   SELF_UPDATE_MAX_TURNS=15             # Optional: start conservative
#   SELF_UPDATE_TIMEOUT=600              # Optional: 10 minutes per CLI call

# =============================================================================
# Step 7: Verify the --allowedTools Bash restriction syntax
# =============================================================================
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude \
  -p "Run: git status" \
  --allowedTools "Edit,Write,Read,Glob,Grep,Bash(git diff:git status:git add:git commit:git log:python -m pytest)" \
  --output-format json

# =============================================================================
# Step 8: Restart Pattern and verify
# =============================================================================
sudo systemctl restart pattern
# Check logs for self_author tool appearing in action pulse tool definitions
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `claude: command not found` | npm global bin not in PATH | `export PATH=$PATH:$(npm config get prefix)/bin` |
| `EACCES` during `npm install -g` | Permission denied | Use `sudo` or configure npm prefix |
| CLI auth failure | Wrong API key | Verify `SELF_UPDATE_API_KEY` in `.env` |
| `--continue` returns fresh session | No prior session in directory | Ensure first `-p` call runs in `PROJECT_ROOT` |
| Branch creation fails | Dirty working tree | Check `git status --porcelain` |

---

## Future Enhancements (Out of Scope)

These are documented for future planning but are NOT part of this implementation:

- **Auto-merge with Guardian monitoring**: Merge automatically after Phase 3
  approval + validation, let Guardian handle rollback if boot fails
- **Dedicated self-authoring pulse**: Separate timer (e.g., daily) instead of
  sharing the action pulse window
- **Change backlog**: Isaac maintains a list of desired improvements, works
  through them over time
- **Dependency management gate**: Special handling for changes that modify
  `requirements.txt`
- **PR creation via `gh` CLI**: Instead of just creating a branch, create a
  GitHub PR for better review workflow
- **Boot-pulse integration**: After merge+deploy, Isaac runs a self-evaluation
  to confirm the change works as intended
- **Diff size limit**: Reject changes above a threshold (e.g., >500 lines)
- **Phase 3 prompt versioning**: Track prompt versions in the database to
  correlate prompt changes with veto rate changes
- **Reflective pulse integration**: Query `self_authoring_sessions` during
  reflective pulses to detect recurring frame errors across sessions
