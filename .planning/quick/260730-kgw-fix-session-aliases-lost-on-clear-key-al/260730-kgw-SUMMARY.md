---
phase: quick-260730-kgw
plan: 01
subsystem: monitor
tags: [python, tkinter, docker, session-state, aliases]

# Dependency graph
requires:
  - phase: 02-state-writer-shadow-mode
    provides: scan_containers()'s container_info (hostname_to_label/hostname_to_status) and scan_state_files()'s hostname-carrying state records, both reused as the alias-identity source
provides:
  - "derive_alias_key(hostname, fallback_key) — the single alias-identity function both engines call"
  - "scan()/scan_containers()/query_container_sessionids() emitting/threading sessionid_to_hostname and alias_key"
  - "scan_state_files() emitting alias_key from its record's hostname, with container_info forwarded into its --state-files diagnostic-mode internal scan() call"
  - "MonitorApp._alias_key()/_alias_keys/_prune_aliases() — row-key-to-alias-key resolution consumed by _edit_alias, _notify, and both render loops"
affects: [03-flip-to-hooks-primary, monitor-ui, alias-persistence]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Namespaced identity keys (ALIAS_HOST_PREFIX = 'host:') to let two different identity spaces (container hostname vs. legacy row key) share one dict without collision"
    - "Row-key -> stable-identity indirection rebuilt once per tick (self._alias_keys), so click handlers can stay bound to a volatile row key while every read/write resolves the durable identity at call time"

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py
    - README.md

key-decisions:
  - "Container HOSTNAME (not container ID or name) is the alias identity, because it's the one identity both the legacy engine (docker inspect) and the hook-written state records can observe — anything else would make the two engines disagree about which alias a row owns"
  - "Container-derived keys are namespaced with ALIAS_HOST_PREFIX ('host:') so a hostname string can never collide with a raw sessionId or dir-fallback key already living in the same aliases dict"
  - "No migration for aliases persisted under old sessionId keys — the existing one-time startup prune drops them once, which is the accepted, documented outcome"
  - "The startup prune's liveness check switched from row-key membership to alias-key membership, and its input switched from raw sessions to render_sessions; in default operation render_sessions IS the legacy list, so this is behaviour-identical to before"

patterns-established:
  - "Pattern: identity indirection layer (_alias_keys) resolved fresh each tick, read at click/render time — avoids re-binding per-row click handlers while still tracking a row's current durable identity"

requirements-completed: [QUICK-260730-kgw]

coverage:
  - id: D1
    description: "derive_alias_key() namespaces a known container hostname and falls back to the row key for None/empty/non-string hostnames"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_derive_alias_key_namespaces_a_known_hostname"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_derive_alias_key_falls_back_when_hostname_unresolvable"
        status: pass
    human_judgment: false
  - id: D2
    description: "scan() emits alias_key on each row (container-derived when container_info resolves the sessionId's hostname, else the row's own key) without changing the row's key"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_scan_row_gets_container_alias_key"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_scan_row_without_container_info_keeps_todays_behaviour"
        status: pass
    human_judgment: false
  - id: D3
    description: "THE REGRESSION: two scans of the same container under two different sessionIds (simulating /clear) emit different row keys but the same alias_key"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_sessionid_rotation_keeps_same_alias_key"
        status: pass
    human_judgment: false
  - id: D4
    description: "scan_containers()/query_container_sessionids() thread sessionId->hostname through to container_info['sessionid_to_hostname'] with no added subprocess call, and the docker-absent early return keeps the 4-tuple shape with all three container_info maps present"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_scan_containers_docker_absent_container_info_has_all_three_maps"
        status: pass
    human_judgment: false
  - id: D5
    description: "MonitorApp._alias_key()/_edit_alias()/_prune_aliases() resolve, store, and prune by the container alias key instead of the row key, so a label set before a sessionId rotation is readable under the new row key afterward"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_alias_key_maps_known_row_key_and_falls_back_for_unknown"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_edit_alias_stores_under_alias_key_readable_via_different_row_key"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_edit_alias_clear_pops_under_alias_key"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_prune_aliases_keeps_live_drops_dead_and_runs_once"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6d_AliasKeyedByContainer.test_prune_aliases_is_noop_on_empty_session_list"
        status: pass
    human_judgment: false
  - id: D6
    description: "The two engines agree on alias identity for the same container: scan_state_files() derives alias_key from its record's hostname (falling back to session_id), matches scan()'s alias_key for the same session/hostname, keeps a carried-through hookless-fallback row's alias_key, and the --state-files diagnostic path's internal scan() fallback now forwards container_info so it keys aliases the same way as default mode"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal6e_AliasKeyParityAcrossEngines.test_state_file_row_alias_key_from_hostname"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6e_AliasKeyParityAcrossEngines.test_state_file_row_without_hostname_falls_back_to_session_id"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6e_AliasKeyParityAcrossEngines.test_parity_legacy_and_state_file_rows_share_alias_key"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6e_AliasKeyParityAcrossEngines.test_carried_through_legacy_row_keeps_its_alias_key"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal6e_AliasKeyParityAcrossEngines.test_diagnostic_mode_internal_scan_forwards_container_info"
        status: pass
    human_judgment: false
  - id: D7
    description: "Shadow-mode plumbing (diff_verdicts, filter_divergence_events, write_divergences, select_render_sessions) is untouched — Phase 02 D-01 preserved"
    verification:
      - kind: other
        ref: "git diff monitor.py | grep -E '^[-+].*(diff_verdicts|filter_divergence_events|write_divergences|select_render_sessions)' returns nothing"
        status: pass
    human_judgment: false
  - id: D8
    description: "A label set on a session row survives a live /clear (sessionId rotation) and a monitor restart (startup prune), both in the overlay row and in a ready-notification"
    verification: []
    human_judgment: true
    rationale: "Requires a live Docker container, a live Claude Code CLI session, and observing the overlay UI across a /clear + monitor restart — this is the plan's Task 2 <human-check>, not run in this non-interactive execution session"

# Metrics
duration: 9min
completed: 2026-07-30
status: complete
---

# Quick 260730-kgw: Fix session aliases lost on /clear Summary

**Container-hostname-keyed alias identity (`derive_alias_key`/`ALIAS_HOST_PREFIX`) replaces sessionId-keyed aliases, so a user-set session label now survives `/clear`, `/resume`, and CLI restarts instead of vanishing every time the jsonl sessionId rotates.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-30T14:52:00Z (approx, first read of plan)
- **Completed:** 2026-07-30T15:01:08Z
- **Tasks:** 2
- **Files modified:** 3 (monitor.py, test_monitor.py, README.md)

## Accomplishments
- Added `derive_alias_key(hostname, fallback_key)` and `ALIAS_HOST_PREFIX = "host:"` — the single, namespaced alias identity both engines derive from
- Threaded container hostname end-to-end: `scan_containers()`'s existing `docker inspect` loop now also builds `cid_to_hostname`; `query_container_sessionids()` returns `sessionId -> hostname` alongside `sessionId -> label` with no added subprocess call; `container_info` carries the new `sessionid_to_hostname` map
- `scan()` and `scan_state_files()` both emit `alias_key` per row (container-derived when resolvable, today's row key otherwise) — proven to agree for the same session/hostname
- `MonitorApp` resolves every alias read/write/prune through a per-tick `_alias_keys` row-key→alias-key map (`_alias_key()`), so `_edit_alias`, `_notify`, and both the standard and compact render loops all key off the container instead of the volatile row key; click bindings stay on the row key, resolved at click time
- Extracted the one-time startup prune into `_prune_aliases()`, now gated on alias-key liveness of `render_sessions` (same three guarantees preserved: runs once, no-op on empty list, saves only when something was dropped)
- Updated the README config table to describe per-container (not per-session) aliases
- Added 16 new regression tests (`Goal6d_AliasKeyedByContainer` x11, `Goal6e_AliasKeyParityAcrossEngines` x5) locking down the `/clear` survival guarantee and cross-engine parity

## Task Commits

Each task was committed atomically:

1. **Task 1: Alias identity = container, wired end-to-end through the default (legacy-rendered) path** - `db8fc86` (feat)
2. **Task 2: Same alias identity in the state-file engine, plus the README config note** - `e558946` (test)

**Plan metadata:** pending — orchestrator commits SUMMARY.md/STATE.md/ROADMAP.md separately per this task's constraints.

## Files Created/Modified
- `monitor.py` - `derive_alias_key`/`ALIAS_HOST_PREFIX`; `scan()`, `scan_containers()`, `query_container_sessionids()`, `scan_state_files()` alias-key plumbing; `MonitorApp._alias_key`/`_alias_keys`/`_prune_aliases`; `_edit_alias`/`_notify`/render-loop alias reads routed through `_alias_key`
- `test_monitor.py` - `Goal6d_AliasKeyedByContainer` (container-key derivation, scan() wiring, sessionId-rotation regression, `scan_containers()` shape, `_alias_key`/`_edit_alias`/`_prune_aliases`); `Goal6e_AliasKeyParityAcrossEngines` (state-file alias_key, cross-engine parity, hookless-fallback carry-through, diagnostic-mode container_info forwarding)
- `README.md` - config table `aliases` row now documents per-container labels surviving `/clear` and CLI restarts

## Decisions Made
- Container hostname chosen as the alias identity over container ID/name — it's the one identity both engines can observe (docker inspect on the legacy side, the hook-written state record on the state-file side)
- `ALIAS_HOST_PREFIX` namespacing prevents a hostname string from ever colliding with a raw sessionId- or dir-fallback-keyed entry already in the same `aliases` dict
- No migration written for aliases persisted under old sessionId keys — per the plan's explicit prohibition, the existing one-time startup prune drops them once, which is the accepted outcome
- The startup prune's "live" set switched from row keys to alias keys, and its input switched from the raw legacy `sessions` list to `render_sessions` — behaviour-identical in default operation since `render_sessions` is the legacy list object itself there

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking, pre-existing latent bug] `container_labels` guarded before `if ids:`**
- **Found during:** Task 1 (reading `scan_containers()` before editing it)
- **Issue:** This was already fixed in the pre-existing code with an explanatory comment ("Pre-existing latent bug in this function... fixed here since this task rewrites the function anyway") before this plan started — not something this plan introduced or needed to touch further. Noted here only because `read_first` pointed directly at that code region; no additional fix was needed.
- **Fix:** N/A — already present in the codebase; `cid_to_hostname` was added following the same pre-existing pattern (declared before `if ids:`, populated inside it).
- **Files modified:** monitor.py (as part of Task 1's planned changes)
- **Verification:** Full test suite green.
- **Committed in:** db8fc86 (Task 1 commit)

**2. [Sequencing slip — not a Rule 1-4 deviation, documented for commit-history accuracy] Task 2's `scan_state_files()` code change landed in Task 1's commit**
- **Found during:** Task 2 (git add/commit step)
- **Issue:** Per the plan's `read_first`/`action` for Task 2, `scan_state_files()`'s `alias_key` field and its `container_info`-forwarding fix to the internal `scan()` fallback call were read and edited during Task 1's exploration pass (before Task 1's `git add`/`git commit`), rather than staged separately for Task 2's commit. Both edits are exactly what Task 2's `<action>` specifies — no scope creep, no extra behavior — but the atomic-commit-per-task boundary was crossed: `db8fc86` (Task 1) contains this 2-line production change, and `e558946` (Task 2) contains only the tests that exercise it plus the README note.
- **Fix:** Left as committed rather than rewriting history (no `git commit --amend` / rebase, per the git safety protocol). Documented here for an accurate record of what each commit contains.
- **Files modified:** monitor.py (2 lines, inside `db8fc86` instead of `e558946`)
- **Verification:** `git show db8fc86 -- monitor.py` contains the `scan_state_files()` alias_key line and the `container_info=container_info` forward; `git show e558946 --stat` shows only test_monitor.py and README.md, confirming no monitor.py re-touch was needed.
- **Committed in:** db8fc86 (code), e558946 (tests covering it)

---

**Total deviations:** 1 documented pre-existing-code note (no fix needed) + 1 commit-boundary sequencing slip (no functional impact, both commits' code is correct and fully tested).
**Impact on plan:** None on correctness or scope — all `<verify>` gates for both tasks pass, and the full three-suite baseline (`test_monitor` + `test_state_writer` + `test_event_logger`) is green at 179 tests (up from the 105+ pre-existing `test_monitor` baseline, now 121 in `test_monitor` alone).

## Issues Encountered
None beyond the commit-boundary sequencing slip documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Alias persistence is now decoupled from the state-writer/legacy shadow-mode work: `derive_alias_key` and `alias_key` are additive fields both `scan()` and `scan_state_files()` already carry, so Phase 03's flip to hooks-primary needs no further alias-identity work.
- **Pending:** the plan's Task 2 `<human-check>` (live `/clear` + monitor-restart verification of label survival) has not been run in this session — see coverage item D8. Recommend running it before considering this fix fully proven end-to-end, since all automated coverage is at the unit level (`scan()`/`scan_state_files()`/`MonitorApp` methods called directly, no live Docker container or live Claude Code CLI session in the loop).

---
*Phase: quick-260730-kgw*
*Completed: 2026-07-30*

## Self-Check: PASSED

- FOUND: monitor.py
- FOUND: test_monitor.py
- FOUND: README.md
- FOUND: .planning/quick/260730-kgw-fix-session-aliases-lost-on-clear-key-al/260730-kgw-SUMMARY.md
- FOUND commit: db8fc86
- FOUND commit: e558946
