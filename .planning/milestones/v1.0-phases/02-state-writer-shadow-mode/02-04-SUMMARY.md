---
phase: 02-state-writer-shadow-mode
plan: 04
subsystem: infra
tags: [python, monitor, shadow-mode, divergence-log, cli-flag]

# Dependency graph
requires:
  - phase: 02-state-writer-shadow-mode (plan 01)
    provides: the tracer diff_verdicts()/write_divergences()/select_render_sessions() this plan replaces with the decisive, episodic, size-bounded versions
  - phase: 02-state-writer-shadow-mode (plan 03)
    provides: scan_state_files() as a full peer of scan(), so this plan's comparator pairs two feature-complete engines
provides:
  - "diff_verdicts() over the union of both engines' keys, with ABSENT for a missing side and a T-02-17-safe legacy_evidence string"
  - "filter_divergence_events() episode tracking: one diverged record per opening disagreement, one resolved record per closing one"
  - "write_divergences() with a 5MB size guard (DIVERGENCE_LOG_MAX_BYTES) and an explicit truncation marker"
  - "state_files_mode() + the --state-files CLI flag, wired into MonitorApp without disturbing the shadow comparison's every-tick cadence"
affects: [02-05 (live runbook), Phase 3 legacy-removal — the divergence log this plan completes is the evidence base for that decision]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure two-stage comparator: diff_verdicts() (stateless per-tick diff) feeding filter_divergence_events() (stateful episode collapse) — both testable without tkinter or a running MonitorApp"
    - "Size-guard-then-append log write with an explicit truncation marker, reused from hooks/event-logger.sh's established convention"

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py

key-decisions:
  - "legacy_evidence is a single compact string (action + two lock booleans + bg/monitors/agents counts + age), not structured fields, so it's trivially greppable for content leaks and stays a single T-02-17 audit surface"
  - "filter_divergence_events() is a pure function taking/returning explicit per-key state rather than a method with internal mutation, so episode logic is testable in isolation from MonitorApp/tkinter"
  - "A verdict-pair change mid-episode opens a brand-new episode (ticks resets to 1) rather than treating it as a continuation, matching the plan's 'writes a second diverged' wording literally"
  - "state_files_mode() and the CLI flag were implemented alongside diff_verdicts()/write_divergences() in a single commit rather than a second atomic commit per Task 2, because the CLI-flag change was two lines (state_files_mode() call + a new attribute) touched while the same functions section was already being edited — see Deviations"

requirements-completed: [ENG-01, ENG-02]

coverage:
  - id: D1
    description: "diff_verdicts() compares the union of legacy/shadow keys, represents a missing side as ABSENT, and every emitted record carries both verdicts plus state-file context (state, last_event, hostname, background_tasks_count, age_sec) and a legacy_evidence string — with no field that classifies which side was correct"
    requirement: "ENG-02"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal14_DivergenceRecords (6 tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "filter_divergence_events() collapses a persisting disagreement to one diverged record when it opens and one resolved record (carrying since_ts_ms and the episode's tick count) when it closes — including a verdict-pair change mid-episode and a session disappearing while diverging"
    requirement: "ENG-02"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal15_DivergenceEpisodes (4 tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "write_divergences() truncates DIVERGENCE_LOG with an explicit marker once it exceeds DIVERGENCE_LOG_MAX_BYTES (5MB), never raises on an unwritable path, and legacy_evidence never carries raw prompt/tool-input text even when seeded into the source jsonl (T-02-17/18/19)"
    requirement: "ENG-02"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal16_DivergenceLogGuard (3 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "state_files_mode() reads --state-files from argv the same way --test-notify already does (no argparse), MonitorApp.state_files_mode is set from it at startup, and select_render_sessions() still returns the legacy list by identity whenever the flag is absent; the shadow comparison runs on refresh()'s unconditional code path regardless of the flag"
    requirement: "ENG-01"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal17_StateFilesMode (4 tests)"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-29
status: complete
---

# Phase 2 Plan 4: Divergence Comparator Completion & --state-files Mode Summary

**diff_verdicts()/filter_divergence_events() turn the shadow comparator into a decisive, episodic, 5MB-bounded evidence log, and --state-files gives monitor.py a diagnostic entry point that renders the state-file engine without touching the default run**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-29T15:49:47Z
- **Completed:** 2026-07-29T15:57:40Z
- **Tasks:** 2 (implemented in one commit — see Deviations)
- **Files modified:** 2 (monitor.py, test_monitor.py)

## Accomplishments
- `diff_verdicts()` rewritten to compare the UNION of legacy/shadow keys (a session only one engine sees is now itself a divergence, verdict `ABSENT`), and every record now carries `hostname`, `background_tasks_count`, `age_sec` and a `legacy_evidence` string assembled only from safe non-content legacy signals — the tool-name-only `action` label, `working_locked`/`auq_locked`, `bg`/`monitors`/`agents` counts and age
- `scan()` now reports `auq_locked`/`working_locked` on every session dict (both were already computed for the status decision, just not surfaced) so `diff_verdicts()` can build `legacy_evidence` without a second lock-file stat
- `filter_divergence_events(records, prev, tick)` added as a pure episode tracker: a new or changed verdict pair emits one `diverged` record; an unchanged pair emits nothing but advances a tick counter; a key that drops out of the current tick's records (agreement restored or session vanished) emits one `resolved` record carrying `since_ts_ms` and the episode's `ticks`
- `write_divergences()` gained `DIVERGENCE_LOG_MAX_BYTES` (5MB, mirroring `hooks/event-logger.sh`'s threshold): a file already over the limit is truncated and an `_truncated` marker record is written first, so truncation is never mistaken for a gap in observation; the whole write stays wrapped in `try/except OSError: pass`
- `state_files_mode(argv=None)` added, reading `--state-files` from `sys.argv` the same way `--test-notify` already is (no argparse introduced); `MonitorApp.__init__` now sets `self.state_files_mode` from it instead of a hardcoded `False`
- `refresh()`'s shadow comparison (`diff_verdicts` → `filter_divergence_events` → `write_divergences`) stays on the unconditional tick path — not gated by the flag — so divergence evidence keeps accumulating during ordinary daily use regardless of which mode is active
- Module docstring and the flag's definition documented per D-01/ENG-01: without the flag every rendering/notification path is legacy-driven exactly as before Phase 2; with it, the same paths are state-file-driven for hands-on verification; the process singleton means a normal monitor instance must be closed first
- 16 new tests across `Goal14_DivergenceRecords`, `Goal15_DivergenceEpisodes`, `Goal16_DivergenceLogGuard`, `Goal17_StateFilesMode` — 163 tests pass total (146 pre-existing + 17 net new, one prior tracer test already covered by the new Goal14/17 suites), zero regressions

## Task Commits

Both tasks landed in one commit — see Deviations below for why.

1. **Task 1 + Task 2: Decisive/episodic/bounded divergence records, plus the --state-files diagnostic flag** - `97c6309` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `monitor.py` - `DIVERGENCE_LOG_MAX_BYTES` constant, `scan()` gains `auq_locked`/`working_locked` on its session dict, rewritten `diff_verdicts()` (union comparison, ABSENT, full context, `legacy_evidence`), new `filter_divergence_events()`, rewritten `write_divergences()` (size guard + truncation marker), new `state_files_mode()`, `MonitorApp.__init__` wires `self.state_files_mode`/`self._divergence_state`, `refresh()` threads the diff→filter→write pipeline, module docstring documents `--state-files`
- `test_monitor.py` - `_legacy_rec`/`_shadow_rec` fixture helpers, `DivergenceLogTestBase`, `Goal14_DivergenceRecords` (6 tests), `Goal15_DivergenceEpisodes` (4 tests), `Goal16_DivergenceLogGuard` (3 tests), `Goal17_StateFilesMode` (4 tests)

## Decisions Made
- `legacy_evidence` is one compact string, not structured sub-fields — makes the T-02-17 content-leak audit a single substring grep instead of a per-field check, and keeps the record shape stable regardless of which legacy signals exist for a given session
- A verdict-pair change mid-episode opens a fresh episode (`ticks` resets to 1, `since_ts_ms` moves to the current tick) rather than being folded into the prior episode's count — matches the plan's "writes a second diverged" description and keeps each episode's duration meaningful (a duration spanning two different disagreements would misrepresent how long either one actually lasted)
- `filter_divergence_events()` is a pure function (records in, state in, events + next-state out) rather than a `MonitorApp` method with internal mutation, so episode collapse logic is unit-testable without tkinter or a constructed app — same discipline `diff_verdicts()` and `scan_state_files()` already established

## Deviations from Plan

### Process deviation (not a Rule 1-4 case)

**Both tasks landed in a single commit instead of two atomic commits.** The plan's Task 1 (`diff_verdicts`/`filter_divergence_events`/`write_divergences`) and Task 2 (`state_files_mode`/CLI flag) both live in the same functions-and-constants region of `monitor.py` that was already open for editing; `state_files_mode()` was added immediately after `select_render_sessions()` in the same edit pass, and wiring `self.state_files_mode = state_files_mode()` into `MonitorApp.__init__` was a two-line change made at the same time as adding `self._divergence_state`. By the time this was noticed the combined commit had already been created. No functional content is missing — every acceptance criterion from both tasks was independently verified against the running code (see Coverage D1-D4 and the acceptance-criteria commands below) — but the per-task commit boundary the plan specifies was not honored. Flagged here rather than corrected via `git commit --amend` per the "always create NEW commits, never amend" rule; a corrective split-commit was judged not worth a history rewrite for a same-session, fully-tested, single-file change.

**Impact on plan:** None on functionality or test coverage. Only the commit-granularity guarantee (one commit per `<task>` block) was not met for this plan.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Every symbol the phase's "Artifacts this phase produces" list names as new in `monitor.py` (`DIVERGENCE_LOG_MAX_BYTES`, `filter_divergence_events`, `select_render_sessions`, `state_files_mode`, `MonitorApp.state_files_mode`, the `--state-files` flag, `scan()`'s `auq_locked`/`working_locked` keys) now exists and is tested.
- All plan-level `<verification>` commands pass: `python3 -m unittest test_monitor.py test_event_logger.py test_state_writer.py` exits 0 (163 tests); `monitor.py` contains no `argparse` import and no `flock` usage (grep-verified — the two hits are prose in docstrings/comments, not code); `select_render_sessions` returns the legacy list by identity whenever the flag is absent (`Goal17` + the tracer's own identity test).
- The divergence log's shape is now stable for a week of real shadow operation: episode collapse cuts write volume roughly two orders of magnitude versus one line per tick, and the 5MB guard bounds worst-case growth on the shared 9p mount — exactly what plan 02-05's live runbook needs to be readable evidence for the Phase 3 flip decision.
- No blockers for continuing into 02-05 (live runbook) in this sandbox.

---
*Phase: 02-state-writer-shadow-mode*
*Completed: 2026-07-29*

## Self-Check: PASSED

Created file verified present on disk (`.planning/phases/02-state-writer-shadow-mode/02-04-SUMMARY.md`)
and the task commit hash (`97c6309`) verified present in `git log`.
