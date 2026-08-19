---
phase: 01-hook-coverage-verification
plan: 01
subsystem: infra
tags: [bash, jq, claude-code-hooks, jsonl, diagnostics]

# Dependency graph
requires: []
provides:
  - "hooks/event-logger.sh — appends one JSONL line per Claude Code hook event to ~/.claude/hook-events.log"
  - "hooks/hook-events.json — canonical 24-event registration list (RESEARCH.md fallback baseline)"
  - "hooks/install.sh — installs/merges the logger alongside existing lock hooks; --remove-logger teardown"
  - "test_event_logger.py — 18 tests locking down the logger + install/teardown behavior"
affects: [01-02-runbook, phase-2-state-file-engine]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single jq -c invocation per hook script reads stdin once and builds the whole output object, matching auq-lock.sh/working-lock.sh's existing convention"
    - "jq `empty` used as a filter branch to suppress output for payloads missing hook_event_name, instead of a shell-level post-filter"
    - "Idempotent settings.json merge: drop-then-append per event key, keyed on a command-string regex (has_cmd pattern already established by install.sh)"

key-files:
  created:
    - hooks/event-logger.sh
    - hooks/hook-events.json
    - test_event_logger.py
  modified:
    - hooks/install.sh
    - README.md

key-decisions:
  - "Used the RESEARCH.md 24-event fallback baseline for hook-events.json instead of a live docs fetch — this execution session had no web-fetch tool available. Documented as such in install.sh's header comment, including a caveat not to treat a silent event as a confirmed negative until checked against current docs."
  - "Logger writes no line for a payload with no hook_event_name (e.g. `{}`), not just for empty/non-JSON/truncated stdin — interpreted CONTEXT's 'partial payloads write no line' as covering a syntactically-valid-but-empty object too."
  - "--remove-logger implemented as a generic sweep across every hooks.<Event> array (not scoped to hook-events.json's current list), so it also cleans up entries from a prior run with a different event list."

requirements-completed: [VER-01]

coverage:
  - id: D1
    description: "event-logger.sh turns any hook payload into exactly one JSONL line on ~/.claude/hook-events.log, capturing scalar metadata plus the payload's own top-level key names"
    requirement: VER-01
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal1_LogLineShape (2 tests)"
        status: pass
      - kind: other
        ref: "01-01-PLAN.md Task 1 <verify> — TRACER_OK"
        status: pass
    human_judgment: false
  - id: D2
    description: "Content-bearing fields (tool_input, tool_response, prompt, last_assistant_message) are never written by value by default; GREENLIGHT_LOG_RAW=1 is the explicit opt-in for full-payload capture"
    requirement: VER-01
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal2_SecretExclusionAndRawOptIn (3 tests)"
        status: pass
      - kind: other
        ref: "01-01-PLAN.md Task 2 <verify> — COVERAGE_OK"
        status: pass
    human_judgment: false
  - id: D3
    description: "A logger failure (empty/non-JSON/truncated/partial stdin) always exits 0 and never writes a malformed or empty-ish line"
    requirement: VER-01
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal3_NeverBreakTheSession (4 tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Appends never overwrite prior lines; an oversized log (>5MB) is truncated with a marker line before the next append"
    requirement: VER-01
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal4_AppendAndSizeGuard (2 tests)"
        status: pass
    human_judgment: false
  - id: D5
    description: "hooks/install.sh registers event-logger.sh on every event in hooks/hook-events.json (24 events), safely on both fresh and existing settings.json, idempotently, and the registered command string actually produces a log line when executed"
    requirement: VER-01
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal5_InstallRegistrationAndIdempotency (3 tests)"
        status: pass
      - kind: unit
        ref: "test_event_logger.py#Goal6_PreservationOfLocksAndUnrelatedSettings (2 tests)"
        status: pass
    human_judgment: false
  - id: D6
    description: "hooks/install.sh --remove-logger strips every logger entry and leaves auq-lock/working-lock entries untouched"
    requirement: VER-01
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal7_RemovalPath (2 tests)"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-29
status: complete
---

# Phase 1 Plan 1: Hook Coverage Diagnostic Instrument Summary

**One shared `event-logger.sh` (registered on 24 Claude Code hook events via an extended `hooks/install.sh`) appends a metadata-only JSONL line per event to `~/.claude/hook-events.log`, with secret exclusion, a `GREENLIGHT_LOG_RAW=1` full-payload opt-in, a 5MB truncate-and-marker size guard, and a `--remove-logger` teardown — all locked down by an 18-test suite in `test_event_logger.py`.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-29T08:08:13Z
- **Completed:** 2026-07-29T08:16:21Z
- **Tasks:** 3
- **Files modified:** 5 (2 created new, 1 new test file, 2 modified)

## Accomplishments
- `hooks/event-logger.sh` reads stdin once, builds a single `jq -c` output object (ts, ts_ms, event, session_id, cwd, keys, plus 14 scalar/identity fields), and appends it atomically to `~/.claude/hook-events.log` — never blocking or failing a Claude Code session
- `hooks/hook-events.json` lists 24 hook event names; `hooks/install.sh` registers the logger on every one of them via a jq `reduce`, dedup'd on re-run, without disturbing the pre-existing auq-lock/working-lock entries
- Content-bearing fields (`tool_input`, `tool_response`, `prompt`, `last_assistant_message`) are never captured by value — only their presence/spelling shows up via the `keys` array — with a scoped `GREENLIGHT_LOG_RAW=1` escape hatch for full-payload capture when deliberately needed
- `hooks/install.sh --remove-logger` sweeps every `hooks.<Event>` array for `event-logger.sh` commands and removes them in one pass, independent of whatever event list was active when they were registered
- `test_event_logger.py`: 18 tests across 7 goal-named classes, all exercising the real shell scripts via `subprocess` with `HOME` pinned to a `TemporaryDirectory` — the real `$HOME/.claude` was never touched by any test or verification run in this session

## Task Commits

Each task was committed atomically:

1. **Task 1: End-to-end "one hook event lands in the log"** - `227969f` (feat) — tracer proven via TRACER_OK before widening
2. **Task 2: Widen to every documented hook event, full metadata, size guard, teardown** - `4030537` (feat) — COVERAGE_OK, plus manual verification of the raw opt-in and size-guard truncation
3. **Task 3: Lock the behavior down in test_event_logger.py** - `9061e6c` (test) — 18/18 tests pass, `test_monitor.py` unaffected (56/56 still pass)

## Files Created/Modified
- `hooks/event-logger.sh` - The logger: stdin→jq→JSONL append, secret exclusion, raw opt-in, size guard
- `hooks/hook-events.json` - Canonical 24-event registration list (RESEARCH.md fallback baseline, 2026-07-28)
- `hooks/install.sh` - Extended: installs event-logger.sh, fixed the fresh-settings early-return trap to fall through to logger registration, added the registration jq pass and `--remove-logger` teardown
- `test_event_logger.py` - New 18-test suite (goal-named classes, subprocess-driven, TemporaryDirectory HOME)
- `README.md` - Added `test_event_logger.py` to the Development section

## Decisions Made
- Live docs fetch of `code.claude.com/docs/en/hooks` was not reachable from this execution session (no web-fetch tool available), so `hooks/hook-events.json` uses the plan's deterministic 24-name RESEARCH.md fallback baseline verbatim, with the provenance and a "re-check before trusting a negative" caveat recorded in `install.sh`'s header comment.
- A payload that parses as valid JSON but carries no `hook_event_name` (e.g. `{}`) is treated the same as an empty/partial payload — no line is written — read as the intent behind the plan's "partial payloads make the logger exit 0 without writing a line" truth.
- `--remove-logger` is implemented as a blanket sweep of every `hooks.<Event>` array rather than being scoped to the current `hook-events.json` list, so a future widening/narrowing of that list can't leave stale logger entries behind after a removal.

## Deviations from Plan

None — plan executed as written. One minor sequencing note: the `--remove-logger` flag (specified as Task 2 scope) was implemented in the Task 1 commit alongside the initial `install.sh` restructure, since the fresh-install-branch fallthrough fix and the teardown flag touch the same control-flow region. Task 2 required no further changes to that flag; it verified `--remove-logger` still worked correctly against the widened 24-event registration.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. `bash`, `jq`, and `python3` are the only dependencies, all already present and used by the existing hooks.

## Known Stubs
None.

## Threat Flags
None — this plan operates entirely within the threat model already registered in 01-01-PLAN.md (T-01-01 through T-01-06, T-01-SC); no new network endpoints, auth paths, or schema changes were introduced.

## Next Phase Readiness
- The diagnostic instrument is code-complete and test-locked; plan 01-02 can now write the UAT runbook against this exact log-line shape (ts, ts_ms, event, session_id, cwd, keys, + scalar metadata fields) and the confirmed 24-event registration list.
- **Not yet done (by design, per CONTEXT.md D-05):** the real `hooks/install.sh` has never been run against the user's actual `$HOME` — every verification in this plan used a `mktemp -d` HOME. The real install is step 1 of plan 01-02's runbook, performed deliberately by the user.
- `hooks/hook-events.json`'s 24-event list is a fallback baseline, not a confirmed-live-fetch list — plan 01-02's runbook (or the user, before running it) should spot-check it against current `code.claude.com/docs/en/hooks` and widen it if warranted before the live matrix run, since a missing event name would silently bias the verdict.

---
*Phase: 01-hook-coverage-verification*
*Completed: 2026-07-29*

## Self-Check: PASSED

All created files found on disk (hooks/event-logger.sh, hooks/hook-events.json, hooks/install.sh, test_event_logger.py, this SUMMARY.md). All task commits found in git log (227969f, 4030537, 9061e6c) plus the summary commit (068cab9).
