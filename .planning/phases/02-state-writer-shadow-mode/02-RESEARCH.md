# Phase 2: State Writer & Shadow Mode - Research

**Researched:** 2026-07-29
**Domain:** Claude Code hooks (state-writer script), atomic file-based IPC on a shared 9p mount, dual-engine (shadow) comparison inside an existing Python/tkinter monitor
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (governing):** The user's experience does not change AT ALL in Phase 2: same labels, same colors, same staleness feel, same notifications. The refactor is entirely under the hood. Every area below was answered "come adesso". Reversibility: reversible — but treat as LOCKED: any visible change in shadow phase is a defect, not an improvement opportunity.
- **D-02:** Divergence review is agent-driven: divergences go to a log file; Claude reads and analyzes it in-session with the user (no overlay indicator, no visual debug UI). The user explicitly does NOT want to watch divergences themselves.
- **D-03:** Flip to Phase 3 is decided TOGETHER after N days without unexplained divergences (N flexible, target ~1 week of real usage; the exact number is agreed when reviewing). No automatic flip.
- **D-04:** A divergence is not automatically a new-engine bug — the user expects "divergenze in meglio" (e.g. hook engine sees the AUQ modal instantly where legacy sees it only at answer time). The divergence log MUST carry enough context per entry (session, tick, both verdicts, last hook event, legacy evidence) to judge WHICH side was right. Classification (legacy-wrong vs hooks-wrong vs both-defensible) happens during review, not in code.
- **D-05:** Labeling works exactly as today (current auto-label mechanism + user-set alias on click). The state-file engine must reproduce today's labels, not invent new ones. The known cwd collision (`/workspace` in every container) is a Phase 2 *internal* problem: the writer should capture container identity (e.g. `$HOSTNAME` at hook time) as data so the engine can map session→container as reliably as today or better, but the displayed label does not change.
- **D-06:** Thresholds and behavior as today (~10 min heartbeat silence + `docker ps` cross-check). Paused containers: rendered like today (no new "frozen" state in UI) — but the engine must not mistake `paused` for `exited` (verdict: paused = alive-but-frozen, never auto-removed as dead). Dead sessions: same visibility/removal behavior as today.
- **D-07:** Permission prompts and AUQ modals stay GREEN, identical to turn-end green — no new color, no distinct notification. `PermissionRequest` improves *timeliness* (instant vs Notification's ~6s lag) but not the rendering.
- **D-08:** SW-01's event list ("SessionStart, UserPromptSubmit, PostToolUse, Notification, Stop, SessionEnd") predates the live campaign. The writer's event set must follow the verdict in TEST-MATRIX.md instead: include `PermissionRequest` (instant needs_input), `PostToolBatch`/`PostToolUseFailure` (heartbeat), `SubagentStop` (ignore for state), and read `background_tasks_count` from Stop payloads (async-in-flight). Notification becomes optional/secondary.
- **D-09:** ENG-06's "badges intact via shell_tracker" is superseded: single unified badge ◉N fed by `background_tasks_count`; the ⚙/◉ pair and shell_tracker are removed. Recorded in PROJECT.md Key Decisions and TEST-MATRIX case 18.

### Claude's Discretion

- State file schema details beyond SW-02's minimum (`state`, `ts`, `cwd`, `last_event`) — e.g. adding `hostname`, `background_tasks_count`, `last_event_ts_ms`.
- Divergence log format/location and the shadow-tick comparison mechanics.
- Orphan state-file cleanup policy (resume-picker ids, /clear old ids, killed sessions) — verdict says these exist; how/when to prune is implementation.
- Exact staleness implementation as long as observable behavior matches today.
- How `--state-files` flag coexists with the default path during shadow (flag naming, config).

### Deferred Ideas (OUT OF SCOPE)

- Campagna ricertificazione hook per versione Claude Code — promoting matrix+runbook out of `.planning/`, per-version fixtures, smoke checklist for major bumps. Not Phase 2 scope.
- Badge unificato ◉N rendering — decided (D-09) but the visible swap happens at Phase 3 flip, not during shadow (D-01 zero UX change).

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SW-01 | Hooks write one state file per session, atomically, on lifecycle events | Event set corrected by D-08 to the TEST-MATRIX-verified list (see Standard Stack → Event-to-State Mapping); atomic tmp+rename pattern in Code Examples; Pitfall 1 (mount atomicity) and Pitfall 10 (exit-0 discipline) |
| SW-02 | Each state file carries `state`, `ts`, `cwd`, `last_event` | Schema proposal in Architecture Patterns → Recommended State File Schema; Pitfall 5 (hostname for container disambiguation, per D-05) |
| SW-03 | working-lock/auq-lock keep functioning unchanged during rollout | Don't Hand-Roll → reuse `hooks/install.sh` idempotent merge pattern; Pitfall 4 (event-logger.sh collision check before/during rollout) |
| ENG-01 | `monitor.py --state-files` derives state from `monitor-state/` as primary source | Architecture Patterns → dual-engine split; Open Question 1 (exact flag semantics) |
| ENG-02 | Shadow mode logs every divergence without changing UI | Architecture Patterns → shadow-tick comparison; Pitfall 3 (render must stay legacy-only); Code Examples → divergence log entry shape (D-04 fields) |
| ENG-03 | Stale sessions via heartbeat silence + `docker ps` cross-check, paused ≠ exited | Don't Hand-Roll → `docker inspect --format '{{.State.Status}}'` instead of parsing `docker ps` Status text; Pitfall 6 (paused/exited distinction) |
| ENG-04 | Corrupt/partial/missing state files never crash the monitor | Pitfall 8 (defensive read pattern, matches `tail_last_line` style); Common Pitfalls → TEST-MATRIX case 20 |
| ENG-05 | Hookless containers stay visible via per-session legacy fallback | Architecture Patterns → per-session engine selection; TEST-MATRIX case 21 verdict (targeted jsonl peek as migration bridge) |
| ENG-06 | Every hook-silent case from TEST-MATRIX verdict covered by its fallback | Full mapping reproduced in Architecture Patterns → Hook-Silent Case Coverage Table |

</phase_requirements>

## Summary

Phase 2 is a pure extension of an already-verified, already-live-tested design: TEST-MATRIX.md's "Verdict to extract" section (Phase 1, live-confirmed on Claude Code 2.1.220) is the ground truth for which hook events fire, what they carry, and which cases need a fallback. There is no remaining exploratory research to do on "does hook X fire" — that question is answered empirically. What Phase 2 actually needs is *engineering* research: how to write one state file per session atomically on a shared 9p mount, how to run two state-derivation engines side by side without letting the new one leak into rendering, and how to cross-check container liveness without the fragile human-readable `docker ps` Status column.

The state writer is a sibling of the existing `hooks/event-logger.sh` (same bash+jq+flock-lite house style, same `exit 0`-always discipline) but with a materially different write pattern: event-logger.sh only ever *appends* a line, which is safe without tmp+rename; the state writer *overwrites* one file per session on every event, which is exactly the case tmp+rename exists for (TEST-MATRIX case 20 — a hook killed mid-write must never leave a truncated/corrupt file at the final path). On the monitor side, the shadow engine is additive: `scan()` (or a new sibling function) keeps producing the sessions list that drives the UI unchanged, while a second pass reads `monitor-state/*.json`, derives its own verdict per session, diffs it against the legacy verdict, and appends one divergence-log line per difference — never touching `_make_session_row`/`_make_compact_chip` inputs.

One important finding from the official docs fetch this session (code.claude.com/docs/en/hooks) that TEST-MATRIX's live campaign did not surface: `background_tasks` array items carry a `status` field (`running`/`completed`/`failed`), not just an id. The current diagnostic logger (`event-logger.sh`) captures `background_tasks_count` as the *raw array length*, which is fine for a one-off diagnostic but would be a correctness bug in the state writer — the unified ◉N badge (D-09) and the async-in-flight grey state (case 17) must count only entries with `status == "running"`, or a Stop event whose array still lists a *completed* background task would keep the session stuck grey/badged after the work is actually done.

**Primary recommendation:** Write `hooks/state-writer.sh` as a single shared script (same shape as `event-logger.sh`, keyed off `hook_event_name` from stdin, zero per-event argv), registered on the TEST-MATRIX-verdict event set (not SW-01's stale list), writing `~/.claude/monitor-state/<session_id>.json` via `mktemp` in the same directory + `mv`. On the monitor side, add a `scan_state_files()` sibling to `scan()`, a `--state-files` flag that makes it the sole renderer for manual ENG-01 verification, and an always-on shadow comparison inside the existing tick loop (`refresh()`) that logs D-04-shaped divergence entries but always renders the legacy `sessions` list.

## Architectural Responsibility Map

This project's "tiers" are not a classic web app's browser/API/DB split — they are the layers between a Claude Code session (running inside a Docker/WSL2 container) and the Windows-side monitor process, connected only by a shared bind-mounted `~/.claude` directory (a 9p filesystem).

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Hook event capture + state-file write | Container / Hook Script (bash+jq) | — | Only place with access to the raw event payload; must write atomically since the writing process can be killed mid-turn (container kill is a first-class case, TEST-MATRIX #9) |
| Per-session state storage | Shared `~/.claude/monitor-state/` (9p bind mount) | Container-local (ephemeral, not authoritative) | Must be readable from Windows without entering a container — this is the entire point of the refactor |
| Primary state derivation (new engine) | Windows Host / Monitor Engine (`monitor.py`, new `scan_state_files()`) | — | Reads only `monitor-state/*.json`; never touches jsonl |
| Legacy state derivation (existing engine, unchanged) | Windows Host / Monitor Engine (`monitor.py`, existing `scan()`) | Container filesystem (jsonl via shared mount) | Stays exactly as-is through Phase 2 (D-01); still drives 100% of what's rendered |
| Container liveness cross-check (paused/exited/running) | Windows Host / Docker CLI (`docker inspect`) | — | Only Windows-side process with `docker` on PATH; hooks cannot see container state from inside |
| Shadow comparison + divergence logging | Windows Host / Monitor Engine (new code in `refresh()` tick loop) | Shared `~/.claude` mount (divergence log file) | Runs every tick alongside both engines; output is a log file, not UI |
| Rendering (overlay, notifications, badges) | Windows Host / tkinter UI (`_make_session_row`, `_make_compact_chip`, `_notify`) | — | Locked to legacy verdict only during Phase 2 (D-01) — the shadow engine's output must never reach this tier |
| Existing lock hooks (working-lock, auq-lock) | Container / Hook Script (bash) | — | Continue running unchanged (SW-03); retire only in Phase 3 |

## Standard Stack

### Core

No new runtime dependencies. This is a zero-dependency-constraint project (Python 3.10+ stdlib on Windows, bash+jq inside containers) and Phase 2 does not change that constraint.

| Tool | Version (confirmed in this environment) | Purpose | Why Standard |
|------|------------------------------------------|---------|---------------|
| bash | present (`/bin/bash`) | State-writer hook script runtime | Matches existing `auq-lock.sh`/`working-lock.sh`/`event-logger.sh` [VERIFIED: codebase] |
| jq | 1.6 | Parse hook stdin JSON, build the state-file JSON | Already a hard dependency of `install.sh` and every existing hook script [VERIFIED: codebase] |
| flock | present (`/usr/bin/flock`) | Optional short-wait serialization if the divergence log needs the same size-guard pattern as `hook-events.log` | `event-logger.sh` already establishes this exact pattern for a shared append-only file on the 9p mount [VERIFIED: codebase] |
| Python | 3.11.2 (this env; project targets 3.10+) | Monitor engine additions (`scan_state_files`, shadow comparison, `--state-files` flag) | stdlib only — `json`, `pathlib`, `time`, `os` — no new imports needed [VERIFIED: codebase] |

### Supporting

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `mktemp` (coreutils, or `jq`'s own temp-file convention `"$file.tmp.$$"`) | Atomic write staging | Every state-file write — see Pitfall 1 |
| `docker inspect --format '{{.State.Status}}'` | Distinguish `running`/`paused`/`exited`/`dead` | Extending the existing `docker inspect` call in `scan_containers()` (already runs per tick) rather than adding a second subprocess call |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Single shared `state-writer.sh` keyed on `hook_event_name` | Per-event scripts like the existing `working-lock.sh set`/`clear` pattern | Not needed: `hook_event_name` is already in every payload (same reasoning `event-logger.sh` used over the lock-script pattern); one script is strictly simpler and is what SW-01/SW-02's "one small state file" framing implies |
| `mktemp` + `mv` for atomic writes | `jq ... > "$file"` direct redirect | Direct redirect truncates the destination file immediately on shell open, before jq even runs — this is precisely the corruption TEST-MATRIX case 20 and ENG-04 exist to prevent. Not a viable alternative, listed here only to name the anti-pattern explicitly (see Pitfall 1) |
| `docker inspect --format '{{.State.Status}}'` for paused/exited | Regex-parsing `docker ps`'s human-readable `Status` column (e.g. `"Paused"`, `"Exited (0) 2 minutes ago"`, `"Up 5 minutes"`) | `docker ps` Status text is meant for humans and its exact wording has changed across Docker versions; `.State.Status` is a stable enum (`created`/`running`/`paused`/`restarting`/`removing`/`exited`/`dead`) meant for scripting |

**Installation:** none — no new packages.

**Version verification:** N/A — no new packages introduced this phase.

## Package Legitimacy Audit

**Not applicable.** This phase introduces zero new external packages (no npm/pip/cargo installs). It extends existing bash+jq hook scripts and existing Python-stdlib monitor code only, preserving the project's zero-dependency constraint (documented in PROJECT.md). The Package Legitimacy Gate is skipped for this reason — there is nothing to check against a registry.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────── Container (WSL2/Docker) ───────────────────────────┐
│                                                                                  │
│  Claude Code process                                                            │
│    │ fires hook events: SessionStart, UserPromptSubmit, PreToolUse,             │
│    │   PostToolUse, PostToolUseFailure, PostToolBatch, PermissionRequest,       │
│    │   Notification, Stop, SubagentStop, SessionEnd  (stdin = JSON payload)     │
│    ▼                                                                             │
│  hooks/state-writer.sh  (bash + jq, keyed on .hook_event_name, exit 0 always)   │
│    │  1. read stdin → jq → {state, ts, cwd, hostname, last_event,               │
│    │     background_tasks_count(running-only), ...}                             │
│    │  2. write to  monitor-state/<session_id>.json.tmp.$$  (same dir)           │
│    │  3. mv  → monitor-state/<session_id>.json   (atomic rename)                │
│    │                                                                             │
│  hooks/working-lock.sh, hooks/auq-lock.sh  ← UNCHANGED, keep running (SW-03)    │
│                                                                                   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                    │ shared 9p bind mount  (~/.claude/*)
                                    ▼
┌────────────────────────── Windows Host ────────────────────────────────────────┐
│                                                                                  │
│  monitor.py  refresh()  tick loop (every REFRESH_MS)                            │
│    │                                                                             │
│    ├─► scan(label_map, sessionid_to_label)          ← LEGACY, UNCHANGED         │
│    │     reads jsonl + working-locks + auq-locks     → sessions[] (rendered)    │
│    │                                                                             │
│    ├─► scan_state_files(label_map, ...)              ← NEW, shadow only         │
│    │     reads monitor-state/*.json                                             │
│    │     + docker inspect .State.Status (paused/exited/running cross-check)     │
│    │     + heartbeat-silence staleness (~10 min, D-06)                          │
│    │     → shadow_sessions[]  (NEVER rendered directly during Phase 2)          │
│    │                                                                             │
│    ├─► compare(sessions, shadow_sessions)             ← shadow-tick comparison  │
│    │     per session_id: legacy verdict vs shadow verdict                       │
│    │     diff? → append divergence-log line (D-04 shape: session, tick,         │
│    │             both verdicts, last_event, legacy evidence)                    │
│    │                                                                             │
│    └─► _refresh_compact(sessions) / row updates       ← renders LEGACY only     │
│          _check_transitions(sessions) → _notify(...)  ← notifies off LEGACY only│
│                                                                                   │
│  `monitor.py --state-files`  (manual/dev mode, ENG-01 isolation)                │
│    → renders scan_state_files() output directly, bypassing legacy entirely      │
│    → used to eyeball-verify the new engine standalone, NOT the daily driver     │
│                                                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

A reader can trace the primary use case end-to-end: a hook event fires inside the
container → `state-writer.sh` derives a state and atomically writes one JSON file →
the Windows-side tick loop reads that file (new path, shadow-only) alongside the
existing jsonl-based path (legacy, still the only one that reaches the screen) →
any disagreement between the two is written to a divergence log for later human
review, never surfaced in the overlay itself.

### Recommended Project Structure

```
hooks/
├── event-logger.sh       # Phase 1 diagnostic instrument — unaffected by Phase 2,
│                          #   but see Pitfall 4 (registration collision check)
├── state-writer.sh        # NEW — the Phase 2 state writer, sibling of event-logger.sh
├── working-lock.sh         # unchanged (SW-03)
├── auq-lock.sh              # unchanged (SW-03)
├── install.sh                # extended: register state-writer.sh on the TEST-MATRIX
│                              #   event set, alongside the existing merge logic
├── hook-events.json            # unaffected (Phase 1 diagnostic event list)
└── state-writer-events.json     # NEW — the state writer's own event list (D-08 verdict
                                  #   set), kept separate from hook-events.json since the
                                  #   two scripts serve different purposes and may diverge

monitor.py                        # extended: scan_state_files(), staleness helpers,
                                    #   docker .State.Status cross-check, shadow-tick
                                    #   comparison + divergence logging, --state-files flag
test_monitor.py                    # extended: new test classes for scan_state_files()
test_state_writer.py                # NEW — sibling of test_event_logger.py, drives
                                     #   state-writer.sh via subprocess with HOME pinned
```

### Pattern 1: Single shared, event-keyed hook script

**What:** One bash script registered on every relevant hook event, branching internally on `hook_event_name` from the JSON payload — not a `set`/`clear` argv pattern like the older lock scripts.
**When to use:** Any hook whose behavior is fully determined by which event fired plus payload fields (no external "which phase of a two-step lock am I in" argument needed).
**Example:**
```bash
# Source: hooks/event-logger.sh (existing codebase pattern, Phase 1)
payload=$(cat)
[ -z "$payload" ] && exit 0
event=$(jq -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null)
[ -z "$event" ] && exit 0
```

### Pattern 2: Atomic same-directory tmp+rename write

**What:** Write the full new content to a temp file in the SAME target directory, then `mv` it over the final path.
**When to use:** Any file the writer fully replaces on every update (state-writer.sh's per-session JSON) — as opposed to append-only files (event-logger.sh's log), which don't need this.
**Example:**
```bash
# NEW pattern for state-writer.sh — event-logger.sh does not need this because
# it only ever appends.
state_dir="$HOME/.claude/monitor-state"
mkdir -p "$state_dir"
tmp="$state_dir/$sid.json.tmp.$$"
printf '%s\n' "$line" > "$tmp" && mv -f "$tmp" "$state_dir/$sid.json"
```
`mv` within the same filesystem is atomic on POSIX (including the 9p bind mount
used here, verified by TEST-MATRIX case 15's flock-based concurrent-write test
passing without corruption for the append-only case — same mount, same
guarantee class). The temp file MUST be created in `$state_dir`, not `/tmp` —
a cross-filesystem `mv` degrades to copy+delete and loses atomicity.

### Pattern 3: Dual-engine tick with single render path

**What:** Compute two independent verdicts per tick (legacy `scan()`, new `scan_state_files()`), diff them, log the diff — but pass only the legacy result into every rendering/notification function.
**When to use:** Exactly this phase's shadow-mode requirement (ENG-02) — this is the mechanism that makes D-01 ("zero UX change") structurally enforceable rather than just a promise: the new engine's output has no code path into `_make_session_row`, `_make_compact_chip`, or `_notify` during Phase 2.
**Example:**
```python
# Sketch — NOT verbatim, illustrates the shape only
def refresh(self) -> None:
    sessions = scan(label_map, sessionid_to_label)          # legacy — UNCHANGED
    if self.shadow_enabled:
        shadow_sessions = scan_state_files(label_map, sessionid_to_label)
        self._log_divergences(sessions, shadow_sessions)     # side effect only
    self._check_transitions(sessions)                        # legacy only
    self._refresh_compact(sessions)                           # legacy only
```

### Hook-Silent Case Coverage Table

Reproduced from TEST-MATRIX.md's "Verdict to extract" section (live-verified,
cc 2.1.220) — this is the ENG-06 requirement's exact input, not a re-derivation:

| Case | Hook signal observed | Fallback | Mechanism |
|------|----------------------|----------|-----------|
| #8 Esc interrupt | None after `PreToolUse` — total silence | heartbeat silence + `docker ps`/`docker inspect` cross-check | No event to hang state transition on; only liveness can unstick a stale `working` |
| #5-deny Permission denied | None after `PermissionRequest` — `PermissionDenied` never fires (0/1300+ live lines) | heartbeat silence + `docker ps`/`docker inspect` cross-check | Same shape as Esc |
| #9 kill/stop/pause | None — `SessionEnd` only fires on clean exit | `docker inspect --format '{{.State.Status}}'`, distinguishing `paused` (alive-but-frozen) from `exited`/`dead` | Container death is invisible to hooks by definition |
| #19 Abandoned prompt (pre-tool) | Only `UserPromptSubmit`, heartbeat never starts | short-window heartbeat silence post-`UserPromptSubmit` + `docker ps`/`docker inspect` | A turn that dies before any tool call has no `PostToolUse`/`PostToolBatch` heartbeat |
| #18 Badges | `background_tasks_count` in `Stop`/`SubagentStop` payload | No jsonl fallback — unified ◉N badge fed directly by the count (D-09) | Filter to `status == "running"` entries only (see Pitfall 2) |
| #21 Hookless container | None, by definition | Targeted per-session jsonl peek (legacy parsing as migration bridge) | Old images stay visible until hooks are everywhere (ENG-05) |

All other TEST-MATRIX cases (#1–7, #10–17, #20) have direct hook-native
signals and need no fallback — see TEST-MATRIX.md rows for the exact event
names per case.

### Recommended State File Schema

```json
{
  "state": "working | waiting | needs_input",
  "ts": "2026-07-29T13:02:38Z",
  "ts_ms": 1785333758000,
  "cwd": "/workspace",
  "hostname": "greenlight-devcontainer",
  "last_event": "Stop",
  "background_tasks_count": 0
}
```
- `state`/`ts`/`cwd`/`last_event` are SW-02's required minimum.
- `hostname` is D-05's container-identity capture — data only, never displayed;
  the label-mapping logic (session_id→label via `docker exec`) stays exactly
  as it is today per D-05.
- `background_tasks_count` is the count of `status == "running"` entries in
  the `background_tasks` array (see Pitfall 2) — feeds both case #17 (stay
  grey while async work is in flight) and the future ◉N badge (D-09,
  Phase 3 rendering).
- `ts_ms` (Claude's Discretion item) is worth adding alongside `ts`: it makes
  divergence-log timing comparisons (open question 3 in TEST-MATRIX,
  render-vs-`Stop` gap) exact rather than second-granularity.

### Event-to-State Mapping (D-08 verdict, supersedes SW-01's literal text)

| Event | Effect on state file |
|-------|----------------------|
| `SessionStart` | create file, `state=idle`/`working` per `source` (fresh prompt not yet submitted → treat as idle until `UserPromptSubmit`) |
| `UserPromptSubmit` | `state=working` |
| `PreToolUse` | (optional) heartbeat touch — mirrors `working-lock.sh`'s re-arm-on-`PreToolUse` reasoning for the prompt→first-flush gap |
| `PostToolUse` | heartbeat touch, `state=working` |
| `PostToolUseFailure` | heartbeat touch (carries `is_interrupt`/`duration_ms` — useful signal, see TEST-MATRIX case 3) |
| `PostToolBatch` | heartbeat touch |
| `PermissionRequest` | `state=needs_input` — instant, ~6s ahead of `Notification` (TEST-MATRIX case 4) |
| `Notification` | secondary/optional per D-08; if kept, same `state=needs_input` effect as a fallback for any `notification_type` not otherwise covered |
| `Stop` | `state=waiting`, UNLESS `background_tasks_count` (running-only) `> 0`, in which case stay `working` (TEST-MATRIX case 17 / D-04 "current async-work semantics") |
| `SubagentStop` | ignored for state (TEST-MATRIX case 12 — can arrive after the parent's `Stop`) |
| `SessionEnd` | remove the state file |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic per-session state write | A custom lock-file/versioning scheme | `mktemp`-in-same-dir + `mv` | POSIX rename is already atomic on this exact mount (established by the existing flock+append pattern's reliability under concurrent writers, TEST-MATRIX case 15); no new primitive needed |
| Paused vs exited vs running | Regex over `docker ps`'s free-text `Status` column | `docker inspect --format '{{.State.Status}}'` (already-open `docker inspect` call in `scan_containers()`, just add a format field) | `.State.Status` is a stable enum meant for scripts; the `Status` text column is meant for humans and has changed wording across Docker versions |
| JSON parsing/building in bash | Hand-written string concatenation of JSON | `jq` (already a hard dependency, `jq -n`/`jq -c` throughout) | Same reasoning `event-logger.sh`/`auq-lock.sh`/`working-lock.sh` already establish — never string-build JSON |
| Divergence log growth control | A brand-new retention/rotation scheme | The exact size-guard + truncation-marker pattern `event-logger.sh` already implements for `hook-events.log` (5MB cap, flock-serialized truncate-then-append) | Same shared-mount, same growth risk, already-solved problem in this codebase |
| Defensive state-file reads (corrupt/partial/missing) | New try/except scaffolding invented from scratch | The existing `tail_last_line()`/`scan()` style: `try: ... except OSError/json.JSONDecodeError: return None/False`, default to the safest visible state | Matches the established codebase idiom exactly (ENG-04 has direct precedent in how `scan()` already tolerates malformed jsonl) |

**Key insight:** every mechanism Phase 2 needs (atomic writes on a 9p mount, jq-only parsing, size-guarded shared logs, defensive parsing that degrades instead of crashing, idempotent `install.sh` merges) already has a working implementation somewhere in this codebase from Phase 1 or earlier. This phase is assembly and extension, not invention — the risk is drifting from those established patterns, not lacking a library for them.

## Common Pitfalls

### Pitfall 1: Direct-redirect writes corrupt the state file on mid-write kill

**What goes wrong:** `jq -n '...' > "$HOME/.claude/monitor-state/$sid.json"` truncates the destination the instant the shell opens it for writing — before `jq` produces any output. If the hook process is killed at that exact moment (TEST-MATRIX case 9, `docker kill` mid-turn), the state file is left empty/truncated, which is exactly the failure mode ENG-04 and TEST-MATRIX case 20 exist to catch.
**Why it happens:** Shell redirection semantics (`>`) truncate-then-write, not write-then-swap.
**How to avoid:** Always write to `"$file.tmp.$$"` in the same directory, then `mv -f` over the final path (Pattern 2). Never redirect directly to the final filename.
**Warning signs:** A state file that parses as valid-but-empty JSON, or 0 bytes, immediately after a kill test.

### Pitfall 2: `background_tasks_count` must filter by status, not just take array length

**What goes wrong:** The official docs (code.claude.com/docs/en/hooks) show `background_tasks` array items carry a `status` field (`running`/`completed`/`failed`) — the Phase 1 diagnostic logger captures the raw array length (`background_tasks_count: (.background_tasks | length)`), which was adequate for a one-off diagnostic but is wrong for the state writer: a `Stop` event whose array still lists a completed or failed task (but zero running ones) would keep the session pinned `working`/grey forever, and the future ◉N badge (D-09) would overcount.
**Why it happens:** The array's *presence* was the signal TEST-MATRIX case 17 tested for; its per-item shape wasn't examined at that level of detail during the live campaign.
**How to avoid:** In `state-writer.sh`, count only entries with `.status == "running"`: `[.background_tasks[]? | select(.status == "running")] | length`.
**Warning signs:** A session stays grey/badged well past the point the user can see all background work has actually finished.

### Pitfall 3: Shadow engine output must have zero code path into rendering

**What goes wrong:** It's easy to accidentally thread the new `scan_state_files()` result into `_check_transitions`, `_notify`, or a row-update call "just for this one field" (e.g. borrowing `hostname` for a label tweak) — which silently violates D-01 (zero UX change is LOCKED, not a suggestion).
**Why it happens:** Both engines produce structurally similar `sessions`-shaped lists, making it tempting to merge fields from one into the other's row data.
**How to avoid:** Keep `scan_state_files()`'s output entirely local to the divergence-logging code path during Phase 2. Any field genuinely needed for legacy rendering (e.g. `hostname` for the cwd-collision fix, D-05) must be threaded through the EXISTING label-resolution mechanism (`sessionid_to_label`), not bypassed via the shadow struct.
**Warning signs:** A code review diff touches `_make_session_row`, `_make_compact_chip`, or `_notify` at all during this phase — that's a signal to stop and re-check against D-01.

### Pitfall 4: event-logger.sh (Phase 1) may still be installed and registered on overlapping events

**What goes wrong:** `event-logger.sh` is registered on `Stop`, `PostToolUse`, `SessionStart`, `SessionEnd`, etc. — the same events the new `state-writer.sh` needs. If both are still active when Phase 2 lands, every one of those events now runs two hook scripts in sequence, doubling per-event latency and settings.json size, without breaking anything functionally (both are independent, both `exit 0`).
**Why it happens:** The Phase 1 diagnostic instrument was explicitly left disposable/optional teardown, and the "campagna ricertificazione" todo (removal timing) was deferred out of Phase 2 scope.
**How to avoid:** Before/during the Phase 2 plan, check `~/.claude/settings.json` (or the repo state) for whether `event-logger.sh` is still registered; if so, decide explicitly whether Phase 2 removes it as part of installing the state writer, or leaves it running (harmless but redundant) until the deferred cleanup todo is picked up. Either choice is fine — leaving it silently unaddressed is the actual risk.
**Warning signs:** `hooks/install.sh` merge logic accidentally clobbers or duplicates `event-logger.sh`'s registration when adding `state-writer.sh`'s.

### Pitfall 5: cwd alone still cannot disambiguate containers — hostname must be captured, never displayed

**What goes wrong:** TEST-MATRIX case 15 confirmed live that two containers mounting the same `/workspace` share the same encoded jsonl directory — `cwd` in the state file has the identical collision. If the planner treats `cwd` as sufficient because "it's one of SW-02's four required fields," the state-file engine reproduces the exact bug D-05 flags.
**Why it happens:** SW-02's four fields (`state`, `ts`, `cwd`, `last_event`) are a floor, not a complete schema — `hostname` is Claude's Discretion, not optional in practice given D-05's explicit requirement to capture container identity.
**How to avoid:** Include `hostname` (or equivalent container-identity signal, e.g. `$HOSTNAME` env var read at hook time) in every state file write. Do not use it to change the displayed label (D-05 — labels must match today exactly) — only to let the engine's internal session→container mapping be as correct as today's `docker exec`-based approach, or better.
**Warning signs:** Two sessions from different containers, same mounted path, showing identical or swapped labels in the shadow engine's output.

### Pitfall 6: paused containers must never be treated as exited

**What goes wrong:** TEST-MATRIX case 9 found `docker pause` is invisible to hooks (no event fires) — if the staleness logic treats "no heartbeat + container not found running" as dead without checking for `paused` specifically, a deliberately paused container's session would incorrectly disappear/reset instead of staying visible-but-frozen (D-06's explicit requirement).
**Why it happens:** A naive `docker ps` (which by default only lists running containers) would simply not list a paused container at all, making it indistinguishable from "gone."
**How to avoid:** Use `docker ps -a` or `docker inspect --format '{{.State.Status}}'` against the specific container ID (already known from `scan_containers()`), checking explicitly for `paused` before falling through to "treat as dead."
**Warning signs:** Pausing a container mid-test makes its session vanish from the shadow engine's view instead of staying present with a frozen/aged look.

### Pitfall 7: PermissionRequest/PostToolBatch/SubagentStop/Stop can literally alter Claude Code's control flow — the state writer must never emit decision-control output

**What goes wrong:** Per official docs, `PermissionRequest` denies the tool call on exit code 2 or a `hookSpecificOutput.decision` JSON response; `PostToolBatch`, `Stop`, and `SubagentStop` can block the agentic loop the same way. A bug in `state-writer.sh` that accidentally exits non-zero, or that echoes stray text to stdout on exit 0 that gets misparsed as `hookSpecificOutput`, would silently start denying permissions or blocking turns in production — a severe functional regression disguised as a state-tracking bug.
**Why it happens:** The writer script is new code touching several blocking-capable events for the first time in this project (the existing lock scripts only used `Notification`/`Stop` for `auq-lock.sh` and `UserPromptSubmit`/`PreToolUse`/`Stop` for `working-lock.sh` — neither previously touched `PermissionRequest` or `PostToolBatch`).
**How to avoid:** Follow the exact `exit 0`-always discipline already established by `event-logger.sh` and both lock scripts: parse via `jq`, write the state file, `exit 0` on every path including malformed/empty stdin — and never write anything to stdout on the events that support decision-control JSON (only `event-logger.sh`-style writes go to the log/state file, nothing to stdout).
**Warning signs:** Tool calls silently start requiring re-approval, or turns stop unexpectedly, after `state-writer.sh` is installed — check its stdout/exit code first, before suspecting Claude Code itself.

### Pitfall 8: state files must degrade gracefully, not crash the monitor

**What goes wrong:** A missing file (hookless container, case 21), a partially-written file caught mid-tmp-rename-window, or a JSON file with unexpected/missing keys must all be handled without raising — mirroring how `scan()`/`tail_last_line()` already treat malformed jsonl.
**Why it happens:** New code reading a new file format is exactly where an unguarded `json.load()` or a `KeyError` on a missing field gets introduced.
**How to avoid:** Wrap every state-file read in `try: ... except (OSError, json.JSONDecodeError): <fallback>`, and use `.get(key, default)` for every field access — the same idiom `scan()` already uses throughout.
**Warning signs:** Monitor crashes or an unhandled traceback correlating with a fresh/incomplete `monitor-state/*.json` file.

### Pitfall 9: divergence log needs the same growth control as hook-events.log

**What goes wrong:** An unbounded divergence log on the shared 9p mount grows indefinitely across a week-plus of shadow-mode operation (D-03's target validation window), potentially becoming large enough to slow reads/writes on a filesystem shared with jsonl session data.
**Why it happens:** It's new code, easy to write as a naive unbounded append without revisiting the size-guard pattern `event-logger.sh` already solved for exactly this shared-mount growth risk.
**How to avoid:** Apply the same size-guard + truncation-marker + flock-short-wait pattern `event-logger.sh` uses for `hook-events.log`, unless a different retention policy is explicitly decided (this is Claude's Discretion per CONTEXT.md — "format/location and mechanics" — but the growth-control *mechanism*, not just the format, should be a deliberate choice, not an omission).
**Warning signs:** `~/.claude/monitor-state-divergence.log` (or wherever it lands) growing unbounded during the validation week.

### Pitfall 10: orphaned state files from resume-picker and /clear need pruning, but must not be mistaken for stuck sessions

**What goes wrong:** TEST-MATRIX cases 10/11 confirmed live: `/resume`'s session picker creates a short-lived (~10s) session_id whose state file becomes an orphan once the real conversation resumes under a different/stable id; `/clear` orphans the OLD session_id's state file the same way. If the staleness/pruning logic doesn't recognize these as legitimately abandoned (vs. a genuinely stuck session), they either accumulate forever or — worse — get flagged as false "session needs attention" cases in the shadow comparison.
**Why it happens:** Both cases are hook-visible (`SessionEnd(reason=resume)`, `SessionEnd(reason=clear)`) but happen fast enough that a naive implementation might not correlate the removal event with the orphaned file before the next tick runs.
**How to avoid:** `SessionEnd` already removes the state file (per the event-to-state mapping above) for the OLD id in both cases — as long as the writer is correctly registered on `SessionEnd` and the removal is unconditional (not gated on any other check), this resolves itself structurally. Verify with a targeted test mirroring TEST-MATRIX cases 10/11.
**Warning signs:** `monitor-state/` accumulating stale files days after a `/resume` or `/clear` session.

## Code Examples

### state-writer.sh — atomic write skeleton

```bash
# Source: pattern derived from hooks/event-logger.sh (existing codebase,
# Phase 1) + Pattern 2 above. NOT a copy — event-logger.sh appends, this
# overwrites, hence the tmp+rename addition.
set -u
payload=$(cat)
[ -z "$payload" ] && exit 0

sid=$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)
[ -z "$sid" ] && exit 0

event=$(jq -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null)
[ -z "$event" ] && exit 0

state_dir="$HOME/.claude/monitor-state"
mkdir -p "$state_dir"

# derive `state` from $event + payload fields (see Event-to-State Mapping) …
# derive background_tasks_count = count of status=="running" entries …

line=$(jq -cn \
  --arg state "$state" \
  --arg ts "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
  --argjson ts_ms "$(($(date +%s%N)/1000000))" \
  --arg cwd "$(jq -r '.cwd // empty' <<<"$payload")" \
  --arg hostname "${HOSTNAME:-$(hostname 2>/dev/null || echo unknown)}" \
  --arg last_event "$event" \
  --argjson btc "$btc" \
  '{state: $state, ts: $ts, ts_ms: $ts_ms, cwd: $cwd, hostname: $hostname,
    last_event: $last_event, background_tasks_count: $btc}')
[ -z "$line" ] && exit 0

tmp="$state_dir/$sid.json.tmp.$$"
printf '%s\n' "$line" > "$tmp" && mv -f "$tmp" "$state_dir/$sid.json"
exit 0
```

### monitor.py — defensive state-file read

```python
# Source: pattern matches existing tail_last_line()/scan() defensive style
# (monitor.py, current codebase) — NOT verbatim, illustrates the shape only.
def _read_state_file(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj
```

### Divergence log entry shape (D-04 required fields)

```json
{
  "ts": "2026-07-29T13:02:41Z",
  "session_id": "84f529f7-...",
  "tick": 1785333761,
  "legacy_verdict": "WORKING",
  "state_file_verdict": "needs_input",
  "last_event": "PermissionRequest",
  "legacy_evidence": "tail=assistant/tool_use(Bash), working_lock=set"
}
```
Every field D-04 requires is present: session, tick, both verdicts, last hook
event, and enough legacy evidence (tail classification + which lock was
active) for a human to judge which side was right during review — without
requiring the reviewer to go re-read raw jsonl.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| SW-01's literal event list (`SessionStart, UserPromptSubmit, PostToolUse, Notification, Stop, SessionEnd`) | TEST-MATRIX-verdict event list (adds `PermissionRequest`, `PostToolBatch`, `PostToolUseFailure`, `SubagentStop`; demotes `Notification` to optional/secondary) | Superseded 2026-07-29 by D-08, based on the live campaign run in Phase 1 | Requirements text in REQUIREMENTS.md is stale — the planner must build against D-08's list, not SW-01's literal wording |
| ENG-06's original "badges intact via shell_tracker" | Unified ◉N badge fed by `background_tasks_count` (running-only), shell_tracker retired entirely | Superseded 2026-07-29 by D-09 (user decision, recorded in PROJECT.md) | shell_tracker.py becomes dead code after Phase 3's flip, not Phase 2's — Phase 2 only needs to capture the count correctly (Pitfall 2), not remove shell_tracker yet |
| Research-predicted "AUQ has no hook signal, needs auq-lock fallback" | AUQ emits `PreToolUse(tool_name=AskUserQuestion)` + `PermissionRequest` on open, `PostToolUse` on answer — hook-native | Live-confirmed 2026-07-29 on cc 2.1.220, overturning pre-live research (issues 28273/12605/15872, which applied to older CC versions) | `auq-lock.sh` is potentially superfluous in the new design, but SW-03 still requires it to keep functioning unchanged through Phase 2 — do not remove it this phase |

**Deprecated/outdated:** none introduced this phase — Phase 2 only extends existing mechanisms.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | `docker inspect --format '{{.State.Status}}'` returns exactly `created/running/paused/restarting/removing/exited/dead` as a stable enum across the Docker versions in the user's Windows+WSL2 setup | Don't Hand-Roll, Pitfall 6 | If the user's Docker version reports a different string, the paused/exited distinction (D-06, ENG-03) silently breaks; low likelihood (this is long-stable Docker API behavior) but not live-verified in this session (no `docker` binary available in this sandbox) — verify with one live `docker inspect` call during planning/execution against the actual Windows Docker install |
| A2 | Official docs' `background_tasks[].status` enum (`running`/`completed`/`failed`) is complete and current for the user's Claude Code version (2.1.220, per TEST-MATRIX) | Pitfall 2, Recommended State File Schema | If an undocumented status value exists (e.g. `pending`, `cancelled`), a strict `status == "running"` filter could undercount active work; mitigate by treating anything NOT in a known-terminal set (`completed`/`failed`) as "still counts," rather than an allowlist of exactly `"running"` |
| A3 | `mv` within the shared 9p bind mount is atomic in the same way local-filesystem `rename(2)` is | Pattern 2, Pitfall 1 | 9p is a network-ish filesystem protocol (used here for the WSL2↔container/host bridge); if its rename semantics differ from POSIX guarantees under concurrent access, tmp+rename could still leave a corrupt window. TEST-MATRIX case 15 verified concurrent *appends* survive without corruption on this mount, which is suggestive but not the same operation as rename — this should be spot-checked with a deliberate kill-during-write test as part of Phase 2 execution, mirroring case 20's intent |
| A4 | `SessionStart`'s `source=startup` with no prior `UserPromptSubmit` should map to an "idle" state distinct from "working" | Event-to-State Mapping | NOTES.md's original design says `SessionStart → idle`; this is consistent but was not explicitly re-confirmed against the D-08 superseding verdict — low risk since D-01 requires reproducing today's rendering exactly regardless of the internal `idle` label's name |

**If this table is empty:** N/A — see entries above; none are load-bearing enough to block planning, but A1 and A3 should get a cheap live spot-check early in Phase 2 execution since they concern the actual Windows/Docker environment this sandbox cannot reach.

## Open Questions

1. **Exact semantics of `monitor.py --state-files`**
   - What we know: ENG-01 requires it to derive state "as primary source"; D-01 requires zero UX change during Phase 2; the shadow comparison (ENG-02) needs BOTH engines computed every tick regardless of the flag.
   - What's unclear: Whether `--state-files` is (a) a manual/dev-only mode that fully replaces rendering with the shadow engine's output for hands-on verification of ENG-01 in isolation (recommended interpretation, used in this research's architecture diagram), or (b) meant to toggle which engine's output normally drives rendering even during ordinary shadow-mode operation.
   - Recommendation: Treat it as (a) — a standalone diagnostic entry point (same spirit as the existing `--test-notify` flag) for verifying `scan_state_files()` correctness directly, separate from the always-on shadow comparison that runs regardless of the flag. This keeps D-01 unconditionally true for normal daily use.

2. **Whether `event-logger.sh` (Phase 1) should be removed as part of this phase**
   - What we know: it's disposable, its removal is explicitly deferred to a "campagna ricertificazione" todo, out of Phase 2 scope per CONTEXT.md's Deferred Ideas.
   - What's unclear: whether leaving it installed alongside the new `state-writer.sh` (both firing on overlapping events) for the duration of shadow mode is acceptable, or whether it should be torn down first to avoid running two extra hook scripts per event during the live validation week.
   - Recommendation: Leave it running unless it demonstrably interferes (it shouldn't — both are independent, both exit 0) — removing it is a separate decision with its own deferred todo; don't fold it into this phase's scope silently (see Pitfall 4).

3. **Whether `PreToolUse` should be part of the state-writer's registered event set**
   - What we know: `working-lock.sh` already uses `PreToolUse` as a heartbeat re-arm; TEST-MATRIX's heartbeat discussion (case 3) centers on `PostToolUse`/`PostToolBatch`/`PostToolUseFailure`, not `PreToolUse`.
   - What's unclear: whether the state writer needs its own `PreToolUse` touch for the prompt→first-tool gap, or whether `UserPromptSubmit`'s initial `working` write is a sufficient bridge given the writer (unlike working-lock.sh) isn't racing a jsonl-tail heuristic — it's the source of truth, not a corrective patch.
   - Recommendation: Likely NOT needed — the state writer is authoritative (no jsonl race to bridge), so `UserPromptSubmit → working` alone should already be correct without a `PreToolUse` re-arm; include it only if execution testing shows a real gap.

## Environment Availability

| Dependency | Required By | Available (this sandbox) | Version | Fallback |
|------------|-------------|----------------------------|---------|----------|
| bash | state-writer.sh execution | ✓ | present | — |
| jq | state-writer.sh JSON handling | ✓ | 1.6 | — |
| flock | divergence-log size guard (if reused) | ✓ | present | — |
| Python 3.10+ | monitor.py engine additions | ✓ | 3.11.2 | — |
| docker CLI | `docker inspect`/`docker ps` cross-check (ENG-03) | ✗ (not installed in this sandbox) | — | None viable — this is genuinely Windows-host-only functionality; must be live-verified on the user's actual Windows+WSL2+Docker environment during execution, same constraint Phase 1 operated under for all live UAT |
| Docker Desktop / WSL2 (Windows host) | Entire production environment (containers bind-mounting `~/.claude`) | ✗ (not this sandbox) | — | Same as above — this sandbox can prepare/unit-test code, but live cross-checks against real container liveness require the user's assistance, exactly as Phase 1's runbook (`01-UAT.md`) already establishes as the working model for this project |

**Missing dependencies with no fallback:**
- `docker` CLI and the real Windows+WSL2+Docker environment — required for ENG-03's live cross-check and for validating A1/A3 above. This is not a blocker for writing/unit-testing the code (as Phase 1 already demonstrated: code, hooks, and `test_event_logger.py`/`test_monitor.py`-style tests can all be built and verified in this sandbox), but the shadow-mode validation week itself (D-03) is unavoidably user-assisted live UAT, matching Phase 1's precedent exactly.

**Missing dependencies with fallback:**
- None beyond the above — everything else needed for Phase 2's code changes is present in this environment.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|--------------------|
| V2 Authentication | No | No auth surface — local hooks, local file IPC |
| V3 Session Management | No (not a web-session concern) | N/A — "session" here means a Claude Code CLI session, not an ASVS web session |
| V4 Access Control | No new surface | `monitor-state/` inherits the same shared-mount access model as the existing `working-locks/`/`auq-locks/`/`projects/` directories — no new exposure introduced |
| V5 Input Validation | Yes | Hook stdin is untrusted-shaped JSON — always parse via `jq`, never string-interpolate a payload field into a shell command (matches `auq-lock.sh`/`working-lock.sh`/`event-logger.sh` convention). Additionally: validate `session_id` before using it to construct a file path (see threat table below) |
| V6 Cryptography | No | No crypto surface introduced |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|-----------------------|
| Path traversal via `session_id` used unsanitized in a file path (`monitor-state/$sid.json`) | Tampering | Reject/sanitize any `session_id` containing `/` or `..` before constructing the target path — even though Claude Code generates well-formed session ids, defensive validation at the point a payload-derived string becomes a filesystem path is standard practice, not optional because the source is "usually trusted" |
| Shell injection via unsanitized payload fields interpolated into a command string | Tampering | Never build shell commands from payload field values; only ever pass raw stdin through `jq` and use `jq`'s own output — established convention, continued unchanged from Phase 1/existing lock scripts |
| Hook exit-code/decision-control misuse silently altering Claude Code's permission or continuation flow | Tampering / Denial of Service | `state-writer.sh` must always `exit 0` and never emit `hookSpecificOutput`/`decision` JSON on stdout for any blocking-capable event it's registered on (`PermissionRequest`, `PostToolBatch`, `Stop`, `SubagentStop`) — see Pitfall 7 |
| Sensitive data retention in the divergence log (tool inputs, prompt text, file contents) | Information Disclosure | Apply the same field-level-extraction / no-content-capture discipline `event-logger.sh` already established (Phase 1 Pitfall 2) — divergence entries carry state verdicts and classification labels only, never raw tool_input/message bodies |
| Concurrent writers corrupting a shared file on the 9p mount | Tampering (data loss) | Per-session-id state files have exactly one writer (that session's own hooks) by construction, avoiding cross-session races; the shared divergence log (many writers) needs the same flock-short-wait pattern `event-logger.sh` already uses for `hook-events.log`'s size guard |

## Sources

### Primary (HIGH confidence)
- `.planning/TEST-MATRIX.md` — 21-case live verification campaign, cc 2.1.220, 2026-07-29 [VERIFIED: live campaign] — the ground truth for every event-to-state mapping and hook-silent-case claim in this document
- `.planning/phases/01-hook-coverage-verification/01-UAT.md` — runbook confirming exactly how each live case was triggered/observed [VERIFIED: live campaign]
- Codebase: `hooks/event-logger.sh`, `hooks/install.sh`, `hooks/working-lock.sh`, `hooks/auq-lock.sh`, `hooks/settings-snippet.json`, `hooks/hook-events.json`, `monitor.py`, `shell_tracker.py`, `test_monitor.py`, `test_event_logger.py` — read directly this session [VERIFIED: codebase]

### Secondary (MEDIUM confidence)
- code.claude.com/docs/en/hooks — official Claude Code hooks reference, fetched live this session for `Stop`/`SessionStart`/`SessionEnd`/`PermissionRequest`/`PostToolUse`/`PostToolUseFailure`/`PostToolBatch`/`Notification`/`SubagentStop` payload schemas and exit-code/decision-control semantics [CITED: code.claude.com/docs/en/hooks] — used to cross-check and extend the TEST-MATRIX live data, notably surfacing the `background_tasks[].status` field (Pitfall 2) that the live campaign's diagnostic logger did not capture at that granularity

### Tertiary (LOW confidence)
- None used — Phase 1's prior research already established (and this session's docs fetch reconfirmed) that community/blog sources on Claude Code hooks are inconsistent enough that only official docs + live verification are treated as authoritative for this project

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, entirely existing/verified tools
- Architecture: HIGH — directly extends a working, tested pattern (event-logger.sh/install.sh) with one well-scoped new primitive (atomic tmp+rename)
- Pitfalls: HIGH for hook-behavior pitfalls (live-verified via TEST-MATRIX + official docs cross-check); MEDIUM for the two environment-dependent assumptions (A1, A3) that need a live spot-check on the user's actual Windows/Docker setup, which this sandbox cannot reach

**Research date:** 2026-07-29
**Valid until:** Tied to the Claude Code version this was verified against (cc 2.1.220) — re-verify against TEST-MATRIX before treating any hook-behavior claim as current if the user's Claude Code version has since changed (same caveat Phase 1's RESEARCH.md already carries forward).
