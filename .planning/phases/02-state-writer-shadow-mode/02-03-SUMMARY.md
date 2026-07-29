---
phase: 02-state-writer-shadow-mode
plan: 03
subsystem: infra
tags: [python, docker, monitor, shadow-mode, staleness, state-files]

# Dependency graph
requires:
  - phase: 02-state-writer-shadow-mode (plan 01)
    provides: the tracer engine (scan_state_files() stub, _read_state_file(), _state_to_status(), diff_verdicts(), write_divergences(), select_render_sessions()) this plan turns into the real engine
  - phase: 02-state-writer-shadow-mode (plan 02)
    provides: the full D-08 event-to-state mapping in hooks/state-writer.sh, so every state field this plan reads is actually populated live
provides:
  - "scan_state_files() as a full peer of scan(): defensive per-file derivation, ts_ms-preferring age, best-effort 24h pruning"
  - "Heartbeat staleness + docker liveness cross-check: a stale WORKING verdict recovers to WAITING unless its container is paused (D-06)"
  - "scan_containers()'s fourth return element, container_info ({hostname_to_label, hostname_to_status}), built from the single existing inspect call"
  - "The ENG-05 migration bridge: legacy_sessions merge keeps hookless-container sessions visible in the shadow list"
affects: [02-state-writer-shadow-mode remaining plans (02-04 comparator/divergence review, 02-05 live runbook), Phase 3 legacy-removal]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-file degrade-one-session-not-the-tick idiom extended to a second engine (scan_state_files mirrors scan()'s try/except-per-candidate shape)"
    - "Extend an existing subprocess call's --format string instead of adding a second call (docker inspect gains two fields for the liveness cross-check)"

key-files:
  created: []
  modified:
    - monitor.py
    - test_monitor.py

key-decisions:
  - "STATE_PROMPT_STALE_SEC is deliberately set equal to legacy's USER_PROMPT_WORKING_SEC (90s) rather than a new value, so the abandoned-prompt staleness window matches today's behavior exactly"
  - "container_labels is initialised to {} before the `if ids:` block in scan_containers() — a pre-existing NameError-on-zero-containers bug fixed as part of rewriting the function this task already touches"
  - "hostname_to_label is a secondary label resolver (after sessionid_to_label) rather than a replacement, because docker exec (which builds sessionid_to_label) cannot reach a paused container — without the fallback the paused-stays-WORKING staleness branch would be unreachable in the shadow list"
  - "Pruning (STATE_PRUNE_AGE_SEC, 24h) runs inline in the same per-file loop as visibility filtering rather than as a separate second pass, since a prune-eligible file is always already past MAX_AGE_SEC too"
  - "legacy_sessions merge happens in scan_state_files() itself (not a caller-side union) so the --state-files diagnostic mode, which omits legacy_sessions, gets the same hookless-fallback behavior for free via an internal scan() call"

patterns-established:
  - "Staleness-then-container-cross-check as a two-stage gate: first decide whether a WORKING verdict is stale by heartbeat age, then only consult docker liveness once staleness is already established — avoids a docker lookup on every fresh session"

requirements-completed: [ENG-01, ENG-03, ENG-04, ENG-05, ENG-06]

coverage:
  - id: D1
    description: "scan_state_files() derives every visible session's verdict from monitor-state/*.json alone (state mapping, ts_ms-preferring age, compact action label from last_event), opening no jsonl for a session with a state file"
    requirement: "ENG-01"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal9_StateFileVerdicts (6 tests)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Nine distinct broken-file shapes (invalid JSON, truncated fragment, zero-byte, JSON array, missing/wrong-typed state, missing ts_ms, non-.json file, file removed mid-scan) each drop exactly one session and never raise; MAX_AGE_SEC visibility and STATE_PRUNE_AGE_SEC orphan cleanup both verified"
    requirement: "ENG-04"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal10_StateFileRobustness (11 tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "A stale WORKING verdict (heartbeat silence past STATE_HEARTBEAT_STALE_SEC, or STATE_PROMPT_STALE_SEC after UserPromptSubmit) recovers to WAITING via docker liveness cross-check, except a paused container which stays WORKING (D-06); container liveness read from .State.Status on the single existing inspect call, not docker ps's text column"
    requirement: "ENG-03"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal11_StateFileStaleness (9 tests), Goal12_ContainerInfoShape (1 test)"
        status: pass
    human_judgment: false
  - id: D4
    description: "A session visible to legacy parsing but with no state file (container running an image without hooks) is carried through into the shadow list unchanged, tagged legacy_origin, via the legacy_sessions migration bridge"
    requirement: "ENG-05"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal13_HooklessFallback (5 tests)"
        status: pass
    human_judgment: false
  - id: D5
    description: "Every hook-silent TEST-MATRIX case this plan owns (8 Esc interrupt, 5-deny permission denial, 9 killed/stopped/paused container, 19 abandoned pre-tool prompt, 21 hookless container) is covered by a named, tested fallback"
    requirement: "ENG-06"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal11_StateFileStaleness + Goal13_HooklessFallback (covers cases 8/5-deny/9/19 via staleness+liveness, case 21 via legacy_sessions)"
        status: pass
    human_judgment: false

duration: 14min
completed: 2026-07-29
status: complete
---

# Phase 2 Plan 3: State-File Engine Completion Summary

**scan_state_files() is now a full peer of legacy scan(): defensive per-file derivation surviving nine broken-file shapes, heartbeat-silence-plus-docker-liveness staleness recovery that spares paused containers, and a legacy_sessions migration bridge keeping hookless containers visible**

## Performance

- **Duration:** 14 min
- **Started:** 2026-07-29T15:34:18Z
- **Completed:** 2026-07-29T15:47:55Z
- **Tasks:** 3
- **Files modified:** 2 (monitor.py, test_monitor.py)

## Accomplishments
- `scan_state_files()` derivation hardened: every field access defaults safely, a record's `state` of the wrong type falls through `_state_to_status`'s own default-WAITING branch (no special-casing needed), age prefers the record's `ts_ms` over file mtime, and a compact `action` label is derived from `last_event`
- Nine distinct broken-state-file shapes (invalid JSON, truncated fragment, zero-byte, JSON array, missing/wrong-typed `state`, missing `ts_ms`, a stray non-`.json` file, and a file removed between the directory listing and the read) each drop exactly one session; the tick and every other session survive
- Best-effort 24h orphan pruning (`STATE_PRUNE_AGE_SEC`) added as the backstop for the one hook-silent orphan path — a killed container — since `SessionEnd` already handles every clean exit/resume/clear
- `scan_containers()` extended to a single 4-field `docker inspect` call (`.State.Status`, `.Config.Hostname` added to the existing two) returning a new fourth `container_info` element (`hostname_to_label`, `hostname_to_status`); a pre-existing `container_labels` `NameError`-on-zero-containers bug fixed in the same rewrite
- Heartbeat staleness gate: a `working` verdict silent past `STATE_HEARTBEAT_STALE_SEC` (or the shorter `STATE_PROMPT_STALE_SEC` after `UserPromptSubmit`) cross-checks docker liveness by hostname and recovers to `WAITING` — unless the container is `paused`, which D-06 requires to stay alive-but-frozen
- `hostname_to_label` wired in as a secondary label resolver (after `sessionid_to_label`) so a paused container's session — unreachable by the `docker exec` that builds `sessionid_to_label` — still gets a label and can reach the staleness gate's paused branch
- `legacy_sessions` migration bridge (ENG-05): every legacy `scan()` session with no matching state file is carried through into the shadow list unchanged, tagged `legacy_origin`; `refresh()` passes its already-computed `sessions` list so the shadow tick never re-scans jsonl a second time
- 146 tests pass total (131 pre-existing + 26 new across `Goal9`–`Goal13`), zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Complete the state-file derivation and make every broken file survivable** - `29d5549` (feat)
2. **Task 2: Add heartbeat staleness and the docker container-liveness cross-check** - `52046ce` (feat)
3. **Task 3: Keep hookless containers visible through a per-session legacy fallback** - `d7cdb20` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified
- `monitor.py` - `STATE_HEARTBEAT_STALE_SEC`/`STATE_PROMPT_STALE_SEC`/`STATE_PRUNE_AGE_SEC` constants, `_state_action_label()`, `_state_record_age()`, completed `scan_state_files()` (robustness, pruning, staleness gate, hostname label fallback, `legacy_sessions` merge), extended `scan_containers()` (4-field inspect, `container_info`, `container_labels` bug fix), `MonitorApp._cached_container_info` wiring through `_kick_docker_query()`/`refresh()`
- `test_monitor.py` - `StateFileTestBase` fixture + `Goal9_StateFileVerdicts`, `Goal10_StateFileRobustness`, `Goal11_StateFileStaleness`, `Goal12_ContainerInfoShape`, `Goal13_HooklessFallback` (26 tests total)

## Decisions Made
- `STATE_PROMPT_STALE_SEC` set equal to `USER_PROMPT_WORKING_SEC` (90s), not a new independently-tuned value, so the abandoned-prompt staleness window matches today's behavior exactly
- `container_labels` in `scan_containers()` initialised to `{}` before the `if ids:` block — fixes a pre-existing latent bug (a tick with zero labelled containers previously hit `NameError` inside the docker worker's blanket `except Exception`, silently freezing the sessionId cache) discovered while rewriting the function this task already had to touch (Rule 1: auto-fix bug in scope)
- Pruning runs inline in the same per-file loop as visibility filtering, not as a separate second pass — a prune-eligible file (>24h) is always already past `MAX_AGE_SEC` (1h) too, so no session-building work is wasted before the unlink
- `legacy_sessions` merge lives inside `scan_state_files()` rather than being the caller's job, so the `--state-files` diagnostic mode (which omits `legacy_sessions`) gets the identical hookless-fallback behavior via an internal `scan()` call — one code path, not two

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `container_labels` NameError on zero labelled containers**
- **Found during:** Task 2 (extending `scan_containers()`)
- **Issue:** `container_labels` was only bound inside the `if ids:` block but read unconditionally afterward at `if container_labels:` — a tick with zero labelled containers raised `NameError`, caught by the docker worker's blanket `except Exception`, silently keeping the prior tick's stale `sessionid_to_label` cache
- **Fix:** Initialised `container_labels: dict[str, str] = {}` before the `if ids:` block
- **Files modified:** monitor.py
- **Verification:** Full test suite (146 tests) passes; `Goal12_ContainerInfoShape` exercises the zero-container path directly (docker binary absent) without raising
- **Committed in:** `52046ce` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug, in-scope of the function this task rewrote)
**Impact on plan:** Necessary correctness fix, no scope creep — the plan's read_first list explicitly called out this bug and instructed fixing it as part of the rewrite.

## Issues Encountered
- Initial `Goal10` robustness test for "file removed between glob and read" hit infinite recursion: `Path.is_file()`/`Path.exists()` both call `self.stat()` internally, so patching `Path.stat` for the mock-and-raise fixture recursed through the test's own `.exists()` check. Fixed by using `os.path.exists`/`os.unlink` (which don't route through the patched `Path.stat`) in the fixture, and by removing an unnecessary standalone `f.is_file()` pre-check in `scan_state_files()` itself (the subsequent `f.stat()` inside its own try/except already covers the same failure mode, and a directory matching `*.json` degrades safely through `_read_state_file`'s `IsADirectoryError` → `OSError` catch).

## User Setup Required

None - no external service configuration required. Two RESEARCH.md assumptions remain flagged for live verification on the user's actual Windows/WSL2/Docker install (unchanged from plan scope, carried into plan 02-05's runbook): A1 (`.State.Status` enum stability) and ENG-05's hookless-container fallback end-to-end (needs a real container running an image without hooks installed).

## Next Phase Readiness
- The state-file engine (`scan_state_files()`) is now feature-complete for shadow mode: full peer of `scan()` in derivation, robustness, staleness, and hookless-container coverage. Plan 02-04's divergence comparator can pair legacy and shadow sessions by `key` on a fully-shaped shadow list.
- All five TEST-MATRIX hook-silent cases this plan owned (8 Esc interrupt, 5-deny permission denial, 9 killed/stopped/paused container, 19 abandoned pre-tool prompt, 21 hookless container) have a named, unit-tested fallback in code — the coverage table's "flagged assumptions" (A1, ENG-05 live check) are the only pieces needing the user's real Docker environment, not new code.
- No blockers for continuing into 02-04 (divergence review/comparator) and 02-05 (live runbook) in this sandbox.

---
*Phase: 02-state-writer-shadow-mode*
*Completed: 2026-07-29*

## Self-Check: PASSED

All modified files verified present on disk (`monitor.py`, `test_monitor.py`,
`.planning/phases/02-state-writer-shadow-mode/02-03-SUMMARY.md`) and all task
commit hashes (`29d5549`, `52046ce`, `d7cdb20`) verified present in `git log`.
