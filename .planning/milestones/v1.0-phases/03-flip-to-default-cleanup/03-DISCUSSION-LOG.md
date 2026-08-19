# Phase 3: Flip to Default & Cleanup - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-06
**Phase:** 03-flip-to-default-cleanup
**Areas discussed:** Legacy bridge survival (document-conflict resolution) — all other areas resolved documentally per user instruction

---

## Mode note

The user explicitly declined an interactive interview: "Il discuss di Phase 3 è già avvenuto: è la review di Sezione E del 2026-08-06." CONTEXT.md was generated from the repo documents (02-DIVERGENCE-REVIEW.md, NOTES.md, TEST-MATRIX.md, STATE.md, 02-UAT.md §Teardown) under five non-negotiable constraints supplied inline (flip approved / hybrid fallbacks / bg badge-only / teardown per 02-UAT / remote out of scope / UAT on Windows). Questions were allowed ONLY for conflicts between documents. One conflict was found and asked.

---

## Legacy bridge for sessions without a state file (the one conflict)

The user's constraint said jsonl fallback "SOLO per Esc-interrupt e silenzio-hook", but ENG-05 (REQUIREMENTS.md), TEST-MATRIX Verdict §2 row 21, and UAT C6 all name the `legacy_origin` bridge as a surviving migration fallback for hookless/state-file-less sessions.

| Option | Description | Selected |
|--------|-------------|----------|
| Ponte resta (3° fallback) | ENG-05 survives: constraint becomes "jsonl only for Esc-interrupt, hook-silence AND hookless bridge"; V2-02 "no data" UI deferred | ✓ |
| Ponte cade + startup check | Strict constraint reading: delete the bridge, sessions without state file invisible, add startup hard-fail from the pending todo | |

**User's choice:** Ponte resta (3° fallback) — confirmed twice ("Confermo la scelta documentale sul ponte (ENG-05 sopravvive)").
**Notes:** Consequence encoded in CONTEXT.md: the startup-check todo folds only in reduced form (warning at Claude's discretion, hard-fail deferred to V2-02), and the ghost-row todo becomes D-06 (bridge must not resurrect clean-ended sessions).

---

## Earlier aborted interview attempt

A standard gray-area selection (4 areas: hookless containers, paused/ghost sessions, rollback & lock hooks, test/docs strategy + recertification-todo fold) was presented and rejected by the user in favor of the document-driven mode above. Those areas were subsequently resolved from documents as D-02c/D-04, D-05/D-06, D-01/D-04/D-08, D-07/D-10 respectively.

## Claude's Discretion

- Paused/kept session rendering detail (no new colors/notifications)
- Ghost-suppression mechanism (tombstone vs alternative)
- `--state-files` flag fate post-default
- Internal refactor shape of monitor.py after deletions
- README vs docs/ split for FLIP-03

## Deferred Ideas

- Remote devbox aggregation + mobile notifications (separate milestone, door-keeping only)
- V2-02 "no data" UI + startup hard-fail re-evaluation
- Recertification campaign machinery (only matrix/runbook doc promotion lands in Phase 3)
- V2-01 badges from PostToolUse payloads (superseded in substance by unified ◉N badge)
