---
phase: 01-hook-coverage-verification
plan: 02
subsystem: infra
tags: [claude-code-hooks, jsonl, diagnostics, uat, documentation]

# Dependency graph
requires:
  - phase: 01-hook-coverage-verification (plan 01-01)
    provides: "hooks/event-logger.sh (24-event JSONL logger), hooks/hook-events.json (registration list), hooks/install.sh (install + --remove-logger teardown)"
provides:
  - "01-UAT.md — a 21-case live runbook: exact trigger, jq observe command, pass condition, and record instruction per TEST-MATRIX.md row, plus setup/teardown and a case-marker helper for a shared, concurrently-written log"
  - "TEST-MATRIX.md updated in place — preamble routes to the runbook and logger, rows 6 and 8 carry research-confirmed answers, and the Verdict to extract section is a fillable template requiring a named concrete fallback per hook-silent case"
affects: [phase-2-state-file-engine, human-uat-checkpoint]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Case-marker helper (mark/extract_case shell functions) makes one live-test case's log lines separable in a shared, concurrently-written JSONL file without needing a lock"
    - "Runbook observation commands are grounded against the real instrument's emitted fields and registered event names, not against doc prose or plan-authoring assumptions — verified mechanically by the plan's <verify> gate"

key-files:
  created:
    - .planning/phases/01-hook-coverage-verification/01-UAT.md
  modified:
    - .planning/TEST-MATRIX.md

key-decisions:
  - "Every jq select() field and .event == \"X\" comparison in 01-UAT.md was written only after reading hooks/event-logger.sh and hooks/hook-events.json as they actually landed in plan 01-01 — not from RESEARCH.md's doc-fetch prose, which the plan itself flags as having inconsistent field names across fetches."
  - "Cases 6 (AskUserQuestion) and 8 (Esc interrupt) are documented as 'Expected: ZERO log lines' up front, citing the specific GitHub issues that establish the negative, so the live tester spends no session time debugging a working logger."
  - "TEST-MATRIX.md rows 6 and 8 are pre-filled with the research-confirmed answer but the Verified column is left explicitly empty — the live run still has to confirm the negative holds on the tester's installed Claude Code version."

requirements-completed: []

coverage:
  - id: D1
    description: "01-UAT.md gives one numbered runbook section (trigger, observe, pass condition, record) for each of the 21 TEST-MATRIX cases, with every jq field/event name grounded in the real event-logger.sh output and hook-events.json registration list"
    requirement: VER-02
    verification:
      - kind: other
        ref: "01-02-PLAN.md Task 1 <verify> — RUNBOOK_OK (21/21 case headings present and numbered to match TEST-MATRIX.md; cases 6/8 declare 'Expected: ZERO log lines'; every select(.field) checked as a substring of hooks/event-logger.sh; every .event==\"X\" checked against hooks/hook-events.json's 24-name list)"
        status: pass
    human_judgment: false
  - id: D2
    description: "TEST-MATRIX.md preamble routes the reader to the runbook and the logger, rows 6 and 8 carry the research-confirmed answers with citations and empty Verified cells, and the Verdict to extract section is a fillable template forcing a named concrete fallback per hook-silent case"
    requirement: VER-02
    verification:
      - kind: other
        ref: "01-02-PLAN.md Task 2 <verify> — MATRIX_OK (21 rows intact, 8-pipe row shape preserved on every row, row 6 cites 28273/auq-lock, row 8 cites 9516/Stop, verdict template contains 'Fallback that covers it' and names ENG-06 as the consumer)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The live 21-case run itself: triggering each case in the real Windows + Docker environment, filling the Verified column, and writing the hybrid verdict into TEST-MATRIX.md"
    requirement: VER-02
    verification: []
    human_judgment: true
    rationale: "D-05 scopes this plan to instrumentation + runbook only; the live matrix run requires docker kill, Esc mid-turn interrupts, and multi-container races in the user's real environment, none of which the agent can execute. VER-02 is only partially satisfied by this plan — the Verified column and the verdict remain to be filled by the human UAT this plan hands off to."

duration: 6min
completed: 2026-07-29
status: complete
---

# Phase 1 Plan 2: Live Runbook and Fillable Verdict Template Summary

**A 21-case live runbook (01-UAT.md) with exact triggers and jq observation commands grounded in the actual event-logger.sh output, plus a TEST-MATRIX.md that routes to it and can no longer be filled in with a vague verdict.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-29T08:17:51Z
- **Completed:** 2026-07-29T08:23:37Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `01-UAT.md`: setup (install → confirm registration count → restart sessions → record `claude --version` → truncate log → open raw + readable followers), a `mark`/`extract_case` shell-function pair for separating one case's lines out of a shared concurrently-written log, and one `### Case N` section per TEST-MATRIX row 1–21 with Trigger/Observe/Pass condition/Record
- Cases 6 (AskUserQuestion) and 8 (Esc interrupt) lead with **"Expected: ZERO log lines"** and the exact GitHub issues (28273, 12605, 15872, 9516) that establish it, so the live tester doesn't burn session time debugging a logger that's working correctly
- Cases 2, 3, 4, 5, 12, 13, 15, 17, 18, 19, 20 carry the extra handling the plan called for: wall-clock-vs-`ts_ms` comparison for case 2, largest-gap computation for case 3, multi-shape prompt testing for case 4, approve/deny for case 5, subagent-vs-real-Stop distinction for case 12, full ordered event sequence for case 13, unparseable-line count for case 15, explicit "design decision, not detection" framing for case 17, `keys`-array-only inspection for case 18, last-event-and-`ts_ms` recording for cases 9/19/21, and a hand-appended truncated line for case 20
- `TEST-MATRIX.md`'s preamble now points at `hooks/event-logger.sh`, `hooks/install.sh` (install + `--remove-logger`), and `01-UAT.md` instead of describing a logger that doesn't exist yet; rows 6 and 8 carry the research-confirmed answers with citations and empty Verified cells; the "Verdict to extract" section is now four fillable slots (hooks-only viability, a per-case fallback table, notification timing, async-work-in-flight design) that cannot be completed without naming a concrete mechanism, and closes by naming Phase 2's ENG-06 as the consumer

## Task Commits

Each task was committed atomically:

1. **Task 1: Write the 21-case live runbook (01-UAT.md)** - `0618f4d` (docs) — RUNBOOK_OK
2. **Task 2: Point TEST-MATRIX.md at the instrument and make its verdict fillable** - `fe5d95e` (docs) — MATRIX_OK

## Files Created/Modified
- `.planning/phases/01-hook-coverage-verification/01-UAT.md` - New 21-case live runbook: setup, case-marker helper, per-case trigger/observe/pass/record, recording format, verdict pointer, teardown
- `.planning/TEST-MATRIX.md` - Preamble routes to the runbook/logger; rows 6 and 8 pre-filled with research-confirmed answers; Verdict to extract rewritten as a 4-slot fillable template

## Decisions Made
- Every observation command was written only after reading the actual `hooks/event-logger.sh` and `hooks/hook-events.json` from plan 01-01 (not from RESEARCH.md's doc-fetch prose, which the research itself notes was internally inconsistent on field names) — this is the single most fragile link the plan called out, and the automated `<verify>` gate checks it mechanically (every `select(.field)` substring-matched against the logger script, every `.event == "X"` looked up in the registered 24-event list).
- Rows 6 and 8 in TEST-MATRIX.md are pre-filled with the research-confirmed negative (no hook fires) but the Verified column stays empty — the live run still needs to confirm the negative holds on the tester's specific Claude Code version, per the plan's explicit "research-confirmed, awaiting live confirmation" framing.
- Case 20 (corrupt state file) is scoped down to what's observable in Phase 1 (no state files exist yet): hand-appending a truncated line to `hook-events.log` and confirming the readable-log workflow tolerates it, carried forward as a note for Phase 2's ENG-04 rather than treated as a hook-coverage finding.

## Deviations from Plan

None - plan executed exactly as written. Both task `<verify>` gates (`RUNBOOK_OK`, `MATRIX_OK`) and all four plan-level `<verification>` checks passed on the first attempt: 21/21 case headings match 21/21 matrix rows with no gaps, the Verified column is still empty on all 21 rows (no live-run data was fabricated), and `git status --porcelain` shows changes scoped to `.planning/TEST-MATRIX.md` and `.planning/phases/01-hook-coverage-verification/01-UAT.md` only — no source or hook files touched.

## Issues Encountered
None.

## User Setup Required

None for this plan's deliverable. However, the **live 21-case run itself is required next** and is user-assisted UAT, not agent-executable (D-05): follow `.planning/phases/01-hook-coverage-verification/01-UAT.md` end to end in the real Windows + Docker environment, fill the Verified column, write the verdict into `.planning/TEST-MATRIX.md`, then run the teardown (`bash hooks/install.sh --remove-logger` + delete `~/.claude/hook-events.log`).

## Known Stubs
None — this plan produces documentation only; no code was written, so no stub-detection scan applies.

## Threat Flags
None — this plan operates entirely within the threat model already registered in this plan's own `<threat_model>` (T-01-07, T-01-08, T-01-09, T-01-SC); no new network endpoints, auth paths, or schema changes were introduced. No source or hook files were touched (verified via `git status --porcelain`).

## Next Phase Readiness
- **VER-02 is only partially satisfied.** Instrumentation (plan 01-01) and the runbook + fillable matrix template (this plan) are done; the Verified column and the written hybrid verdict are pending the human UAT that follows this phase's execution. The phase verifier should not read VER-02 as closed until that UAT completes.
- Phase 2's fallback design (ENG-06) and the state-writer's event-to-state mapping in NOTES.md are blocked on the verdict this UAT produces — specifically the per-case fallback table (Verdict question 2), the notification-timing decision (question 3), and the async-work-in-flight design decision (question 4, case 17).
- `hooks/hook-events.json`'s 24-event list is a RESEARCH.md fallback baseline, not a confirmed-live-fetch list (per 01-01-SUMMARY.md). The user should spot-check it against current `code.claude.com/docs/en/hooks` before or during the live run, since a missing event name would silently bias the verdict.

---
*Phase: 01-hook-coverage-verification*
*Completed: 2026-07-29*

## Self-Check: PASSED

All created/modified files found on disk (01-UAT.md, TEST-MATRIX.md, this SUMMARY.md). All task commits found in git log (0618f4d, fe5d95e) plus the summary commit (44e02fd).
