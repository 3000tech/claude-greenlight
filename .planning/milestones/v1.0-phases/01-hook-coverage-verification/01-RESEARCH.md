# Phase 1: Hook Coverage Verification - Research

**Researched:** 2026-07-28
**Domain:** Claude Code hooks system (event catalog, payload schemas, execution semantics) + bash/jq diagnostic instrumentation
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Instrument, don't guess.** Phase 1 delivers a logging hook that appends every hook event (event name, session_id, cwd, timestamp, relevant payload fields — e.g. tool_name for Pre/PostToolUse, message for Notification, source for SessionStart) as one JSON line to `~/.claude/hook-events.log`. No state-derivation logic in this phase.
- **Non-invasive:** the logger installs alongside the existing hooks (working-lock, auq-lock, permission Notification) without changing their behavior. Same install mechanism family as `hooks/install.sh` (bash + jq, settings.json snippet).
- **Register the logger on every hook event type Claude Code supports** (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Notification, Stop, SubagentStop, SessionEnd, and any others found in current docs) — the whole point is discovering which events fire in which cases; logging a subset would bias the verdict.
- **Log format is append-only JSONL** on the shared `~/.claude` mount so it is visible from Windows; must be safe under concurrent writers from multiple containers (single-line O_APPEND writes).
- **The live matrix run is user-assisted UAT.** The agent-executable part ends with: logger installed + a runbook telling the user how to trigger each TEST-MATRIX.md case and what to look for in the log. Filling the matrix columns and writing the hybrid verdict happens at the UAT checkpoint with the user in the loop.
- **The verdict updates TEST-MATRIX.md in place** (the Verified column + the "Verdict to extract" section) — no separate report file.
- **Hybrid is the expected outcome** (hooks primary + targeted fallbacks); the verdict must name, per hook-silent case, the concrete fallback (existing auq-lock, shell_tracker, jsonl peek, docker cross-check). Preserve current async-work semantics (grey while bg work runs) unless live data contradicts it.

### Claude's Discretion

- Logger implementation details (single script with event name as arg vs per-event entries in settings.json).
- Payload field selection per event, as long as enough is captured to answer the matrix questions (notably: does AUQ emit anything? does Stop fire on Esc? what fires on bg-task re-invocation?).
- Log rotation/size guard (a simple max-size truncate is fine; this is a temporary diagnostic instrument).
- Runbook format and location (suggest `.planning/phases/01-hook-coverage-verification/01-UAT.md` or extending TEST-MATRIX.md with a "how to run" preamble).

### Deferred Ideas (OUT OF SCOPE)

- Any state-file writing (`monitor-state/`) — Phase 2.
- Any change to monitor.py — Phase 2.
- Removing legacy parsing — Phase 3.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VER-01 | A logging hook records every Claude Code hook event (name + relevant payload fields + timestamp + session_id) to `~/.claude/hook-events.log`, installable alongside the existing hooks without disturbing them | Event catalog + payload schemas below give the field list to capture per event; `install.sh` merge pattern (Architecture Patterns) shows how to add the logger non-invasively; Code Examples give a working script + settings fragment |
| VER-02 | TEST-MATRIX.md verification columns are filled from live runs and a written hybrid verdict names, per hook-silent case, the fallback that covers it (user-assisted UAT for the live runs) | Confirmed-silent cases (AskUserQuestion, Stop-on-interrupt) below let the planner pre-fill the verdict's known answers and scope the runbook to the still-open cases; Runtime/Concurrency pitfalls flag what to watch for during the live run |
</phase_requirements>

## Summary

Claude Code's hook system has grown well beyond the ~9 events the project's existing hooks use (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Notification`, `Stop`, `SubagentStop`, `SessionEnd`, `PreCompact`). Current official documentation (code.claude.com/docs/en/hooks, fetched live) lists 30 named hook events covering session lifecycle, tool execution, permission flow, subagents, background tasks/teammates, config/file watching, worktrees, MCP elicitation, and compaction. Two of the project's three open questions are **already answered by public sources, no live test needed to confirm the negative**: AskUserQuestion does not trigger any PreToolUse/PostToolUse hook (three separate open GitHub feature requests confirm this gap), and Stop does not fire on user interrupt (Escape/Ctrl+C) — the official docs state this explicitly, corroborated by a dedicated GitHub issue. The third open question — what fires when a background task (`run_in_background`) completes and re-invokes Claude — is only partially answered: docs describe `TaskCreated`/`TaskCompleted` hooks tied to the newer "teammate"/background-agent framework, but nothing confirms whether a plain `run_in_background` Bash/Task completion (the case this project cares about, matrix #13) fires `TaskCompleted`, `PostToolUse` on the original tool, both, or neither — this genuinely needs the live matrix run.

Because the doc-fetch tooling paraphrases pages through a summarization pass, two independent fetches of the same page returned slightly different field names for the same event (`tool_response` vs `tool_output` on PostToolUse, `message` vs `notification_type` on Notification). This is not a research gap to agonize over — it is exactly the kind of ambiguity the logging hook itself resolves for free: once the hook is installed, `~/.claude/hook-events.log` becomes the ground truth for exact field names, no doc-trust required. The planner should treat the schemas below as "what fields to look for," not as verbatim contract.

The existing `hooks/install.sh` / `hooks/settings-snippet.json` pair already establishes the pattern to extend: bash + jq, `session_id`-keyed side files, idempotent jq-based settings.json merge keyed on a `has_cmd(...)` regex over the hook command string. The logger should follow the same shape — one shared script, `hook_event_name` already present in every payload so no per-event argv is needed (simpler than the existing "set"/"clear" pattern), one settings.json entry per event key with no matcher (omitted matcher = fires on everything for that event).

**Primary recommendation:** Ship one `event-logger.sh` script that reads stdin once, extracts `hook_event_name` + common fields + a best-effort union of event-specific fields via `jq -c` (nulls stripped), and appends a single compact JSON line to `~/.claude/hook-events.log` with a byte-size guard that truncates the file when it exceeds a threshold (e.g. 5 MB). Register it with `timeout: 2` on every event key found in the current docs (matching the existing hooks' low-timeout, no-decision-control convention), merged into settings.json via the same jq dedup pattern `install.sh` already uses for working-lock/auq-lock.

## Architectural Responsibility Map

This project's "tiers" are not a classic web app's browser/API/DB split — they are the layers between a Claude Code session and the Windows-side monitor.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Hook event capture (reading stdin JSON, extracting fields) | Container / Hook Script (bash+jq) | — | Hooks execute inside the Claude Code process, only place with access to the raw event payload |
| Persistent event record (JSONL) | Shared `~/.claude` bind mount | Container filesystem | Must be readable from Windows without entering a container, for both the user's live UAT and (in Phase 2) the monitor |
| Settings registration (which events call the logger) | `~/.claude/settings.json` (shared mount) | `hooks/install.sh` (repo, source of truth) | Same install mechanism as existing hooks; settings.json is the merge target, install.sh is what's versioned |
| Live case triggering + observation | User (UAT, real Windows+Docker) | — | Locked decision: agent cannot fabricate container kills, Esc interrupts, or multi-container races; requires the real environment |
| Verdict authoring (fallback-per-silent-case) | `.planning/phases/01.../TEST-MATRIX.md` (docs) | — | Locked decision: verdict updates TEST-MATRIX.md in place, no separate report |

## Standard Stack

### Core

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|---------------|
| bash | 5.2.15 (confirmed in this env) | Hook script runtime | Matches existing `auq-lock.sh`/`working-lock.sh`; Claude Code invokes hook `command` entries as shell commands |
| jq | 1.6 (confirmed in this env) | Parse stdin JSON, build compact output JSON | Already a hard dependency of `install.sh` and both existing hook scripts; zero new dependency |

### Supporting

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| `stat` (GNU coreutils) | 9.1 (confirmed) | Read log file byte size for the size-guard/truncate check | Before each append, or on a cheap modulo (e.g. only check every Nth write) to avoid a syscall per event |
| `flock` (util-linux) | 2.38.1 (confirmed) | Optional: serialize the size-check-then-truncate critical section | Only needed if the truncate path itself needs to be race-safe across containers; plain appends do not need it (see Concurrency pitfall below) |
| python3 | 3.11.2 (confirmed) | JSON-validate settings.json after the jq merge | `install.sh` already does this (`python3 -c "import json; json.load(...)"`) — reuse, don't reintroduce a new validator |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| One shared `event-logger.sh` keyed off `hook_event_name` in the payload | Per-event script/argv like `auq-lock.sh set`/`clear` | Not needed here: the logger has no "set"/"clear" duality, `hook_event_name` is already in every payload, so one script with zero args is strictly simpler and is what the "single script vs per-event entries" discretion point in CONTEXT.md is asking about |
| Plain `>>` append (O_APPEND) | `flock`-wrapped append | `>>` append of a single line well under 4 KB is atomic on Linux (POSIX `O_APPEND` + write-below-`PIPE_BUF` guarantee); `flock` adds overhead and a stale-lock failure mode for no benefit on the append path itself — only worth it for the truncate/rotate path |
| Registering the logger on every documented event (30, if the planner takes CONTEXT.md's "every hook event type" literally) | Registering only on the 9 classic + a handful of state-relevant new ones (`TaskCreated`, `TaskCompleted`, `SubagentStart`, `PermissionRequest`) | Full-coverage registration directly serves VER-01's "discover everything, don't bias the verdict" intent, but adds noisy/irrelevant entries (`FileChanged`, `ConfigChange`, `WorktreeCreate/Remove`, `Elicitation*`) to settings.json and increases per-event overhead across many hook types. See Open Questions — flagging this for the planner rather than deciding it here, since it changes both scope and settings.json size |

**Installation:** No package installation. Both `bash` and `jq` are already installed and used by the existing hook scripts in `/workspace/hooks/`. No `npm install` / `pip install` step applies to this phase.

## Package Legitimacy Audit

**Not applicable.** This phase installs no external packages (no npm/pip/cargo dependencies). It adds one bash script using tools (`bash`, `jq`) already present as hard dependencies of the existing `hooks/install.sh`. Package Legitimacy Gate skipped per its own scope ("whenever this phase installs external packages").

## Architecture Patterns

### System Architecture Diagram

```
 Claude Code process (inside a container)
        │  fires a hook event (e.g. PreToolUse, Stop, SessionEnd, ...)
        ▼
 settings.json hook entry for that event
   (no matcher = fires on every occurrence of that event)
        │  spawns: bash "$HOME/.claude/hooks/event-logger.sh"
        │  stdin = JSON payload (session_id, cwd, hook_event_name, event-specific fields)
        ▼
 event-logger.sh
   1. read stdin once into a var
   2. jq -c: build {ts, event, session_id, cwd, ...event-specific fields, nulls stripped}
   3. size guard: if hook-events.log > threshold, truncate first
   4. append the one JSON line with O_APPEND (>>)
   5. exit 0 (no stdout JSON — logger never blocks or alters Claude's behavior)
        ▼
 ~/.claude/hook-events.log   (JSONL, on the host bind mount)
        │
        ├── visible to the user from Windows (UAT: tail -f style review while
        │    triggering each TEST-MATRIX.md case)
        └── (Phase 2, out of scope here) becomes an input the monitor could
             cross-reference — NOT wired up in this phase
```

### Recommended Project Structure

```
hooks/
├── install.sh              # extend: merge logger entries for every discovered event
├── settings-snippet.json   # extend: add one entry per event key, matcher omitted
├── auq-lock.sh              # unchanged
├── working-lock.sh          # unchanged
└── event-logger.sh          # NEW — the Phase 1 deliverable script
.planning/phases/01-hook-coverage-verification/
├── 01-CONTEXT.md
├── 01-RESEARCH.md           # this file
└── 01-UAT.md                # NEW (or TEST-MATRIX.md preamble) — runbook for the live matrix
```

### Pattern 1: Idempotent settings.json merge via jq, keyed on command regex

**What:** `install.sh` already solves "add hook entries without duplicating on re-run" by matching on a regex over `.hooks[]?.command` (e.g. `has_cmd("working-lock\\.sh")`) and dropping-then-re-adding matching entries before appending the snippet's canonical set.
**When to use:** Extend this exact pattern for the logger — add a `drop_logger` filter matching `event-logger\.sh`, apply it to every event key the logger is registered on, then append the snippet's per-event logger entries.
**Example:**
```bash
# Source: /workspace/hooks/install.sh (existing pattern in this repo)
jq --slurpfile snip "$SNIPPET" '
  def has_cmd($re): [.hooks[]?.command] | any(. // "" | test($re));
  def drop_logger: map(select(has_cmd("event-logger\\.sh") | not));
  .hooks.SessionStart = ((.hooks.SessionStart // []) | drop_logger) + ($snip[0].hooks.SessionStart // []) |
  .hooks.PreToolUse   = ((.hooks.PreToolUse   // []) | drop_working | drop_logger) + ($snip[0].hooks.PreToolUse   // [])
  # ... one line per event key the logger is registered on
' "$SETTINGS" > "$SETTINGS.tmp"
```

### Pattern 2: Single stdin read, jq builds the output shape, nulls stripped

**What:** Read stdin exactly once (hooks only get one shot at stdin), then let `jq` do all field extraction and shaping in a single invocation rather than multiple `jq -r` calls per field (which would each need their own `cat`/re-read).
**When to use:** Any hook script that logs/records payload data rather than making a single yes/no decision.
**Example:**
```bash
# Source: pattern extending /workspace/hooks/auq-lock.sh's stdin handling
payload=$(cat)
[ -z "$payload" ] && exit 0
line=$(jq -c '
  {ts: (now|floor), event: .hook_event_name, session_id, cwd,
   source, reason, tool_name, notification_type, message,
   agent_type, trigger}
  | with_entries(select(.value != null))
' <<<"$payload" 2>/dev/null) || exit 0
[ -n "$line" ] && printf '%s\n' "$line" >> "$HOME/.claude/hook-events.log"
exit 0
```

### Pattern 3: Matcher omission for full-coverage registration

**What:** For events that support a matcher dimension (tool name on `PreToolUse`/`PostToolUse`, `source` on `SessionStart`, `reason` on `SessionEnd`, `notification_type` on `Notification`, `trigger` on `PreCompact`), omitting the `matcher` key (or `"*"`/`""`) fires the hook for every value of that dimension — confirmed by the official docs' matcher table.
**When to use:** The logger wants every occurrence of every event, so every entry should omit `matcher` entirely — exactly like the existing `working-lock.sh` PreToolUse entry in `settings-snippet.json` (no `"matcher"` key = fires on every tool).

### Anti-Patterns to Avoid

- **Per-field `jq -r` calls re-reading stdin:** stdin can only be consumed once per process; the existing scripts avoid this by doing `sid=$(cat | jq -r ...)` a single time. The logger needs multiple fields, so it must build one `jq -c` object, not multiple `jq -r` extractions.
- **Blocking on a synchronous logger inside `PreToolUse`:** `PreToolUse` gates the tool call. A slow logger (contention on the log file, cold jq startup) adds latency to every single tool call in every session, which is the opposite of "zero overhead." Keep `timeout` low (2s, matching existing hooks) and the script itself sub-50ms in the common case.
- **Assuming every event supports a matcher:** several events (`Stop`, `PostToolUse`, `UserPromptSubmit`) have no matcher dimension at all per the docs' table — don't add a `"matcher"` key to those entries; it's a no-op at best, a silent mismatch at worst if the matcher syntax is misapplied.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Settings.json merge/dedup on reinstall | A new merge algorithm | Extend `install.sh`'s existing `has_cmd`/`drop_*` jq pattern | Already solved, already idempotent, already tested by the two existing hooks; a second, different merge strategy in the same file is a maintenance trap |
| "Which hook events exist" | Guessing from training-data memory of Claude Code's hook system | The live official docs fetch (30-event catalog below) + this phase's own live log | Training data is stale by construction (this project's whole premise is that Claude Code's internals move fast); the doc catalog is dated 2026-07-28 and the log is ground truth |
| Concurrent-write safety | A custom lock-file protocol for every log write | Single-line `jq -c` output + plain `>>` append (POSIX `O_APPEND` atomicity for writes under `PIPE_BUF`) | This is a temporary diagnostic file, not a database; a full locking protocol is disproportionate engineering for a throwaway instrument, and CONTEXT.md's discretion note explicitly allows "a simple max-size truncate" as sufficient |
| Log rotation | A rotating-log library or logrotate integration | A byte-size check + truncate-when-over-threshold, per CONTEXT.md's explicit discretion allowance | This log gets deleted/ignored once Phase 1 concludes; logrotate-grade tooling is solving a problem this instrument doesn't have |

**Key insight:** Everything about this phase is disposable-by-design (CONTEXT.md: "this is a temporary diagnostic instrument"). The main hand-rolling risk isn't over-engineering the logger — it's under-verifying the *event catalog and field names*, since that's the one artifact this phase produces that Phase 2 actually depends on.

## Common Pitfalls

### Pitfall 1: Trusting paraphrased doc field names over the live log

**What goes wrong:** Two independent fetches of the same official docs page returned different field names for the same event (`tool_response` vs `tool_output` on `PostToolUse`; `message` vs `notification_type` on `Notification`). If the logger is coded narrowly to only extract the field name from one doc pass, the actual payload field may be named differently and silently log `null`.
**Why it happens:** Doc-fetch tooling runs content through a summarization pass; exact identifiers are the kind of detail that pass can drift on.
**How to avoid:** Have the logger capture a **broad union** of plausible field names for ambiguous cases (extract both `tool_response` and `tool_output` if either is present; both `message` and `notification_type`), and/or log the *entire* payload for events with schema uncertainty rather than a curated subset. Since this is a one-time diagnostic log, over-capturing is cheap and safe; under-capturing silently produces `null` and defeats the phase's purpose.
**Warning signs:** A field is consistently `null` across every occurrence of an event during UAT — check the raw log against what Claude Code actually sent (dump the whole payload for a few sample events, not just the extracted fields) before concluding a hook doesn't carry that data.

### Pitfall 2: Sensitive data captured in the log

**What goes wrong:** `PreToolUse`/`PostToolUse` payloads for `Bash` carry `tool_input.command` verbatim — which can include secrets typed inline (API keys, tokens, `export FOO=...`), and `Edit`/`Write` payloads can carry file contents. A full-payload logger writing to a file that persists on the shared host mount is a real (if temporary) credential-exposure surface.
**Why it happens:** The instrumentation goal ("capture everything, don't bias the verdict") pulls toward over-logging exactly when the payload is most sensitive (Bash commands, file contents).
**How to avoid:** Prefer field-level extraction (tool_name, not full tool_input) for `Bash`/`Edit`/`Write` where practical, or explicitly document that `hook-events.log` is a temporary, locally-scoped diagnostic artifact to be deleted after the UAT concludes and never committed to git (it already isn't, since it lives under `~/.claude`, outside the repo). If full `tool_input` capture is needed for coverage-verification fidelity (a legitimate ask given the AUQ/interrupt questions), scope the log's lifetime tightly and say so in the runbook.
**Warning signs:** The log file containing recognizable secrets/tokens from real development sessions during the UAT window.

### Pitfall 3: AskUserQuestion produces nothing in the log — this is the correct outcome, not a bug

**What goes wrong:** During the live matrix run (case #6), the tester might assume a silent AUQ case means the logger is broken and debug the wrong thing.
**Why it happens:** Every other tool-related event in the catalog (`PreToolUse`, `PostToolUse`, `PermissionRequest`) fires reliably for ordinary tools, so a total silence for AUQ reads as anomalous unless the tester already knows it's expected.
**How to avoid:** The runbook for case #6 should state upfront: "expect zero log lines for this trigger — confirming silence *is* the pass condition, per public GitHub issues #28273/#12605/#15872." Confirmed via research, no live test needed to discover the negative — only to confirm it still holds on the tester's installed version.
**Warning signs:** N/A — this is a known-good silent case, documented here precisely so it isn't mistaken for a defect during UAT.

### Pitfall 4: Stop-on-interrupt is also a confirmed silent case

**What goes wrong:** Same shape as Pitfall 3 — case #8 (Esc mid-turn) is expected to produce no `Stop` log line, confirmed by official docs ("User interrupt (Escape): Does NOT fire Stop hook") and GitHub issue #9516.
**Why it happens:** Same as above.
**How to avoid:** Pre-fill this row of TEST-MATRIX.md's "Suspected gap / fallback" column with the confirmed answer before the live run, so UAT time is spent on genuinely open cases (background-task re-invocation, multi-container concurrency, corrupt-file handling) rather than re-discovering documented gaps.
**Warning signs:** N/A — known-good silent case.

### Pitfall 5: Concurrent multi-container appends over a Windows bind mount

**What goes wrong:** POSIX `O_APPEND` atomicity for sub-`PIPE_BUF` writes is a Linux-filesystem guarantee. This project's `~/.claude` directory is bind-mounted from Windows into multiple containers (NOTES.md/README.md describe this explicitly, and CONTEXT.md itself names "9p/bind mount" as the concern). Whether that atomicity guarantee survives the mount translation layer (WSL2 9p / Docker Desktop's VirtioFS or gRPC-FUSE backend) is not something official Claude Code docs can answer — it's a property of the user's specific Windows+Docker setup.
**Why it happens:** Bind-mount/network-filesystem implementations don't uniformly preserve local-filesystem write semantics (this is the same reason `install.sh`'s comments already single out `~/.claude` as bind-mounted, and why `monitor.py`'s comments note `/tmp` is deliberately container-local "unlike `~/.claude`").
**How to avoid:** Keep each write a single short JSON line (well under 4 KB) to minimize the interleaving window regardless of the mount's exact guarantees, and design the consumer side (a human reading the log, and later Phase 2 if it ever reads this file) to skip malformed/partial lines rather than fail on them — mirrors TEST-MATRIX case #20's "corrupt state file" requirement, applied here to the log file. This project's specific case (multiple Docker containers on one WSL2 host writing to one bind-mounted file) is exactly what TEST-MATRIX case #15 exercises live — treat any observed interleaving/corruption during that case as a real finding for the verdict, not a logger bug to silently work around.
**Warning signs:** Truncated or concatenated JSON on a single line in `hook-events.log` after a multi-container test run (case #15/#16).

### Pitfall 6: "Every hook event Claude Code supports" is a moving, and large, target

**What goes wrong:** The current docs list 30 named events (up from the ~9 this project's existing hooks use). Several of the newer ones (`TeammateIdle`, `WorktreeCreate/Remove`, `Elicitation`/`ElicitationResult`, `ConfigChange`) belong to features (agent teams, MCP elicitation, worktree management) with no obvious relationship to session working/waiting/needs-input state. Registering the logger on literally all 30 is faithful to the locked decision's letter but adds settings.json entries, and per-event script invocations, for events that will almost certainly never appear in this project's TEST-MATRIX.md cases.
**Why it happens:** The locked decision was written before the full current event catalog was known (it names 8-9 events plus "and any others found in current docs" — written as a hedge, not a considered choice about all 30).
**How to avoid:** Flagged as an Open Question below rather than resolved here — the planner should decide (possibly re-confirming with the user) whether "every event" means the full 30 or the state-relevant subset, since it changes settings.json's size and the install.sh diff meaningfully.
**Warning signs:** N/A — a scoping decision, not a runtime failure mode.

## Code Examples

### Minimal event-logger.sh (Pattern 2, expanded)

```bash
#!/usr/bin/env bash
# Appends one JSONL line per Claude Code hook event to ~/.claude/hook-events.log.
# Diagnostic-only: never blocks, never emits decision-control stdout, exits 0
# unconditionally so a logger failure can never break a session.
#
# Source: pattern derived from /workspace/hooks/auq-lock.sh and working-lock.sh's
# stdin-handling convention; hook_event_name usage confirmed present in every
# event's payload per code.claude.com/docs/en/hooks (fetched 2026-07-28).
set -eu
LOG="$HOME/.claude/hook-events.log"
MAX_BYTES=$((5 * 1024 * 1024))

payload=$(cat)
[ -z "$payload" ] && exit 0

# Size guard: truncate before appending if the log has grown past the threshold.
if [ -f "$LOG" ]; then
  size=$(stat -c%s "$LOG" 2>/dev/null || echo 0)
  [ "$size" -gt "$MAX_BYTES" ] && : > "$LOG"
fi

line=$(jq -c '
  {
    ts: (now | todate), event: .hook_event_name, session_id, cwd,
    source, reason, trigger,
    tool_name, tool_use_id,
    notification_type, message,
    agent_type, agent_id,
    last_assistant_message, stop_hook_active
  }
  | with_entries(select(.value != null))
' <<<"$payload" 2>/dev/null) || exit 0

[ -n "$line" ] && printf '%s\n' "$line" >> "$LOG"
exit 0
```

### settings-snippet.json fragment (one event, pattern repeats per event key)

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [
        { "type": "command", "command": "bash \"$HOME/.claude/hooks/auq-lock.sh\" clear", "timeout": 2 },
        { "type": "command", "command": "bash \"$HOME/.claude/hooks/working-lock.sh\" clear", "timeout": 2 },
        { "type": "command", "command": "bash \"$HOME/.claude/hooks/event-logger.sh\"", "timeout": 2 }
      ]}
    ]
  }
}
```
*(Source: extends the existing pattern in `/workspace/hooks/settings-snippet.json`; the logger is appended as an additional entry in each event's `hooks` array alongside the existing lock scripts, not a replacement.)*

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| ~9 core hook events (session/prompt/tool/notification/stop/compact) | 30 named hook events including background-task/"teammate" lifecycle (`TaskCreated`, `TaskCompleted`, `TeammateIdle`), MCP elicitation (`Elicitation`, `ElicitationResult`), worktree management, and granular failure variants (`PostToolUseFailure`, `StopFailure`) | Undated in the fetched docs, but represents growth well beyond this project's existing `hooks/` scripts and beyond typical Claude Code hook documentation from before 2026 | This project's existing hooks only use the classic ~9; the new events (particularly `TaskCreated`/`TaskCompleted`) are the most promising unexplored lead for TEST-MATRIX case #13 (background task completion) and should be included in the live matrix run even though CONTEXT.md's locked-decision list doesn't name them explicitly |
| Assumed: Stop covers "turn ended," including interrupts | Confirmed: Stop explicitly excludes user-interrupt (Escape/Ctrl+C) termination | Documented as of the current fetch; matches this project's own suspicion in TEST-MATRIX #8 | Confirms the hybrid model's necessity for at least one case without needing the live run to discover it — only to confirm it holds on the tester's version |

**Deprecated/outdated:** Nothing in this domain is deprecated; the catalog has only grown. No action needed.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|-----------------|
| A1 | POSIX `O_APPEND` atomicity for sub-`PIPE_BUF` writes generally holds even across WSL2/Docker Desktop bind-mount backends | Concurrency (Pitfall 5), Alternatives Considered | If the mount layer doesn't preserve this, concurrent multi-container writes (TEST-MATRIX case #15/#16) could interleave/corrupt log lines during the live UAT — mitigated regardless by designing the reader to skip malformed lines, so impact is bounded to "some events lost during races," not a crash |
| A2 | The exact field names in each event's JSON payload (e.g. `tool_response` vs `tool_output`, `message` vs `notification_type`) as reported by the two independent doc fetches | Standard Stack, Code Examples | If the logger only captures the doc-reported name and the actual field differs, that field logs as absent/null for that event — mitigated by capturing a broad union of plausible names (already reflected in the Code Examples) and by the live log itself being the final source of truth |
| A3 | `TaskCreated`/`TaskCompleted` are the correct events to watch for TEST-MATRIX case #13 (background task completion re-invoking Claude) | State of the Art, Open Questions | If these events are unrelated to plain `run_in_background` completion (they may be scoped to a distinct "teammate"/agent-team feature), case #13 may still show no hook signal at all — this is exactly what the live UAT needs to determine either way, no different from the AUQ/interrupt cases already confirmed |
| A4 | Whether "async": true / "asyncRewake": true are available on this project's installed Claude Code version | Standard Stack (Alternatives), Anti-Patterns | If unavailable/unsupported, using them in the settings snippet could silently no-op or error; low risk since the recommendation defaults to synchronous+low-timeout (matching the existing proven pattern) and only surfaces async as an optional discretion-level optimization |

**If this table is empty:** N/A — see rows above.

## Open Questions

1. **Does "every hook event Claude Code supports" mean all 30 documented events, or the state-relevant subset?**
   - What we know: CONTEXT.md's locked decision names 8-9 classic events plus "and any others found in current docs." The current docs list 30.
   - What's unclear: Whether the intent was "be exhaustive" (register all 30, maximal discovery, larger settings.json diff) or "cover what we knew about plus whatever else turns out to matter" (a smaller, curated set including the promising new leads like `TaskCreated`/`TaskCompleted`/`SubagentStart`/`PermissionRequest`, skipping clearly irrelevant ones like `WorktreeCreate`/`Elicitation*`/`ConfigChange`).
   - Recommendation: Register the logger on the classic 9 plus the newer events with plausible relevance to session/turn state (`PermissionRequest`, `PermissionDenied`, `SubagentStart`, `TaskCreated`, `TaskCompleted`, `PostToolUseFailure`, `StopFailure`) — roughly 16 events — and explicitly log this scoping choice in the plan so the user can expand it during UAT review if a matrix case turns out to need one of the skipped events (e.g. `FileChanged` if a case involving watched-file changes ever comes up). This keeps the settings.json diff proportionate while still satisfying "logging a subset would bias the verdict" for every event that could plausibly relate to state detection.

2. **What exactly fires for background-task (`run_in_background`) completion and re-invocation (TEST-MATRIX case #13)?**
   - What we know: `TaskCreated`/`TaskCompleted` hooks exist and relate to background work; `PostToolBatch` fires "after parallel tool calls resolve."
   - What's unclear: None of the fetched sources confirm the exact event sequence for a plain backgrounded Bash/Task tool call finishing while Claude is otherwise idle, versus the more elaborate "teammate" agent-team framework these events may actually be scoped to.
   - Recommendation: This is squarely a live-UAT question (case #13 already exists in TEST-MATRIX.md for exactly this reason) — no further desk research is likely to resolve it; register the logger broadly enough to catch whichever event(s) actually fire.

3. **Exact field names per event** — see Assumptions A2. Resolved by the live log itself; not something further research can pin down more precisely than the two (mutually inconsistent) doc fetches already have.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|--------------------|
| V2 Authentication | No | No auth boundary — local hook script running as the container's own user |
| V3 Session Management | No | `session_id` here is Claude Code's own concept, not an auth session |
| V4 Access Control | No | No access-control decisions made by this script |
| V5 Input Validation | Yes | Treat hook stdin as untrusted-shaped JSON: always pipe through `jq` for parsing/extraction, never `eval`/string-interpolate a field into a shell command; a malformed or adversarial-shaped payload should fail the `jq` parse and hit the script's `|| exit 0` fallback, never crash or execute injected content |
| V6 Cryptography | No | No crypto in scope |
| V7 Error Handling & Logging (informative, not a numbered ASVS-1 category but directly relevant) | Yes | Standard control: do not log secrets/credentials. Directly applicable — see Pitfall 2 (sensitive data in `tool_input`/file contents). Recommendation: prefer field-level extraction over full-payload capture where practical, and treat the log file's lifetime as bounded to the diagnostic window |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Shell injection via unsanitized payload fields interpolated into a command string | Tampering | Never build shell commands from payload field values; only ever pass the raw stdin payload into `jq` and use `jq`'s own output, matching the existing `auq-lock.sh`/`working-lock.sh` convention of `cat \| jq -r ...` |
| Credential/secret exposure via full `tool_input`/file-content logging | Information Disclosure | Field-level extraction over full-payload capture for `Bash`/`Edit`/`Write`-shaped events; treat `hook-events.log` as a temporary artifact not to be retained past the UAT window (see Pitfall 2) |
| Log file used as an uncontrolled-growth DoS vector (fills the shared mount) | Denial of Service | Byte-size guard + truncate, already a locked-decision requirement (CONTEXT.md discretion note) and reflected in the Code Examples |

## Sources

### Primary (MEDIUM confidence — official docs, doc-fetch tooling paraphrase risk noted throughout)
- code.claude.com/docs/en/hooks — hook event catalog, JSON payload schemas, matcher rules, timeout/async semantics, exit-code behavior per event, SessionEnd reason values, Stop-on-interrupt behavior (fetched twice independently, 2026-07-28; minor field-name inconsistency between the two fetches noted in Pitfall 1 / Assumption A2)
- code.claude.com/docs/en/hooks.md — raw-markdown re-fetch of the same page, used to cross-check the first fetch's summary

### Secondary (MEDIUM confidence — community/GitHub, corroborates official docs)
- github.com/anthropics/claude-code/issues/28273, #12605, #15872 — three independent open feature requests confirming AskUserQuestion triggers no PreToolUse/PostToolUse hook
- github.com/anthropics/claude-code/issues/9516 — "User Interrupt Hook" feature request confirming Stop does not fire on user interrupt
- github.com/disler/claude-code-hooks-mastery — third-party reference repo cross-checked for event-name consistency (13 events demonstrated with test validation status noted, subset of the full 30-event catalog)

### Tertiary (LOW confidence — not relied on for factual claims, background context only)
- morphllm.com/claude-code-hooks, claudefa.st/blog/tools/hooks/hooks-guide, various other blog/guide sites surfaced in search results — used only to corroborate the existence/scale of the 30-event catalog, not as a primary source for any specific field name or behavior claim

## Metadata

**Confidence breakdown:**
- Standard stack (bash/jq): HIGH — directly confirmed present and versioned in this environment, matches existing repo pattern exactly
- Event catalog & payload schemas: MEDIUM — official docs fetched twice, cross-checked against community sources for the two confirmed-silent cases, but doc-fetch summarization introduced field-name inconsistencies that only the live log can fully resolve
- Confirmed-silent cases (AUQ, Stop-on-interrupt): MEDIUM-HIGH — official docs + multiple independent GitHub issues agree, but not verified live in this session (that's the phase's own job)
- Background-task event (case #13): LOW — genuinely unresolved by available sources, correctly scoped as a live-UAT question

**Research date:** 2026-07-28
**Valid until:** ~14 days (Claude Code hook system is fast-moving per this project's own premise — "already happened three times" that internal changes broke prior assumptions; re-verify against current docs if planning is delayed)
