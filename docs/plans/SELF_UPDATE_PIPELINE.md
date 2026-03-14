# Self-Update Pipeline: Claude Code CLI Integration

## Overview

This plan adds the ability for Isaac to propose changes to his own codebase by
invoking the Claude Code CLI as a subprocess. Changes are created on isolated
git branches and require human approval before merging.

**Scope**: New tool (`propose_code_change`), new module (`agency/self_update/`),
config additions, and registration in the existing tool/executor system.

**What this does NOT do**: Auto-merge, auto-deploy, or modify Guardian. The
human gate is non-negotiable in this first iteration.

---

## Architecture Decision Record

**Why `subprocess.run()` (blocking) instead of async/SubprocessManager?**

The SubprocessManager (`subprocess_mgmt/manager.py`) is designed for long-lived
child processes with health endpoints (HTTP health checks, PID monitoring,
auto-restart). Claude Code CLI is a short-lived, single-shot process — it runs,
produces output, and exits. `subprocess.run()` with a timeout is the right tool.

Isaac's ChatEngine processes messages synchronously on a single thread. During a
code change, Isaac is blocked (up to 10 minutes). This is acceptable because:
- Code changes are triggered during action pulses, not user conversations
- The pulse system already pauses timers during processing
- A blocked pulse simply delays the next one

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
    model: str,               # e.g. "sonnet" — the model Claude Code uses internally
    max_turns: int,           # Cap on agentic tool-use loops (e.g. 25)
    timeout_seconds: int,     # Hard timeout on subprocess (e.g. 600)
    allowed_tools: str        # --allowedTools value
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
This prevents Claude Code CLI from accidentally committing Isaac's runtime
artifacts or uncommitted work.

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

**Note**: If no tests exist yet (pytest returns exit code 5 = "no tests collected"),
treat this as `passed=True, skipped=True`. The project currently has no test
suite, so this will be the initial state. The validator is forward-looking
infrastructure.

#### 5. `agency/tools/definitions/self_update_tools.py`

**Purpose**: Tool schema for the Anthropic API. Follows the exact pattern of
`communication_tools.py`.

```python
"""Self-update tool definitions (Claude Code CLI integration)."""

from typing import Any, Dict

PROPOSE_CODE_CHANGE_TOOL: Dict[str, Any] = {
    "name": "propose_code_change",
    "description": """Propose a change to your own codebase using Claude Code CLI.

This tool creates a git branch, runs Claude Code CLI with your task description,
validates the result, and reports the diff. Changes are NOT automatically merged —
they require human review and approval.

Use this when you want to:
- Add a new tool or capability to yourself
- Fix a bug you've noticed in your own behavior
- Improve an existing feature
- Add a new integration

Constraints:
- Protected files (config.py, main.py, deploy/, CORE_MEMORIES.md, the self-update
  system itself) cannot be modified through this tool
- Changes that fail validation (tests) will be reported but preserved for inspection
- Only one code change can run at a time (blocks during execution)
- Maximum execution time: 10 minutes

The result will include the branch name and a summary of changes. Brian will
review and merge if approved.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Detailed description of what to build or change. Be specific about file locations, expected behavior, and any constraints. The more detail, the better the result."
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

#### 6. `agency/commands/handlers/self_update_handler.py`

**Purpose**: CommandHandler subclass that orchestrates the full pipeline. This is
the handler that `ToolExecutor` calls.

**Class**: `ProposeCodeChangeHandler(CommandHandler)`

**Method**: `execute(self, query: str, context: dict) -> CommandResult`

The `query` parameter will be a pipe-delimited string `"task | branch_suffix"`
following the pattern used by other multi-param handlers in executor.py (see
how file_handler.py receives `"filename | content"`). However, since we control
the executor method, we can also pass structured data via context. The cleaner
approach (used by newer handlers) is to have the `_exec_` method in executor.py
extract fields from `tool_input` and pass them individually.

**Actual approach**: The `_exec_propose_code_change` method in executor.py will
extract `task` and `branch_suffix` from `tool_input`, construct the query, and
pass both via a structured approach. Looking at the codebase pattern, the
simplest is:

```python
# In executor.py _exec_propose_code_change:
handler = ProposeCodeChangeHandler()
task = input.get("task", "")
branch_suffix = input.get("branch_suffix", "auto")
query = task  # Primary query is the task
ctx["_branch_suffix"] = branch_suffix  # Pass branch via context
result = handler.execute(query, ctx)
```

**Handler pipeline** (in `execute()`):

```python
def execute(self, query: str, context: dict) -> CommandResult:
    import config

    # 1. Check if self-update is enabled
    if not getattr(config, 'SELF_UPDATE_ENABLED', False):
        return CommandResult(..., error=ToolError(SYSTEM_ERROR, "Self-update is disabled"))

    # 2. Build branch name
    branch_suffix = context.get("_branch_suffix", "auto")
    branch_name = f"isaac/{branch_suffix}"

    # 3. Run CLI
    from agency.self_update.cli_runner import CLIRunner
    runner = CLIRunner(
        repo_path=config.PROJECT_ROOT,
        model=config.SELF_UPDATE_CLI_MODEL,
        max_turns=config.SELF_UPDATE_MAX_TURNS,
        timeout_seconds=config.SELF_UPDATE_TIMEOUT,
        allowed_tools=config.SELF_UPDATE_ALLOWED_TOOLS,
    )
    cli_result = runner.execute(task=query, branch_name=branch_name)

    if not cli_result.success:
        return CommandResult(..., error=ToolError(SYSTEM_ERROR, f"CLI failed: {cli_result.stderr}"))

    # 4. Check protected paths
    from agency.self_update.protected_paths import check_diff
    violation = check_diff(config.PROJECT_ROOT, cli_result.original_branch, branch_name)
    if violation:
        # Delete the offending branch
        subprocess.run(["git", "branch", "-D", branch_name], cwd=str(config.PROJECT_ROOT))
        return CommandResult(..., error=ToolError(VALIDATION, f"BLOCKED: {violation}"))

    # 5. Validate (run tests)
    from agency.self_update.change_validator import validate
    validation = validate(config.PROJECT_ROOT, branch_name)

    # 6. Get diff summary for the result
    diff_result = subprocess.run(
        ["git", "diff", "--stat", f"{cli_result.original_branch}..{branch_name}"],
        cwd=str(config.PROJECT_ROOT), capture_output=True, text=True
    )

    # 7. Build result
    status = "ready for review" if validation.passed else "validation failed"
    data = {
        "branch": branch_name,
        "status": status,
        "diff_stat": diff_result.stdout.strip(),
        "validation_passed": validation.passed,
        "validation_output": validation.output if not validation.passed else None,
    }

    display = f"Code change proposed on branch '{branch_name}' ({status})"
    return CommandResult(
        command_name=self.command_name,
        query=query,
        data=data,
        needs_continuation=True,
        display_text=display
    )
```

**`format_result()`**:
```python
def format_result(self, result: CommandResult) -> str:
    if result.error:
        return f"  {result.get_error_message()}"
    d = result.data
    lines = [
        f"  Branch: {d['branch']}",
        f"  Status: {d['status']}",
        f"  Changes:\n{d['diff_stat']}",
    ]
    if not d['validation_passed']:
        lines.append(f"  Validation output:\n{d['validation_output']}")
    return "\n".join(lines)
```

### Modified Files

#### 7. `config.py` — Add Self-Update Configuration Block

Insert a new section after the Guardian configuration block (after line ~741).
Follow the existing config.py conventions:
- Section header with `# =====` separators
- Comments explaining each constant
- Environment variable overrides where appropriate
- `getattr()` pattern for feature flags

```python
# =============================================================================
# SELF-UPDATE (Claude Code CLI)
# =============================================================================
# Allows Isaac to propose code changes via Claude Code CLI subprocess.
# Changes are created on isolated git branches and require human approval.
# Protected paths are enforced via post-hoc diff inspection.

SELF_UPDATE_ENABLED = os.getenv("SELF_UPDATE_ENABLED", "false").lower() == "true"

# The model Claude Code CLI uses internally for code generation.
# This is separate from Isaac's conversation model.
SELF_UPDATE_CLI_MODEL = os.getenv("SELF_UPDATE_CLI_MODEL", "sonnet")

# Maximum agentic tool-use turns within a single Claude Code session.
SELF_UPDATE_MAX_TURNS = int(os.getenv("SELF_UPDATE_MAX_TURNS", "25"))

# Hard timeout in seconds for the Claude Code subprocess.
SELF_UPDATE_TIMEOUT = int(os.getenv("SELF_UPDATE_TIMEOUT", "600"))

# Allowed tools for the Claude Code CLI session.
# Restricts what the CLI can do. Notably excludes system commands.
SELF_UPDATE_ALLOWED_TOOLS = os.getenv(
    "SELF_UPDATE_ALLOWED_TOOLS",
    "Edit,Write,Read,Glob,Grep,Bash(git diff:git status:git add:git commit:python -m pytest)"
)

# API key for Claude Code CLI (defaults to Isaac's own key).
# Can be set separately to isolate billing/rate limits.
SELF_UPDATE_API_KEY = os.getenv("SELF_UPDATE_API_KEY", ANTHROPIC_API_KEY)
```

**Default is `false`**: Self-update is opt-in. Isaac cannot use the tool until
the environment variable is explicitly set. This is a safety decision.

#### 8. `agency/tools/definitions/__init__.py` — Register the New Tool

Add import at the top (after the blog tools import, line ~117):

```python
# --- Self-Update (Claude Code CLI) ---
from agency.tools.definitions.self_update_tools import PROPOSE_CODE_CHANGE_TOOL
```

Add conditional registration inside `get_tool_definitions()`. This goes in the
pulse-only section (after line 234, inside the `if is_pulse:` block):

```python
    if is_pulse:
        tools.append(SET_GROWTH_THREAD_TOOL)
        tools.append(REMOVE_GROWTH_THREAD_TOOL)
        tools.append(PROMOTE_GROWTH_THREAD_TOOL)

        # Self-update tool (action pulse only — not reflective)
        if pulse_type == "action" and getattr(config, 'SELF_UPDATE_ENABLED', False):
            tools.append(PROPOSE_CODE_CHANGE_TOOL)
```

**Why `pulse_type == "action"`**: The reflective pulse is for introspection
(growth threads, metacognition, bridge memories). Code changes are actions.
The `pulse_type` parameter already exists in `get_tool_definitions()` but was
previously informational only (see docstring at line 133-134). This is its
first functional use.

#### 9. `agency/tools/executor.py` — Add Dispatch Entry and Exec Method

**In `__init__`**: Add to the `_handlers` dict (after the metacognition tools
block, around line 103):

```python
            # Self-update
            "propose_code_change": self._exec_propose_code_change,
```

**New method** (add after the metacognition exec methods, before the class ends):

```python
    # =========================================================================
    # SELF-UPDATE TOOLS
    # =========================================================================

    def _exec_propose_code_change(
        self, input: Dict, id: str, ctx: Dict
    ) -> ToolResult:
        """Propose a code change via Claude Code CLI."""
        from agency.commands.handlers.self_update_handler import ProposeCodeChangeHandler

        handler = ProposeCodeChangeHandler()
        task = input.get("task", "")
        branch_suffix = input.get("branch_suffix", "auto")

        # Pass branch suffix via context (handler extracts it)
        ctx["_branch_suffix"] = branch_suffix

        result = handler.execute(task, ctx)

        if result.error:
            return ToolResult(
                tool_use_id=id,
                tool_name="propose_code_change",
                content=result.get_error_message(),
                is_error=True
            )

        formatted = handler.format_result(result)
        return ToolResult(
            tool_use_id=id,
            tool_name="propose_code_change",
            content=formatted
        )
```

This follows the exact pattern of `_exec_send_telegram` (executor.py lines
576-600): instantiate handler, extract input fields, call execute, check error,
format result, return ToolResult.

---

## Notification After Change

When a code change is successfully proposed, Isaac's LLM response will naturally
mention it (the tool result tells Isaac the branch name and diff summary). If
Telegram is enabled, Isaac can choose to also send a notification — the
`send_telegram` tool is already available during action pulses, and Isaac
routinely uses it for things it considers noteworthy.

No special notification plumbing is needed. Isaac's judgment handles this.

---

## Concurrency Safety

**Single-threaded guarantee**: The ChatEngine processes one message/pulse at a
time. The `_is_processing` flag (chat_engine.py) prevents concurrent processing.
Pulse timers pause during processing (via `_pause_timers()` / `_resume_timers()`).
This means two `propose_code_change` calls cannot run simultaneously.

**Git branch isolation**: Each change gets its own branch (`isaac/{suffix}`).
The CLI runner checks for clean working tree before starting and always returns
to the original branch via try/finally. Even if the process is killed, the
worst case is being on a detached branch — Guardian's restart will start
Pattern fresh (which checks out the configured branch).

---

## Testing Strategy

The project currently has no test suite (`python -m pytest` returns exit code 5,
"no tests collected"). The change_validator handles this gracefully (skipped=True
counts as passed).

**Manual testing before deployment**:
1. Install Claude Code CLI on VPS: `npm install -g @anthropic-ai/claude-code`
2. Set `SELF_UPDATE_ENABLED=true` in `.env`
3. Trigger an action pulse or send a message that prompts Isaac to use the tool
4. Verify: branch created, diff clean, protected paths enforced, original
   branch restored
5. Review the proposed branch, merge or delete

**Future**: Add unit tests for `protected_paths.check_diff()` and integration
tests for `CLIRunner.execute()` with a mock repo.

---

## Files Changed Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `agency/self_update/__init__.py` | Create | 1 |
| `agency/self_update/cli_runner.py` | Create | ~120 |
| `agency/self_update/protected_paths.py` | Create | ~50 |
| `agency/self_update/change_validator.py` | Create | ~60 |
| `agency/tools/definitions/self_update_tools.py` | Create | ~45 |
| `agency/commands/handlers/self_update_handler.py` | Create | ~130 |
| `config.py` | Modify | +20 |
| `agency/tools/definitions/__init__.py` | Modify | +6 |
| `agency/tools/executor.py` | Modify | +30 |

**Total**: 6 new files, 3 modified files, ~460 lines of code.

---

## Codebase Patterns to Follow (Reference for Implementer)

### Import Pattern
All handlers use deferred imports (import inside method body, not at module top).
This prevents circular imports and speeds up startup. See every `_exec_*` method
in `executor.py` — they all do `from agency.commands.handlers.X import XHandler`
inside the method body.

### Singleton Pattern
Global instances use the `_instance: Optional[T] = None` + `get_instance() -> T`
pattern. See `guardian_check.py` lines 310-345 and `executor.py` lines 1248-1259.
The CLI runner does NOT need a singleton — it's instantiated fresh each time
by the handler.

### Config Access Pattern
Handlers import config inside the method body:
```python
def execute(self, query, context):
    import config
    if not getattr(config, 'FEATURE_ENABLED', False):
        ...
```
The `getattr()` with default is used for newer config values to handle the case
where config.py hasn't been updated yet. See `definitions/__init__.py` lines
181, 194, 203, 210, 221.

### Error Pattern
All errors use `ToolError` from `agency/commands/errors.py`. The error types
are: `FORMAT_ERROR`, `VALIDATION`, `INVALID_INPUT`, `NOT_FOUND`, `PARSE_ERROR`,
`SYSTEM_ERROR`, `RATE_LIMITED`. Self-update errors will use `SYSTEM_ERROR` for
CLI failures and `VALIDATION` for protected path violations.

### CommandResult Pattern
- `command_name`: Use `self.command_name` (inherited from base, returns class name)
- `query`: The original task description
- `data`: Dict with structured result data
- `needs_continuation`: Always `True` for tools that produce results Isaac
  should see (Isaac needs to tell the human what happened)
- `display_text`: Short status string shown in UI events
- `error`: `ToolError` instance or `None`

### Tool Definition Pattern
- Module-level constant: `TOOL_NAME_TOOL: Dict[str, Any] = { ... }`
- `name` field must exactly match the key in `executor.py`'s `_handlers` dict
- `description` is multi-line, includes usage guidance and constraints
- `input_schema` is JSON Schema with `type`, `properties`, `required`

### Subprocess Pattern
The codebase uses `subprocess.Popen` for long-lived detached processes
(Guardian) and `subprocess.run` for quick commands. The self-update pipeline
uses `subprocess.run` because Claude Code CLI is a finite process. Always:
- Set `cwd` explicitly
- Use `capture_output=True, text=True`
- Handle `TimeoutExpired` and `FileNotFoundError`
- Never use `shell=True`

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
   `python -m pytest`. No `rm`, `systemctl`, `curl`, `pip install`, etc.

---

## Risk Assessment

### Low Risk (well-handled in current design)

- **Git state corruption**: The try/finally pattern for branch checkout
  restoration is solid. The working-tree cleanliness check
  (`git status --porcelain`) before starting prevents accidental commits of
  runtime artifacts. Verified: `chat_engine.py:59` `_is_processing` flag and
  `_pause_timers()`/`_resume_timers()` (lines 128–140) guarantee sequential
  pulse processing, so two `propose_code_change` calls cannot race on git state.
- **Protected paths enforcement**: Hardcoded in Python source, self-referential
  protection (`agency/self_update/protected_paths.py` protects itself), and
  post-hoc diff checking is the correct approach given that `--allowedTools`
  cannot restrict file-level access. Branch deletion on violation (`git branch
  -D`) is appropriately aggressive.
- **Command injection**: All subprocess calls use list arguments (no
  `shell=True`). Task descriptions flow into the `-p` flag as a single list
  element, not interpolated into a shell string.
- **Concurrency**: Single-threaded ChatEngine (`_is_processing` at
  `chat_engine.py:59`) plus pulse timer pausing (lines 128–140) means no
  concurrent git operations. The SubprocessManager (used by Guardian) is a
  separate concern and does not interact with the CLI runner's
  `subprocess.run()` calls.

### Medium Risk (needs attention during implementation)

- **10-minute blocking window**: Isaac is fully unresponsive during CLI
  execution. The `_pause_timers()` call (chat_engine.py:128) pauses both the
  PulseManager and TelegramListener, so incoming Telegram messages queue but
  are not lost. However, if a user sends multiple messages during the block,
  they will all arrive at once when `_resume_timers()` fires (line 135). Edge
  case: if the CLI subprocess hangs past the 600s timeout and the
  `TimeoutExpired` handler takes additional time to kill the process + restore
  the branch, the total block could exceed 10 minutes. **Mitigation**: Add a
  generous buffer to the timeout kill logic and log a warning if cleanup takes
  more than 10 seconds.

- **Branch accumulation**: Failed, abandoned, or reviewed-but-not-merged
  `isaac/*` branches will pile up on the VPS. No cleanup mechanism is described.
  Over weeks/months this becomes git clutter and could slow `git branch`
  operations. **Mitigation**: Document a manual cleanup command
  (`git branch --list 'isaac/*' | xargs git branch -D`) or add a future
  enhancement for periodic branch pruning.

- **`--allowedTools` Bash restriction syntax**: The plan specifies
  `Bash(git diff:git status:git add:git commit:python -m pytest)` as the
  `--allowedTools` value. This is a colon-delimited allowlist of Bash
  subcommands. **Open question**: Does Claude Code CLI enforce this as prefix
  matching or exact string matching? If prefix, `git commit -a -m "..."` would
  be allowed (acceptable). If exact, it might reject valid git commands with
  flags. This must be verified against the current Claude Code CLI version
  before deployment.

- **API cost exposure**: 25 max turns with Sonnet, up to 10 minutes. A single
  misfired self-update (e.g., an overly ambitious task description that causes
  the CLI to loop) could burn significant tokens. The separate
  `SELF_UPDATE_API_KEY` config helps isolate billing, but there is no
  per-invocation cost tracking or budget cap. **Mitigation**: Start with
  `SELF_UPDATE_MAX_TURNS=15` in production and increase only after observing
  typical usage patterns. Consider adding token-count logging from the CLI's
  JSON output.

- **No diff size limit**: Claude Code could generate a 5,000-line change. The
  handler captures `git diff --stat` for the result, but there is no gate that
  rejects changes above a certain size. Large diffs are harder to review and
  more likely to contain subtle issues. **Mitigation**: Add a line-count check
  in the handler (e.g., `git diff --shortstat` → parse insertions/deletions →
  reject if >500 lines changed) as a future enhancement.

### Higher Risk (warrants caution before deployment)

- **API key flow gap in spec**: The `CLIRunner` constructor (section 2 of the
  plan) accepts `repo_path`, `model`, `max_turns`, `timeout_seconds`, and
  `allowed_tools` — but NOT `api_key`. However, the `subprocess.run()` call
  inside `execute()` references `api_key` in the env dict
  (`env={**os.environ, "ANTHROPIC_API_KEY": api_key}`). The spec must be
  updated to either: (a) add `api_key: str` as a constructor parameter, or
  (b) have `execute()` read `SELF_UPDATE_API_KEY` from config directly. Option
  (a) is cleaner and matches the existing pattern where config values are
  passed into constructors. **This is a spec bug that must be fixed before
  implementation.**

- **Protected paths block writes but not reads**: The `--allowedTools` value
  includes `Read` and `Grep`, which are unrestricted. Claude Code can read
  `.env`, `config.py`, `CORE_MEMORIES.md`, and any other file, then
  potentially include sensitive content (API keys, personal information) in
  commit messages, branch names, or code comments on the proposed branch.
  **Mitigation**: Add a post-hoc check that scans the diff content (not just
  filenames) for patterns matching API key formats (`sk-ant-*`, `sk-*`).
  Alternatively, ensure `.env` is in `.gitignore` (so it can't be committed
  even if read). This is a defense-in-depth concern, not a blocker.

- **pytest subprocess orphaning**: The `change_validator.py` runs
  `python -m pytest` with a 60-second timeout. If pytest spawns child
  processes (e.g., via subprocess fixtures or integration tests),
  `subprocess.run()` timeout kills the parent pytest process but child
  processes may orphan. **Mitigation**: Use `subprocess.Popen` with
  `os.killpg()` to kill the entire process group, or accept this as a
  low-probability issue given the project currently has no test suite (pytest
  exit code 5).

---

## Outstanding Questions

These must be resolved before or during implementation:

### 1. API Key Flow into CLIRunner

The `CLIRunner` constructor does not include an `api_key` parameter, but the
`execute()` method's subprocess call passes it via environment. How does
`api_key` get into scope?

**Recommended resolution**: Add `api_key: str` to the constructor signature.
In `self_update_handler.py`, pass `config.SELF_UPDATE_API_KEY` (which defaults
to `ANTHROPIC_API_KEY` per the config block at line 440 of the plan).

### 2. Exact `--allowedTools` Bash Subcommand Syntax

The plan assumes `Bash(git diff:git status:git add:git commit:python -m pytest)`
is valid syntax. This needs verification:
- Does Claude Code CLI parse this as prefix matching or exact matching?
- Are colons the correct delimiter?
- Does `python -m pytest` (with spaces) work as a single subcommand entry?

**Action**: Run `claude -p "test" --allowedTools "Bash(echo hello)" --output-format json`
on the VPS after install to verify the syntax is accepted.

### 3. `requirements.txt` Protection

`requirements.txt` is NOT on the protected paths list. A proposed change that
adds a malicious or incompatible dependency could break the environment on next
deploy (e.g., `pip install` during deploy script). Should it be protected?

**Trade-off**: Protecting it blocks Isaac from adding legitimate dependencies
for new features. Not protecting it allows supply-chain risk. **Recommended
resolution**: Add `requirements.txt` to `PROTECTED_PATHS` in this first
iteration. Isaac can describe needed dependencies in the branch's commit
message, and Brian adds them manually after review.

### 4. Tool Definition File Self-Protection

`agency/tools/definitions/self_update_tools.py` is NOT on the protected paths
list. Only `agency/tools/definitions/__init__.py` and `agency/self_update/`
are protected. Isaac could modify the tool schema to remove constraint
documentation from its own prompt (e.g., strip the "Protected files..." text
from the tool description), which would weaken the LLM-level guardrail.

**Recommended resolution**: Add
`agency/tools/definitions/self_update_tools.py` to `PROTECTED_PATHS`.

### 5. Guardian Restart Branch Behavior

The plan states "Guardian's restart will start Pattern fresh (which checks out
the configured branch)" as the worst-case recovery for a killed process
mid-checkout. What branch does Guardian configure?

**Action**: Check `guardian.toml` or Guardian's restart logic to confirm it
does an explicit `git checkout main` (or equivalent) on restart, rather than
inheriting whatever branch the repo happens to be on.

### 6. Invocation Rate Limiting

Nothing prevents Isaac from calling `propose_code_change` on every action
pulse. If the action pulse fires every ~30 minutes, Isaac could invoke 48
CLI sessions per day.

**Recommended resolution**: Add a cooldown check in the handler — e.g., read
a timestamp file (`DATA_DIR / "last_self_update.json"`) and reject invocations
within 4 hours of the last attempt. This is simple, file-based, and matches
existing codebase patterns (see heartbeat files).

### 7. `pulse_type` Parameter Reliability

The plan gates the tool on `pulse_type == "action"` in
`definitions/__init__.py`. The `pulse_type` parameter exists in
`get_tool_definitions()` (line 127: `pulse_type: str = None`) but is
documented as "currently informational" (lines 133–134). This would be its
first functional use.

**Action**: Trace all call sites of `get_tool_definitions()` to confirm
`pulse_type` is passed correctly in action pulse codepaths. If any call site
omits it (passes `None`), the tool will silently not appear. This is safe
(fails closed) but could cause confusion if Isaac never sees the tool.

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
# Check if Node.js is already present and sufficient:
node --version 2>/dev/null
# If missing or below v18, install via NodeSource:

curl -fsSL https://deb.nodesource.com/setup_18.x | sudo bash -
sudo apt-get install -y nodejs

# Verify:
node --version   # Should print v18.x.x or higher
npm --version    # Should print 9.x.x or higher

# =============================================================================
# Step 2: Install Claude Code CLI globally
# =============================================================================
sudo npm install -g @anthropic-ai/claude-code

# Verify binary is in PATH:
which claude        # Should print /usr/bin/claude or /usr/local/bin/claude
claude --version    # Should print version info

# =============================================================================
# Step 3: Verify CLI can authenticate and produce JSON output
# =============================================================================
# Use the API key that Isaac will use for self-update:
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude -p "Say hello" --output-format json

# Expected: JSON output with a "result" field containing a greeting.
# If this fails with auth errors, the key is wrong.
# If this fails with "command not found", the npm install didn't work.

# =============================================================================
# Step 4: Configure git identity for Claude Code's commits
# =============================================================================
cd /opt/pattern   # Or wherever PROJECT_ROOT points

# Set identity so commits are attributed properly:
git config user.name "Isaac (automated)"
git config user.email "isaac-auto@your-domain.com"

# Verify:
git config user.name
git config user.email

# =============================================================================
# Step 5: Add environment variables to .env
# =============================================================================
# Add these lines to /opt/pattern/.env (or your .env location):
#
#   SELF_UPDATE_ENABLED=true
#   SELF_UPDATE_API_KEY=sk-ant-...       # Optional: separate key for billing isolation
#   SELF_UPDATE_CLI_MODEL=sonnet         # Optional: defaults to "sonnet"
#   SELF_UPDATE_MAX_TURNS=15             # Optional: start conservative, increase later
#   SELF_UPDATE_TIMEOUT=600              # Optional: 10 minutes, default
#
# NOTE: SELF_UPDATE_ENABLED defaults to "false" if omitted.
# Isaac cannot use the tool until this is explicitly set to "true".

# =============================================================================
# Step 6: Verify the --allowedTools Bash restriction syntax
# =============================================================================
# This confirms the Bash subcommand allowlist works as expected:
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude \
  -p "Run: echo hello" \
  --allowedTools "Bash(echo hello)" \
  --output-format json

# If Claude Code executes the echo, the syntax is valid.
# Then test the full restriction string from config:
ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE" claude \
  -p "Run: git status" \
  --allowedTools "Edit,Write,Read,Glob,Grep,Bash(git diff:git status:git add:git commit:python -m pytest)" \
  --output-format json

# =============================================================================
# Step 7: Restart Pattern to pick up new .env values
# =============================================================================
# Use whatever process manager is configured (systemd, supervisor, etc.):
sudo systemctl restart pattern    # if using systemd
# OR
sudo supervisorctl restart pattern  # if using supervisor
# OR manually restart the process

# =============================================================================
# Step 8: Post-deploy verification
# =============================================================================
# After Pattern restarts, trigger an action pulse (or wait for one) and check
# logs for the propose_code_change tool appearing in the tool definitions.
# You can also manually test by sending Isaac a message that prompts code change
# consideration during an action pulse.
```

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `claude: command not found` | npm global bin not in PATH | `export PATH=$PATH:$(npm config get prefix)/bin` and add to shell profile |
| `EACCES` during `npm install -g` | Permission denied on global dir | Use `sudo` or configure npm prefix to `~/.npm-global` |
| CLI auth failure | Wrong API key | Verify `SELF_UPDATE_API_KEY` or `ANTHROPIC_API_KEY` in `.env` |
| `node: not found` after install | Shell hasn't picked up new PATH | `source ~/.bashrc` or restart shell |
| Branch creation fails | Dirty working tree | Isaac's handler checks `git status --porcelain`; ensure no uncommitted files in `/opt/pattern` |
| `git checkout` fails on restore | Branch deleted externally | The try/finally in CLIRunner will log the error; manual `git checkout main` recovers |

---

## Future Enhancements (Out of Scope)

These are documented for future planning but are NOT part of this implementation:

- **Auto-merge with Guardian monitoring**: Merge automatically after validation,
  let Guardian handle rollback if boot fails
- **Dedicated self-update pulse**: Separate timer (e.g., daily) instead of
  sharing the action pulse window
- **Change backlog**: Isaac maintains a list of desired improvements, works
  through them over time
- **Dependency management gate**: Special handling for changes that modify
  `requirements.txt`
- **PR creation via `gh` CLI**: Instead of just creating a branch, create a
  GitHub PR for better review workflow
- **Boot-pulse integration**: After merge+deploy, Isaac runs a self-evaluation
  to confirm the change works as intended
