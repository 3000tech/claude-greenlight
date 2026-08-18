---
phase: quick-260818-ejg
plan: 01
subsystem: infra
tags: [hooks, install.sh, jq, worktree, event-logger, claude-code]

# Dependency graph
requires:
  - phase: 03-flip-to-default-cleanup
    provides: hooks/install.sh, hooks/hook-events.json, hooks/state-writer-events.json, hooks/settings-snippet.json
provides:
  - "hooks/hook-events.json trimmed to 22 names, WorktreeCreate/WorktreeRemove removed"
  - "hooks/install.sh DELEGATION_EVENTS guard + prune pass, machine-enforced"
  - "test_event_logger.py Goal9 regression coverage for the ban/prune/collateral-safety guarantees"
  - "03-UAT.md Setup runbook expectation corrected to 22"
affects: [03-flip-to-default-cleanup, macbook-devbox]

actuals:
  tokens: 4100
  tasks: 3
  commits: 3

tech-stack:
  added: []
  patterns:
    - "jq denylist constant feeds both a pre-write guard and a command-level prune pass, so ban and cleanup can never drift apart"

key-files:
  created: []
  modified:
    - hooks/hook-events.json
    - hooks/install.sh
    - test_event_logger.py
    - .planning/phases/03-flip-to-default-cleanup/03-UAT.md

key-decisions:
  - "Prune pass placed between the logger-registration pass and the state-writer-registration pass, reusing the file's established jq>tmp+python3-validate+mv rewrite protocol verbatim"
  - "Filtered at the individual hooks[].command level (not the whole entry), matching the --remove-auq-lock/drop_working_cmd precedent, so a co-located foreign command (e.g. GSD's gsd-worktree-path-guard.js) on the same event survives byte-identical"
  - "Event key deleted outright once its array empties (not left as []), so Claude Code cannot read a leftover empty key as a configured delegation hook"
  - "Guard placed before the first filesystem write so a tripped guard leaves the machine untouched — no settings.json, no ~/.claude/hooks/ directory"
  - "New Goal9 test class placed after the pre-existing Goal8 class (added by an unrelated quick task after this plan was authored), not literally 'after Goal7' as the plan assumed"

patterns-established: []

requirements-completed: [QUICK-260818-ejg]

coverage:
  - id: D1
    description: "hooks/hook-events.json is a 22-name array with neither WorktreeCreate nor WorktreeRemove"
    requirement: "QUICK-260818-ejg"
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal9_WorktreeDelegationHooksStayLoggerFree.test_source_json_files_contain_no_worktree_delegation_event_name"
        status: pass
    human_judgment: false
  - id: D2
    description: "install.sh refuses to run (exits non-zero, writes nothing) if hook-events.json re-acquires a delegation event"
    requirement: "QUICK-260818-ejg"
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal9_WorktreeDelegationHooksStayLoggerFree.test_guard_rejects_reinstated_delegation_event_before_any_write"
        status: pass
    human_judgment: false
  - id: D3
    description: "install.sh prunes a stale event-logger.sh attachment on WorktreeCreate/WorktreeRemove from an existing settings.json, deleting the event key when its array empties, and preserving a co-located foreign command"
    requirement: "QUICK-260818-ejg"
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal9_WorktreeDelegationHooksStayLoggerFree.test_upgrade_path_prunes_stale_worktreecreate_and_deletes_the_key"
        status: pass
      - kind: unit
        ref: "test_event_logger.py#Goal9_WorktreeDelegationHooksStayLoggerFree.test_collateral_safety_foreign_worktreeremove_command_survives_logger_pruned"
        status: pass
      - kind: unit
        ref: "test_event_logger.py#Goal9_WorktreeDelegationHooksStayLoggerFree.test_idempotent_second_install_leaves_pruned_state_unchanged"
        status: pass
    human_judgment: false
  - id: D4
    description: "03-UAT.md Setup runbook step expects the current 22-count so re-running Setup does not false-FAIL"
    requirement: "QUICK-260818-ejg"
    verification:
      - kind: other
        ref: "grep -q 'expect 22' .planning/phases/03-flip-to-default-cleanup/03-UAT.md"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-08-18
status: complete
---

# Quick Task 260818-ejg: Installer must not attach event-logger to worktree delegation hooks — Summary

**`hooks/install.sh` now refuses to register the passive `event-logger.sh` on Claude Code's `WorktreeCreate`/`WorktreeRemove` delegation hooks, and prunes stale attachments left by earlier installs — command-level filter, foreign hooks survive, empty keys deleted outright.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-08-18T10:28:00Z
- **Completed:** 2026-08-18T10:39:37Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- `hooks/hook-events.json` trimmed from 24 to 22 names — `WorktreeCreate` and `WorktreeRemove` removed, since those two events are DELEGATION hooks (Claude Code expects the configured hook to create/remove the worktree and print its path itself; a passive logger there fails every worktree operation with `WorktreeCreate hook failed`)
- `hooks/install.sh` gained a `DELEGATION_EVENTS` constant feeding two new mechanisms: a pre-write guard (exits non-zero, writes nothing, if either name reappears in `hook-events.json`) and a post-registration prune pass (strips stale `event-logger.sh` attachments from an already-installed machine, filtering at the individual `hooks[].command` level so a co-located foreign command like GSD's `gsd-worktree-path-guard.js` survives byte-identical, deleting the event key outright once its array empties)
- `test_event_logger.py` gained a new `Goal9_WorktreeDelegationHooksStayLoggerFree` class (6 tests) locking the upgrade path, collateral safety, fresh-install cleanliness, idempotency, the guard, and source-list hygiene across all three JSON files — every count still derives from `len(_hook_events())` at runtime, nothing hardcoded
- `03-UAT.md`'s live Setup runbook step now expects 22 (was 24), dated and attributed to this task, while the 2026-08-06 recorded observation rows stay byte-identical

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end — installer never attaches the logger to a delegation hook, and cleans up the ones it already attached** - `4329624` (feat)
2. **Task 2: Lock the ban, the prune and the sibling-file cleanliness down in the test suite** - `cbe0a02` (test)
3. **Task 3: Keep the 03-UAT Setup runbook step truthful without touching its recorded observations** - `ac4085f` (docs)

**Plan metadata:** pending (orchestrator commits STATE.md/SUMMARY.md separately)

## Files Created/Modified
- `hooks/hook-events.json` - 22-name event list, both delegation events removed
- `hooks/install.sh` - `DELEGATION_EVENTS` constant, pre-write guard, post-registration prune pass, updated header comment
- `test_event_logger.py` - new `Goal9` regression class (upgrade path, collateral safety, fresh install, idempotency, guard, source-list hygiene)
- `.planning/phases/03-flip-to-default-cleanup/03-UAT.md` - Setup step's inline expectation corrected to 22, with a dated attribution note; 2026-08-06 result rows untouched

## Decisions Made
- Prune pass placed between the logger-registration pass and the state-writer-registration pass, reusing the file's established `jq > .tmp` + `python3 json.load` + `mv` rewrite protocol verbatim (no new failure mode introduced)
- Filtered at the individual `hooks[].command` level rather than the whole entry object — same reasoning as the existing `--remove-auq-lock`/`drop_working_cmd` precedent — so a co-located foreign command on the same event (verified with a synthetic `gsd-worktree-path-guard.js` fixture) is provably untouched
- Event key deleted outright (`del(.hooks[$event])`) once its command array empties, rather than left as `[]`, since Claude Code could otherwise still read an empty key as "a hook is configured here" and stay in delegation mode
- New test class placed after the file's actual last class (`Goal8`, added by an unrelated later quick task) rather than literally "after Goal7" as the plan's action text assumed — the plan's placement instruction predates that addition

## Deviations from Plan

None — plan executed exactly as written. The one placement note above (Goal9 after Goal8, not literally after Goal7) is a location adjustment to match the file's actual current structure, not a scope or behavior deviation; it doesn't change any of the `must_haves`.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

**One remaining machine-level follow-up worth flagging to the user:** the live `~/.claude/settings.json` on THIS machine needed no action — it already had 22 `event-logger.sh` attachments and zero `Worktree*` keys, verified during planning. The MacBook devbox at `matteo@192.168.1.139` is the one machine known to still carry (or risk re-acquiring) the stale attachment; it self-repairs on its next plain `bash hooks/install.sh` run, no flag and no manual edit required.

## Next Phase Readiness
- Repo state is safe for `bash hooks/install.sh` on any newly-provisioned machine — `git worktree add` will keep working after install.
- Phase 3's UAT (03-UAT.md) remains open at Sections D–I (per STATE.md); this task only kept the Setup step's registration-count expectation truthful for any future re-run, it did not perform or advance the live UAT.
- 313 tests green (test_event_logger.py + test_state_writer.py + test_monitor.py combined), up from the 307 baseline, no pre-existing assertion edited or weakened.

## Self-Check: PASSED

All 5 claimed files verified present on disk (hooks/hook-events.json, hooks/install.sh, test_event_logger.py, 03-UAT.md, this SUMMARY.md). All 3 claimed commit hashes (4329624, cbe0a02, ac4085f) verified present in git log.

---
*Phase: quick-260818-ejg*
*Completed: 2026-08-18*
