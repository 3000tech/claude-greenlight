---
phase: 04-notification-truth
plan: 01
subsystem: infra
tags: [bash, jq, hooks, monitor.py, unittest, notifications]

# Dependency graph
requires:
  - phase: 03-flip-to-default-cleanup
    provides: hook-native state-writer.sh as the sole state source, notifications.log, gate_notification() hold/release
provides:
  - "hooks/state-writer.sh Notification branch split from PermissionRequest, with an idle_prompt no-write guard"
  - "Goal10_IdlePingNeverPages end-to-end regression suite (writer -> state file -> scan_state_files -> gate_notification)"
  - "Goal30_IdlePingHoldIntegrity + Goal30b_IdlePingDiskReplay pinning D-02 hold semantics unchanged"
  - "docs/TEST-MATRIX.md case 4 verdict + dated revision entry recording D-01/D-02"
affects: [04-02, ops-devbox-rollout]

# Actuals (#2632)
actuals:
  tokens: 6735
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Writer-side event-type sub-filtering (split a shared case label into two, one exiting 0 without writing) as the pattern for 'this event usually pages but one payload shape must not'"

key-files:
  created: []
  modified:
    - hooks/state-writer.sh
    - test_state_writer.py
    - test_monitor.py
    - docs/TEST-MATRIX.md

key-decisions:
  - "D-01 implemented literally: the Notification branch checks notification_type with the file's standard `jq -r '... // empty'` extraction and exits 0 (no write at all) only when the value is exactly the string idle_prompt; every other value — missing, empty, unrecognised, a number, an object — falls through unchanged to state=needs_input. Fail-safe direction preserved: silence only on the one proven-harmless literal."
  - "D-02 needed zero monitor.py changes. gate_notification()'s existing background_tasks refusal, hold-open/release/expire/reason-change and _check_transitions' session_resumed discard already implement exactly what D-02 ratifies — the bug was entirely the writer manufacturing a fake needs_input/background_tasks_count=0 record. Goal30_IdlePingHoldIntegrity pins this as a finding, not a fix: if any of its 5 tests had needed a monitor.py edit, that would have been a D-02 discrepancy to report, and none did."
  - "hooks/state-writer-events.json left untouched, as the plan required — Notification stays registered; all filtering lives inside the script, so a future notification_type the writer hasn't seen yet still pages (fail-safe) rather than silently stopping needs_input entirely (the rejected matcher-based alternative)."

patterns-established: []

requirements-completed: [NOTIF-01, NOTIF-02]

coverage:
  - id: D1
    description: "A real idle_prompt Notification (live payload key set, no background_tasks key) leaves the session's state file byte-identical, and the shadow engine + notification gate see it as if nothing happened — replays the real 2026-08-17 13:05:44Z/13:06:49Z episode end to end (writer -> state file -> scan_state_files -> gate_notification)."
    requirement: "NOTIF-01"
    verification:
      - kind: integration
        ref: "test_state_writer.py#Goal10_IdlePingNeverPages.test_idle_ping_leaves_state_byte_identical_and_gate_still_refuses"
        status: pass
    human_judgment: false
  - id: D2
    description: "Fail-safe direction: permission_prompt, an absent/empty/unrecognised/non-string notification_type, a bare PermissionRequest, and an idle ping for a session with no existing state file all behave exactly as before — needs_input still writes, no-file-created path stays a no-op."
    requirement: "NOTIF-01"
    verification:
      - kind: integration
        ref: "test_state_writer.py#Goal10_IdlePingNeverPages (4 remaining tests: permission_prompt, fail-safe subTests, PermissionRequest unconditional, no-existing-file)"
        status: pass
    human_judgment: false
  - id: D3
    description: "A background-tasks hold survives repeated unchanged idle-ping ticks (zero notifications, one log record), still releases genuinely when background_tasks_count truly reaches zero, still discards on self-resume, and still expires at NOTIFY_GATE_MAX_HOLD_SEC — all unchanged from D-02's original ratification, with zero monitor.py edits required."
    requirement: "NOTIF-02"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal30_IdlePingHoldIntegrity (5 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "End-to-end disk replay of the real 34518633/2340e510e2ef session (state waiting, background_tasks_count 1) through scan_state_files() -> gate_notification(), confirming the refusal a post-fix idle ping now leaves untouched."
    requirement: "NOTIF-02"
    verification:
      - kind: integration
        ref: "test_monitor.py#Goal30b_IdlePingDiskReplay.test_20260817_session_stays_refused_on_background_tasks"
        status: pass
    human_judgment: false
  - id: D5
    description: "docs/TEST-MATRIX.md case 4 and a new dated section-4 revision entry record the implemented verdict, the episode, the devbox evidence, and the D-01/D-02 decision text."
    verification:
      - kind: other
        ref: "grep -q idle_prompt docs/TEST-MATRIX.md"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-08-19
status: complete
---

# Phase 4 Plan 1: Notification Truth — Writer Guard Summary

**The state writer now ignores `idle_prompt` Notification events outright, closing both the false-page bug (NOTIF-01) and the notification-gate hold leak it caused (NOTIF-02), with an end-to-end regression suite replaying the real 2026-08-17 episode.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-19T10:20:00Z (approx.)
- **Completed:** 2026-08-19T10:33:09Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- `hooks/state-writer.sh`'s `Notification` branch now exits 0 without writing anything when (and only when) `notification_type` is exactly `idle_prompt`; every other case — including missing, empty, unrecognised, or non-string values — still writes `needs_input` exactly as before. `PermissionRequest` was split into its own case label and is completely untouched.
- Because an ignored idle ping never touches the state file, the last real record (waiting, `background_tasks_count` N) stands untouched — which is precisely the evidence `gate_notification()` reads to keep a hold open. NOTIF-02's leak (`gate_cleared` fired by an idle ping, not a real needs_input) is closed at its source with zero changes to `monitor.py`.
- `Goal10_IdlePingNeverPages` in `test_state_writer.py` replays the real 2026-08-17 13:05:44Z/13:06:49Z episode end to end: hook script → state file → `monitor.scan_state_files()` → `monitor.gate_notification()`, proving the state file stays byte-identical (bytes AND `mtime_ns`) and the gate still refuses.
- `Goal30_IdlePingHoldIntegrity` + `Goal30b_IdlePingDiskReplay` in `test_monitor.py` pin the monitor-side half of D-02: a hold survives any number of repeated unchanged idle-ping ticks, genuine release/self-resume-discard/max-hold-expiry are all still correct, and a disk replay of the real session confirms the refusal. None of these needed a `monitor.py` change — the bug lived entirely in the writer.
- `docs/TEST-MATRIX.md` case 4 and a new dated section-4 revision entry record the implemented verdict, the devbox evidence (45/45 idle pings, ~20 false pushes overnight), the live payload key set proving a Notification carries no `background_tasks`, and the D-01/D-02 decision text.

## Task Commits

Each task was committed atomically:

1. **Task 1: An idle ping changes nothing, end to end — hook script to gate decision** - `c570595` (feat)
2. **Task 2: The hold survives an idle ping and still releases when work truly ends** - `ed9e9e3` (test)
3. **Task 3: Record the changed verdict where the project keeps its verdicts** - `d379067` (docs)

_Note: Task 1 followed the plan's RED→GREEN tracer discipline (new tests run and confirmed failing against unmodified `state-writer.sh` first, then the guard implemented) but both steps landed in one commit per the plan's task boundaries — RED was verified interactively, not committed separately, since the plan defines Task 1 as a single `type="tracer"` unit._

## Files Created/Modified
- `hooks/state-writer.sh` - Split `PermissionRequest|Notification)` into two branches; new `Notification)` branch reads `notification_type` and exits 0 without writing when it is exactly `idle_prompt`; header event-to-state mapping table updated to document the exception and its evidence
- `test_state_writer.py` - New `Goal10_IdlePingNeverPages` class (5 tests): the full episode replay, permission_prompt still pages, fail-safe subTests (missing/empty/unrecognised/non-string), PermissionRequest unconditional, idle ping for an unknown session writes nothing
- `test_monitor.py` - New `Goal30_IdlePingHoldIntegrity` class (5 tests) and `Goal30b_IdlePingDiskReplay` class (1 test): hold survives repeated unchanged ticks, the pre-fix leak dict correctly releases (documented as the monitor being right, the writer being wrong), genuine release, self-resume discard, max-hold expiry, and an end-to-end disk replay
- `docs/TEST-MATRIX.md` - Case 4 row amended with the implemented verdict; new dated revision entry in section 4 recording the episode, devbox evidence, payload key set, and both decisions

## Decisions Made
- D-01 implemented as an outright ignore inside the script (not a matcher change in `state-writer-events.json`) — the rejected alternative fails toward silence on any future unknown `notification_type`; the shipped guard fails toward paging, which is the only fail-safe direction consistent with every other guard in this file.
- D-02 required no `monitor.py` change. This was checked explicitly (plan instruction: "if a test cannot be made to pass without changing monitor.py, stop and record the discrepancy as a D-02 finding") — all 6 new monitor-side tests passed against the unmodified gate logic, confirming `gate_notification()`'s background_tasks refusal and `_check_transitions`' hold bookkeeping already implement D-02 correctly.
- `message` (content-bearing, flagged by 01-REVIEW.md) is never read, captured, or logged by the new branch — only `notification_type`, a short fixed enum, consistent with T-04-01's threat-model disposition.

## Deviations from Plan

None — plan executed exactly as written. Task 1's RED phase was run and confirmed failing (2 of 5 new tests failed with the exact expected symptoms — state file rewritten to `needs_input`/`background_tasks_count: 0`, gate returning `allowed=True`) before the guard was implemented, per the plan's tracer discipline.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The fix lives only in this repo's `hooks/state-writer.sh`; it is NOT yet installed into the real `~/.claude/hooks/state-writer.sh` on this or the devbox machine (constraint: `install.sh` must never run against the real `$HOME` from inside this plan). Live deployment + the overnight verification run is plan 04-02's UAT scope.

## Before/After Evidence (this machine)

`~/.claude/notifications.log` on this machine (the live monitor, still running the pre-fix installed hook) currently shows:

```
174 total records
10 gate_cleared records
```

This matches the plan's planning-time count exactly (10). The "after" count cannot be produced by this plan — it requires installing the fixed `hooks/state-writer.sh` into the real `$HOME` and restarting the live monitor, which is explicitly out of scope here (constraint: never run `install.sh` against the real `$HOME`) and belongs to plan 04-02's live rollout + overnight UAT.

## Next Phase Readiness
- The writer guard and its regression suite are complete and self-contained; nothing in this plan touched `monitor.py`, `state-writer-events.json`, or `docs/RECERTIFICATION.md`.
- Plan 04-02 can proceed directly to: (a) NOTIF-03's `notification_text()` host-in-title change, and (b) the live devbox rollout + overnight UAT verifying zero illegitimate notifications with the loop session active, plus a real permission prompt still notifying. Both were explicitly deferred here per ROADMAP Phase 4 success criteria.
- `python3 -m unittest test_monitor test_state_writer` ends in a bare `OK` at 283 tests (272 baseline + 11 new: 5 Goal10 + 5 Goal30 + 1 Goal30b) — no skips, no errors.

---
*Phase: 04-notification-truth*
*Completed: 2026-08-19*

## Self-Check: PASSED

- `hooks/state-writer.sh` — FOUND
- `test_state_writer.py` — FOUND
- `test_monitor.py` — FOUND
- `docs/TEST-MATRIX.md` — FOUND
- `.planning/phases/04-notification-truth/04-01-SUMMARY.md` — FOUND
- Commit `c570595` — FOUND in git log
- Commit `ed9e9e3` — FOUND in git log
- Commit `d379067` — FOUND in git log
- `python3 -m unittest test_monitor test_state_writer` — bare `OK`, 283 tests
