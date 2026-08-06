---
phase: 03-flip-to-default-cleanup
verified: 2026-08-06T00:00:00Z
status: human_needed
score: 21/21 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 20/21
  gaps_closed:
    - "The needs_input parity gate (Section H of 03-UAT.md) must be cleared before the retired auq-lock hook's registrations are removed from an existing/pre-flip install (D-04)"
  gaps_remaining: []
  regressions: []
---

# Phase 3: Flip to Default & Cleanup Verification Report

**Phase Goal:** The state-file engine is trusted enough to be the default — legacy jsonl parsing is deleted, tests are rewritten against state files, and the docs describe the architecture that actually ships.
**Verified:** 2026-08-06
**Status:** human_needed
**Re-verification:** Yes — after gap closure (commits `b94617a` + `b5e69cd`)

## Re-verification Summary

The prior pass (score 20/21) found one BLOCKER: the WR-02 review-fix (`932500f`) had folded `--remove-auq-lock`'s sweep into the *default* `bash hooks/install.sh` path, so a single flagless install run silently stripped every `auq-lock.sh` registration — bypassing D-04's live needs_input-parity gate (`03-UAT.md` Section H) and contradicting `03-04-PLAN.md`'s own must_have ("the runbook contains an explicit needs_input parity gate the user must clear before removing the retired lock hook from a live install"). Reproduced empirically in-sandbox at the time (4 → 0 auq-lock entries after one flagless install).

The coordinator applied remediation option 1 from the prior report (revert the default-install sweep; keep gated removal only via `--remove-auq-lock`), commits `b94617a` (fix) + `b5e69cd` (docs). Re-verification below confirms the fix and closes the gap; no regressions found.

### Direct reproduction of the original repro, re-run against the fixed code

```
BEFORE:  auq-lock entries = 4 (PreToolUse/PostToolUse/Notification/Stop, including one co-located
         with a working-lock.sh command inside the same Stop entry object)
RUN:     bash hooks/install.sh                      (no flag — the "required" README step)
AFTER:   auq-lock entries = 4   ← PRESERVED (was 0 before the fix — this is the confirmed reversal)
         working-lock entries = 3  (correctly re-registered on PreToolUse/UserPromptSubmit/Stop)
RUN AGAIN: bash hooks/install.sh                     (idempotency check)
AFTER:   auq-lock entries = 4 (unchanged, still no duplication), working-lock entries = 3 (unchanged)
RUN:     bash hooks/install.sh --remove-auq-lock
AFTER:   auq-lock entries = 0   ← fully removed, only via the explicit gated flag
         working-lock entries = 3  ← untouched, including the entry that was co-located with an
                                      auq-lock.sh command (the entry-level collateral-damage bug
                                      the coordinator also fixed in this same pass)
```

All of this was re-run live in this verification pass (not taken on the coordinator's word) using the identical synthetic pre-flip `settings.json` fixture from the original repro. Every step matched the coordinator's claim exactly.

### What else was checked

- `python3 -m unittest discover -q` → **236 tests, OK** (unchanged from before — the WR-02 correction replaced one test with its inverse, `test_plain_install_preserves_pre_flip_auq_lock_entries_until_gated_removal`, net count unchanged).
- `bash -n hooks/install.sh` → exits 0, clean syntax.
- `test_state_writer.py#Goal9_AuqLockRetired` (6 tests, including the new preservation test) → all pass.
- `docs/RECERTIFICATION.md` gained an "Upgrading from a pre-flip install" section (lines 15-31) stating plainly that a plain install does **not** remove auq-lock registrations, quoting the installer's own informational note, and pointing at `03-UAT.md` Section H as the gate to clear before running `--remove-auq-lock`. File is 89 lines — still under the plan's 100-line ceiling.
- `README.md` — confirmed zero occurrences of `auq-lock` or `--state-files` (`grep -c` → 0), consistent with `03-04-PLAN.md`'s locked prohibition against naming the retired script there; the upgrade note correctly lives in `docs/RECERTIFICATION.md` instead, not README.
- `.planning/phases/03-flip-to-default-cleanup/03-UAT.md` — left untouched by the coordinator's fix, and correctly so: with the sweep reverted, Setup step 3's original assumption ("if this container's settings.json carries a pre-flip auq-lock.sh registration... that count will be > 0 here — that is the existing-install case Section H's teardown addresses") is true again against the corrected installer. No stale text remains.
- `.planning/phases/03-flip-to-default-cleanup/03-REVIEW-FIX.md` — WR-02's row updated to describe the correction, explicitly named as reverted "by direction of the phase verifier," with the corrected reasoning and a `Notes` entry acknowledging the original fix violated a locked decision. Accurate and matches what shipped.

No new regressions were introduced by the fix: the co-located-command preservation logic (working-lock's merge filtering at the command level, not the entry level) actually *fixed* a pre-existing collateral-damage bug in the default-merge path as a side effect (a pre-flip Stop entry sharing one object between an `auq-lock.sh` command and a `working-lock.sh` command previously risked losing the `auq-lock.sh` half when the working-lock merge ran; now both entries individually survive intact).

## Goal Achievement (updated)

All 21 previously-derived truths now verify. Truth #21 ("The needs_input parity gate is cleared before auq-lock is removed from a live install") flips from ✗ FAILED to ✓ VERIFIED:

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 21 | The needs_input parity gate (D-04/Section H) is cleared before auq-lock is removed from a live install | ✓ VERIFIED | `hooks/install.sh`'s default merge path no longer touches `auq-lock.sh` entries in any array; a pre-flip install's registrations survive a flagless `bash hooks/install.sh` run (and repeated runs) untouched; only `bash hooks/install.sh --remove-auq-lock` removes them, and `03-UAT.md`'s Teardown step still correctly gates that flag behind Section H passing — reproduced directly in this sandbox, not taken on report |

(Truths 1-20 are unchanged from the prior pass — see the git history of this file, or the phase's plans/summaries, for their individual evidence; nothing in the coordinator's fix touched any of that surface. Re-checked for regression via the full 236-test run above.)

**Score:** 21/21 truths verified (0 present-but-behavior-unverified, 0 failed).

## Human Verification Required

The following were already correctly identified as expected human/live-machine work (D-12) in the prior pass and remain outstanding — none of them are gaps; all have a runbook.

### 1. Full 03-UAT.md live run (Sections A-I) on the Windows machine

**Test:** Execute `.planning/phases/03-flip-to-default-cleanup/03-UAT.md` end to end against real Docker containers and a live Claude Code session.
**Expected:** All nine lettered sections pass as specified (render seam live, Esc-recovery ~90s, hook-silence pin, hookless bridge, ghost suppression, paused-container visibility, badge-only turn-end, needs_input parity, preserved fixes). Section H (BLOCKING) in particular must now be exercised against a *pre-flip* live install with real `auq-lock.sh` registrations still present (now guaranteed to survive Setup, per this re-verification) to prove the gate is meaningful in practice, not just in the code path.
**Why human:** D-12 scopes all live container/session behavior to the Windows machine; this execution environment has no Docker and no live Claude Code session.

### 2. WR-01/WR-04 logic-change confirmation

**Test:** Observe a real tool-free long-generation turn (WR-01's D-02a corroboration) and a container with a deliberately skewed clock (WR-04's clock-skew guard) against the live monitor.
**Expected:** No false-positive Esc-recovery on the long turn; no false suppression/forcing of staleness transitions from clock skew.
**Why human:** `03-REVIEW-FIX.md` itself flags both as "requires human verification" despite passing unit tests — a logic/threshold change the review process explicitly declines to consider closed by tests alone.

### 3. TEST-MATRIX rows 19-21 (IN-05)

**Test:** Exercise the abandoned-pre-tool-prompt, corrupt-state-file, and hookless-container cases live and record the outcome in `docs/TEST-MATRIX.md`'s Verified column.
**Expected:** Live behavior confirms the reasoned/unit-tested assumptions behind the short-window recovery, atomic tmp+rename, and `legacy_origin` bridge fallbacks this phase makes permanent.
**Why human:** No Claude Code session or Docker container available in this execution environment; `docs/RECERTIFICATION.md` exists for exactly this closure but has not yet been run against these three rows.

## Conclusion

The one BLOCKER gap from the prior verification pass is closed and confirmed by direct, independent reproduction in this environment (not taken on the coordinator's report alone). All 21 derived truths now verify against the codebase: the render-seam flip, the three-consumer hybrid model, badge unification, tombstone/sweep logic, FLIP-02's coverage bar, FLIP-03's documentation promotion, and the D-04 gated-retirement sequencing are all solidly implemented, tested (236 green tests), and internally consistent across code, tests, and docs.

What remains is exclusively the live-machine work D-12 always scoped to the Windows environment — expected, not a gap, and already has a runbook (`03-UAT.md`) plus a recertification loop (`docs/RECERTIFICATION.md`) for closing it.

---

_Verified: 2026-08-06_
_Verifier: Claude (gsd-verifier)_
