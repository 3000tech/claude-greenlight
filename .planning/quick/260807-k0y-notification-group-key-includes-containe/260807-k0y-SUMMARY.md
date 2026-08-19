---
phase: quick-260807-k0y
plan: 01
subsystem: notifications
tags: [notification-gate, group-key, container-identity, hostname, tdd]

requires:
  - phase: quick-260807-iz2
    provides: notification_group_key(), gate_notification(), the hold/release wiring in _check_transitions, and notifications.log — this plan narrows the first function only
provides:
  - notification_group_key() now folds hostname into the group identity (label :: worktree-folded root :: hostname), splitting duplicate-project containers into independent notification channels
affects: [notifications, monitor-overlay, multi-container-workflows]

actuals:
  tokens: 6060
  tasks: 2
  commits: 3

tech-stack:
  added: []
  patterns: ["group identity keyed on container identity (hostname) in addition to project label + worktree-folded cwd, mirroring the existing derive_alias_key/container_display_name per-container disambiguation pattern"]

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py
    - README.md

key-decisions:
  - "hostname read directly via s.get('hostname'), never through derive_alias_key() — that function's fallback returns the row key for an unknown host, which would destroy the ungrouped-\"\" fallback this plan depends on"
  - "Accepted consequence (explicit user decision): the real 2026-08-07 main-tree/worktree pair (hosts 8d5f9694f1de and 4353e1441213) now resolves to two independent groups instead of one shared one — both real Stops still suppress on their own background_tasks_count (checked first), so no user-visible regression in the real episodes"
  - "Goal27's test_20260807_1328_episode_blocked_by_sibling_only renamed to test_20260807_1328_episode_own_background_tasks_only and re-asserted on the background_tasks condition, since the cross-container sibling can no longer block it"

requirements-completed: [QUICK-260807-k0y]

coverage:
  - id: D1
    description: "Two containers of the same project (nursy / nursy-2 — same label, same cwd, different hostname) resolve to different notification_group_key values and no longer block each other"
    requirement: "QUICK-260807-k0y"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal25_GroupGatedNotifications.test_duplicate_project_containers_get_different_keys_and_dont_block"
        status: pass
      - kind: integration
        ref: "test_monitor.py#Goal27_NotificationGateWiring.test_duplicate_project_containers_notify_independently"
        status: pass
    human_judgment: false
  - id: D2
    description: "Within one container the worktree fold and the project-label collision guard are unchanged when hostname matches"
    requirement: "QUICK-260807-k0y"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal25_GroupGatedNotifications.test_worktree_checkout_folds_onto_main_checkout"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal25_GroupGatedNotifications.test_shared_cwd_and_hostname_different_project_labels_never_merge"
        status: pass
    human_judgment: false
  - id: D3
    description: "A session with a missing/empty/non-string hostname is ungrouped, exactly like an unknown cwd, and never blocks or is blocked"
    requirement: "QUICK-260807-k0y"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal25_GroupGatedNotifications.test_unknown_hostname_is_ungrouped"
        status: pass
    human_judgment: false
  - id: D4
    description: "Both 2026-08-07 real episode regressions still assert zero _notify calls and exactly one suppressed record each, now suppressed purely on their own background_tasks_count"
    requirement: "QUICK-260807-k0y"
    verification:
      - kind: integration
        ref: "test_monitor.py#Goal27_NotificationGateWiring.test_20260807_1314_episode_never_notifies_and_logs_once"
        status: pass
      - kind: integration
        ref: "test_monitor.py#Goal27_NotificationGateWiring.test_20260807_1328_episode_own_background_tasks_only"
        status: pass
    human_judgment: false
  - id: D5
    description: "Hold/release and mid-hold reason-change paths still hold verbatim against a real same-container sibling"
    requirement: "QUICK-260807-k0y"
    verification:
      - kind: integration
        ref: "test_monitor.py#Goal27_NotificationGateWiring.test_release_fires_exactly_once_with_held_sec"
        status: pass
      - kind: integration
        ref: "test_monitor.py#Goal27_NotificationGateWiring.test_reason_change_reopens_and_logs_once"
        status: pass
    human_judgment: false
  - id: D6
    description: "notification_group_key()'s docstring and README's grouping bullet describe the same-container rule, and the full 198-test suite stays green"
    requirement: "QUICK-260807-k0y"
    verification:
      - kind: other
        ref: "python3 -m unittest test_monitor.py (198 tests, OK)"
        status: pass
    human_judgment: false

duration: 20min
completed: 2026-08-07
status: complete
---

# Quick Task 260807-k0y: Container identity in the notification group key Summary

**`notification_group_key()` now folds hostname into a three-part key (label :: worktree-folded root :: hostname), so two devcontainers of the same project (nursy / nursy-2) get independent notification channels instead of silencing each other.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-08-07T14:19:00Z (approx, per plan commit e44bb08)
- **Completed:** 2026-08-07T14:39:11Z
- **Tasks:** 2
- **Files modified:** 3 (monitor.py, test_monitor.py, README.md)

## Accomplishments

- `notification_group_key()` in `monitor.py` grows a third `::`-separated component read directly from `s.get("hostname")`, with the same missing/empty/non-string → `""` ungrouped fallback the cwd half already had.
- Docstring fully rewritten: states the container-identity rule, why hostname specifically (same identity family as `derive_alias_key`/`container_display_name`, already stamped by `scan_state_files()`, survives sessionId rotation), what's still retained (worktree fold, project label) and why, and the accepted consequence as a recorded decision rather than a regret.
- `Goal25_GroupGatedNotifications` and `Goal25b_GroupGateEpisodeReplay` re-fixtured with explicit hostnames on every dict whose grouping is under test, plus two new tests: the nursy-vs-nursy-2 pure-function case and the accepted-consequence assertion pinning that the real 2026-08-07 pair now resolves to different groups.
- `Goal27_NotificationGateWiring`'s `_sibling()` helper gained a `hostname` parameter (default: a different container from `_me()`, matching the real 13:28 episode's host); `_nursy`/`_nursy_2` fixtures added for the new end-to-end regression.
- `test_20260807_1328_episode_blocked_by_sibling_only` renamed to `test_20260807_1328_episode_own_background_tasks_only` and re-asserted on the `background_tasks` reason (bg=1, matching the real Stop) since the cross-container sibling can no longer block it; zero-notify and one-record assertions preserved verbatim.
- `test_release_fires_exactly_once_with_held_sec` and `test_reason_change_reopens_and_logs_once` now pass `_me()`'s own hostname to `_sibling()`, keeping a real same-container blocker in play — every existing assertion unchanged.
- New `test_duplicate_project_containers_notify_independently` proves the guarantee end to end through `_check_transitions`: exactly one `_notify` call, one `"sent"` record, and the logged `group` field carries the three-part key.
- README's "What it does" bullet corrected: the wait now explicitly applies "inside one container", with two containers of the same project called out as independent jobs that page separately.
- `gate_notification()`'s body is untouched by this diff (verified via `git diff` inspection) — only `notification_group_key()` changed, per the plan's prohibition.

## Task Commits

Each task was committed atomically:

1. **Task 1: Container identity in the group key, proven on nursy vs nursy-2** - `874f8b0` (feat) — `notification_group_key()` change + docstring + Goal25/Goal25b re-fixtured
2. **Task 2: Re-fixture the wiring regressions, add the firing regression, correct the README** - `6ea432f` (test) — Goal27 re-fixtured, new end-to-end regression, README bullet fixed
3. **Follow-up: docstring typo fix** - `f04478d` (docs) — sentence-case fix in the rewritten docstring, no behavioral change

_Note: split into 3 commits rather than the plan's TDD test→feat pairing per task, since Task 1 edited monitor.py and its own tests together (tracer-style, both changes needed for the new guard to be provable) and Task 2 was test/docs only._

## Files Created/Modified

- `monitor.py` - `notification_group_key()` gains a hostname guard + third key component; docstring rewritten to state the container-identity rule and accepted consequence
- `test_monitor.py` - Goal25/Goal25b re-fixtured with hostnames + 2 new tests; Goal27's `_sibling()` gains a `hostname` param, `_nursy`/`_nursy_2` added, 3 tests updated, 1 new end-to-end regression added
- `README.md` - "What it does" bullet corrected to describe the same-container grouping rule

## Decisions Made

- Read `s.get("hostname")` directly rather than through `derive_alias_key()`, per the plan's explicit prohibition (that function's fallback returns the row key for an unknown host, which would give every hostname-less session a non-empty singleton key).
- Kept the cwd normalisation (backslash conversion, trailing-separator strip, `WORKTREE_MARKER` truncation) byte-identical — only appended the hostname component, changing nothing about how cwd is folded.
- Renamed `test_20260807_1328_episode_blocked_by_sibling_only` rather than leaving a stale name on a test whose assertions now describe a different mechanism (own `background_tasks_count`, not the sibling) — the plan explicitly called this out as expected.

## Deviations from Plan

None — plan executed exactly as written. One minor self-correction: after committing Task 1, a sentence-case typo was noticed in the freshly-written docstring ("...toward silence.\nunder-grouping...") and fixed in a small follow-up commit (`f04478d`) rather than amending — this is a same-file, same-plan, zero-behavior-change cleanup, not a new task or a deviation from the plan's substance.

## Issues Encountered

None.

## Known Stubs

None.

## Threat Flags

None — the plan's own `<threat_model>` covers this diff's full surface (hostname already logged, already string-only, no new consumer).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

This closes the QUICK-260807-k0y todo end to end: duplicate-project containers (nursy/nursy-2) now notify independently, the two real 2026-08-07 episodes stay suppressed for the same reason they always were (their own `background_tasks_count`), and the full `test_monitor.py` suite is green at 198 tests (194 baseline + 4 new: 1 pure-function nursy/nursy-2 case, 1 accepted-consequence assertion, 1 end-to-end nursy/nursy-2 regression, plus the renamed 13:28 test replaces rather than adds to the count).

No blockers. Nothing in Phase 3's `03-UAT.md` live-verification queue is affected by this change — it lives entirely in `notification_group_key()`/`test_monitor.py`/`README.md`, outside the hook-driven state-detection engine that plan is verifying.

---
*Phase: quick-260807-k0y*
*Completed: 2026-08-07*

## Self-Check: PASSED

All created/modified files found (monitor.py, test_monitor.py, README.md, this SUMMARY.md); all 3 task commits found in `git log` (874f8b0, 6ea432f, f04478d).
