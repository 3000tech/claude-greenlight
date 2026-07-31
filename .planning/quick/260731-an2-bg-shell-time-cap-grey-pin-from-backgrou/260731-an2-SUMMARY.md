---
phase: quick-260731-an2
plan: 01
subsystem: monitor-status-decision
tags: [legacy-engine, bg-shell, status-decision, test-matrix, rev2]
status: complete
dependency-graph:
  requires: []
  provides:
    - "REV.2 (final): a live background shell never pins WORKING — badge-only, no time cap"
    - "TEST-MATRIX record of the no-cap decision for the Phase 3 hook-native rule"
  affects:
    - "monitor.py scan() status decision (legacy branch only)"
tech-stack:
  added: []
  patterns:
    - "REV.2: has_bg dropped entirely from the WORKING OR-chain; the row's raw has_bg still feeds the badge/evidence field unchanged"
key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py
    - .planning/TEST-MATRIX.md
decisions:
  - "REV.2 (final, supersedes rev.1's time-cap): NO cap — a bg shell must NEVER pin WORKING. Removed BG_PIN_MAX_SEC/bg_pinned entirely; has_bg dropped from the WORKING OR-chain"
  - "Grey during a re-invoked turn comes purely from case-13 (UserPromptSubmit -> working-lock), not from the bg shell signal"
  - "Accepted trade-off (user-approved): a finite bg task (build) whose turn ended shows green immediately while it runs — notification fires, badge shows the process"
  - "~~rev.1: BG_PIN_MAX_SEC = 900s time cap~~ SUPERSEDED same day (2026-07-31) by user decision — see Rev. 2 Amendment section"
actuals:
  tokens: 58000
  tasks: 2
  commits: 4
metrics:
  duration: 40min
  completed: 2026-07-31
---

# Phase quick-260731-an2 Plan 01: Background-shell WORKING pin — badge-only (rev.2) Summary

**Final shipped behavior (rev.2):** a live background shell (dev server,
build, anything started with `run_in_background`) never pins a session
grey by itself, at any age. Once the turn has ended the session goes
green immediately and the bg badge alone reports the running process.
Grey during a re-invoked turn (a finite bg task finishing and re-invoking
Claude) comes from the existing case-13 mechanism (`UserPromptSubmit` →
working-lock), not from the bg-shell signal.

This plan originally shipped as a time-capped pin (rev.1, `BG_PIN_MAX_SEC`
= 900s) — see the Rev. 2 Amendment section below for what changed and why.
The commit history preserves both revisions; this summary describes the
final state.

## What was built (rev.1, original plan execution)

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
- Added `Goal2h_BgShellPinTimeCap` with 4 tests (fresh bg shell → WORKING,
  stale bg shell past cap → WAITING with badge still True, finite-task
  inside cap → still WORKING, stale async agent → still WORKING).

**Task 2 — `.planning/TEST-MATRIX.md`:**
- Appended one Italian bullet to `### 4. Async-work-in-flight design (case
  #17)` recording that the Phase 3 hook-native rule inherits the same
  unbounded-pin bug and needs the same time cap, naming `BG_PIN_MAX_SEC` as
  the legacy analogue.

**Verification at rev.1:** `test_monitor` 125/125 (121 baseline + 4 new);
`test_state_writer`/`test_event_logger` 58/58 confirming the shadow/hook
side untouched. Commits `362105c` (code) and `2c6f4d3` (TEST-MATRIX).

## Rev. 2 Amendment (2026-07-31, same day)

**Trigger:** user decision change delivered mid-task-completion — the
15-minute time cap was dropped entirely in favor of a stricter rule: a
background shell must **never** pin WORKING, at any age. The semaphore
goes green as soon as no *other* signal (working-lock, fresh tails,
`is_certainly_working`, agents/monitors/async_agents) says otherwise; the
bg process is reported by the badge only.

**Changes applied (all still legacy-branch only, shadow engine untouched):**

1. **`monitor.py`** — removed the `BG_PIN_MAX_SEC` constant and the
   `bg_pinned` derivation entirely; `has_bg` no longer appears anywhere in
   the WORKING OR-chain. The row's `"bg": has_bg` field is unchanged — it
   is now literally the *only* place `has_bg` is consumed. Rewrote the two
   surrounding comment blocks (GREEN-by-default block + the OR-chain
   comment) to state the new semantics: bg shells are badge-only; grey
   during a re-invoked turn comes from case-13
   (`UserPromptSubmit` → working-lock), not from the shell itself.
2. **`test_monitor.py`** — reworked `Goal2h_BgShellPinTimeCap` into
   `Goal2h_BgShellBadgeOnly` (3 tests, down from 4 — the "inside the cap"
   test no longer applies since there is no cap): fresh bg shell with an
   ended turn → WAITING + badge True; stale bg shell (30 min old) with an
   ended turn → WAITING + badge True (proves no lingering age dependency);
   async agent still in flight → unaffected, still WORKING. Each fixture's
   only tail signal is a plain assistant text block, so nothing besides
   the (now-removed) bg pin could have held the fresh case grey.
3. **`.planning/TEST-MATRIX.md`** — rewrote the section 4 bullet from the
   rev.1 "apply the same cap hook-side" note to the final decision: no
   cap, `background_tasks_count>0` must never hold the hook-native state
   at working — it feeds the ◉N badge (case 18) only. Attributed to
   "quick task 260731-an2 rev.2, 2026-07-31".

**New commits:** `574be6d` (monitor.py + test_monitor.py, atomic) and
`9f18b8f` (TEST-MATRIX.md).

**Test count after rev.2:** `test_monitor` 124/124 (125 rev.1 count − 1,
since Goal2h shrank from 4 to 3 tests). Combined with
`test_state_writer`/`test_event_logger`: 182/182 (183 rev.1 baseline − 1).
Shadow-engine files (`hooks/`, `shell_tracker.py`, `test_state_writer.py`,
`test_event_logger.py`) verified untouched again via `git status
--porcelain` after rev.2.

**Final shape of the OR-chain condition** (monitor.py `scan()`):

```python
if auq_locked:
    status, dot, color, rank = "WAITING", "●", "#4ade80", 1
elif (agents > 0 or async_agents > 0 or monitors > 0
        or is_certainly_working(last_line) or fresh_user_tail
        or working_locked):
    status, dot, color, rank = "WORKING", "●", "#666", 2
else:
    status, dot, color, rank = "WAITING", "●", "#4ade80", 1
```

`has_bg`/`bg_pinned` no longer appear in this chain at all.

## Expected new divergence (flagged for Section E review — rev.2 shape)

Rev.2 changes the divergence surface described at rev.1 (which was
time-bounded) into an unbounded one: the shadow engine's hook-native rule
(`scan_state_files()`, `background_tasks_count>0` → working, still
uncapped by design at this stage) will now diverge from legacy for **any**
bg-shell session whose turn has ended, at any age — not just past 900s.
Whenever a build/test/install bg task outlives its triggering turn, legacy
will say WAITING (green, badge showing the process) while shadow says
WORKING, for the entire remaining lifetime of that bg task. This is
larger and more frequent than the rev.1 divergence, and is the direct,
intended consequence of the user's decision — not a regression.

The shadow engine's code paths remain deliberately untouched per the
review-window constraint — `scan_state_files`, `select_render_sessions`,
`diff_verdicts`, `filter_divergence_events`, `write_divergences`,
`hooks/state-writer.sh` and `hooks/install.sh` are all byte-identical to
before this task (verified by the git-status gate in both revisions).
TEST-MATRIX section 4 (rev.2 bullet) carries the final decision so
whoever executes the Phase 3 flip applies the no-cap, badge-only rule to
the hook-native engine directly, rather than rediscovering it live.

## Deviations from Plan

**1. [User decision change] Time cap replaced with badge-only, same day**
- **Found during:** immediately after rev.1 completion, before the
  orchestrator's docs commit
- **Issue:** the user reconsidered the accepted trade-off in rev.1 (grey
  persisting up to 15 min after an eternal bg process starts) and decided
  the simpler, stricter rule (bg shells never pin, no cap at all) better
  serves the "this session needs you now" core value
- **Fix:** removed `BG_PIN_MAX_SEC`/`bg_pinned` from `monitor.py`, dropped
  `has_bg` from the WORKING OR-chain, reworked the Goal2h tests, and
  rewrote the TEST-MATRIX bullet — see Rev. 2 Amendment section above
- **Files modified:** `monitor.py`, `test_monitor.py`,
  `.planning/TEST-MATRIX.md`
- **Commits:** `574be6d`, `9f18b8f`

## Self-Check: PASSED

- FOUND: monitor.py (no `BG_PIN_MAX_SEC`/`bg_pinned` references; `has_bg` only in the row dict)
- FOUND: test_monitor.py (`Goal2h_BgShellBadgeOnly`, 3 tests, `_bg_shell_start` helper reused)
- FOUND: .planning/TEST-MATRIX.md (rev.2 bullet in section 4, no `BG_PIN_MAX_SEC` reference remaining except historical mention)
- FOUND commit 362105c: feat(quick-260731-an2): time-cap the background-shell WORKING pin (rev.1)
- FOUND commit 2c6f4d3: docs(quick-260731-an2): carry the bg-shell time cap into the hook-native rule (rev.1)
- FOUND commit 574be6d: fix(quick-260731-an2): drop the bg-shell pin entirely — badge-only (rev.2)
- FOUND commit 9f18b8f: docs(quick-260731-an2): rev.2 — no cap, bg shells are badge-only (TEST-MATRIX)
