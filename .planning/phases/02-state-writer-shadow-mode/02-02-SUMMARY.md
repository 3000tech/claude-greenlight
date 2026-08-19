---
phase: 02-state-writer-shadow-mode
plan: 02
subsystem: infra
tags: [bash, jq, hooks, monitor, shadow-mode, state-machine]

# Dependency graph
requires:
  - phase: 02-state-writer-shadow-mode
    plan: 01
    provides: hooks/state-writer.sh's atomic tmp+rename write path (Stop-only tracer), the state-writer-events.json registration list, and install.sh's --remove-state-writer teardown skeleton
provides:
  - hooks/state-writer.sh — the complete D-08 event-to-state mapping (UserPromptSubmit, PostToolUse/PostToolUseFailure/PostToolBatch, PermissionRequest, Notification, SessionStart idle/compact-guard, Stop background-task gate, SubagentStop no-op, SessionEnd removal)
  - test_state_writer.py Goal5-Goal8 (25 new tests) locking down the mapping, the turn-end semantics, the teardown path, and the SW-03 migration guarantee
affects: [02-state-writer-shadow-mode remaining plans (02-03..02-05), Phase 3 legacy-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Resolve a payload-derived gate value (background_tasks_count) exactly once per invocation and pass it by variable into both the branching decision and the jq record builder, so the two can never disagree"
    - "Handle the one destructive/no-`state` branch (SessionEnd's rm -f) ahead of the state-resolution case, since it has nothing to resolve"

key-files:
  created: []
  modified:
    - hooks/state-writer.sh
    - test_state_writer.py

key-decisions:
  - "background_tasks_count computed once, before the event case statement, from the deny-list rule (not completed/not failed counts as in-flight, including entries with no status key at all) — feeds both the Stop gate and the record field so they can never diverge (per RESEARCH assumption A2, carried over from plan 02-01)"
  - "SessionStart with source=compact exits 0 without writing rather than writing idle, since /compact re-fires SessionStart on the SAME session_id mid-turn (TEST-MATRIX case 11) — writing here would blank a live working state"
  - "SubagentStop is an explicit branch that exits 0, not an implicit fall-through to the default case — TEST-MATRIX case 12 recorded it arriving after the parent's Stop twice, so the no-op has to be intentional and tested, not accidental"
  - "hooks/install.sh's --remove-state-writer was already complete from plan 02-01 (mirrors --remove-logger's backup/sweep/validate/mv shape exactly, including the null-.hooks guard); Task 3 of this plan added the Goal7/Goal8 regression tests rather than new install.sh code"

patterns-established:
  - "Compute-once-use-twice for any value that both gates a branch and appears in the record it produces — prevents the gate and the recorded number from silently disagreeing"

requirements-completed: [SW-01, SW-02, SW-03, ENG-06]

coverage:
  - id: D1
    description: "Every in-turn event (UserPromptSubmit working; PostToolUse/PostToolUseFailure/PostToolBatch working; PermissionRequest/Notification needs_input; SessionStart idle unless source=compact, which writes nothing) resolves to the TEST-MATRIX D-08 verdict"
    requirement: "SW-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal5_EventToStateMapping (5 tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Stop resolves waiting when background_tasks_count is zero and working when non-terminal tasks are in flight, using a deny-list (not completed/not failed) so an undocumented status value can't undercount; SubagentStop never mutates the file; SessionEnd unconditionally removes it for every reason value; no background_tasks descriptor text ever reaches the written file"
    requirement: "SW-02"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal6_TurnEndSemantics (7 tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "hooks/install.sh --remove-state-writer strips every state-writer entry from settings.json, no-ops cleanly on {} or a missing settings.json, preserves working-lock/auq-lock/event-logger entry counts and unrelated settings content, and --bogus-flag still errors without installing anything"
    requirement: "SW-03"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal7_RemovalPath (5 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "working-lock/auq-lock command counts and script bytes are identical across install, reinstall, and --remove-state-writer teardown — the migration guarantee is asserted by tests, not assumed"
    requirement: "SW-03"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal8_MigrationNonRegression::test_lock_counts_unchanged_across_install_reinstall_and_teardown"
        status: pass
    human_judgment: false
  - id: D5
    description: "Full test suite (state writer + monitor + event logger) exits 0 with no regressions, and working-lock.sh/auq-lock.sh/settings-snippet.json remain byte-for-byte untouched by this plan"
    requirement: "ENG-06"
    verification:
      - kind: unit
        ref: "python3 -m unittest test_state_writer.py test_monitor.py test_event_logger.py -> Ran 114 tests, OK"
        status: pass
      - kind: other
        ref: "git diff --stat hooks/working-lock.sh hooks/auq-lock.sh hooks/settings-snippet.json -> empty"
        status: pass
    human_judgment: false

duration: 15min
completed: 2026-07-29
status: complete
---

# Phase 2 Plan 2: Full Event-to-State Mapping Summary

**hooks/state-writer.sh now covers the complete D-08 verdict — every registered event resolves the exact state TEST-MATRIX.md prescribes, including the async-in-flight gate on Stop, the SubagentStop no-op, and unconditional SessionEnd pruning**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-29T15:26:00Z
- **Completed:** 2026-07-29T15:32:48Z
- **Tasks:** 3
- **Files modified:** 2 (hooks/state-writer.sh, test_state_writer.py)

## Accomplishments
- `hooks/state-writer.sh` widened from the plan 02-01 tracer's single `Stop -> waiting` branch to the full 10-event D-08 mapping: `UserPromptSubmit`/`PostToolUse`/`PostToolUseFailure`/`PostToolBatch` -> working, `PermissionRequest`/`Notification` -> needs_input, `SessionStart` -> idle (no-op on `source=compact`), `Stop` -> waiting/working gated on a once-resolved `background_tasks_count`, `SubagentStop` -> explicit no-op, `SessionEnd` -> unconditional file removal
- `background_tasks_count` is resolved exactly once per invocation (deny-list: not completed, not failed, missing status still counts) and reused for both the Stop gate and the record field, so the two numbers can never disagree
- `hooks/install.sh --remove-state-writer` confirmed already complete from plan 02-01 — no code change needed; this plan added the regression tests that lock the guarantee down instead of leaving it implicit
- `test_state_writer.py` grew from 12 to 37 tests across 4 new goal classes (`Goal5_EventToStateMapping`, `Goal6_TurnEndSemantics`, `Goal7_RemovalPath`, `Goal8_MigrationNonRegression`); full suite (state writer + monitor + event logger) is 114 tests, all passing

## Task Commits

Each task was committed atomically:

1. **Task 1: Map the in-turn events — prompt, heartbeats, and the two needs_input signals** - `8817d17` (feat)
2. **Task 2: Map turn end — the background-task gate, the subagent no-op, and session teardown** - `0294af0` (feat)
3. **Task 3: Add the state-writer teardown path and lock the migration guarantee down** - `cb0af4c` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `hooks/state-writer.sh` - Complete D-08 event-to-state mapping; `background_tasks_count` resolved once and shared between the Stop gate and the record builder; `SessionEnd` handled ahead of the state-resolution case since it has no state to resolve
- `test_state_writer.py` - 25 new tests (Goal5-Goal8): every in-turn branch, the `/compact` byte-identical no-op, the background-tasks count gate across zero/running/completed+failed/missing-status, `SubagentStop`'s byte-identical no-op, `SessionEnd` removal across three `reason` values plus absent-file no-op, a no-leak assertion for `background_tasks` descriptor text, the full `--remove-state-writer` removal path, and the SW-03 lock-count/lock-bytes non-regression across install/reinstall/teardown

## Decisions Made
- `background_tasks_count` computed once, before the event `case` statement, from the deny-list rule — feeds both the Stop gate and the record field so they can never diverge (carries forward RESEARCH assumption A2 from plan 02-01)
- `SessionStart(source=compact)` exits 0 without writing rather than writing `idle`, since `/compact` re-fires `SessionStart` on the SAME session_id mid-turn (TEST-MATRIX case 11) — writing here would blank a live `working` state
- `SubagentStop` is an explicit branch that exits 0, not an implicit fall-through to the default case — TEST-MATRIX case 12 recorded it arriving after the parent's `Stop` twice, so the no-op needed to be intentional and directly tested
- `hooks/install.sh`'s `--remove-state-writer` was already complete from plan 02-01 (mirrors `--remove-logger`'s backup/sweep/validate/mv shape exactly, including the null-`.hooks` guard) — verified against every Task 3 acceptance criterion via manual smoke test, then locked down with `Goal7_RemovalPath`/`Goal8_MigrationNonRegression` rather than re-implementing anything

## Deviations from Plan

None — plan executed exactly as written. All three tasks matched their `<action>` and `<acceptance_criteria>` blocks. Task 3's `install.sh` portion turned out to already exist from plan 02-01's tracer commit (`6cf8e77`); this was verified line-by-line against every stated acceptance criterion (backup, generic hooks sweep, null-.hooks guard, json.load validation, unrelated-key preservation, --bogus-flag rejection) via a manual smoke test before concluding no code change was needed — the task's actual deliverable (the regression tests) was still written in full.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. (Live verification of the full mapping on the user's real Windows/WSL2/Docker setup remains deferred to this phase's live-verification plan, per RESEARCH.md's Environment Availability table — unchanged from plan 02-01.)

## Next Phase Readiness

- `hooks/state-writer.sh` now implements the complete D-08 verdict event set with no remaining functionality gaps — every event in `hooks/state-writer-events.json` has an explicit branch, verified by grep (`SubagentStop`'s branch exists and is a deliberate no-op, not an omission).
- The teardown/migration guarantee (SW-03) is now asserted by tests (`Goal7_RemovalPath`, `Goal8_MigrationNonRegression`), not just implemented and assumed correct.
- `hooks/working-lock.sh`, `hooks/auq-lock.sh`, and `hooks/settings-snippet.json` remain byte-for-byte untouched across all three tasks (`git diff --stat` empty), confirmed after every task commit.
- No blockers for continuing into the remaining 02-state-writer-shadow-mode plans. The shadow-engine seam (`scan_state_files`, `diff_verdicts`, `select_render_sessions`) built in plan 02-01 is unaffected by this plan's changes — it already reads whatever `state-writer.sh` writes generically.

---
*Phase: 02-state-writer-shadow-mode*
*Completed: 2026-07-29*

## Self-Check: PASSED

All modified files verified present on disk (`hooks/state-writer.sh`,
`test_state_writer.py`, `.planning/phases/02-state-writer-shadow-mode/02-02-SUMMARY.md`)
and all task commit hashes (`8817d17`, `0294af0`, `cb0af4c`) verified present in `git log`.
