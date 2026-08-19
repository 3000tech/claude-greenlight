---
phase: 01-hook-coverage-verification
fixed_at: 2026-07-29T09:00:00Z
review_path: .planning/phases/01-hook-coverage-verification/01-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-07-29T09:00:00Z
**Source review:** .planning/phases/01-hook-coverage-verification/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (5 Warnings + 1 Info, per `--fix` scope `all`)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### WR-01: `install.sh --remove-logger` crashes on a `settings.json` without a `hooks` key

**Files modified:** `hooks/install.sh`, `test_event_logger.py`
**Commit:** `07c17ca`
**Applied fix:** Changed the removal-path jq filter from `.hooks |= with_entries(...)` to `.hooks = ((.hooks // {}) | with_entries(...))`, matching the null-guard pattern already used on the install path. Added two regression tests (`Goal7b_RemovalPathOnUnpopulatedSettings`) covering `--remove-logger` against `{}` and against a settings file with unrelated top-level keys but no `hooks` key — both now assert exit code 0. Verified by direct reproduction: `echo '{}' > settings.json && bash install.sh --remove-logger` now exits 0 (was exit 5 with a jq traceback).

### WR-02: `install.sh` silently performs a full install on an unrecognized argument

**Files modified:** `hooks/install.sh`, `test_event_logger.py`
**Commit:** `5ad4dfa`
**Applied fix:** Added an argument-validation guard immediately after `mode="${1:-install}"`: any first argument other than `--remove-logger` now prints `unknown argument: $1 (expected: --remove-logger)` to stderr and exits 1, before any install/removal side effects run. Added `test_unrecognized_argument_errors_and_does_not_install` (Goal 5) asserting non-zero exit, the stderr message, and that neither `~/.claude/hooks/` nor `settings.json` get created. Verified normal `install` and `--remove-logger` paths still exit 0 as before.

### WR-03: Size-guard truncation in `event-logger.sh` has a read-check-truncate race that can drop log lines

**Files modified:** `hooks/event-logger.sh`, `test_event_logger.py`
**Commit:** `09cfc22`
**Applied fix:** Implemented per the user's explicit decision, which differs slightly from the review's suggested patch (blocking `flock -x 9`): wrapped the check-truncate-append critical section in a subshell holding fd 9 on `$LOG.lock`, using `flock -w 0.5 9` (short-wait, not indefinite blocking). If the lock isn't acquired within 0.5s, the truncation check is skipped for that invocation but the line is still appended (unprotected, same as the pre-existing accepted append-only race) — this preserves the hard "never hang a session, always exit 0" invariant over stronger race protection. Added `test_concurrent_invocations_racing_the_size_guard_lose_no_lines`, which fires 20 concurrent `event-logger.sh` invocations against a pre-filled oversized log and asserts all 20 distinct `session_id`s survive (no lines dropped by a racing truncation). All 22 pre-existing tests plus this new test pass.
**Note:** This is a concurrency-race fix; flagged for human verification below since automated tests (even the added concurrency test) cannot exhaustively prove absence of races under all timing conditions on all platforms.

### WR-04: Notification `message` captured by value without being on the script's own content-bearing exclusion list

**Files modified:** `hooks/event-logger.sh`, `test_event_logger.py`
**Commit:** `7c4d8a1`
**Applied fix:** Implemented per the user's explicit decision (a middle option between the review's two alternatives): kept `message` captured by default (not moved fully behind the raw gate), but truncate it to 200 characters (`+ "…[truncated]"` suffix) in the default jq output. Under `GREENLIGHT_LOG_RAW=1`, the full untruncated `message` value is preserved. Updated the header comment to document this explicitly. Added three tests: long message truncated to ≤220 chars (200 + suffix) by default and not equal to the original; short message passes through untruncated; raw opt-in preserves the full untruncated value. Verified manually with a 300-char message in both default and raw modes.

### WR-05: `test_event_logger.py`'s jq-availability guard aborts the suite instead of skipping cleanly

**Files modified:** `test_event_logger.py`
**Commit:** `e36b0f4`
**Applied fix:** Moved the `shutil.which("jq") is None` check from bare module-import scope into a new `setUpModule()` function, which `unittest` does special-case for `SkipTest`. Verified directly: running the suite with a `jq`-less `PATH` now produces `setUpModule (test_event_logger) ... skipped '...'` / `OK (skipped=1)` / exit 0, instead of the prior unhandled traceback / exit 1. Normal (jq present) runs are unaffected — all 25 tests still collect and pass.

### IN-01: Redundant non-empty check after an already-guaranteed-non-empty value

**Files modified:** `hooks/event-logger.sh`
**Commit:** `d29396e`
**Applied fix:** Simplified the append call sites (inside the WR-03 lock-protected subshell and in its fallback branch) to a direct `printf '%s\n' "$line" >> "$LOG"` with a one-line comment noting `$line` is already guaranteed non-empty by the earlier `if [ -z "$line" ]; then exit 0; fi` check, instead of re-guarding with `if [ -n "$line" ]; then ... fi` in two places. Purely a readability simplification; no behavior change (confirmed by full test suite still passing).

## Skipped Issues

None — all findings were fixed.

## Verification

- `python3 -m unittest test_event_logger.py`: 25/25 pass.
- `python3 -m unittest test_monitor.py`: 56/56 pass.
- Also verified: `test_event_logger.py` cleanly reports `OK (skipped=1)` / exit 0 on a `jq`-less `PATH` (WR-05 regression check).

## Human Verification Needed

- **WR-03** (`hooks/event-logger.sh` size-guard flock): the concurrency fix passed an added 20-way concurrent-invocation test locally, but lock-contention behavior can vary across filesystems/platforms (the project runs inside Docker/WSL2 per project conventions). Recommend a quick live smoke check — fire several hook events in rapid succession during a real session and confirm `hook-events.log` still parses cleanly and no lines are silently dropped around a truncation boundary — before treating this as fully closed.

---

_Fixed: 2026-07-29T09:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
