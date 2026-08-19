# Phase 1: Hook Coverage Verification — Context

**Source:** Autonomous run — decisions distilled from .planning/NOTES.md, .planning/TEST-MATRIX.md, and prior user analysis (no interactive discuss-phase; user reviews at the end).

## Locked Decisions

- **Instrument, don't guess.** Phase 1 delivers a logging hook that appends every hook event (event name, session_id, cwd, timestamp, relevant payload fields — e.g. tool_name for Pre/PostToolUse, message for Notification, source for SessionStart) as one JSON line to `~/.claude/hook-events.log`. No state-derivation logic in this phase.
- **Non-invasive:** the logger installs alongside the existing hooks (working-lock, auq-lock, permission Notification) without changing their behavior. Same install mechanism family as `hooks/install.sh` (bash + jq, settings.json snippet).
- **Register the logger on every hook event type Claude Code supports** (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification, Stop, SubagentStop, SessionEnd, and any others found in current docs) — the whole point is discovering which events fire in which cases; logging a subset would bias the verdict.
- **Log format is append-only JSONL** on the shared `~/.claude` mount so it is visible from Windows; must be safe under concurrent writers from multiple containers (single-line O_APPEND writes).
- **The live matrix run is user-assisted UAT.** The agent-executable part ends with: logger installed + a runbook telling the user how to trigger each TEST-MATRIX.md case and what to look for in the log. Filling the matrix columns and writing the hybrid verdict happens at the UAT checkpoint with the user in the loop.
- **The verdict updates TEST-MATRIX.md in place** (the Verified column + the "Verdict to extract" section) — no separate report file.
- **Hybrid is the expected outcome** (hooks primary + targeted fallbacks); the verdict must name, per hook-silent case, the concrete fallback (existing auq-lock, shell_tracker, jsonl peek, docker cross-check). Preserve current async-work semantics (grey while bg work runs) unless live data contradicts it.

## Claude's Discretion

- Logger implementation details (single script with event name as arg vs per-event entries in settings.json).
- Payload field selection per event, as long as enough is captured to answer the matrix questions (notably: does AUQ emit anything? does Stop fire on Esc? what fires on bg-task re-invocation?).
- Log rotation/size guard (a simple max-size truncate is fine; this is a temporary diagnostic instrument).
- Runbook format and location (suggest `.planning/phases/01-hook-coverage-verification/01-UAT.md` or extending TEST-MATRIX.md with a "how to run" preamble).

## Deferred

- Any state-file writing (`monitor-state/`) — Phase 2.
- Any change to monitor.py — Phase 2.
- Removing legacy parsing — Phase 3.

## Canonical References

- `.planning/TEST-MATRIX.md` — the 21 cases and columns to fill
- `.planning/NOTES.md` — target architecture and migration plan
- `hooks/install.sh`, `hooks/settings-snippet.json` — existing hook install mechanism to extend
