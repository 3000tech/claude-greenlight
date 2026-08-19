---
phase: quick-260731-bu8
plan: 01
subsystem: monitor-state-detection
tags: [regex, jsonl-parsing, shell-tracker, background-shells, tdd]

# Dependency graph
requires:
  - phase: quick-260731-an2
    provides: "has_active_shells feeds only the ⚙ badge and diff_verdicts evidence, never the WORKING/WAITING decision (badge-only invariant this task preserves)"
provides:
  - "BG_START_RE recognises both auto-backgrounded (run_in_background=True) and manually-backgrounded (Ctrl+B) shell starts through one pattern and one capture group"
  - "Regression coverage (Goal2i, 3 tests) for the manual-background badge: lights while running, clears on completion, resists escaped-echo spoofing"
affects: [phase-3-flip, shell-tracker-legacy-fallback]

actuals:
  tokens: 2600
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Single-pattern non-capturing alternation for near-identical marker phrasings, rather than a second constant + second finditer loop — keeps the anchoring rationale in exactly one place"

key-files:
  created: []
  modified:
    - shell_tracker.py
    - test_monitor.py

key-decisions:
  - "Widened BG_START_RE with a non-capturing alternation on the middle phrasing only ('running in background' | 'was manually backgrounded by user'), keeping the shared 'Command ' prefix, ' with ID:' suffix, tool_result content anchor, and single capture group byte-identical otherwise"
  - "No changes to has_active_shells, monitor.py, or the shadow-mode hooks — the badge wiring already consumed has_active_shells, so widening the start pattern was sufficient end-to-end"
  - "Split into two atomic commits per plan structure: Task 1 (production code + first detection/invariant test), Task 2 (termination + no-spoof guard tests, test-only)"

patterns-established:
  - "Regression tests for jsonl marker parsing are grounded in verbatim live-captured record shapes (key ordering, toolUseResult fields) rather than minimal synthetic stubs, so a fixture drift signals a real format change"

requirements-completed: [QUICK-260731-bu8]

coverage:
  - id: D1
    description: "A manually-backgrounded (Ctrl+B) shell lights the ⚙ badge exactly like an auto-backgrounded one, while status stays WAITING (badge-only invariant preserved)"
    requirement: "QUICK-260731-bu8"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal2i_ManualBgShellDetected.test_manual_bg_shell_lights_badge_stays_waiting"
        status: pass
    human_judgment: false
  - id: D2
    description: "The manually-backgrounded shell's completion notification clears the badge with no new termination code"
    requirement: "QUICK-260731-bu8"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal2i_ManualBgShellDetected.test_manual_bg_shell_completion_clears_badge"
        status: pass
    human_judgment: false
  - id: D3
    description: "An escaped grep/cat echo of a jsonl containing the manual marker does not spoof the badge — anchoring holds"
    requirement: "QUICK-260731-bu8"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal2i_ManualBgShellDetected.test_escaped_echo_of_manual_marker_does_not_spoof_badge"
        status: pass
    human_judgment: false
  - id: D4
    description: "Live human check with the monitor running: Ctrl+B on a foreground command lights the badge, completion clears it within a tick"
    verification: []
    human_judgment: true
    rationale: "Deferred to end-of-phase verification per the plan's <verification> section — requires a running monitor and a live terminal interaction, not reproducible in the unit-test harness"

duration: 12min
completed: 2026-07-31
status: complete
---

# Quick Task 260731-bu8: Recognise manually-backgrounded (Ctrl+B) shells

**Widened `BG_START_RE` in shell_tracker.py with a non-capturing alternation so the ⚙ background badge lights for shells the user promotes with Ctrl+B, not just ones Claude starts with `run_in_background` — closing the gap verified live on 2026-07-31 (cc 2.1.220+).**

## Performance

- **Duration:** 12 min
- **Tasks:** 2
- **Files modified:** 2 (shell_tracker.py, test_monitor.py)

## Accomplishments
- `BG_START_RE` now matches both `Command running in background with ID:` and `Command was manually backgrounded by user with ID:`, sharing the same tool_result content anchor and single capture group — `has_active_shells` needed zero edits
- Module docstring and anchoring comment updated to document both background paths and why the anchor tolerates `tool_use_id` preceding `type` in the manual-start record
- Three new regression tests (`Goal2i_ManualBgShellDetected`) grounded in a real live-captured jsonl: badge lights + status stays WAITING, completion notification clears the badge, escaped grep/cat echo of the marker does not spoof it

## Task Commits

1. **Task 1: Recognise the manual-background marker end-to-end** - `c703af0` (feat)
2. **Task 2: Lock down termination and the escaped-echo false positive** - `bbb2444` (test)

## Files Created/Modified
- `shell_tracker.py` - Widened `BG_START_RE` with a non-capturing alternation covering both background-start phrasings; updated module docstring and anchoring comment
- `test_monitor.py` - Added `_manual_bg_shell_start` and `_bg_task_notification` fixture helpers, and `Goal2i_ManualBgShellDetected` (3 tests)

## Decisions Made
- One pattern, one capture group, one `finditer` loop — the plan explicitly forbade a second constant/loop, since that would duplicate the anchoring rationale
- `monitor.py` and `hooks/` left byte-identical, verified by `git diff --name-only -- monitor.py hooks` returning empty after each task — the badge already consumed `has_active_shells`, so the fix flows through existing wiring with zero downstream changes
- Live human verification (Ctrl+B on a running monitor) deferred to end-of-phase per the plan — not a blocking gate for this task

## Deviations from Plan

None - plan executed exactly as written. The regex was implemented with the middle-phrasing alternation exactly as specified (shared "Command " prefix, shared " with ID:" suffix, alternation only on "running in background" vs "was manually backgrounded by user"), verified against both live marker strings before writing tests.

## Issues Encountered
None.

## Verification Results

- `python3 -m unittest test_monitor.Goal2i_ManualBgShellDetected test_monitor.Goal2h_BgShellBadgeOnly -v` → 4/4 pass (Task 1 gate)
- `python3 -m unittest test_monitor.Goal2i_ManualBgShellDetected -v` → 3/3 pass (Task 2 gate)
- `python3 -m unittest test_monitor` → 127 tests, OK (124 baseline + 3 new)
- `git diff --name-only -- monitor.py hooks` → empty after both tasks
- `git diff --stat 1ae5296 HEAD` (plan commit → HEAD) → exactly `shell_tracker.py` and `test_monitor.py` changed, confirming the scope gate

## Next Phase Readiness
- Legacy `shell_tracker.py` badge detection now covers both background-start paths; no follow-on work required for this fix
- Live human check (Ctrl+B on a running monitor, badge lights and clears) still pending per the plan's deferred verification step — candidate for the next opportunistic live-UAT pass alongside the other Phase 3 pre-flip items tracked in STATE.md Pending Todos
- No blockers for Phase 02 (state-writer-shadow-mode) continuation

---
*Phase: quick-260731-bu8*
*Completed: 2026-07-31*

## Self-Check: PASSED

- FOUND: shell_tracker.py
- FOUND: test_monitor.py
- FOUND: .planning/quick/260731-bu8-recognize-manually-backgrounded-ctrl-b-s/260731-bu8-SUMMARY.md
- FOUND: c703af0
- FOUND: bbb2444
