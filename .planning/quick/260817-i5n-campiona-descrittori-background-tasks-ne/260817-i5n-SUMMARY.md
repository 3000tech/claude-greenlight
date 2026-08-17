---
phase: quick-260817-i5n
plan: 01
subsystem: infra
tags: [jq, bash, hooks, diagnostics, privacy]

requires:
  - phase: 03-flip-to-default-cleanup
    provides: hooks/event-logger.sh diagnostic instrument, TEST-MATRIX.md case #17 rev.2 (badge-only background_tasks_count)
provides:
  - "background_tasks_shape sampler inside event-logger.sh's single jq program (name allowlist + value-shape regex, capped at 5 entries)"
  - "scripts/bg-task-shape-report.sh privacy-safe aggregator with --self-test"
  - "TEST-MATRIX.md case #17 rev.3: live evidence that the type field discriminates shell vs subagent descriptors"
affects: [state-writer-verdict-followup, notification-gate]

actuals:
  tokens: 6169
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Two independent guards for privacy-safe sampling: closed field-NAME allowlist + independent value-SHAPE regex, so an undocumented content-bearing field named innocuously still cannot leak a value"
    - "Report/aggregator script pattern: jq -Rc 'fromjson? // empty' to tolerate malformed/partial JSONL lines without aborting the whole read"

key-files:
  created:
    - scripts/bg-task-shape-report.sh
  modified:
    - hooks/event-logger.sh
    - test_event_logger.py
    - docs/TEST-MATRIX.md

key-decisions:
  - "Deployed the refreshed event-logger.sh live to ~/.claude/hooks/ immediately after tests went green, per plan — sampling started mid-session and captured real organic evidence (a genuine background gsd-executor agent and the deliberate long-lived sleep shell) before Task 3 was even written"
  - "Documented the provenance of each sample explicitly in the TEST-MATRIX evidence (which shell sample was a Task 1 smoke-test synthetic vs which was the real Task 2 background shell) rather than presenting all samples as equally organic — matters for calibrating confidence in the type discriminator"
  - "No verdict change shipped: hooks/state-writer.sh untouched, Stop still resolves to waiting unconditionally, D-03 intact"

requirements-completed: [QUICK-260817-i5n]

coverage:
  - id: D1
    description: "background_tasks_shape sampler in event-logger.sh — field names + closed enum/id allowlist, two independent guards, capped at 5 entries, deployed live and byte-identical to the repo copy"
    requirement: QUICK-260817-i5n
    verification:
      - kind: unit
        ref: "test_event_logger.py#Goal8_BackgroundTaskDescriptorShapeSampling (8 tests)"
        status: pass
      - kind: unit
        ref: "test_event_logger.py (all 35 tests, incl. pre-existing Goal1-7b)"
        status: pass
      - kind: unit
        ref: "test_state_writer.py (all 44 tests, D-03 untouched)"
        status: pass
    human_judgment: false
  - id: D2
    description: "scripts/bg-task-shape-report.sh — privacy-safe aggregator over the live log with --self-test"
    requirement: QUICK-260817-i5n
    verification:
      - kind: other
        ref: "bash scripts/bg-task-shape-report.sh --self-test"
        status: pass
      - kind: other
        ref: "bash scripts/bg-task-shape-report.sh (against the real live log, both no-samples and samples-present states exercised)"
        status: pass
    human_judgment: false
  - id: D3
    description: "TEST-MATRIX.md case #17 rev.3 entry: both false-positive episodes, hypothesis, method, live evidence tables, three-branch proposed rule, no-verdict-change scope statement"
    verification: []
    human_judgment: true
    rationale: "Whether the observed type discriminator (shell vs subagent) is robust enough to greenlight a follow-up state-writer verdict change is a judgment call on real-world evidence volume, not something a test can auto-pass — the plan's own Task 3 <human-check> asks the user to read the tables after the background shell and a fresh background agent complete their turns."

duration: 10min
completed: 2026-08-17
status: complete
---

# Quick Task 260817-i5n: Sample background_tasks Descriptor Shape for the Agent-vs-Shell Rule Summary

**Name-and-enum-only background_tasks descriptor sampler deployed live to event-logger.sh, a privacy-safe report script to read it, and a TEST-MATRIX rev.3 entry showing the `type` field already discriminates a background shell from a background subagent in real samples.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-08-17T13:13:25Z (plan commit)
- **Completed:** 2026-08-17T13:22:39Z
- **Tasks:** 3
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- `hooks/event-logger.sh` now samples the first 5 `background_tasks` descriptor entries on Stop/SubagentStop by field NAME plus a closed 14-name allowlist of enum/id-shaped VALUES, gated by two independent guards (name allowlist + value-shape regex `^[A-Za-z0-9_.:-]{1,64}$`) — command/prompt text never lands on the shared `~/.claude` mount even when carried alongside an allowlisted field on the same entry.
- Deployed live via `install -m 0755` (byte-identical to the repo copy; `settings.json` untouched — confirmed no new `.bak` file and unchanged mtime).
- `scripts/bg-task-shape-report.sh` aggregates the log into three sections (distinct field-name shapes, per-field observed values, descriptor-id-to-agent_id join) plus explicit no-samples-yet / no-log-yet paths, all exit 0.
- Real live evidence, captured mid-session before Task 3 was even written: a genuine background `gsd-executor` subagent (5 samples, `type: subagent`, joins to its own `agent_id`) and a genuine background shell (the deliberate 21-minute `sleep` started in Task 2, `type: shell`) — the `type` field cleanly distinguishes the two classes in every sample observed so far.
- `docs/TEST-MATRIX.md` case #17 now carries a rev.3 entry: both false-positive episodes (11:14:15Z and the post-plan 13:05:44Z sample), the agent-vs-shell hypothesis, the sampling method, the live evidence tables (with an explicit note on which samples were synthetic vs organic), and the three-branch proposed rule — with no verdict change shipped.

## Task Commits

Each task was committed atomically:

1. **Task 1: Sample background_tasks descriptors by name and enum value, end to end into the live log** - `7479eec` (feat)
2. **Task 2: Repeatable privacy-safe report over sampled descriptors, plus the deliberate live repro** - `5cfcd85` (feat)
3. **Task 3: Record the rev.3 finding and the proposed agent-vs-shell rule in TEST-MATRIX section 4** - `83a2b19` (docs)

**Plan metadata:** `7e49dac` (docs: plan commit, made prior to this execution)

## Files Created/Modified

- `hooks/event-logger.sh` - Added `background_tasks_shape` sampler inside the existing jq program; rewrote the header comment to describe the new capture
- `test_event_logger.py` - New `Goal8_BackgroundTaskDescriptorShapeSampling` class (8 tests: field-name listing, sentinel-secret exclusion, value-shape guard, absent/non-array cases, 5-entry cap vs uncapped count, hostile non-object entries, empty-array case, SubagentStop coverage)
- `scripts/bg-task-shape-report.sh` - New aggregator script with `--self-test`
- `docs/TEST-MATRIX.md` - Appended rev.3 entry to case #17, section 4

## Decisions Made

- Deployed the sampler live immediately after tests went green (as the plan specified), which meant the log had already accumulated real organic evidence — both a genuine background agent and the deliberate background shell — by the time Task 3 was written. Documented in the rev.3 entry exactly which sample came from which source (Task 1 smoke-test synthetic vs Task 2's real long-lived shell) rather than blurring the two, since T-i5n-07 (repudiation) explicitly calls out not asserting findings the samples don't support.
- No verdict change shipped, per plan scope: `hooks/state-writer.sh` is unchanged (confirmed via `git diff` — zero content difference from HEAD), Stop still resolves to waiting unconditionally, and `test_state_writer.Goal6_TurnEndSemantics` (D-03) is still green.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-existing CRLF corruption in the working tree blocked test execution**
- **Found during:** Task 1 (running `python3 -m unittest test_event_logger.py` for the first time)
- **Issue:** The sandbox working tree had CRLF line endings on nearly every tracked text file (including `hooks/install.sh`, `hooks/state-writer.sh`, `monitor.py`, `test_state_writer.py`, `test_monitor.py`) despite git considering the tree clean at session start. This is a filesystem/mount artifact of this sandbox, not a real repo defect — `git hash-object` confirmed every restored file is byte-identical to its HEAD blob (zero real diff), and the live-deployed hooks on this same machine were already running fine. `set -euo pipefail` fails outright on a script whose shebang line carries a trailing `\r` (`set: pipefail\r: invalid option name`), which broke `hooks/install.sh`-dependent tests (Goal5/Goal7b) and would have broken `test_state_writer.py` similarly.
- **Fix:** Restored each affected file's exact committed content via `git show HEAD:<path> > <path>` (a no-op from git's perspective — content hash matches the index exactly both before and after, confirmed with `git hash-object`/`cmp`/`md5sum`). Also stripped an equivalent CRLF artifact that the Edit tool itself introduced into `hooks/event-logger.sh` and `test_event_logger.py` during my own edits, and into `docs/TEST-MATRIX.md` during Task 3's edit.
- **Files modified:** No net content change to any file outside the plan's four `files_modified` — the CRLF fix on `hooks/install.sh`, `hooks/state-writer.sh`, `hooks/working-lock.sh`, `hooks/hook-events.json`, `hooks/settings-snippet.json`, `hooks/state-writer-events.json`, `monitor.py`, `test_state_writer.py`, `test_monitor.py` produced byte-identical content to `HEAD` (verified via `git diff --stat`, which shows zero lines changed for all of them) and was not staged or committed.
- **Verification:** `git diff --stat a390c2b..HEAD -- hooks/state-writer.sh monitor.py` returns empty; `python3 -m unittest test_event_logger.py` and `test_state_writer.py` both green (35 and 44 tests respectively).
- **Committed in:** Not committed — content is identical to HEAD, so there was nothing to stage.

---

**Total deviations:** 1 auto-fixed (1 blocking, environment-only, zero net content change)
**Impact on plan:** No scope creep — the plan's own four files are the only ones with a real diff. Everything else touched during triage reverted to byte-identical HEAD content, confirmed via hash comparison, and stayed unstaged.

## Issues Encountered

- `git status --porcelain` continues to show a spurious `M` on files whose content is verified byte-identical to `HEAD` (`hooks/state-writer.sh`, `monitor.py`, etc.) — a stat-cache artifact of this sandbox's filesystem, not a real modification. `git diff` and `git hash-object` are the reliable checks and both confirm zero content change. Left as-is since attempting to "fix" it (e.g. touching mtimes) is out of this task's scope and touching it further risks masking a genuine future diff.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The deliberate 21-minute background shell (`sleep 1260`, started in Task 2) is still running as of this summary and will still be in flight at the point the user reads this — it guarantees a genuine shell-typed sample at this session's own next turn end, for the plan's Task 3 `<human-check>`.
- **Awaiting human follow-up (per the plan's Task 3 `<human-check>`):** once this session's current turn ends (with the background shell and/or a freshly-launched background agent still in flight), run `bash scripts/bg-task-shape-report.sh` and read the tables. The live evidence already gathered during this run (5 `type: subagent` samples joining to a known `agent_id`, 2 `type: shell` samples — 1 synthetic, 1 organic) points toward branch (a) of the rev.3 rule (a clean `type` discriminator), but the sample volume is still small. If further samples confirm it, a follow-up quick task can change `hooks/state-writer.sh`'s Stop verdict for agent-only background tasks; if not, say which branch it landed in so the rev.3 entry can be closed with the real answer.
- No blockers. `hooks/state-writer.sh` is untouched and D-03 is intact — today's behavior (Stop always resolves to waiting, `background_tasks_count` is badge-only) has not moved.

## Self-Check: PASSED

- FOUND: hooks/event-logger.sh
- FOUND: test_event_logger.py
- FOUND: scripts/bg-task-shape-report.sh
- FOUND: docs/TEST-MATRIX.md
- FOUND: .planning/quick/260817-i5n-campiona-descrittori-background-tasks-ne/260817-i5n-SUMMARY.md
- FOUND commit: 7479eec
- FOUND commit: 5cfcd85
- FOUND commit: 83a2b19

---
*Phase: quick-260817-i5n*
*Completed: 2026-08-17*
