---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 02
current_phase_name: state-writer-shadow-mode
status: executing
stopped_at: Completed 02-04-PLAN.md
last_updated: "2026-07-29T15:59:40.143Z"
last_activity: 2026-07-29
last_activity_desc: Phase 02 execution started
progress:
  total_phases: 2
  completed_phases: 1
  total_plans: 7
  completed_plans: 6
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-28)

**Core value:** Keep telling the user "this session needs you now" reliably — stop breaking every time Claude Code changes its internal jsonl format; hook-derived state is correct by construction instead of guessed.
**Current focus:** Phase 02 — state-writer-shadow-mode

## Current Position

Phase: 02 (state-writer-shadow-mode) — EXECUTING
Plan: 5 of 5
Status: Ready to execute
Last activity: 2026-07-29 — Phase 02 execution started

Progress: [█████████░] 86%

## Performance Metrics

**Velocity:**

- Total plans completed: 2
- Average duration: - min
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 2 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 8min | 3 tasks | 5 files |
| Phase 01 P02 | 6min | 2 tasks | 3 files |
| Phase 02 P01 | 13min | 2 tasks | 5 files |
| Phase 02 P02 | 15min | 3 tasks | 2 files |
| Phase 02 P03 | 14min | 3 tasks | 2 files |
| Phase 02 P04 | 8min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Hybrid model (hooks primary + targeted fallbacks), not hooks-only — pending live verification in Phase 1
- Never big-bang: extend hooks → shadow mode → flip default — 3-phase roadmap follows this exactly
- Preserve current async-work semantics (grey while bg shells/agents run) unless live data says otherwise
- ~~shell_tracker jsonl (V2-01)~~ SUPERSEDED 2026-07-29: badge unificato ◉N da background_tasks_count, shell_tracker eliminato — zero jsonl a regime dopo Phase 3
- [Phase ?]: Used RESEARCH.md's 24-event fallback baseline for hooks/hook-events.json (no live docs fetch available this session); documented provenance + re-check caveat in install.sh header
- [Phase ?]: event-logger.sh writes no line for a payload lacking hook_event_name (e.g. {}), treating it as a partial payload alongside empty/non-JSON/truncated stdin
- [Phase ?]: install.sh --remove-logger sweeps all hooks.<Event> arrays generically rather than scoping to the current hook-events.json list, so it cleans up stale entries from any prior event-list version
- [Phase ?]: [Phase 01-02]: Every jq field/event in 01-UAT.md was grounded against the real hooks/event-logger.sh and hooks/hook-events.json (plan 01-01), not RESEARCH.md doc-fetch prose, and mechanically verified by the plan's <verify> gate
- [Phase ?]: [Phase 01-02]: TEST-MATRIX.md rows 6 (AskUserQuestion) and 8 (Esc interrupt) pre-filled with research-confirmed answers (issues 28273, 12605, 15872, 9516) but Verified column left empty pending live confirmation on the tester's Claude Code version
- [Phase ?]: [Phase 02-01]: background_tasks_count uses a deny-list (not completed/failed) rather than an == running allowlist (RESEARCH assumption A2), so an undocumented status value can't undercount live async work
- [Phase ?]: [Phase 02-01]: Only the Stop event is mapped to a state write this plan; every other registered event exits 0 without writing — remaining D-08 event mapping is plan 02-02's scope
- [Phase ?]: [Phase 02-01]: select_render_sessions() is the single seam through which either engine's output can reach rendering, enforcing D-01 structurally rather than by convention
- [Phase ?]: [Phase 02-02]: background_tasks_count resolved once (deny-list: not completed, not failed) and shared between the Stop gate and the record field so they can never disagree
- [Phase ?]: [Phase 02-02]: SessionStart(source=compact) exits without writing rather than writing idle, since /compact re-fires SessionStart on the SAME session_id mid-turn (TEST-MATRIX case 11)
- [Phase ?]: [Phase 02-02]: SubagentStop is an explicit no-op branch (not a fall-through) since it can arrive after the parent's Stop (TEST-MATRIX case 12)
- [Phase ?]: [Phase 02-02]: install.sh --remove-state-writer was already complete from plan 02-01; this plan only added the Goal7/Goal8 regression tests locking the SW-03 guarantee down
- [Phase ?]: [Phase 02-03]: STATE_PROMPT_STALE_SEC set equal to legacy's USER_PROMPT_WORKING_SEC (90s) so the abandoned-prompt staleness window matches today's behavior exactly
- [Phase ?]: [Phase 02-03]: hostname_to_label is a secondary label resolver (after sessionid_to_label) because docker exec cannot reach a paused container — without it the paused-stays-WORKING staleness branch would be unreachable
- [Phase ?]: [Phase 02-03]: legacy_sessions migration bridge lives inside scan_state_files() itself, not caller-side, so --state-files diagnostic mode gets identical hookless-fallback behavior via an internal scan() call
- [Phase ?]: [Phase 02-04]: legacy_evidence is one compact string, not structured sub-fields, so the T-02-17 content-leak audit is a single substring grep
- [Phase ?]: [Phase 02-04]: a verdict-pair change mid-episode opens a fresh divergence episode (ticks resets to 1) rather than continuing the prior one's count
- [Phase ?]: [Phase 02-04]: filter_divergence_events() is a pure records-in/state-in -> events/next-state-out function, no MonitorApp mutation, so episode collapse is unit-testable without tkinter

### Pending Todos

- [minor/testing] Campagna ricertificazione hook per versione Claude Code (2026-07-29) — promuovere matrice+runbook fuori da .planning, fixture per versione, smoke ai major bump
- [minor/general] Show paused-container sessions in overlay instead of dropping them (2026-07-30) — idea da UAT C4: il motore state-file le tiene già (D-06), è solo rendering al flip di Phase 3

### Blockers/Concerns

- ~~UAT live Phase 1~~ COMPLETATA 2026-07-29 (campagna opportunistica, 17/21 campionati live, 0 issues): verdetto ibrido in TEST-MATRIX.md § 'Verdict to extract' — input diretto di Phase 2/ENG-06.
- ~~Open question AUQ~~ RISOLTA 2026-07-29 live: AUQ emette PreToolUse+PermissionRequest (apertura) e PostToolUse (risposta) su cc 2.1.220 — vedi TEST-MATRIX caso 6.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-07-29T15:59:40.104Z
Stopped at: Completed 02-04-PLAN.md
Resume file: None
