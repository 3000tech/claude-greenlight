---
phase: 01-hook-coverage-verification
reviewed: 2026-07-29T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - README.md
  - hooks/event-logger.sh
  - hooks/hook-events.json
  - hooks/install.sh
  - test_event_logger.py
findings:
  critical: 0
  warning: 5
  info: 1
  total: 6
status: fixed
fixed_at: 2026-07-29T09:00:00Z
fix_report: 01-REVIEW-FIX.md
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-29T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** fixed (see `01-REVIEW-FIX.md`)

## Summary

Reviewed the Phase 1 diagnostic instrument: `hooks/event-logger.sh` (JSONL logger for hook events), `hooks/hook-events.json` (24-event registration catalog), `hooks/install.sh` (idempotent installer/teardown that must not disturb the pre-existing `auq-lock`/`working-lock` entries), and `test_event_logger.py` (18 subprocess-driven tests). All 18 tests pass as written, and the two critical invariants called out in the task brief — `event-logger.sh` always exits 0, and `install.sh` preserves the lock-hook entries across install/remove — hold up under direct verification (confirmed by running the installer against hand-crafted `settings.json` fixtures, not just trusting the test suite).

No Critical/BLOCKER findings. Five Warnings were confirmed by direct reproduction (not just code reading): `install.sh --remove-logger` crashes with a raw jq error on a `settings.json` that has no `hooks` key yet; `install.sh` silently performs a full (re)install instead of erroring when given an unrecognized/mistyped flag; the size-guard truncation in `event-logger.sh` has a read-check-truncate race that can silently drop log lines under concurrent hook firing (a step beyond the append-only race the project's own RESEARCH.md already accepts); the Notification `message` field is captured by value despite not appearing in the script's own "content-bearing, therefore excluded" list, which is in tension with the stated "no content-bearing payload fields by default" invariant; and the test suite's jq-availability guard raises `unittest.SkipTest` at module import time, which unittest does **not** handle gracefully — it aborts the whole run with a traceback and exit code 1 instead of a clean skip. One Info-level redundant conditional was also found.

## Warnings

### WR-01: `install.sh --remove-logger` crashes on a `settings.json` without a `hooks` key

**Status:** Fixed (commit `07c17ca`)

**File:** `hooks/install.sh:48-51`
**Issue:** The teardown path does:
```jq
def has_logger: [.hooks[]?.command] | any(. // "" | test("event-logger\\.sh"));
.hooks |= with_entries(.value |= map(select(has_logger | not)))
```
`with_entries` requires an object; if `.hooks` is absent (i.e. the settings file exists but nothing has ever registered a hook — a realistic state for a `~/.claude/settings.json` that only carries e.g. model preferences), `.hooks` evaluates to `null` and `with_entries` throws `null (null) has no keys`. Because `install.sh` runs under `set -euo pipefail`, this aborts the script with jq's exit code (verified: exit 5), leaving a stray `settings.json.tmp` file behind (the pre-existing `settings.json.bak.*` backup is harmless, but the operation itself fails instead of no-op'ing). Reproduced directly:
```
$ echo '{}' > ~/.claude/settings.json
$ bash hooks/install.sh --remove-logger
jq: error (at .../settings.json:1): null (null) has no keys
$ echo $?
5
```
The main install path already guards this correctly via `(.hooks.X // [])` defaults; the removal path does not. No test in `test_event_logger.py` covers this because `Goal7`'s `setUp()` always runs a full `_run_install()` first, so `.hooks` is always populated by the time `--remove-logger` runs in the suite.
**Fix:**
```jq
def has_logger: [.hooks[]?.command] | any(. // "" | test("event-logger\\.sh"));
.hooks = ((.hooks // {}) | with_entries(.value |= map(select(has_logger | not))))
```
Also add a regression test: run `--remove-logger` against a freshly-created `settings.json` (`{}` or a file with unrelated top-level keys but no `hooks`) and assert exit code 0.

### WR-02: `install.sh` silently performs a full install on an unrecognized argument

**Status:** Fixed (commit `5ad4dfa`)

**File:** `hooks/install.sh:40-56`
**Issue:** `mode="${1:-install}"` is only ever compared against the literal string `--remove-logger`; any other value (including a typo like `--remove-logge`) falls through to the full install path with no error. Reproduced directly:
```
$ bash hooks/install.sh --remove-logge
installed: .../auq-lock.sh
installed: .../working-lock.sh
installed: .../event-logger.sh
created: .../settings.json
registered: event-logger.sh on 24 event(s) in .../settings.json
```
A user intending to tear the instrument down gets a fresh install instead, with no diagnostic that their flag was not recognized.
**Fix:**
```bash
mode="${1:-install}"
if [ $# -gt 0 ] && [ "$1" != "--remove-logger" ]; then
  echo "unknown argument: $1 (expected: --remove-logger)" >&2
  exit 1
fi
```

### WR-03: Size-guard truncation in `event-logger.sh` has a read-check-truncate race that can drop log lines

**Status:** Fixed (commit `09cfc22`) — requires human verification (concurrency logic; see REVIEW-FIX.md)

**File:** `hooks/event-logger.sh:97-111`
**Issue:** The size guard does a plain read-then-act sequence with no locking:
```bash
if [ -f "$LOG" ]; then
  log_size=$(stat -c%s "$LOG" 2>/dev/null)
  ...
  if [ "$log_size" -gt "$MAX_BYTES" ]; then
    : > "$LOG"
    ... append marker ...
  fi
fi
...
printf '%s\n' "$line" >> "$LOG"
```
When multiple hooks fire close together (routine for this project — e.g. `PreToolUse` and the pre-existing `auq-lock`/`working-lock` hooks, or several subagents), two `event-logger.sh` invocations can both observe the log past the 5 MB threshold and both truncate. Whichever truncates second wipes out whatever the first process appended (marker line and/or its own event line) between the two truncations. This is a stronger risk than the append-only interleaving race the project's own `01-RESEARCH.md` (Assumptions Log, A1) already accepts as bounded ("some events lost during races, not a crash") — that assumption covers concurrent `>>` appends, not a concurrent truncate racing an append, which can silently erase more than one line's worth of otherwise-successful writes. No test exercises concurrent invocations.
**Fix:** Serialize the check-truncate-append critical section with `flock`, e.g.:
```bash
{
  flock -x 9
  if [ -f "$LOG" ]; then
    log_size=$(stat -c%s "$LOG" 2>/dev/null || echo 0)
    if [ "$log_size" -gt "$MAX_BYTES" ]; then
      : > "$LOG"
      printf '%s\n' "$marker" >> "$LOG"
    fi
  fi
  printf '%s\n' "$line" >> "$LOG"
} 9>"$LOG.lock"
```
(Keep the `flock` call itself best-effort / non-fatal so a locking failure still falls through to `exit 0`, preserving the "never break a session" invariant.)

### WR-04: Notification `message` is captured by value without being in the script's own content-bearing exclusion list

**Status:** Fixed (commit `7c4d8a1`) — implemented per explicit user decision: kept `message` captured by default, truncated to 200 chars; full value only under `GREENLIGHT_LOG_RAW=1`.

**File:** `hooks/event-logger.sh:13-24, 70`
**Issue:** The header comment explicitly enumerates what must stay excluded because it can carry secrets — `tool_input, tool_response/tool_output, prompt, last_assistant_message` — and the code correctly omits those from the default capture. `message` (Notification's payload field) is captured by value in the jq filter (`notification_type, message,`) and is not on that exclusion list. Per the phase's own `01-RESEARCH.md` (doc-fetch ambiguity notes), the exact shape/content of Notification `message` was never confirmed before this was written — it may be a short fixed string ("Claude needs your permission") or it may echo back contentful text (tool name, a path, or a command fragment) depending on the notification type, which is precisely the kind of value the "no content-bearing payload fields by default" invariant is meant to guard against. As written, any content that does end up in `message` lands unredacted on the shared `~/.claude` bind mount by default, with no raw-opt-in gate.
**Fix:** Either (a) move `message` behind the same `GREENLIGHT_LOG_RAW` gate as other content-bearing fields until the live UAT confirms its actual content is safe, or (b) once confirmed safe via the live log, add an explicit note next to the header's exclusion list stating why `message` was kept by default. Minimal code change for (a):
```jq
{
  ts: (now | todate), ts_ms: (now * 1000 | floor), event: .hook_event_name,
  session_id, cwd, keys: (keys),
  source, reason, trigger, matcher, permission_mode,
  tool_name, tool_use_id, notification_type,
  agent_type, agent_id, subagent_type, task_id, stop_hook_active
}
+ (if $raw_flag == "1" then {raw: $payload, message} else {} end)
```

### WR-05: `test_event_logger.py`'s jq-availability guard aborts the suite instead of skipping cleanly

**Status:** Fixed (commit `e36b0f4`)

**File:** `test_event_logger.py:33-34`
**Issue:**
```python
if shutil.which("jq") is None:
    raise unittest.SkipTest("jq is required to run hooks/event-logger.sh and is not on PATH")
```
This runs at module import time, outside any test/`setUpModule` context. `unittest.SkipTest` raised during a bare module import is **not** caught by the loader as a skip — it propagates as an ordinary exception through `__import__`, producing a full traceback and a non-zero exit code. Verified directly:
```
$ PATH=<python-only> python3 -m unittest test_event_logger.py -v
Traceback (most recent call last):
  ...
  File "test_event_logger.py", line 34, in <module>
    raise unittest.SkipTest("jq is required to run hooks/event-logger.sh and is not on PATH")
unittest.case.SkipTest: jq is required to run hooks/event-logger.sh and is not on PATH
$ echo $?
1
```
On any machine/CI runner without `jq` on PATH, the exact command documented in `README.md` (`python3 -m unittest test_event_logger.py`) fails hard instead of reporting a clean, intentional skip — indistinguishable at a glance from a real regression.
**Fix:** Move the guard into `setUpModule()`, which unittest *does* special-case for `SkipTest` (verified: produces `OK (skipped=1)`, exit 0):
```python
def setUpModule() -> None:
    if shutil.which("jq") is None:
        raise unittest.SkipTest("jq is required to run hooks/event-logger.sh and is not on PATH")
```

## Info

### IN-01: Redundant non-empty check after an already-guaranteed-non-empty value

**Status:** Fixed (commit `d29396e`)

**File:** `hooks/event-logger.sh:88-90, 113-115`
**Issue:** Line 88-90 already does `if [ -z "$line" ]; then exit 0; fi`, so by line 113 `$line` is guaranteed non-empty. The subsequent `if [ -n "$line" ]; then printf ... fi` is dead-guard code — harmless, but it's redundant and slightly obscures that the append always happens at that point.
**Fix:** Drop the redundant guard:
```bash
printf '%s\n' "$line" >> "$LOG"
```

---

_Reviewed: 2026-07-29T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
