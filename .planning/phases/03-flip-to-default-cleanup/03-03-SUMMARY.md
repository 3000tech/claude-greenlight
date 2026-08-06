---
phase: 03-flip-to-default-cleanup
plan: 03
subsystem: monitor-state-engine
tags: [bash, jq, python, hooks, security, testing, refactor]

# Dependency graph
requires:
  - phase: 03-flip-to-default-cleanup
    provides: "03-01's single-engine render seam (scan_state_files() drives all rendering) and 03-02's staleness fallbacks/tombstones — this plan finishes the hook side and closes FLIP-02"
provides:
  - "hooks/state-writer.sh's Stop branch resolves to waiting unconditionally (D-03) — background_tasks_count is badge-only everywhere, divergence class 3 eliminated at its source"
  - "hooks/auq-lock.sh deleted; the default install path no longer installs or registers it; hooks/install.sh --remove-auq-lock tears down an existing install's entries at the individual-command level (not the whole hook-entry object)"
  - "hooks/working-lock.sh backports state-writer.sh's session-id character allowlist (T-03-01) ahead of the lock directory creation and the set/clear branch"
  - "FLIP-02's equivalent-coverage bar closed: the sessionId-rotation alias-parity case ported to state-file fixtures, paused-container visibility locked down, the 60s notification threshold pinned, and the three edge predicates (adjacency/empty/ordering) proven — two were already covered by existing tests"
affects: [03-04-uat-and-docs-promotion]

# Actuals (#2632)
actuals:
  tokens: 7738
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Teardown filters strip at the individual hook-COMMAND level, not the whole hook-entry object — the pre-flip Stop array co-located two different hooks' commands in one entry, and an entry-level select() would have silently deleted the still-live neighbor alongside the retired one"
    - "A hook's session-id validation guard is now duplicated byte-for-byte in shape across every hook that builds a path from payload-derived data (state-writer.sh, working-lock.sh) rather than shared via import — bash hooks have no module system, so the discipline is 'same allowlist, same silent exit-zero,' checked by inspection"

key-files:
  created: []
  modified:
    - hooks/state-writer.sh
    - hooks/install.sh
    - hooks/settings-snippet.json
    - hooks/working-lock.sh
    - test_state_writer.py
    - test_monitor.py
  deleted:
    - hooks/auq-lock.sh

key-decisions:
  - "D-03's Stop branch is unconditional waiting, not gated on background_tasks_count — the count still resolves once and rides into the record, but only ever feeds bg_badge_text(), never the verdict (TEST-MATRIX case 17 rev.2, 02-DIVERGENCE-REVIEW carry-forward #2)"
  - "The --remove-auq-lock teardown filters at the hooks[].command level within each entry, then drops an entry only once its own hooks array is empty — an entry-level filter (matching the pre-existing has_state_writer/has_logger pattern) would have deleted working-lock.sh's co-located Stop-clear command alongside auq-lock.sh's, since the pre-flip snippet put both in one entry object. Caught by this task's own teardown test before committing (Rule 1 auto-fix)."
  - "monitor.py's scan() auq_locked block and AUQ_LOCK_DIR constant are deliberately UNTOUCHED — RESEARCH.md Pitfall 3's anti-bundling rule: the read stays meaningful until every install has run the teardown, and its removal is gated on the live parity confirmation in the 03-UAT.md runbook (plan 03-04), not this mechanical retirement"
  - "FLIP-03 is only PARTIALLY complete after this plan (the hooks/install.sh half); the README half is explicitly plan 03-04's scope per this plan's own <action> text. requirements.mark-complete was run for FLIP-01/FLIP-02 only (both already Complete from 03-01/03-02) — FLIP-03 stays Pending in REQUIREMENTS.md until 03-04 closes it. Deviation from the plan's literal frontmatter list (which names all three), applied deliberately rather than mechanically."
  - "Paused-container visibility (D-05) renders as an ordinary row, no dimming, no new color — the least-surprising reading of CONTEXT.md's 'no new colors, no new notification types' fence, requiring zero rendering code"

patterns-established:
  - "Coverage-accounting table (deleted class -> guarantee -> now-covered-by) as a first-class SUMMARY artifact for FLIP-02-style consolidation plans, not just prose bullets — see the table below"

requirements-completed: [FLIP-01, FLIP-02]

coverage:
  - id: D1
    description: "hooks/state-writer.sh's Stop branch is badge-only: no Stop payload, at any background-task count, ever writes a working verdict; background_tasks_count still feeds bg_badge_text() unchanged"
    requirement: "FLIP-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal6_TurnEndSemantics (rewritten turn-end family: one-running/mixed-three/missing-status all assert waiting; new parameterised counts-0/1/5 never-working guard)"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal21_UnifiedBadge.test_bg_count_never_pins_working (already present from plan 03-02, monitor-side half)"
        status: pass
      - kind: other
        ref: "bash -n hooks/state-writer.sh; manual Stop-payload drives for counts 0/1/3-mixed all produced state=waiting with the correct count field"
        status: pass
    human_judgment: false
  - id: D2
    description: "The AskUserQuestion lock hook (auq-lock.sh) is retired: deleted from the repo, no longer installed or registered by the default path, and a validated --remove-auq-lock teardown exists for installs that already registered it"
    requirement: "FLIP-03"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal9_AuqLockRetired (fresh install registers zero auq-lock entries, teardown strips only retired entries at command granularity, missing-settings no-op, unknown-arg usage lists all three modes)"
        status: pass
      - kind: other
        ref: "grep -rn auq-lock hooks/ | grep -v install.sh | grep -v comment -> empty; test ! -f hooks/auq-lock.sh"
        status: pass
    human_judgment: false
  - id: D3
    description: "hooks/working-lock.sh validates session_id against the same filename-safe allowlist state-writer.sh uses, before the lock directory is created and before either branch runs; a malformed id writes nothing outside the lock directory"
    requirement: "FLIP-01"
    verification:
      - kind: unit
        ref: "test_state_writer.py#Goal9a_WorkingLockSessionIdValidation (path-traversal set creates no file, path-traversal clear removes nothing outside the lock dir, well-formed id still sets/clears)"
        status: pass
    human_judgment: false
  - id: D4
    description: "FLIP-02's equivalent-coverage bar: every user-facing guarantee that lost its legacy test has a state-file (or already-existing) successor, evidenced by the deleted-class table below; three suites (233 tests) green individually and together, above the 205 pre-flip baseline"
    requirement: "FLIP-02"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6e_AliasKeyParityAcrossEngines.test_sessionid_rotation_keeps_same_alias_key_on_state_files, #Goal11_StateFileStaleness.test_paused_container_session_visible_via_hostname_label_ordinary_row, #Goal8_NotificationDebounce.test_minimum_work_threshold_is_60_seconds, #Goal20_RenderSeamFlip.test_one_state_file_alone_yields_exactly_one_row + test_one_legacy_session_alone_yields_exactly_one_row"
        status: pass
      - kind: other
        ref: "python3 -m unittest test_monitor.py test_state_writer.py test_event_logger.py (233 tests, one process and per-file: 163+43+27)"
        status: pass
      - kind: other
        ref: "git diff 8925c22 -- monitor.py over the _notify_toast secondary-display clamp block: no output (byte-identical, multi-monitor fix preserved)"
        status: pass
    human_judgment: false

# Metrics
duration: 27min
completed: 2026-08-06
status: complete
---

# Phase 3 Plan 3: Badge-only turn-end, retired AUQ lock, FLIP-02 closed Summary

**hooks/state-writer.sh's Stop branch now resolves to waiting unconditionally (D-03, eliminating divergence class 3 at its source); the AskUserQuestion lock hook is retired from the default install with a validated command-level teardown for existing installs; hooks/working-lock.sh gained state-writer.sh's session-id allowlist; and FLIP-02's equivalent-coverage bar is closed with a full deleted-class-to-replacement table — three suites at 233 tests, up from the 205 pre-flip baseline.**

## Performance

- **Duration:** 27 min
- **Started:** 2026-08-06T11:59:00Z (approx.)
- **Completed:** 2026-08-06T12:26:00Z
- **Tasks:** 3
- **Files modified:** 6 (`hooks/state-writer.sh`, `hooks/install.sh`, `hooks/settings-snippet.json`, `hooks/working-lock.sh`, `test_state_writer.py`, `test_monitor.py`); 1 deleted (`hooks/auq-lock.sh`)

## Accomplishments

- **Task 1 — Turn-end becomes badge-only at the source.** `hooks/state-writer.sh`'s `Stop` branch resolves to `waiting` unconditionally instead of gating on `background_tasks_count > 0`. The count is still resolved once (same deny-list rule, unchanged) and still written into the record — `bg_badge_text()` is its only remaining consumer. The header's event-to-state mapping comment now states the shipped rule and points at TEST-MATRIX section 4 rev.2 rather than the original case 17 reading. `test_state_writer.py`'s `Goal6_TurnEndSemantics` family was rewritten: the one-running and missing-status cases now assert `waiting`, a new mixed running/completed/failed case proves the deny-list count rule is untouched (count `1`), and a parameterised counts-0/1/5 test proves no `Stop` payload ever produces a `working` verdict. `test_monitor.py` needed no change — plan Test 5 (the monitor-side end-to-end half) was already present from plan 03-02 (`Goal21_UnifiedBadge.test_bg_count_never_pins_working`).
- **Task 2 — Retire the AskUserQuestion lock hook, validate the working lock.** `hooks/auq-lock.sh` is deleted from the repo. The default install path no longer installs it, no longer creates its lock directory, and the settings merge no longer touches `PostToolUse`/`Notification` (which existed solely to register it) or filters `PreToolUse` by AskUserQuestion matcher. A new `--remove-auq-lock` teardown mode, cloned from the existing backup/jq/validate/move sequence, strips an existing install's retired entries — but at the individual `hooks[].command` level within each entry, not the whole entry object: the pre-flip `Stop` array co-located `auq-lock.sh`'s clear command with `working-lock.sh`'s in one shared entry, and the first (entry-level) filter implementation silently deleted the still-live `working-lock.sh` clear alongside the retired one. Caught and fixed (Rule 1) by this task's own synthetic teardown test before the commit. `hooks/settings-snippet.json` now ships only the working-lock/state-writer/event-logger set. `hooks/working-lock.sh` backports `state-writer.sh`'s session-id character allowlist verbatim in shape, placed before the lock directory is created and before either branch runs, with the same silent exit-zero on rejection. `monitor.py`'s `scan()` `auq_locked` block and `AUQ_LOCK_DIR` constant are deliberately unchanged.
- **Task 3 — FLIP-02 equivalent coverage.** Diffed `Goal6d_AliasKeyedByContainer` (legacy) against `Goal6e_AliasKeyParityAcrossEngines` (state-file); the one confirmed gap — sessionId rotation with a shared container hostname — is now `Goal6e`'s `test_sessionid_rotation_keeps_same_alias_key_on_state_files`. Paused-container visibility (D-05) is locked down as an ordinary row (no dimming, no new color) via a state record resolved only through `container_info["hostname_to_label"]`. The 60-second notification threshold is pinned directly (`NOTIFY_MIN_WORK_SEC == 60`) alongside its existing end-to-end coverage in `Goal8_NotificationDebounce`. The multi-monitor toast-placement clamp guard was verified byte-identical against the phase-start commit (`8925c22`) — no diff, no regression to fix. Two of the plan's edge predicates (adjacency, ordering) were already covered by existing tests (`Goal13_HooklessFallback.test_legacy_session_sharing_key_with_state_file_is_not_duplicated`, `Goal20_RenderSeamFlip.test_equal_sort_keys_keep_input_order_stable`); the empty/single edge was completed with two new explicit single-element tests.

## Task Commits

Each task was committed atomically:

1. **Task 1: Turn-end becomes badge-only at the source** - `be40e5d` (feat)
2. **Task 2: Retire the AskUserQuestion lock hook and validate the working lock** - `9fc675c` (feat)
3. **Task 3: FLIP-02 — equivalent coverage on state-file fixtures** - `3ec0917` (test)

**Plan metadata:** (this commit, docs)

## Files Created/Modified

- `hooks/state-writer.sh` - `Stop` branch resolves to `waiting` unconditionally; header mapping comment updated
- `hooks/install.sh` - default path drops auq-lock install/registration; new `--remove-auq-lock` teardown mode (command-level filter); argv validation extended; header rewritten to describe the shipped hook set
- `hooks/settings-snippet.json` - reduced to working-lock/state-writer/event-logger registration only; `PostToolUse`/`Notification` removed entirely
- `hooks/working-lock.sh` - session-id character allowlist added before the lock directory is created
- `hooks/auq-lock.sh` - deleted
- `test_state_writer.py` - `Goal6_TurnEndSemantics` rewritten for the badge-only rule; `Goal8_MigrationNonRegression` updated (auq-lock byte-comparison dropped); new `Goal9a_WorkingLockSessionIdValidation` and `Goal9_AuqLockRetired`
- `test_monitor.py` - new tests in `Goal6e_AliasKeyParityAcrossEngines` (rotation parity), `Goal11_StateFileStaleness` (paused visibility), `Goal8_NotificationDebounce` (threshold pin), `Goal20_RenderSeamFlip` (single-element edges)

## Decisions Made

See `key-decisions` in frontmatter. The two most consequential:
1. The `--remove-auq-lock` teardown filters at the command level, not the entry level, after a synthetic test caught the entry-level version silently deleting a co-located `working-lock.sh` command.
2. `requirements.mark-complete` was run for FLIP-01 and FLIP-02 only. FLIP-03 is explicitly split across this plan (hooks/install.sh half) and plan 03-04 (README half) per this plan's own `<action>` text — marking it complete now would be inaccurate. It stays `Pending` in REQUIREMENTS.md.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `--remove-auq-lock`'s entry-level filter would have deleted a co-located `working-lock.sh` command**
- **Found during:** Task 2, writing the synthetic teardown test against a settings.json shaped like a real pre-flip install
- **Issue:** The first implementation copied the existing `has_state_writer`/`has_logger` pattern verbatim: `map(select(has_auq_lock | not))` drops the whole entry object if ANY command inside it matches. That pattern is safe for state-writer/logger because each of those always gets its own dedicated entry object (one command per entry, via the reduce-loop registration). But the pre-flip `Stop` array put `auq-lock.sh`'s clear command and `working-lock.sh`'s clear command in ONE shared entry — so the entry-level filter deleted both, silently breaking `working-lock.sh`'s Stop-clear guarantee for anyone running the teardown against a real pre-flip install.
- **Fix:** Rewrote the filter to operate on `.hooks[]` (the individual command list) within each entry, dropping only commands matching `auq-lock\.sh`, then dropping an entry only once its own `.hooks` array is empty.
- **Files modified:** hooks/install.sh
- **Verification:** New `test_remove_auq_lock_strips_only_retired_entries_leaving_working_lock_intact` (test_state_writer.py#Goal9_AuqLockRetired) asserts the working-lock command count is unchanged (2) after teardown against a two-command Stop entry.
- **Committed in:** `9fc675c` (Task 2 commit)

**2. [Rule 3 - Blocking] `Goal8_MigrationNonRegression`'s cross-install regression test asserted `hooks/auq-lock.sh` exists**
- **Found during:** Task 2, running the full three-suite verify command
- **Issue:** `_lock_scripts_match_repo()` asserted both `working-lock.sh` and `auq-lock.sh` are installed and byte-identical to the repo copies — a direct consequence of this task's own deletion, not a pre-existing failure.
- **Fix:** Dropped the `auq-lock.sh` half of the assertion (and the now-dead `AUQ_LOCK_SH`/`LOCK_PATTERN` auq-lock alternation), documented why in a docstring.
- **Files modified:** test_state_writer.py
- **Verification:** `python3 -m unittest test_state_writer.py` green; `Goal8`'s install/reinstall/teardown lock-count assertions still pass unchanged for `working-lock.sh`.
- **Committed in:** `9fc675c` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 Rule 1 - a real correctness bug caught by this plan's own new test before it shipped; 1 Rule 3 - test breakage caused directly by this plan's own deletion)
**Impact on plan:** Both fixes were necessary for correctness and for the plan's own "suite green" acceptance gate. No scope creep — no behavior outside the retirement and its teardown was touched.

## FLIP-02 Coverage Table

| Deleted/reduced class (phase) | Guarantee it asserted | Now covered by |
|---|---|---|
| `Goal2h_BgShellBadgeOnly` (03-02) | A live background shell in the transcript never pins the row at WORKING by itself | `test_monitor.py#Goal21_UnifiedBadge.test_bg_count_never_pins_working` (03-02) + this plan's `test_state_writer.py#Goal6_TurnEndSemantics` (the hook-native source of that same guarantee, now badge-only at the writer) |
| `Goal2i_ManualBgShellDetected` (03-02) | Manually-backgrounded (Ctrl+B) shells surface in the badge | Superseded by the hook-native badge: `bg_badge_text()` sources from `background_tasks_count` regardless of how a task was backgrounded — `Goal21_UnifiedBadge`'s badge-text tests cover the unified mechanism directly; the manual-vs-automatic distinction no longer exists as a code path to test |
| `Goal14_DivergenceRecords` (03-01) | State-file engine's verdict differs from legacy jsonl parsing only in currently-accepted ways | Superseded by direct verdict-correctness coverage now that the state-file engine is the sole engine, not diffed against legacy: `Goal9_StateFileVerdicts` (state->status mapping) + `Goal11_StateFileStaleness` (17 tests, staleness/fallback correctness) + this plan's `Goal6_TurnEndSemantics` (badge-only Stop rule) |
| `Goal15_DivergenceEpisodes` (03-01) | Repeated divergences collapse into one tracked episode instead of spamming the log | N/A — shadow-mode diagnostic log retired outright with this plan/03-01's predecessors; no user-facing successor exists because users never saw the divergence log. Matches 03-01 SUMMARY's disposition for the sibling `Goal16`/T-02-17 case below |
| `Goal16_DivergenceLogGuard` (03-01, T-02-17) | The divergence log never contains raw prompt/tool-input text | N/A — the `legacy_evidence` builder it guarded was deleted with the code (03-01 Task 2); 03-01's SUMMARY records this explicitly and the `must_haves` prohibition against reintroducing such a builder stays flagged for future plans, unbroken as of this plan |
| `Goal17_StateFilesMode` (03-01, reduced) | The `--state-files`/engine-selection flag resolves to the correct engine | Superseded by D-01's decision that the flag is inert: `Goal17_RenderSeam`'s identity-seam assertions prove `select_render_sessions()` is an unconditional 1-argument identity function — "correct resolution" now means "the flag does nothing," asserted directly rather than via a resolver |

## Issues Encountered

None beyond the two deviations above, both caught by this plan's own acceptance gates before committing.

## User Setup Required

None - no external service configuration required. `hooks/state-writer.sh`'s Stop-branch change and `hooks/working-lock.sh`'s new guard are picked up automatically by any host that already has the hooks installed (script content changed, not registration). A host with an existing `auq-lock.sh` registration keeps it until the user runs `bash hooks/install.sh --remove-auq-lock` there — that run is plan 03-04's UAT runbook, not this plan's scope.

## Next Phase Readiness

- The hook side of the flip is finished: `hooks/state-writer.sh` is badge-only at the source, `hooks/install.sh`/`hooks/settings-snippet.json` ship the retired-hook-free default with a validated teardown, and `hooks/working-lock.sh` matches `state-writer.sh`'s input-validation standard.
- FLIP-02 is closed with an evidenced coverage table — no empty cell, no silently-shrunk guarantee.
- FLIP-03 is half-done: the `hooks/install.sh` half ships here; the README half (documenting the shipped architecture, the retired hook, and `--remove-auq-lock`) is plan 03-04's scope, along with the live parity confirmation gate for eventually removing `monitor.py`'s `auq_locked` read.
- Three suites: 163 (`test_monitor.py`) + 43 (`test_state_writer.py`) + 27 (`test_event_logger.py`) = 233 tests, green individually and together, above the 205 (147+31+27) pre-flip baseline recorded in plan 03-01's SUMMARY.
- No blockers.

---
*Phase: 03-flip-to-default-cleanup*
*Completed: 2026-08-06*

## Self-Check: PASSED

All files created/modified confirmed present on disk (`hooks/state-writer.sh`, `hooks/install.sh`, `hooks/settings-snippet.json`, `hooks/working-lock.sh`, `test_state_writer.py`, `test_monitor.py`); `hooks/auq-lock.sh` confirmed absent. All three task commit hashes (`be40e5d`, `9fc675c`, `3ec0917`) confirmed present in `git log --oneline --all`.
