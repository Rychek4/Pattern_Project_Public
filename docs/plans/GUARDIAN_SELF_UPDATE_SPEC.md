# Guardian Update Spec: Self-Update Pipeline Support

**Context**: The Pattern project is adding a self-update pipeline
(`SELF_UPDATE_PIPELINE.md`) that allows Isaac to propose code changes via
Claude Code CLI on isolated git branches. This creates a narrow edge case
where Guardian restarts Pattern while the repo is on a non-`main` branch.

**This document is a spec for the Guardian project's Claude Code instance.**
It describes the changes needed in Guardian to support Pattern's self-update
pipeline safely.

---

## Problem

Pattern's self-update pipeline creates temporary `isaac/*` git branches,
runs Claude Code CLI on them, then checks out back to the original branch
via try/finally. The failure mode is:

1. Pattern's `CLIRunner.execute()` creates branch `isaac/some-feature`
2. `git checkout -b isaac/some-feature` succeeds
3. Claude Code CLI runs on the branch
4. **Pattern process is killed (SIGKILL, OOM, power loss) before the
   try/finally restores the original branch**
5. Guardian detects Pattern is dead and respawns it
6. Pattern starts on `isaac/some-feature` instead of `main`

This is a very narrow window (try/finally makes it SIGKILL-only), but
Guardian should handle it defensively.

### Current Guardian Restart Behavior

Guardian spawns Pattern via:
```python
subprocess.Popen(["python", str(executable_path)], ...)
```

It does not interact with git at all. Pattern inherits whatever branch the
repo happens to be on.

---

## Required Change: Pre-Restart Branch Check

### What to Add

Before spawning Pattern, Guardian should verify the repo is on the expected
branch. If not, check out the expected branch first.

### Where to Add It

In Guardian's restart/respawn logic, immediately before the
`subprocess.Popen` call that starts Pattern. The exact location depends on
Guardian's codebase structure — look for the function that spawns the Pattern
process.

### Implementation

```python
import subprocess
from pathlib import Path

def ensure_correct_branch(repo_path: str, expected_branch: str = "main") -> bool:
    """
    Verify the Pattern repo is on the expected branch before restart.
    If not, attempt to checkout the expected branch.

    Returns True if the repo is on (or was restored to) the expected branch.
    Returns False if checkout failed (Pattern should still be started —
    running on the wrong branch is better than not running at all).
    """
    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        current_branch = result.stdout.strip()

        if current_branch == expected_branch:
            return True

        # Log the unexpected state
        # (use Guardian's logging mechanism)
        log_warning(
            f"Pattern repo on unexpected branch '{current_branch}', "
            f"expected '{expected_branch}'. "
            f"This may be from a killed self-update. Restoring."
        )

        # Discard any uncommitted changes (self-update artifacts)
        # and checkout the expected branch
        subprocess.run(
            ["git", "checkout", "-f", expected_branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )

        # Verify
        verify = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10
        )
        if verify.stdout.strip() == expected_branch:
            log_info(
                f"Restored Pattern repo to '{expected_branch}' branch."
            )
            return True
        else:
            log_error(
                f"Failed to restore Pattern repo to '{expected_branch}'. "
                f"Currently on: {verify.stdout.strip()}"
            )
            return False

    except Exception as e:
        log_error(f"Branch check failed: {e}")
        return False  # Don't block restart on check failure
```

### Configuration

Add to Guardian's config (e.g., `guardian.toml` or equivalent):

```toml
# Expected git branch for the Pattern repo. Guardian will restore this
# branch before restarting Pattern if a self-update was interrupted.
expected_branch = "main"
```

If Guardian uses a Python config or environment variables instead of TOML,
the equivalent is:

```python
EXPECTED_BRANCH = os.getenv("GUARDIAN_EXPECTED_BRANCH", "main")
```

### Integration Point

Call `ensure_correct_branch()` immediately before spawning Pattern:

```python
# In Guardian's restart/respawn function:
ensure_correct_branch(
    repo_path=pattern_repo_path,    # e.g., "/opt/pattern"
    expected_branch=config.expected_branch  # e.g., "main"
)
# Always proceed with restart even if branch check fails —
# running on the wrong branch is better than not running.
process = subprocess.Popen(["python", str(executable_path)], ...)
```

### Important: Do NOT Block Restart on Failure

The branch check is best-effort. If `git checkout` fails (merge conflicts,
missing branch, corrupt repo), Guardian must still restart Pattern. A Pattern
instance on the wrong branch is recoverable; a Pattern instance that never
starts is not.

---

## What NOT to Change

- **No new dependencies**: This uses only `subprocess` and `pathlib` (stdlib).
- **No changes to heartbeat logic**: The heartbeat system is unrelated.
- **No changes to Pattern's restart triggers**: The conditions for restart
  (PID dead, heartbeat stale, etc.) remain the same.
- **No branch deletion**: Guardian should NOT delete `isaac/*` branches.
  They may contain proposed changes awaiting human review.

---

## Testing

### Manual Testing Steps

1. **Normal case**: With Pattern repo on `main`, verify Guardian spawns
   Pattern normally and the branch check is a no-op.

2. **Recovery case**: Manually checkout an `isaac/test-branch` in the Pattern
   repo, then kill Pattern. Verify Guardian:
   - Detects the wrong branch (check logs)
   - Checks out `main`
   - Spawns Pattern successfully

3. **Failure case**: Checkout a non-existent branch scenario is unlikely, but
   verify that if `git checkout` fails, Guardian still spawns Pattern anyway.

### Requires Testing After Claude Code CLI Install

The full end-to-end scenario (self-update creates branch → Pattern killed →
Guardian restores branch → Pattern restarts on main) should be tested after
the self-update pipeline is deployed and Claude Code CLI is installed on the
VPS. This is a low-priority test — the failure mode is narrow and the manual
recovery is trivial (`git checkout main`).

---

## Summary

| Item | Detail |
|------|--------|
| **Files changed** | 1 (Guardian's restart/respawn module) |
| **New function** | `ensure_correct_branch(repo_path, expected_branch)` |
| **Config addition** | `expected_branch` (default: `"main"`) |
| **Call site** | Immediately before `subprocess.Popen` for Pattern |
| **Failure behavior** | Best-effort; never blocks restart |
| **Dependencies** | None (stdlib only) |
| **Lines of code** | ~50 |
