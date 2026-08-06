# Phase 03: Code Review Fix Report

**Source review:** `.planning/phases/03-flip-to-default-cleanup/03-REVIEW.md`
**Scope:** Critical (CR-01) + Warnings (WR-01..WR-05). Info findings out of scope (not applied).
**Branch:** `feat/hook-refactor` (main working tree — no worktree/branch created)

## Summary

| Finding | Status | Commit | Notes |
|---|---|---|---|
| CR-01 | fixed | `e90a3fd` | `hooks/working-lock.sh`: dropped `set -e`, kept `set -u`, guarded every fallible fs op with `2>/dev/null \|\| true`, mirroring `state-writer.sh`'s discipline. |
| WR-01 | fixed: requires human verification | `e754fc5` | Added `legacy_match.get("status") != "WORKING"` corroboration to D-02a Esc-recovery condition. This is a logic-condition change — flagged per verification_strategy's logic-bug limitation for manual confirmation, even though all 236 tests pass and the fix does not touch the locked `STATE_PROMPT_STALE_SEC` floor or the "legacy evidence required" rule. |
| WR-02 | fixed | `932500f` | Folded `--remove-auq-lock`'s command-level filter into the default `install.sh` merge path (applied globally via `with_entries` over all `.hooks` keys, not just PostToolUse/Notification — testing surfaced that PreToolUse could also carry a stale entry). Added regression test `test_plain_install_sweeps_stale_auq_lock_entries_from_a_pre_flip_install`. |
| WR-03 | fixed | `c377021` | `StateFileTestBase.setUp()`/`tearDown()` now also repoint `monitor.PROJECTS_DIR` to an empty temp dir, matching the isolation `Goal13_HooklessFallback`/`Goal6e_AliasKeyParityAcrossEngines` already apply locally. Zero call-site changes needed. |
| WR-04 | fixed: requires human verification | `2bbed06` | Added a one-directional clock-skew guard to `_state_record_age`: only distrusts `ts_ms` when it under-reports age relative to `mtime` by more than `STATE_CLOCK_SKEW_GUARD_SEC` (300s) — guards only the dangerous "container clock ahead" direction (silently suppresses staleness recovery). Deliberately left the "container clock behind" direction untouched, since the entire `Goal11_StateFileStaleness` test suite (12+ tests) simulates staleness by writing a deliberately-backdated `ts_ms` into a fresh-mtime file; a symmetric clamp (as REVIEW.md's literal suggestion implied) would have broken that whole test suite and defeated the documented "prefer ts_ms over mtime" design. Flagged for human verification since this is a logic/threshold change, not just structural. Added regression test `test_working_record_with_clock_ahead_ts_ms_still_flips_stale`. |
| WR-05 | fixed | `a38b581` | Added a word-boundary check to `container_display_name()`: the character immediately after the shared prefix must be `-`/`_` or end-of-string. Added regression test for the `project="dev"` / `name="devops"` false-positive case. |

**Fixed:** 6 (all in scope) — 2 flagged `requires human verification` (WR-01, WR-04) per the logic-bug limitation in verification_strategy.
**Skipped:** 0

## Verification

- `python3 -m unittest discover -q` → **236 tests, OK** (started at 234 before WR-05/WR-04 each added one regression test: 234 → 235 → 236).
- `bash -n` on every `hooks/*.sh` (`event-logger.sh`, `install.sh`, `state-writer.sh`, `working-lock.sh`) → all pass, no syntax errors.
- Manually exercised `hooks/install.sh` (no flag) against a synthetic pre-flip `settings.json` fixture (PreToolUse + PostToolUse + Notification + Stop all carrying `auq-lock.sh` entries, including one co-located with a `working-lock.sh` command in the same Stop entry) to confirm the WR-02 fix sweeps every array while leaving `working-lock.sh` intact.

## Design decisions respected

No fix contradicts a locked decision from `03-CONTEXT.md`:
- **D-02a** (Esc-recovery floor/legacy-evidence requirement): WR-01's fix only adds an additional corroboration check on top of the existing `STATE_PROMPT_STALE_SEC < age <= window` floor and `legacy_match is not None` requirement — it does not remove or weaken either.
- **D-03** (bg badge-only): untouched by any fix in scope.
- **D-04** (working-lock stays, auq-lock retired): CR-01 keeps `working-lock.sh` installed and functioning identically (same set/clear semantics), just fixes its exit-code contract. WR-02 extends the *removal* of stale `auq-lock.sh` registrations to the default install path — consistent with, not contradicting, D-04's retirement.

## Notes

- WR-04's REVIEW.md fix suggestion literally proposed a `min`/`max` bidirectional clamp between `ts_ms`- and `mtime`-derived age. Applied a narrower, one-directional version instead (see table above) because the bidirectional version would have broken the existing staleness test suite's simulation technique. This is "intelligent adaptation of guidance," not a deviation from the finding's underlying concern (Core Value: never silently fail to recover a dead WORKING session) — the one direction the finding actually flags as dangerous ("if a container's clock is skewed ahead... the WORKING verdict never recovers") is exactly the direction now guarded.

---

_Fixed: 2026-08-06_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
