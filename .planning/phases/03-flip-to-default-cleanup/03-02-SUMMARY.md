---
phase: 03-flip-to-default-cleanup
plan: 02
subsystem: monitor-state-engine
tags: [python, tkinter, state-machine, hooks, refactor, dead-code-removal, bash]

# Dependency graph
requires:
  - phase: 03-flip-to-default-cleanup
    provides: "03-01's single-engine render seam (scan_state_files() drives all rendering/notification; scan() stays live feeding the D-02c hookless bridge)"
provides:
  - "shell_tracker.py deleted; its badge-driving detections (bg-shell start/kill, older task-wrapper status) are gone for good — the badge is hook-native (background_tasks_count) from here on"
  - "_peek_agent_activity(): a single-read trimmed in-file peek absorbing only the Monitor/foreground-Agent/async-agent evidence D-02b still needs, replacing three independent whole-file reads per session per tick"
  - "bg_badge_text(): one unified badge (teal ◉, count-only) replacing the gold bg-shell gear + teal Monitor-count pair on both the standard row and the compact chip"
  - "scan_state_files() staleness block extended with D-02a (Esc-interrupt early recovery) and D-02b (hook-silence pin), both reading only the passed-in legacy_sessions evidence — never a second jsonl read or WORKING_LOCK_DIR stat"
  - "SessionEnd tombstones (STATE_TOMBSTONE_SUFFIX = '.ended'): hooks/state-writer.sh drops a marker alongside removing the state file; scan_state_files() excludes any legacy entry whose key/session_id matches one, closing D-06's ghost-row outcome across monitor restarts"
  - "Orphaned tombstone and atomic-write *.json.tmp.* sweeps inside scan_state_files(), same STATE_PRUNE_AGE_SEC threshold and best-effort single-file isolation as the existing state-file prune"
affects: [03-03-cleanup-and-docs, 03-04-uat-and-docs-promotion]

# Actuals (#2632)
actuals:
  tokens: 19037
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-read tail peek: _peek_agent_activity() opens a jsonl exactly once and derives all three activity signals (Monitor/Agent/async-agent) from that one buffer, instead of shell_tracker's three independent whole-file reads (T-03-09)"
    - "Fallback evidence flows through the caller-computed legacy_sessions list, never a second I/O call inside scan_state_files() — proven by a test that repoints PROJECTS_DIR/WORKING_LOCK_DIR at nonexistent paths and still gets the correct pinned/recovered verdict"
    - "On-disk tombstone markers (not an in-process set) for cross-restart-durable 'this session ended' facts — the same durability reasoning STATE_DIR itself already relies on"

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py
    - test_state_writer.py
    - hooks/state-writer.sh
  deleted:
    - shell_tracker.py

key-decisions:
  - "D-02b's Monitor/foreground-Agent/async-agent evidence is RETAINED as a trimmed in-file peek (per 02-DIVERGENCE-REVIEW carry-forward #1 and RESEARCH.md's Open Question 1 orchestrator ruling), while D-03's badge-parsing deletion still stands — the peek and the badge are two separate concerns that shell_tracker previously conflated in one module"
  - "D-02a's early-recovery trigger is floored at STATE_PROMPT_STALE_SEC (90s), not unconditional on age — a state record's own file mtime and its matching legacy jsonl mtime can race within milliseconds of each other at genuine turn start (both hook and jsonl write land in the same instant), and an unfloored comparison misfired on exactly that race during task 2's own test run (Goal13_HooklessFallback's fresh-state-file fixture). The floor costs nothing in the real interrupt case, whose window is 90-600s wide."
  - "Tombstone suffix chosen as '.ended' (STATE_TOMBSTONE_SUFFIX) — cannot collide with the '*.json' glob the state-record loop uses, and is deliberately un-prefixed with '.json' so it can never be mistaken for a partial/malformed state record by any future glob"
  - "A live state record for a session id deletes that session's own stale tombstone as it's read (not just skips it) — a resumed session must not carry a from-a-previous-life tombstone forward to suppress some future legacy bridge entry for the same id"
  - "Badge widget key collapsed from two ('bg', 'monitor') to one ('badge') in both the row and compact-chip dicts and in _bind_alias_click's slot tuple — reuses the surviving teal styling/glyph rather than inventing a third"

patterns-established:
  - "A single-read tail peek returns ONE boolean derived from multiple internal signal sets, never exposing the sets themselves — keeps the caller's WORKING OR-chain a one-term check instead of a three-term one, and keeps the row dict from re-growing per-signal fields"
  - "Fallback branches inside scan_state_files()'s staleness block are documented in its own docstring by TEST-MATRIX case number and divergence class, not left as inline-only comments, so a future reader can trace 'why does this exist' back to the verification matrix"

requirements-completed: [FLIP-01, FLIP-02]

coverage:
  - id: D1
    description: "shell_tracker.py deleted; one unified badge (bg_badge_text) sourced only from the hook-captured background_tasks_count on both the standard row and the compact chip — the two-badge pair and all jsonl-derived badge parsing are gone by construction"
    requirement: "FLIP-01"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal21_UnifiedBadge (4 tests: empty/glyph/count text, status-independence, never-pins-working)"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal23_ShellTrackerRemoved (module ModuleNotFoundError + monitor has no shell_tracker symbols)"
        status: pass
      - kind: other
        ref: "grep -c 'class Goal2h_|class Goal2i_' test_monitor.py == 0; set(row) & {bg,monitors,agents} == set() for both scan() and scan_state_files() rows"
        status: pass
    human_judgment: false
  - id: D2
    description: "scan()'s badge/agent detection collapses to one single-read peek (_peek_agent_activity) covering only Monitor/foreground-Agent/async-agent evidence; scan() emits agent_activity (bool) in place of bg/monitors/agents"
    requirement: "FLIP-01"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal22_AgentActivityPeek (4 tests: unterminated Monitor task true/TaskStop clears it, unmatched Agent true/matching tool_result clears it)"
        status: pass
    human_judgment: false
  - id: D3
    description: "D-02a Esc-interrupt early recovery and D-02b hook-silence pin extend scan_state_files()'s staleness block, both reading only the passed-in legacy_sessions evidence"
    requirement: "FLIP-01"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal11_StateFileStaleness (17 tests total, 8 new: early recovery + two guards, two pin signals + no-pin flip, paused-overrides-fallback, and a PROJECTS_DIR/WORKING_LOCK_DIR-repointed-to-nonexistent-path proof the evidence came from the passed list)"
        status: pass
    human_judgment: false
  - id: D4
    description: "hooks/state-writer.sh's SessionEnd branch drops a tombstone marker alongside removing the state file; scan_state_files() excludes tombstoned sessions from the legacy_origin bridge and sweeps orphaned tombstones + atomic-write temp files"
    requirement: "FLIP-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal6_TurnEndSemantics (tombstone written on SessionEnd; path-traversal session_id writes nothing anywhere)"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal24_SessionEndTombstones (6 tests: bridge suppression, bridge-unaffected-without-tombstone, stale tombstone/temp-file sweeps with fresh-one-kept, tombstone never renders as a row, resumed session self-heals its own tombstone)"
        status: pass
      - kind: other
        ref: "bash -n hooks/state-writer.sh; python3 -m unittest test_monitor.py test_state_writer.py test_event_logger.py (218 tests, one process and per-file)"
        status: pass
    human_judgment: false

# Metrics
duration: 19min
completed: 2026-08-06
status: complete
---

# Phase 3 Plan 2: Retire shell_tracker, add the two staleness fallbacks, close the ghost/temp-file gaps Summary

**Deleted shell_tracker.py and its two-badge pair in favor of one hook-native badge; added D-02a (Esc-interrupt early recovery) and D-02b (hook-silence pin) to scan_state_files()'s staleness block, both reading only already-computed legacy evidence; and closed D-06 (SessionEnd tombstones suppress ghost rows) and D-08 (orphaned atomic-write temp-file sweep) — `monitor.py` net-grows by ~250 lines of hybrid-fallback logic while shedding the 247-line shell_tracker module entirely, three unit suites (218 tests) green throughout.**

## Performance

- **Duration:** 19 min
- **Started:** 2026-08-06T11:39:15Z
- **Completed:** 2026-08-06T11:58:15Z
- **Tasks:** 3
- **Files modified:** 4 (`monitor.py`, `test_monitor.py`, `test_state_writer.py`, `hooks/state-writer.sh`); 1 deleted (`shell_tracker.py`)

## Accomplishments

- **Task 1 — Badge unification.** `shell_tracker.py` (247 lines, 12 regex patterns, 4 public functions) is deleted in full. A new module-private `_peek_agent_activity()` in `monitor.py` opens a jsonl exactly once and derives Monitor/foreground-Agent/async-agent evidence from that single buffer — the exact patterns D-02b still needs, ported byte-anchor-for-byte-anchor, with the bg-shell start/kill and older task-wrapper patterns dropped for good. `scan()`'s row dict drops `bg`/`monitors`/`agents` and gains `agent_activity` (bool); `scan_state_files()`'s row dict drops the same three fields (the hook-captured `background_tasks_count` was already its badge source). A new module-level `bg_badge_text(count)` renders the single unified badge; both the standard row and the compact chip now build one badge label (key `"badge"`) instead of two, reusing the surviving teal `◉` glyph/colour. `Goal2h_BgShellBadgeOnly`/`Goal2i_ManualBgShellDetected` are deleted; their guarantee is re-asserted on state-file fixtures (`Goal21_UnifiedBadge`), the peek gets its own coverage (`Goal22_AgentActivityPeek`), and the module's removal gets its own coverage (`Goal23_ShellTrackerRemoved`).
- **Task 2 — D-02a/D-02b staleness fallbacks.** `scan_state_files()` now builds a `key`/`session_id` lookup from `legacy_sessions` once per tick before its per-record loop, so both new fallbacks read only that already-computed evidence — never a second jsonl read or `WORKING_LOCK_DIR` stat (proven by a test that repoints both to nonexistent paths and still gets the correct verdict). D-02a recovers a WORKING record early — before its heartbeat window elapses — when the matching legacy entry shows `working_locked` False AND a jsonl `mtime` newer than the record's own, the conjunct that turns an ambiguous lock-clear into proof an Esc interrupt already happened; floored at `STATE_PROMPT_STALE_SEC` so a record that's still genuinely fresh can't misfire this as an interrupt. D-02b pins a WORKING record past its window when the legacy entry shows `agent_activity` or `working_locked` True, suppressing the false WAITING notification divergence class 6 (long Monitor/subagent/slow-Bash work) would otherwise produce. `Goal11_StateFileStaleness` grows from 9 to 17 tests.
- **Task 3 — SessionEnd tombstones and the stale temp-file sweep.** `hooks/state-writer.sh`'s SessionEnd branch drops a zero-byte `<session_id>.ended` tombstone alongside the existing unconditional state-file removal, built from the same `session_id` already past the script's path-traversal allowlist guard. `monitor.py` gains `STATE_TOMBSTONE_SUFFIX`; `scan_state_files()` globs tombstones before its legacy-merge tail and excludes any legacy entry whose key/session_id matches one — closing D-06's ghost-row outcome durably across monitor restarts (an in-process suppression set would have forgotten on restart). A live state record for a resumed session id deletes its own stale tombstone as it's read, so a resume can never be suppressed by its earlier SessionEnd. The same function sweeps orphaned tombstones and leftover atomic-write `*.json.tmp.*` files past `STATE_PRUNE_AGE_SEC`, best-effort and single-file-isolated like the existing state-file prune.

## Task Commits

Each task was committed atomically:

1. **Task 1: Retire shell_tracker and unify the badge on the hook-captured count** - `cff55f7` (feat)
2. **Task 2: The two staleness fallbacks — Esc recovery and the hook-silence pin** - `7afba11` (feat)
3. **Task 3: SessionEnd tombstones and the stale temp-file sweep** - `fd88c3f` (feat)

**Plan metadata:** (this commit, docs)

## Files Created/Modified

- `monitor.py` - `shell_tracker` import removed; `_peek_agent_activity()` (single-read Monitor/Agent/async-agent peek) and `bg_badge_text()` added; `scan()`/`scan_state_files()` row dicts drop `bg`/`monitors`/`agents`; `scan_state_files()`'s staleness block gains D-02a/D-02b fallbacks plus tombstone-aware bridge suppression and the tombstone/temp-file sweeps; row/chip builders and `_bind_alias_click` collapse to one badge widget key
- `test_monitor.py` - `Goal2h_BgShellBadgeOnly`/`Goal2i_ManualBgShellDetected` deleted; new `Goal21_UnifiedBadge`, `Goal22_AgentActivityPeek`, `Goal23_ShellTrackerRemoved`, `Goal24_SessionEndTombstones`; `Goal9_StateFileVerdicts`'s key-set assertion updated; `Goal11_StateFileStaleness` grows by 8 tests; dead `_bg_shell_start`/`_manual_bg_shell_start`/`_bg_task_notification` fixtures replaced with `_monitor_started_result`/`_task_stop`
- `test_state_writer.py` - `Goal6_TurnEndSemantics` gains SessionEnd-tombstone and path-traversal-writes-nothing tests
- `hooks/state-writer.sh` - SessionEnd branch writes a tombstone marker after the existing state-file removal; header event-mapping comment documents both effects
- `shell_tracker.py` - deleted in full

## Decisions Made

See `key-decisions` in frontmatter. The one genuine deviation from the plan's literal text: D-02a's early-recovery trigger needed an explicit `age > STATE_PROMPT_STALE_SEC` floor (not just `age <= window`) to avoid misfiring on a same-instant write-order race between the state-file hook and the legacy jsonl at genuine turn start — documented below as a Rule 1 auto-fix, caught by the plan's own acceptance gate (task 2's `<verify>` command) before the task was considered done.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-02a's early-recovery condition needed a floor to avoid a false-positive on fresh state-file writes**
- **Found during:** Task 2, running the `<verify>` command after adding the two fallback branches
- **Issue:** The plan's literal condition (`age <= window` + `working_locked` False + newer legacy mtime) has no lower bound on `age`. A pre-existing test (`Goal13_HooklessFallback.test_legacy_session_sharing_key_with_state_file_is_not_duplicated`) writes a state file and its matching jsonl a few milliseconds apart with no explicit `mtime=`, both landing at "now" — and the jsonl's real-world write happens fractionally after the state file's. That is indistinguishable, under the literal condition, from an actual interrupt's jsonl-advance signal, so the record spuriously recovered to WAITING instead of staying WORKING.
- **Fix:** Added `STATE_PROMPT_STALE_SEC < age` to the `early_recovery` conjunction — a state record has to be genuinely aged (past the shortest legitimate staleness window) before the jsonl-mtime-advance signal is trusted as interrupt evidence. This matches the plan's own Test 1 example verbatim (age "past 90s but well inside 600s"); no test in the plan's Test 1-7 list exercises D-02a below that floor, so no coverage was weakened.
- **Files modified:** monitor.py
- **Verification:** `python3 -m unittest test_monitor.py test_state_writer.py` green before and after; `Goal13_HooklessFallback` unaffected; `Goal11_StateFileStaleness`'s new D-02a tests (which explicitly use ages in the 90-600s range) pass unchanged.
- **Committed in:** `7afba11` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug, caught by the plan's own acceptance gate)
**Impact on plan:** The fix tightens the D-02a trigger to match the plan's own worked example precisely; no scope creep, no test coverage removed or weakened.

## Issues Encountered

None beyond the deviation above.

## User Setup Required

None - no external service configuration required. `hooks/state-writer.sh`'s tombstone write is picked up automatically by any host that already has the hook installed (no reinstall/re-registration needed — the script content changed, not its registration in `settings.json`).

## Next Phase Readiness

- FLIP-01's engine work is complete per this plan's success criteria: `scan()` now serves exactly the three named fallbacks (D-02a evidence source, D-02b evidence source, D-02c hookless bridge source) and nothing else — divergence class 3 (bg-shell rule mismatch) is gone by construction, divergence class 6 (hook silence) is covered by the D-02b pin, and cleanly-ended sessions stay gone across a monitor restart via the D-06 tombstone.
- Chosen tombstone suffix: `STATE_TOMBSTONE_SUFFIX = ".ended"` (in `monitor.py`, mirrored literally as `.ended` in `hooks/state-writer.sh` — kept in sync by inspection since the shell side has no import mechanism to share the Python constant; a future plan touching either side should grep both files together).
- `Goal11_StateFileStaleness`: 9 tests (pre-task) -> 17 tests (post-task).
- `monitor.py`: 2216 lines (pre-plan, end of 03-01) -> 2463 lines (post-plan) — a net addition (`shell_tracker`'s absorbed peek + the two staleness fallbacks + tombstone/sweep logic together add more than the badge-parsing deletion removes), consistent with this plan's `estimate.confidence: low` framing (it always added logic, unlike 03-01's pure-deletion Task 2).
- No blockers. Plan 03-03 (cleanup and docs) can proceed against a `monitor.py` where `scan()`'s only remaining callers/consumers are the three named hybrid fallbacks; plan 03-04 (UAT and docs promotion) has three fresh named behaviours (D-02a/D-02b/D-06 tombstones) to exercise live.

---
*Phase: 03-flip-to-default-cleanup*
*Completed: 2026-08-06*
