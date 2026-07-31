---
phase: quick-260731-an2
plan: 01
subsystem: monitor-status-decision
tags: [legacy-engine, bg-shell, status-decision, test-matrix]
status: complete
dependency-graph:
  requires: []
  provides:
    - "BG_PIN_MAX_SEC time cap on the legacy scan() bg-shell WORKING pin"
    - "TEST-MATRIX record of the same cap requirement for the Phase 3 hook-native rule"
  affects:
    - "monitor.py scan() status decision (legacy branch only)"
tech-stack:
  added: []
  patterns:
    - "Capped derived boolean (bg_pinned) feeding a decision, raw field (has_bg) feeding rendering/evidence — same split pattern as the existing tool_result/user_prompt freshness windows"
key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py
    - .planning/TEST-MATRIX.md
decisions:
  - "BG_PIN_MAX_SEC = 900s (15 min), same magnitude as TOOL_RESULT_WORKING_SEC — one tunable order-of-magnitude for 'work might still be happening' instead of two competing ones"
  - "Cap applies to the status decision only; the row's bg field (badge + diff_verdicts legacy_evidence) stays uncapped by construction"
  - "Cap scoped to bg shells only — monitors/agents/async_agents unchanged, each has its own bounded-lifetime signal already"
actuals:
  tokens: 42000
  tasks: 2
  commits: 2
metrics:
  duration: 25min
  completed: 2026-07-31
---

# Phase quick-260731-an2 Plan 01: Time-cap the background-shell WORKING pin Summary

A never-ending `run_in_background` shell (dev server, watcher) no longer pins
a session grey forever once its jsonl has gone quiet for `BG_PIN_MAX_SEC`
(900s); a finite bg task (build, test, install) still keeps today's
grey-while-running semantics because it re-invokes Claude on completion.

## What was built

**Task 1 — `monitor.py` + `test_monitor.py`:**
- Added `BG_PIN_MAX_SEC = 900` to the constants block, right after
  `TOOL_RESULT_WORKING_SEC`, with a rationale comment in the same style as
  its neighbours (what it caps, why 900, the accepted trade-off).
- In `scan()`, derived `bg_pinned = has_bg and age < BG_PIN_MAX_SEC`
  immediately before the status decision, and swapped it in for the raw
  `has_bg` in the WORKING OR-chain. The row dict's `"bg": has_bg` field is
  untouched — it still feeds the badge and `diff_verdicts()`'s
  `legacy_evidence` with the raw signal.
- Extended the GREEN-by-default block comment with the asymmetry rationale.
- Added a scope-guard comment at the `bg_pinned` derivation stating
  explicitly that monitors/agents/async_agents are NOT capped.
- Added fixture helper `_bg_shell_start(shell_id, tool_use_id, session_id)`
  next to `_async_agent_launch`, producing the two-record shape
  `shell_tracker.has_active_shells()` expects (key order preserved:
  `type`, `tool_use_id`, `content`, no nested object between the anchors).
- Added `Goal2h_BgShellPinTimeCap` with 4 tests: fresh bg shell → WORKING
  + bg badge True; stale bg shell (age > cap) → WAITING + bg badge still
  True; stale-but-inside-cap bg shell (finite task) → still WORKING;
  stale async agent (age > cap) → still WORKING (cap is bg-shell-scoped).

**Task 2 — `.planning/TEST-MATRIX.md`:**
- Appended one Italian bullet to `### 4. Async-work-in-flight design (case
  #17)`, after the existing Decision bullet, recording that the Phase 3
  hook-native rule (`Stop` with `background_tasks_count>0` → resta working)
  inherits the same unbounded-pin bug, must get the same cap measured
  against hook/heartbeat age (no jsonl mtime available hook-side), names
  `BG_PIN_MAX_SEC` as the legacy analogue, reaffirms the finite-task/case-13
  safety argument, and states the badge (case 18) stays uncapped. Dated
  and attributed to quick task 260731-an2 (2026-07-31).

## Verification

- `python3 -m unittest test_monitor.Goal2h_BgShellPinTimeCap -v` — 4/4 pass
- `python3 -m unittest test_monitor` — 125 tests OK (121 baseline + 4 new)
- `python3 -m unittest test_state_writer test_event_logger` — 58 tests OK,
  confirming the shadow/hook side was not touched
- `git status --porcelain hooks/ shell_tracker.py test_state_writer.py
  test_event_logger.py` — empty, confirming the shadow-engine files stayed
  byte-identical
- Grep gates: `BG_PIN_MAX_SEC = 900` appears exactly once, `bg_pinned`
  appears twice (derivation + use in the OR-chain), `"bg": has_bg,` appears
  exactly once
- TEST-MATRIX gates: `260731-an2` and `BG_PIN_MAX_SEC` both present within
  section 4; `git diff --name-only -- .planning/TEST-MATRIX.md` touched
  exactly that one file

## Expected new divergence (flagged for Section E review)

This change intentionally opens a new legacy-vs-shadow divergence shape:
for an eternal-bg session past `BG_PIN_MAX_SEC`, legacy `scan()` now says
WAITING while the shadow engine (`scan_state_files()`, rule
`background_tasks_count>0` with no cap) still says WORKING. The shadow
engine's code paths were deliberately left untouched per the review-window
constraint — `scan_state_files`, `select_render_sessions`, `diff_verdicts`,
`filter_divergence_events`, `write_divergences`, `hooks/state-writer.sh`
and `hooks/install.sh` are all byte-identical to before this task (verified
by the git-status gate above).

When the Section E review (running to ~2026-08-06) reads the divergence
log and finds `legacy=WAITING` / `shadow=WORKING` episodes with
`bg=True age>900s` in the `legacy_evidence` string, that is this known,
intended consequence — not a fresh anomaly. TEST-MATRIX section 4 now
carries the pointer so whoever executes the Phase 3 flip applies the
matching cap to the hook-native rule at that time, rather than
rediscovering the bug live.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- FOUND: monitor.py (BG_PIN_MAX_SEC constant, bg_pinned derivation, scope-guard comment)
- FOUND: test_monitor.py (Goal2h_BgShellPinTimeCap, 4 tests, _bg_shell_start helper)
- FOUND: .planning/TEST-MATRIX.md (260731-an2 bullet in section 4)
- FOUND commit 362105c: feat(quick-260731-an2): time-cap the background-shell WORKING pin
- FOUND commit 2c6f4d3: docs(quick-260731-an2): carry the bg-shell time cap into the hook-native rule
