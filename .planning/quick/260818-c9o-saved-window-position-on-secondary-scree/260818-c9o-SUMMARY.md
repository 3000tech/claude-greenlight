---
phase: quick-260818-c9o
plan: 01
subsystem: ui
tags: [tkinter, geometry, multi-monitor, ctypes, win32]

# Dependency graph
requires:
  - phase: quick-260818-bfm
    provides: notify-channel split (local switch mutes audio only) — unrelated code area, no functional dependency
provides:
  - "_virtual_screen_rect(): Win32 GetSystemMetrics lookup for the desktop bounding box across all attached displays, signed, None off Windows or on failure"
  - "_screen_bounds(): virtual rect on Windows, primary-rect fallback everywhere else (byte-identical to the old inline primary computation)"
  - "_sanitize_geometry() rewritten to measure the 60x30 px overlap threshold against _screen_bounds() instead of the primary screen only"
  - "Goal29_SavedGeometrySurvivesSecondaryScreen: 15-case keep/reset verdict table + seam contract tests, real-code coverage on non-Windows CI"
affects: [monitor-ui, geometry-persistence]

actuals:
  tokens: 2578
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Deferred ctypes import inside a broad try/except returning None on any failure — same shape as _flash_taskbar()'s os.name==\"nt\" guard, kept the module importable on Linux/CI"
    - "Module-level seam function (_virtual_screen_rect) + instance method (_screen_bounds) split specifically so a test can monkeypatch the Win32 lookup and drive the overlap math on a non-Windows host"

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py

key-decisions:
  - "Fake._screen_bounds in the test helper delegates lazily to the real MonitorApp method (a wrapper calling monitor.MonitorApp._screen_bounds(self) at call time) rather than binding it eagerly at class-body-eval time — eager binding referenced an attribute that didn't exist yet during the RED phase and broke every stubbed-bounds test too, not just the end-to-end fallback case"

patterns-established:
  - "Geometry sanitization rect is queried live at apply time (never cached) — Task 2 preserved this from the original design so unplugging a monitor is still noticed on next start"

requirements-completed: [QUICK-260818-c9o]

coverage:
  - id: D1
    description: "Saved geometry on a secondary display (left/right/above the primary) survives _sanitize_geometry() unchanged instead of resetting to the default corner"
    requirement: "QUICK-260818-c9o"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_secondary_left_of_primary_kept"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_secondary_right_of_primary_kept"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_secondary_above_primary_kept"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unplugged-monitor protection intact: fully-outside and now-orphaned (secondary unplugged) geometries still reset to _default_geometry(); malformed geometry still resets; 60x30 threshold unchanged in value and strictness"
    requirement: "QUICK-260818-c9o"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_fully_outside_virtual_rect_resets"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_unplugged_secondary_collapses_rect_and_resets"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_malformed_geometry_resets"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_horizontal_overlap_59_resets"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_vertical_overlap_29_resets"
        status: pass
    human_judgment: false
  - id: D3
    description: "Off Windows (or on any Win32 failure), behaviour is identical to today — primary-only verdict preserved"
    requirement: "QUICK-260818-c9o"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_end_to_end_non_windows_fallback_still_resets_left_of_primary"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal29_SavedGeometrySurvivesSecondaryScreen.test_virtual_screen_rect_none_when_win32_entry_point_unreachable"
        status: pass
    human_judgment: false
  - id: D4
    description: "Live Windows behaviour — drag overlay to secondary, restart, verify it reopens in place; unplug secondary, restart, verify it falls back to primary corner"
    verification: []
    human_judgment: true
    rationale: "Requires a physical multi-monitor Windows host; not reproducible in this Linux CI environment. Flagged in the plan's verification section as manual smoke, not a gate."

duration: 5min
completed: 2026-08-18
status: complete
---

# Quick Task 260818-c9o: Saved Window Position on Secondary Screen Summary

**Fixed `_sanitize_geometry()` to measure the 60x30 px overlap threshold against the virtual-screen rect (bounding box of all attached displays) instead of the primary screen only, so a window parked on a secondary monitor survives a restart.**

## Performance

- **Duration:** ~5 min (commit-to-commit)
- **Started:** 2026-08-18T08:56:38Z
- **Completed:** 2026-08-18T09:01:07Z
- **Tasks:** 2
- **Files modified:** 2 (monitor.py, test_monitor.py)

## Accomplishments
- `_sanitize_geometry()` now scores overlap against `_screen_bounds()` — the virtual screen on Windows, primary screen everywhere else — fixing the reported bug where the window always snapped back to the primary's bottom-right corner on restart unless it had last been on the primary
- New module-level `_virtual_screen_rect()` reads `SM_XVIRTUALSCREEN`/`SM_YVIRTUALSCREEN`/`SM_CXVIRTUALSCREEN`/`SM_CYVIRTUALSCREEN` via ctypes with an explicit signed `restype`, deferred import, and broad exception handling — same shape as `_flash_taskbar()`'s existing Windows guard
- The unplugged-monitor protection, the 60x30 px threshold (exact value and strictness), malformed-geometry reset, `_default_geometry()`'s primary-corner behavior, `parse_geometry()`, and the toast placement clamp are all byte-for-byte unchanged
- 15-case `Goal29_SavedGeometrySurvivesSecondaryScreen` test class locks the keep/reset verdict table, both threshold boundary pairs, and drives the real (unbound) `_screen_bounds`/`_virtual_screen_rect` seam on this non-Windows host

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — lock the multi-monitor keep/reset verdict table** - `445dcc2` (test)
2. **Task 2: GREEN — measure geometry overlap against the virtual-screen rect** - `c953cee` (feat)

_TDD plan: RED then GREEN, no separate refactor commit needed._

## Files Created/Modified
- `monitor.py` - Added `_virtual_screen_rect()`, four `SM_*VIRTUALSCREEN` index constants, `_screen_bounds()` instance method, and rewrote `_sanitize_geometry()`'s overlap math to move both edges of each min/max to the new origin
- `test_monitor.py` - Added `Goal29_SavedGeometrySurvivesSecondaryScreen` (15 tests: 3 keep verdicts, 2 reset verdicts, 1 malformed, 4 threshold boundary, 5 seam contract)

## Decisions Made
- Kept the fallback rect fully identical to the old inline primary-screen computation (`(0, 0, winfo_screenwidth(), winfo_screenheight())`), which is what keeps the entire pre-existing suite green on this Linux host without a single edit to any other test
- Did not clamp either low edge to 0 in the overlap math — moving `max(x, 0)` to `max(x, sx)` and `min(x+w, sw)` to `min(x+w, sx+sw)` on both sides is what makes the left-of-primary case pass; a half-fix (raising only the high edge) would have silently left it broken

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed eager attribute binding in the Task 1 test helper that would have broken GREEN**
- **Found during:** Task 2 (implementing `_screen_bounds()` and re-running the suite)
- **Issue:** My first attempt at making the "no stub" end-to-end fallback case exercise the real `_screen_bounds()` method bound `Fake._screen_bounds = monitor.MonitorApp._screen_bounds` directly in the class body. That expression evaluates every time `_fake_app()` runs, including for the stubbed-bounds tests, and `monitor.MonitorApp._screen_bounds` didn't exist during Task 1's own RED phase — so simply calling `_fake_app()` at all would have raised `AttributeError` regardless of which test invoked it, corrupting the RED gate's carefully separated pass/fail shape.
- **Fix:** Replaced the eager class-attribute binding with a `_screen_bounds` method defined directly on `Fake` that delegates to `monitor.MonitorApp._screen_bounds(self)` only when actually called (lazy lookup), leaving the class body itself inert to whether the real method exists yet. The `if bounds is not None: Fake._screen_bounds = lambda self: bounds` override still works unchanged.
- **Files modified:** test_monitor.py
- **Verification:** Re-ran `python3 -m unittest test_monitor.Goal29_SavedGeometrySurvivesSecondaryScreen -v` (15/15 OK) and the full suite (222/222 OK)
- **Committed in:** c953cee (Task 2 commit, alongside the monitor.py implementation, since the bug was in the mechanism Task 2's implementation needed to exercise)

---

**Total deviations:** 1 auto-fixed (1 bug in my own Task 1 test authoring, caught before it could ship)
**Impact on plan:** No scope creep — the fix only touches the test helper's internal wiring, none of the locked verdict assertions changed.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The fix is code-complete and fully covered by unit tests on this Linux host (222/222 green, up from the 207 baseline)
- Manual smoke test on the actual Windows host (drag to secondary, restart, verify position; unplug secondary, restart, verify fallback) remains — noted in the plan's verification section as non-gating, and tracked in STATE.md's pending todos (multi-monitor fix line item)
- `git diff HEAD --stat` at completion lists exactly `monitor.py` and `test_monitor.py` — no `hooks/*` content diff was staged or committed

---
*Phase: quick-260818-c9o*
*Completed: 2026-08-18*

## Self-Check: PASSED

- FOUND: monitor.py
- FOUND: test_monitor.py
- FOUND: SUMMARY.md (this file)
- FOUND commit: 445dcc2 (Task 1 RED)
- FOUND commit: c953cee (Task 2 GREEN)
