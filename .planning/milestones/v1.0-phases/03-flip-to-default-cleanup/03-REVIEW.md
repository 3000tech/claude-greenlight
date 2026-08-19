---
phase: 03-flip-to-default-cleanup
reviewed: 2026-08-06T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - monitor.py
  - test_monitor.py
  - test_state_writer.py
  - hooks/state-writer.sh
  - hooks/working-lock.sh
  - hooks/install.sh
  - hooks/settings-snippet.json
  - README.md
  - docs/TEST-MATRIX.md
  - docs/RECERTIFICATION.md
  - .claude/CLAUDE.md
findings:
  critical: 1
  warning: 5
  info: 5
  total: 11
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-08-06
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the flip-to-default-cleanup phase: `scan_state_files()` becoming the
primary render/notify engine, the D-02a/D-02b jsonl-evidence fallbacks, the
SessionEnd tombstone sweep, the badge unification, `shell_tracker.py`
deletion, and the AskUserQuestion-lock retirement (D-04) across
`monitor.py`, both test suites, and the three `hooks/*.sh` scripts. The core
`scan_state_files()` staleness/bridge logic is carefully reasoned and has
extensive matching test coverage; I did not find a way to break it that the
233-test suite doesn't already exercise.

One clear-cut BLOCKER survives the shell scripts: `hooks/working-lock.sh`
runs under `set -eu` with unguarded `mkdir -p`/`touch`/`rm -f` calls,
directly contradicting the project's own "hooks must always exit 0"
contract (a contract `hooks/state-writer.sh` visibly goes out of its way to
uphold by *not* using `set -e`). The rest of the findings are lower-severity:
a plausible false-positive path in the new D-02a Esc-recovery heuristic, a
migration gap where the documented upgrade command doesn't clean up retired
AUQ-lock hook registrations, a test-isolation gap where most
`scan_state_files()` tests silently read the real (unmocked) `~/.claude/projects`,
and a handful of dead code / stale comments left behind by the shadow-mode
removal.

## Critical Issues

### CR-01: `hooks/working-lock.sh` can exit non-zero, violating the "hooks must always exit 0" contract

**File:** `hooks/working-lock.sh:23,41,43-44`
**Issue:**

The script declares `set -eu` (line 23) and then runs three bare,
unprotected filesystem commands:

```bash
lock_dir="$HOME/.claude/working-locks"
mkdir -p "$lock_dir"          # line 41
case "$mode" in
  set)   touch "$lock_dir/$sid" ;;   # line 43
  clear) rm -f "$lock_dir/$sid" ;;   # line 44
esac
exit 0
```

None of `mkdir -p`, `touch`, or `rm -f` are protected by `|| true` (unlike
line 25's `jq ... || true`, which shows the author *was* aware `set -e`
needed guarding for fallible commands, just not consistently). Under bash's
documented `-e` semantics, a bare statement (not the left side of `&&`/`||`,
not an `if`/`while` condition) that exits non-zero terminates the script
immediately — it never reaches the final `exit 0`.

This directly contradicts the project's own hook contract, stated
explicitly for the sibling script `hooks/state-writer.sh`:

> "Never emits decision-control stdout and never fails a session: every
> code path below ends in `exit 0`... this matters MORE here than for the
> Phase 1 diagnostic logger."

and reiterated in this phase's own constraints ("hooks must always exit 0
and write atomically... on a 9p mount"). `state-writer.sh` deliberately
does **not** use `set -e` for exactly this reason. `working-lock.sh` is the
one remaining lock hook after D-04 retires `auq-lock.sh`, so it is now the
sole non-`state-writer.sh` script gating WORKING detection — a `mkdir`/`touch`/`rm`
failure on the 9p mount this project explicitly calls out as fragile (see
`AUQ_LOCK`/`WORKING_LOCK` comments in `monitor.py` and the CLAUDE.md
constraint) would propagate a non-zero exit status back to Claude Code from
a `PreToolUse`/`UserPromptSubmit`/`Stop` hook — the exact failure mode this
codebase otherwise treats as unacceptable.

**Fix:** Either drop `set -e` (keep `set -u`) and mirror
`state-writer.sh`'s explicit-exit-0 discipline, or guard every fallible
statement:

```bash
set -u
...
mkdir -p "$lock_dir" 2>/dev/null || true
case "$mode" in
  set)   touch "$lock_dir/$sid" 2>/dev/null || true ;;
  clear) rm -f "$lock_dir/$sid" 2>/dev/null || true ;;
esac
exit 0
```

## Warnings

### WR-01: D-02a Esc-interrupt early recovery can misfire on a legitimate long turn, not just an interrupt

**File:** `monitor.py:755-764`
**Issue:**

```python
early_recovery = (
    STATE_PROMPT_STALE_SEC < age <= window
    and legacy_match is not None
    and legacy_match.get("working_locked") is False
    and isinstance(legacy_match.get("mtime"), (int, float))
    and legacy_match["mtime"] > mtime
)
```

This inspects the legacy row's raw `working_locked` boolean, not its overall
computed `status`. `working_locked` flips to `False` whenever the
stale-lock guard in `scan()` fires (`monitor.py:1054-1056`:
`if working_locked and latest_mtime > wlock_mtime + 5: working_locked = False`)
— i.e. whenever the jsonl's mtime advances past the working-lock's mtime by
more than 5 seconds, for *any* reason, not only a genuine Esc interrupt. If
Claude produces a long, tool-free stretch (e.g. an extended `thinking`
block or a text-only reply that Claude Code happens to flush mid-turn)
without any new `PreToolUse` re-arming the lock, the jsonl can advance past
the stale working-lock mtime purely from that flush — at which point
`working_locked` reads `False` even though `is_certainly_working()` (and
the legacy engine's actual `status`) would still correctly report WORKING.
Because D-02a only checks the raw lock flag and the raw mtime comparison —
not the legacy engine's `status` — this combination can flip the
hook-derived verdict to WAITING (and fire a notification) for a session
that is still genuinely working, not one that was interrupted.

No test in `Goal11_StateFileStaleness` exercises a tool-free long-generation
turn against this exact condition (all of them construct a synthetic
`legacy` list directly rather than deriving it from a `scan()` reproducing
this timing).

**Fix:** Require the legacy row's own computed `status` to also be
non-WORKING (or otherwise corroborate with `is_certainly_working`) before
trusting `working_locked is False` as interrupt evidence, e.g.:

```python
early_recovery = (
    STATE_PROMPT_STALE_SEC < age <= window
    and legacy_match is not None
    and legacy_match.get("working_locked") is False
    and legacy_match.get("status") != "WORKING"
    and isinstance(legacy_match.get("mtime"), (int, float))
    and legacy_match["mtime"] > mtime
)
```

### WR-02: Plain `bash hooks/install.sh` re-run does not clean up a pre-flip install's AUQ-lock registrations

**File:** `hooks/install.sh:155-166`, `README.md:59-65`
**Issue:**

The normal (non-flag) merge path only touches `.hooks.PreToolUse`,
`.hooks.UserPromptSubmit`, and `.hooks.Stop`, filtering out entries whose
command matches `working-lock\.sh` (and, for `Stop`, `auq-lock\.sh` too) —
but it never touches `.hooks.PostToolUse` or `.hooks.Notification`, which
is where a pre-Phase-3 install's `auq-lock.sh` entries for the
`AskUserQuestion` PostToolUse-clear and the Notification-set live (see the
fixture in `test_state_writer.py:784-816`, `Goal9_AuqLockRetired`). Running
the documented upgrade command (`bash hooks/install.sh`, called out in
README.md as step 4, "required") on an existing installation leaves those
stale `PostToolUse`/`Notification` `auq-lock.sh` entries — and the
`~/.claude/auq-locks/` directory `monitor.py`'s `scan()` still reads —
completely untouched. Only the separate, undocumented-in-README
`--remove-auq-lock` flag removes them. `install.sh`'s own header comment
acknowledges this is a deliberate, separately-gated follow-up, but the
user-facing README doesn't mention the extra step is needed when upgrading
from a pre-flip install, so an operator following the README alone will
silently keep the retired hook wired up.

**Fix:** Either fold `--remove-auq-lock`'s filtering into the default
install path (idempotent, since a fresh install has nothing to strip), or
add an explicit upgrade note to README.md's install section: "Upgrading
from a pre-3.x install? Also run `bash hooks/install.sh --remove-auq-lock`
once."

### WR-03: Most `scan_state_files()` tests are not hermetic — they silently fall through to the real, unmocked `~/.claude/projects`

**File:** `test_monitor.py:1141-1152` (`StateFileTestBase`), and ~55 call sites across `Goal9_StateFileVerdicts`, `Goal10_StateFileRobustness`, `Goal11_StateFileStaleness`, `Goal21_UnifiedBadge`
**Issue:**

`StateFileTestBase.setUp()` only repoints `monitor.STATE_DIR`:

```python
def setUp(self) -> None:
    self._tmp = TemporaryDirectory()
    self.root = Path(self._tmp.name)
    self._orig_state_dir = monitor.STATE_DIR
    monitor.STATE_DIR = self.root
```

It never repoints `monitor.PROJECTS_DIR`. Any test derived from this base
that calls `monitor.scan_state_files(...)` without an explicit
`legacy_sessions=` argument (the large majority — e.g. every test in
`Goal9_StateFileVerdicts`, `Goal10_StateFileRobustness`, and roughly half of
`Goal11_StateFileStaleness`) triggers the internal fallback
`legacy_sessions = scan(label_map, sessionid_to_label, container_info=container_info)`,
which walks the **real** `Path.home() / ".claude" / "projects"` on whatever
machine runs the suite. One test explicitly repoints `PROJECTS_DIR` to prove
"no second jsonl read" for a specific fallback
(`test_fallback_evidence_comes_from_passed_legacy_list_not_fresh_io`), which
shows the author was aware of the dependency for that one case but didn't
apply the same isolation systematically. In practice the synthetic session
ids used (`"a"`, `"keep"`, `"stale"`, …) are unlikely to collide with a real
session id, so this rarely produces a visibly-wrong assertion — but it makes
the suite non-hermetic (reads outside the test's own temp dir, behaves
differently depending on whether the machine running it has live Claude
Code sessions under `~/.claude/projects`) and undermines the "no second jsonl
read" guarantee the one explicit test above is trying to document as a
property of the whole class.

**Fix:** Have `StateFileTestBase.setUp()`/`tearDown()` also repoint
`monitor.PROJECTS_DIR` to an empty temp directory (or pass
`legacy_sessions=[]` uniformly), the same way `Goal13_HooklessFallback` and
`Goal6e_AliasKeyParityAcrossEngines` already do for their own local setUp.

### WR-04: Staleness gate trusts container-supplied `ts_ms` with no cross-check against clock drift

**File:** `monitor.py:540-550` (`_state_record_age`), `553-826` (`scan_state_files`)
**Issue:**

```python
def _state_record_age(obj: dict, mtime: float, now: float) -> float:
    ts_ms = obj.get("ts_ms")
    if isinstance(ts_ms, (int, float)) and ts_ms > 0:
        return now - (ts_ms / 1000.0)
    return now - mtime
```

`ts_ms` is written inside the container by `hooks/state-writer.sh` via
`date +%s%N` (its own clock domain), while `now = time.time()` is read on
the monitor host (Windows/WSL2). The docstring reasons that `mtime` "is
always trustworthy... but ts_ms is the more precise signal when present" —
but there is no bound check comparing the two before trusting `ts_ms`
outright for the `STATE_HEARTBEAT_STALE_SEC`/`STATE_PROMPT_STALE_SEC`
staleness comparisons. If a container's clock is skewed ahead of the host
(common failure mode for containers without NTP), `age` computed from
`ts_ms` under-reports the true age indefinitely, and the WORKING verdict
never recovers via the heartbeat-silence fallback even though the
underlying container/session is genuinely dead. If skewed behind, sessions
could flip to WAITING (and notify) prematurely. This is exactly the class of
failure the "Core Value" in `.claude/CLAUDE.md` calls out as unacceptable
("must keep telling the user this session needs you now reliably").

**Fix:** Clamp `ts_ms`-derived age against `mtime`-derived age (e.g. use
`min`/`max` or fall back to `mtime` whenever the two diverge by more than a
generous bound, such as a few minutes), so a skewed container clock can't
indefinitely suppress or force a staleness transition.

### WR-05: `container_display_name`/`session_display_name` prefix match has no word-boundary check

**File:** `monitor.py:1110-1141` (`container_display_name`)
**Issue:**

```python
if name.startswith(project):
    return name
return project
```

The intent (per the docstring) is to detect a launcher-suffixed duplicate
container name like `dev-tools-2` for project label `dev-tools`. But a bare
`str.startswith` has no boundary check: for `project="dev"` and an unrelated
docker-generated container `name="devops"` (or any container whose raw name
merely begins with the same characters as an unrelated project's label),
`"devops".startswith("dev")` is `True`, so the function would misidentify
`devops` as a disambiguating suffix of `dev` and display `devops` where the
plain project label was intended — a display-only mislabel, but one the
existing test suite (`Goal18_ContainerDisplayName`) doesn't cover, since its
one boundary-adjacent test (`test_shared_head_shorter_than_project_label_is_not_a_prefix_match`)
only checks the reverse direction (name shorter than project).

**Fix:** Require the character immediately after the shared prefix to be a
separator or end-of-string, e.g.:

```python
if name.startswith(project) and (len(name) == len(project) or name[len(project)] in "-_"):
    return name
```

## Info

### IN-01: `_STATE_ACTION_LABELS` contains entries for `last_event` values `hooks/state-writer.sh` can never write

**File:** `monitor.py:516-528`
**Issue:** The `"PreToolUse": "tool start"` and `"SubagentStop": "subagent"`
entries can never be exercised: `hooks/state-writer.sh`'s event-to-state
`case` statement (`hooks/state-writer.sh:132-169`) has no `PreToolUse`
branch at all (only `working-lock.sh` registers on `PreToolUse`, and it
writes to a different file entirely), and `SubagentStop` is an explicit
no-op (`exit 0` without writing). Since a state file's `last_event` field
can only ever be one of the events `state-writer.sh` actually handles, these
two dict entries are dead. Harmless (`_state_action_label` falls back
gracefully for any value), but misleading to a future maintainer skimming
the table for "what can `last_event` be."
**Fix:** Drop the two unreachable entries, or add a comment noting they are
aspirational/defensive rather than reachable today.

### IN-02: `test_state_writer.py`'s module docstring references a deleted function

**File:** `test_state_writer.py:1-3`
**Issue:** "...monitor.py's shadow-engine seam it feeds (scan_state_files,
diff_verdicts, select_render_sessions)." `diff_verdicts` was deleted in this
phase's shadow-mode-removal commits (`7b82ca0`/`db991fd`) along with
`filter_divergence_events`/`write_divergences`/`DIVERGENCE_LOG`. The
docstring is now inaccurate.
**Fix:** Update to `(scan_state_files, select_render_sessions)`.

### IN-03: `AUQ_LOCK_DIR`/`auq_locked` remains fully wired in `monitor.py` though nothing populates it by default anymore

**File:** `monitor.py:47,1017-1041,1059-1060,1101`; `test_monitor.py:371-444` (`Goal1e_AuqLockOverride`, `Goal1f_PermissionPromptOverride`)
**Issue:** `hooks/auq-lock.sh` is deleted from the repo and no longer
installed or registered by `hooks/install.sh`'s default path (D-04). Yet
`scan()` still reads `~/.claude/auq-locks/<sid>` and lets it override every
other WORKING signal. This is a documented, deliberate decision ("The live
parity confirmation that gates removing monitor.py's own auq-lock READ...
lives in the 03-UAT.md runbook... a separately-gated follow-up") — not a
functional bug — but as of this phase, on any fresh install, this ~25-line
code path (and the two dedicated test classes exercising it, which touch
the lock files directly rather than through a real hook) can never actually
be triggered by production traffic, since nothing writes to that directory
anymore. Worth tracking to closure rather than leaving indefinitely, since
it's easy for this to quietly bit-rot into a false sense of coverage.
**Fix:** No action required for this phase; flagging for the tracked
follow-up removal already referenced in the code comments.

### IN-04: Stale docstring claims `scan_state_files()` rows carry no `display_name`

**File:** `test_monitor.py:1983-1986`
**Issue:**
```python
def test_display_text_falls_back_to_name_for_shadow_engine_rows(self):
    """A row from the frozen state-file engine carries no display_name
    key at all — the fallback is what lets it render unchanged."""
```
This was true before this phase (03-01/03-04), when `scan_state_files()`
was described elsewhere in this same diff as "frozen" and pre-dated
`display_name` support. As of this phase, `scan_state_files()` does stamp
`display_name` on every row it produces
(`monitor.py:797`, `session_display_name(name, hostname, hostname_to_name)`).
The test still passes (it constructs a bare dict by hand), but the
docstring's factual claim about the production function is now wrong.
**Fix:** Reword the docstring to describe what it actually demonstrates
(the fallback path for *any* row missing `display_name`, e.g. a
hand-constructed dict or a future producer that forgets to set it), not a
claim about `scan_state_files()` specifically.

### IN-05: Three of 21 TEST-MATRIX cases this phase's fallbacks depend on remain unverified against a live Claude Code session

**File:** `docs/TEST-MATRIX.md:45-47` (rows 19, 20, 21)
**Issue:** Rows 19 (abandoned pre-tool prompt — the basis for
`STATE_PROMPT_STALE_SEC`'s shorter window), 20 (corrupt/partially-written
state file — the basis for the atomic tmp+rename requirement), and 21
(container without hooks installed — the basis for the `legacy_origin`
bridge this phase makes permanent) all have empty "Verified" columns, unlike
every other row (1-18), which carries a `2026-07-29 / cc 2.1.220` live
observation. This phase flips these three fallbacks into permanent,
default-on production behavior (per the phase's own framing: "hook-silence
pins", "legacy_origin bridge", "atomic tmp+rename") while their underlying
assumptions about Claude Code's actual runtime behavior are still only
reasoned/unit-tested, not confirmed live. `docs/RECERTIFICATION.md` exists
specifically to close this kind of gap on every version bump — worth
scheduling rows 19-21 into the next recertification pass explicitly rather
than treating the whole matrix as closed.
**Fix:** No code change; track closing the three empty "Verified" cells
against a live Claude Code session as a fast-follow.

---

_Reviewed: 2026-08-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
