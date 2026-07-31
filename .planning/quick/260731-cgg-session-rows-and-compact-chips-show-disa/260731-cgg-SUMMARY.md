---
phase: quick-260731-cgg
plan: 01
subsystem: ui
tags: [tkinter, docker, session-display, disambiguation]

# Dependency graph
requires:
  - phase: quick-260731-c52
    provides: container_display_name() prefix rule for duplicate-project docker rows
provides:
  - session_display_name() and session_display_text() pure display-resolution helpers
  - scan_containers()'s fifth return element (hostname_to_name), kept out of container_info
  - scan() rows carry a display_name field alongside the identity-only name
  - Standard session row, compact chip, and WORKING→WAITING notification all draw the
    disambiguated text
affects: [phase-03-flip, quick-260730-kgw]

# Actuals (#2632)
actuals:
  tokens: 5372
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Display-resolution rule lives once in container_display_name(); session_display_name()
      delegates to it rather than restating the prefix test, so docker rows and session
      rows can never drift apart"
    - "New display-only fields (display_name) travel alongside identity fields (name) rather
      than replacing them, keeping sort/dedup/divergence-log untouched while text-drawing
      call sites read the display field via a tolerant helper (session_display_text)"

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py

key-decisions:
  - "session_display_name() delegates to container_display_name() instead of restating the
    prefix rule, so the two can never diverge"
  - "hostname_to_name is a NEW fifth return element from scan_containers(), kept OUT of
    container_info — the frozen state-file engine's cross-check reads container_info and its
    values must stay pure project labels"
  - "The notification label (WORKING→WAITING toast) is converted to session_display_text too,
    so the toast names the same container the compact chip/session row shows"

patterns-established:
  - "Compute-once-then-compare-then-configure at each drawing call site (existing pattern),
    extended to session_display_text(s) for all three text-drawing sites"

requirements-completed: [QUICK-260731-cgg]

coverage:
  - id: D1
    description: "Session row and compact chip for the SECOND container of a duplicated project
      render dev-tools-2 while the first container's session still renders dev-tools"
    requirement: "QUICK-260731-cgg"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal19_SessionDisplayName.test_duplicate_container_session_resolves_end_to_end"
        status: pass
    human_judgment: false
  - id: D2
    description: "Sessions in randomly-named or unresolvable containers render exactly today's
      text (every fallback branch of session_display_name and scan() row construction)"
    requirement: "QUICK-260731-cgg"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal19_SessionDisplayName (fallback-branch tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "WORKING→WAITING notification label matches the disambiguated chip/row text"
    requirement: "QUICK-260731-cgg"
    verification:
      - kind: unit
        ref: "test_monitor.py (session_display_text used at the _check_transitions call site,
          exercised indirectly via the display-text unit tests; no dedicated notify-path test)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Sort order unchanged: a session displaying dev-tools-2 still sorts at the
      dev-tools launcher position, and s[name] stays the identity everywhere (sort key,
      alias_key, container_info)"
    requirement: "QUICK-260731-cgg"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal19_SessionDisplayName.test_sort_order_unaffected_by_display_name"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal19_SessionDisplayName.test_container_info_keeps_pure_project_labels"
        status: pass
    human_judgment: false
  - id: D5
    description: "Manual smoke: with two dev-tools containers running, the compact bar shows two
      chips reading dev-tools and dev-tools-2, agreeing with the docker rows underneath"
    verification: []
    human_judgment: true
    rationale: "Requires a live Docker environment with two running containers of the same
      project — not reproducible in this sandbox; the PLAN marks this verification step
      optional/user-side"

# Metrics
duration: 15min
completed: 2026-07-31
status: complete
---

# Quick Task 260731-cgg: Session Rows and Compact Chips Show Disambiguated Container Name Summary

**Session rows, compact chips, and the WORKING→WAITING toast now draw `dev-tools-2` for the
second container of a duplicated project instead of a second `dev-tools`, by reusing quick
260731-c52's `container_display_name()` prefix rule through two new pure helpers threaded
through `scan_containers()` and `scan()`.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-31T09:07:00Z (approx)
- **Completed:** 2026-07-31T09:11:57Z
- **Tasks:** 2
- **Files modified:** 2 (`monitor.py`, `test_monitor.py`)

## Accomplishments
- `session_display_name(label, hostname, hostname_to_name)` and `session_display_text(s)` added
  as pure, module-level, tkinter-free functions, delegating the disambiguation rule to the
  existing `container_display_name()` so the rule exists in exactly one place.
- `scan_containers()` now returns a fifth element `hostname_to_name` (hostname → container NAME),
  built from the ps/inspect data it already fetches — no new subprocess call — and kept
  structurally separate from `container_info` so the frozen shadow engine's cross-check is
  untouched.
- `scan()` rows carry a new `display_name` field alongside the identity-only `name`; the sort
  expression, `key`, and `alias_key` are all untouched.
- All three text-drawing call sites (standard session row, compact chip, WORKING→WAITING
  notification) now read `session_display_text(s)` instead of `s["name"]` directly.
- `Goal19_SessionDisplayName` test class (12 tests) locks the end-to-end wiring, every fallback
  branch, the sort guard, and the `container_info` purity guard.

## Task Commits

Each task was committed atomically:

1. **Task 1: One duplicate-container session, resolved end-to-end and drawn in standard mode** -
   `e8f97ff` (feat)
2. **Task 2: Compact chips and the notification label, plus every fallback and the sort guard** -
   `1e07ee1` (feat)

_Note: both tasks were `tdd="true"` but implemented as tracer/auto with tests written alongside
the implementation in the same commit, matching the plan's `<action>` instructions (tests were
part of each task's deliverable, not split into separate RED/GREEN commits)._

## Files Created/Modified
- `monitor.py` - Added `session_display_name()` / `session_display_text()`; `scan_containers()`
  gained `cid_to_name`/`hostname_to_name` and a fifth return element; `scan()` gained a
  `hostname_to_name` parameter and a `display_name` field on each row; `MonitorApp` gained
  `_cached_hostname_to_name`, unpacked in `_kick_docker_query`'s worker and passed to `scan()`;
  the standard session row, `_refresh_compact` chip, and `_check_transitions` notification call
  site all converted to `session_display_text(s)`.
- `test_monitor.py` - `Goal19_SessionDisplayName` test class (12 tests): end-to-end wiring, rule
  fallback branches, `session_display_text` fallback, scan()-row fallbacks, sort guard,
  `container_info` purity guard. Two pre-existing tests (`Goal6d`'s
  `test_scan_containers_docker_absent_container_info_has_all_three_maps` and `Goal12`'s
  `test_scan_containers_returns_four_elements_with_container_info_maps`) updated from
  `len(result) == 4` to `len(result) == 5` to match the new arity (see Deviations).

## Decisions Made
- `session_display_name()` delegates to `container_display_name()` rather than restating the
  prefix test — the whole point is that docker rows and session rows can never drift apart.
- `hostname_to_name` is a new, separate return element from `scan_containers()`, not folded into
  `container_info` — the frozen state-file engine's cross-check reads `container_info` and its
  values must stay pure project labels (verified by a dedicated purity-guard test).
- The notification label is included in the conversion (not just the two visual sites) because a
  toast naming `dev-tools` while the chip reads `dev-tools-2` would point the user at the wrong
  container — the churn is one function argument.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated two pre-existing tests asserting `scan_containers()`'s old 4-element arity**
- **Found during:** Task 1, immediately after the structural change to `scan_containers()`'s
  return signature
- **Issue:** `Goal6d_AliasKeyedByContainer.test_scan_containers_docker_absent_container_info_has_all_three_maps`
  and `Goal12_ContainerInfoShape.test_scan_containers_returns_four_elements_with_container_info_maps`
  both asserted `len(result) == 4` explicitly (in addition to reading `result[3]` by index, which
  the plan correctly predicted would stay green). The plan's context note ("Goal12 reads result[3]
  by INDEX, so appending a fifth return element leaves it green") did not account for these two
  explicit length assertions.
- **Fix:** Changed both assertions to `len(result) == 5` and renamed the Goal12 test method to
  `test_scan_containers_returns_five_elements_with_container_info_maps` for accuracy; no other
  assertion in either test changed.
- **Files modified:** test_monitor.py
- **Verification:** Full suite green (134 → 135 after Task 1) before proceeding to the Goal19 test.
- **Committed in:** e8f97ff (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug caused by the plan's own structural change)
**Impact on plan:** Necessary correctness fix to keep the pre-existing test suite accurate against
the new 5-tuple contract. No scope creep — no other test or behavior touched.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Test suite green at 147 tests (baseline 134 + 13 new: 1 from Task 1, 12 more added/extended in
  Task 2 across the Goal19 class), comfortably above the 143 target.
- Frozen-function gate confirmed byte-identical to HEAD for `scan_state_files`, `diff_verdicts`,
  `filter_divergence_events`, `select_render_sessions`, `write_divergences`.
- `git status --porcelain` over `hooks/` and `shell_tracker.py` returns 0 lines — shadow-mode
  freeze respected.
- Manual live smoke (two real `dev-tools` containers, compact bar showing both chips) remains
  optional/user-side per the plan's verification section — not exercised in this sandbox (no
  Docker daemon / no second running container available here).
- No blockers for the Phase 3 flip; this quick task's changes are purely additive display fields
  read by non-frozen call sites.

---
*Phase: quick-260731-cgg*
*Completed: 2026-07-31*

## Self-Check: PASSED

- FOUND: `.planning/quick/260731-cgg-session-rows-and-compact-chips-show-disa/260731-cgg-SUMMARY.md`
- FOUND: commit `e8f97ff`
- FOUND: commit `1e07ee1`
