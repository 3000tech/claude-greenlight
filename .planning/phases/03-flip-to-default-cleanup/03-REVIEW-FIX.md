# Phase 03: Code Review Fix Report

**Source review:** `.planning/phases/03-flip-to-default-cleanup/03-REVIEW.md`
**Scope:** Critical (CR-01) + Warnings (WR-01..WR-05). Info findings out of scope (not applied).
**Branch:** `feat/hook-refactor` (main working tree — no worktree/branch created)

## Summary

| Finding | Status | Commit | Notes |
|---|---|---|---|
| CR-01 | fixed | `e90a3fd` | `hooks/working-lock.sh`: dropped `set -e`, kept `set -u`, guarded every fallible fs op with `2>/dev/null \|\| true`, mirroring `state-writer.sh`'s discipline. |
| WR-01 | fixed: requires human verification | `e754fc5` | Added `legacy_match.get("status") != "WORKING"` corroboration to D-02a Esc-recovery condition. This is a logic-condition change — flagged per verification_strategy's logic-bug limitation for manual confirmation, even though all 236 tests pass and the fix does not touch the locked `STATE_PROMPT_STALE_SEC` floor or the "legacy evidence required" rule. |
| WR-02 | fixed (corrected) | `932500f`, corrected by `b94617a` | **Original resolution (932500f) was reverted by direction of the phase verifier — see below.** Corrected resolution: the default `bash hooks/install.sh` path does NOT remove `auq-lock.sh` registrations. D-04's retirement is gated (03-UAT.md Section H): a pre-flip install's `auq-lock.sh` entries must survive a plain install run untouched until the user confirms `needs_input` parity live and explicitly runs `--remove-auq-lock`. `install.sh`'s working-lock merge now filters at the COMMAND level (not entry level), so a pre-flip entry that co-locates an `auq-lock.sh` command alongside a `working-lock.sh` command in the same object no longer loses the `auq-lock.sh` command as a side effect of stripping the stale working-lock entry — this closes a preservation gap that predated this phase's WR-02 work too. The default path now prints an informational (non-removing, always exit-0) note when stale `auq-lock.sh` entries are detected, pointing at the gated `--remove-auq-lock` teardown. `--remove-auq-lock` itself is unchanged and remains the only removal path. Regression test inverted to `test_plain_install_preserves_pre_flip_auq_lock_entries_until_gated_removal` (asserts preservation across all four event arrays, including the co-located Stop entry, plus that `--remove-auq-lock` still removes everything). Added an "Upgrading from a pre-flip install" note to `docs/RECERTIFICATION.md` (not README.md, which has a locked automated gate in `03-04-PLAN.md` asserting the literal string `auq-lock` never appears there). |
| WR-03 | fixed | `c377021` | `StateFileTestBase.setUp()`/`tearDown()` now also repoint `monitor.PROJECTS_DIR` to an empty temp dir, matching the isolation `Goal13_HooklessFallback`/`Goal6e_AliasKeyParityAcrossEngines` already apply locally. Zero call-site changes needed. |
| WR-04 | fixed: requires human verification | `2bbed06` | Added a one-directional clock-skew guard to `_state_record_age`: only distrusts `ts_ms` when it under-reports age relative to `mtime` by more than `STATE_CLOCK_SKEW_GUARD_SEC` (300s) — guards only the dangerous "container clock ahead" direction (silently suppresses staleness recovery). Deliberately left the "container clock behind" direction untouched, since the entire `Goal11_StateFileStaleness` test suite (12+ tests) simulates staleness by writing a deliberately-backdated `ts_ms` into a fresh-mtime file; a symmetric clamp (as REVIEW.md's literal suggestion implied) would have broken that whole test suite and defeated the documented "prefer ts_ms over mtime" design. Flagged for human verification since this is a logic/threshold change, not just structural. Added regression test `test_working_record_with_clock_ahead_ts_ms_still_flips_stale`. |
| WR-05 | fixed | `a38b581` | Added a word-boundary check to `container_display_name()`: the character immediately after the shared prefix must be `-`/`_` or end-of-string. Added regression test for the `project="dev"` / `name="devops"` false-positive case. |

**Fixed:** 6 (all in scope) — 2 flagged `requires human verification` (WR-01, WR-04) per the logic-bug limitation in verification_strategy.
**Skipped:** 0

## Verification

- `python3 -m unittest discover -q` → **236 tests, OK** (started at 234 before WR-05/WR-04 each added one regression test: 234 → 235 → 236; the WR-02 correction replaced one test with another, net count unchanged).
- `bash -n` on every `hooks/*.sh` (`event-logger.sh`, `install.sh`, `state-writer.sh`, `working-lock.sh`) → all pass, no syntax errors.
- Manually exercised `hooks/install.sh` (no flag, then twice for idempotency, then `--remove-auq-lock`) against a synthetic pre-flip `settings.json` fixture (PreToolUse + PostToolUse + Notification + Stop all carrying `auq-lock.sh` entries, including one co-located with a `working-lock.sh` command in the same Stop entry) to confirm the corrected WR-02 fix: all 4 `auq-lock.sh` entries survive a plain install (idempotently), and `--remove-auq-lock` still removes all 4 on request.

## Design decisions respected

No fix contradicts a locked decision from `03-CONTEXT.md`:
- **D-02a** (Esc-recovery floor/legacy-evidence requirement): WR-01's fix only adds an additional corroboration check on top of the existing `STATE_PROMPT_STALE_SEC < age <= window` floor and `legacy_match is not None` requirement — it does not remove or weaken either.
- **D-03** (bg badge-only): untouched by any fix in scope.
- **D-04** (working-lock stays, auq-lock retired, retirement GATED behind 03-UAT.md Section H's live parity confirmation): CR-01 keeps `working-lock.sh` installed and functioning identically (same set/clear semantics), just fixes its exit-code contract. WR-02's original resolution (932500f) violated D-04's gated sequencing by folding removal into the default install path with no confirmation step — corrected by `b94617a` to preserve pre-flip `auq-lock.sh` entries by default and keep `--remove-auq-lock` as the sole, explicit, user-invoked removal path.

## Notes

- WR-04's REVIEW.md fix suggestion literally proposed a `min`/`max` bidirectional clamp between `ts_ms`- and `mtime`-derived age. Applied a narrower, one-directional version instead (see table above) because the bidirectional version would have broken the existing staleness test suite's simulation technique. This is "intelligent adaptation of guidance," not a deviation from the finding's underlying concern (Core Value: never silently fail to recover a dead WORKING session) — the one direction the finding actually flags as dangerous ("if a container's clock is skewed ahead... the WORKING verdict never recovers") is exactly the direction now guarded.
- WR-02's original resolution (932500f) was caught by the phase verifier as a violation of D-04's locked gated-retirement sequencing (03-CONTEXT.md, 03-UAT.md Section H, 03-04-PLAN.md must_have). This is a documented case of "the correct fix for a finding would change designed behavior" — per this fixer's own constraints, that should have been grounds to skip rather than apply the reviewer's literal PostToolUse/Notification sweep suggestion. Corrected by `b94617a` per explicit coordinator direction (not re-litigated): the default install path now preserves, `--remove-auq-lock` remains the only removal path.

---

_Fixed: 2026-08-06_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
