---
phase: 02-state-writer-shadow-mode
plan: 01
subsystem: infra
tags: [bash, jq, hooks, tkinter, monitor, shadow-mode, atomic-write]

# Dependency graph
requires:
  - phase: 01-hook-coverage-verification
    provides: TEST-MATRIX.md's live-verified event-to-state mapping (D-08 verdict event set) and the hybrid-model verdict this plan's writer event set is built against
provides:
  - hooks/state-writer.sh, the atomic per-session state writer (Stop event only, this plan)
  - hooks/state-writer-events.json, the D-08 verdict event registration list
  - hooks/install.sh registration/removal for the state writer, alongside the unchanged lock/logger passes
  - monitor.py shadow engine: scan_state_files(), diff_verdicts(), write_divergences(), select_render_sessions()
  - The single render seam (select_render_sessions) that structurally enforces D-01 (legacy-only rendering during Phase 2)
affects: [02-state-writer-shadow-mode remaining plans (02-02..02-05), Phase 3 legacy-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomic same-directory tmp+rename write for a per-session file a hook script fully overwrites on every update"
    - "Dual-engine tick: compute legacy + shadow verdicts every refresh(), diff and log, but render only through select_render_sessions()"

key-files:
  created:
    - hooks/state-writer.sh
    - hooks/state-writer-events.json
    - test_state_writer.py
  modified:
    - hooks/install.sh
    - monitor.py

key-decisions:
  - "background_tasks_count uses a deny-list (not completed/failed) rather than an == running allowlist, per RESEARCH assumption A2, so an undocumented status value can't undercount live work"
  - "Only the Stop event is mapped to a state write in this plan; every other registered event name exits 0 without writing — the full D-08 mapping is plan 02-02's scope, tracked as a known, intentional gap"
  - "select_render_sessions() is the single seam through which either engine's output can reach rendering — chosen over scattering state_files_mode checks through refresh(), so D-01 is enforced by one identity-return function, not a convention"

patterns-established:
  - "Pattern 2 (RESEARCH.md): same-directory tmp+rename atomic write for any per-session file a hook fully overwrites"
  - "Pattern 3 (RESEARCH.md): dual-engine tick with a single render seam function, reusable by future shadow-mode work in this codebase"

requirements-completed: [SW-01, SW-02, ENG-01, ENG-02]

coverage:
  - id: D1
    description: "hooks/state-writer.sh atomically writes a complete per-session state file (all 7 schema fields: state, ts, ts_ms, cwd, hostname, last_event, background_tasks_count) on a Stop event, staged via same-directory tmp file + mv -f, and survives SIGKILL mid-write without ever leaving a corrupt/truncated final file"
    requirement: "SW-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal1_TracerEndToEnd::test_stop_event_becomes_shadow_waiting_verdict_with_divergence"
        status: pass
      - kind: unit
        ref: "test_state_writer.py#Goal4_AtomicWriteUnderStress (4 tests: sigkill, concurrent writers, same-cwd separation, non-ASCII cwd)"
        status: pass
    human_judgment: false
  - id: D2
    description: "state-writer.sh never blocks a Claude Code session: exits 0 and writes nothing on empty stdin, non-JSON stdin, {}, a payload missing session_id, or a session_id containing a path separator (path-traversal guard, T-02-01/T-02-02)"
    requirement: "SW-02"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal2_NeverBreakTheSession (5 tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "hooks/install.sh registers state-writer.sh on every event in state-writer-events.json via its own idempotent jq pass, creates monitor-state/, and leaves the working-lock/auq-lock entry counts unchanged (SW-03)"
    requirement: "SW-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal3_InstallRegistration (2 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "monitor.scan_state_files() derives a WAITING verdict (dot_color #4ade80, legacy's exact WAITING colour) from a state file without reading any jsonl; diff_verdicts() emits exactly one record when legacy/shadow disagree and zero when they agree"
    requirement: "ENG-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal1_TracerEndToEnd::test_stop_event_becomes_shadow_waiting_verdict_with_divergence"
        status: pass
    human_judgment: false
  - id: D5
    description: "select_render_sessions(legacy, shadow, False) returns the legacy list object itself (identity, not a copy) — the shadow engine has no code path into rendering/notification during default operation (D-01)"
    requirement: "ENG-02"
    verification:
      - kind: other
        ref: "python3 -c \"import sys,types; sys.modules.setdefault('tkinter', types.ModuleType('tkinter')); import monitor; L=['L']; S=['S']; print(monitor.select_render_sessions(L,S,False) is L, monitor.select_render_sessions(L,S,True) is S)\" -> True True"
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-07-29
status: complete
---

# Phase 2 Plan 1: State Writer & Shadow Mode Summary

**Tracer end-to-end: a Stop hook event becomes an atomically-written state file, monitor.py derives a shadow WAITING verdict from it without reading jsonl, disagreements with legacy are logged, and the overlay keeps rendering legacy exclusively**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-29T15:10:36Z
- **Completed:** 2026-07-29T15:22:49Z
- **Tasks:** 2
- **Files modified:** 5 (3 new: hooks/state-writer.sh, hooks/state-writer-events.json, test_state_writer.py; 2 modified: hooks/install.sh, monitor.py)

## Accomplishments
- `hooks/state-writer.sh`: authoritative, atomic, exit-0-always hook script that writes `~/.claude/monitor-state/<session_id>.json` on `Stop`, path-traversal-guarded on `session_id`, staged via same-directory `tmp.$$` + `mv -f`
- `monitor.py` shadow engine seam: `scan_state_files()`, `_read_state_file()`, `_state_to_status()`, `diff_verdicts()`, `write_divergences()`, `select_render_sessions()` — wired into `refresh()` without touching `_make_session_row`, `_make_compact_chip`, or `_notify`
- `hooks/install.sh` registers the writer on the D-08 verdict event set (10 events) via its own idempotent jq pass, plus `--remove-state-writer` teardown; lock/logger registrations byte-for-byte unchanged
- `test_state_writer.py` (12 tests): tracer end-to-end, never-break-the-session edge cases, install registration/idempotency, and a mechanical proof that SIGKILL mid-write (30 iterations) and 5 concurrent writers never corrupt the final state file
- 95 tests pass total (83 pre-existing + 12 new), zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end "a Stop event becomes a shadow WAITING verdict" — one path only** - `6cf8e77` (feat)
2. **Task 2: Prove the atomic write survives a mid-write kill and concurrent writers** - `5e2289b` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `hooks/state-writer.sh` - Atomic, event-keyed hook script; maps only `Stop` to a state write this plan
- `hooks/state-writer-events.json` - D-08 verdict event registration list (10 events, `PreToolUse` deliberately absent)
- `hooks/install.sh` - `STATE_WRITER_CMD`/`STATE_WRITER_EVENTS_FILE`, install step, its own jq registration pass, `--remove-state-writer`
- `monitor.py` - `STATE_DIR`/`DIVERGENCE_LOG` constants, `_read_state_file`, `_state_to_status`, `scan_state_files`, `diff_verdicts`, `write_divergences`, `select_render_sessions`, `MonitorApp.state_files_mode`, `refresh()` wiring
- `test_state_writer.py` - 12 tests across 4 goal classes (tracer, never-break-the-session, install registration, atomic-write-under-stress)

## Decisions Made
- `background_tasks_count` filters on a deny-list (`status != completed and != failed`) rather than an exact `== "running"` allowlist, per RESEARCH assumption A2, so an undocumented status value can't silently undercount live work
- Only `Stop -> state=waiting` is mapped this plan; every other registered event exits 0 without writing. This is the full intended scope of the tracer task — the remaining D-08 event mapping is plan 02-02's job, tracked as a known functionality gap, not a defect
- `select_render_sessions()` is the sole seam through which either engine's output can reach rendering, chosen deliberately over scattering `state_files_mode` checks through `refresh()` — D-01 is now enforced structurally (one identity-returning function) rather than by convention alone

## Deviations from Plan

None — plan executed exactly as written. Both tasks matched their `<action>` and `<acceptance_criteria>` blocks without needing an architectural change (Rule 4) or an out-of-scope fix.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required. (The state writer only becomes live on the user's real Windows/WSL2/Docker setup once `hooks/install.sh` is run there — deferred to this phase's live-verification plan, per RESEARCH.md's Environment Availability table.)

## Next Phase Readiness

- The atomic-write primitive (tmp+rename), the shadow-engine seam (`scan_state_files`/`diff_verdicts`/`select_render_sessions`), and the install registration pattern are all proven end-to-end on one event — plan 02-02 extends `state-writer.sh`'s event-to-state mapping to the full D-08 table (`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `Notification`, `SubagentStop` ignored, `SessionEnd` removes the file) using the exact same script skeleton and test harness.
- RESEARCH.md flagged two assumptions needing a live spot-check on the user's actual Windows/WSL2/Docker environment (not this sandbox): A1 (`docker inspect --format '{{.State.Status}}'` enum stability) and A3 (9p mount rename atomicity — this plan's Task 2 proved rename atomicity on this sandbox's local filesystem; the 9p-specific case is carried into plan 02-05's live runbook).
- No blockers for continuing 02-02 through 02-05 in this sandbox.

---
*Phase: 02-state-writer-shadow-mode*
*Completed: 2026-07-29*

## Self-Check: PASSED

All created files verified present on disk (`hooks/state-writer.sh`,
`hooks/state-writer-events.json`, `test_state_writer.py`,
`.planning/phases/02-state-writer-shadow-mode/02-01-SUMMARY.md`) and all task
commit hashes (`6cf8e77`, `5e2289b`, `54f3f2a`) verified present in `git log`.
