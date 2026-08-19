# Phase 3: Flip to Default & Cleanup - Research

**Researched:** 2026-08-06
**Domain:** Python/Bash desktop monitor internals — deleting a dual-engine (jsonl+hooks) shadow architecture down to a single hook-driven engine with three named legacy fallbacks
**Confidence:** HIGH (codebase-grounded — every architectural claim below was verified by reading the actual source this session, not inferred from the phase description)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** FLIP APPROVED (Section E review GREEN, user + Claude 2026-08-06). The state-file engine is the default and only primary engine; dead legacy jsonl-parsing paths are removed from `monitor.py`. Expectation from NOTES.md: the file shrinks substantially. — **Reversibility:** costly — undo means reverting large deletions across `monitor.py`, `shell_tracker.py`, tests and hooks; recoverable only via git history, and the README/install docs would describe an architecture that no longer exists.
- **D-02:** Exactly THREE jsonl/legacy consumers survive the flip (the hybrid model) — no other legacy path may remain:
  - **(a) Esc-interrupt recovery** — targeted legacy signal so an interrupted turn recovers in ~90s instead of the 600s heartbeat window (UAT C1: legacy was MORE timely; a pure hook engine would regress interrupt recovery).
  - **(b) Hook-silence pins** — during long-running Monitor tool / subagents / slow Bash (divergence class 6, 9 events/week), active Monitor/agent evidence + working-lock evidence keeps the session pinned WORKING instead of degrading to WAITING at 600s.
  - **(c) `legacy_origin` bridge** — sessions with no state file (hookless containers per ENG-05, or state file already removed) stay visible via per-session legacy parsing. **User-confirmed 2026-08-06** as the third surviving fallback (resolves the conflict with the stricter "only Esc + hook-silence" wording in the handoff). Replacement with an explicit "no data" UI stays deferred to V2-02.
- **D-03:** Bg shells are badge-only, NEVER a state verdict: `background_tasks_count` feeds the single unified ◉N badge and nothing else (TEST-MATRIX §4 revision, quick task 260731-an2 rev.2 — the earlier 15-min-cap idea is dead). The ⚙/◉ badge pair and `shell_tracker.py` are deleted; jsonl badge parsing ends (Phase 2 D-09). At the flip, divergence class 3 (37 events) disappears by construction.
- **D-04:** `working-lock` hooks STAY — they are named evidence for the hook-silence pins (D-02b) and drive the ~90s Esc recovery via the stale-lock guard (UAT C1). `auq-lock` RETIRES: AUQ is hook-native on cc 2.1.220 (`PreToolUse`/`PermissionRequest` → `needs_input` via the state writer; TEST-MATRIX case 6, UAT section F showed both engines agree). Retirement ships with an UAT gate: confirm `needs_input` parity live on the Windows machine before `install.sh` stops installing it. — **Reversibility:** reversible — re-adding a hook entry restores it.
- **D-05:** Paused/kept sessions become VISIBLE in the overlay at the flip (folded todo 2026-07-30; UAT C4: legacy dropped paused containers, shadow keeps them via `hostname_to_label`). 82 events/week of class 1 divergences are legacy-wrong. Rendering detail (normal vs dimmed row) is Claude's discretion; no new state colors, no new notification types.
- **D-06:** A session the state engine KNOWS ended (SessionEnd removed its state file) must NOT be resurrected by the D-02c bridge while its ghost jsonl row survives (folded todo 2026-07-30 "ghost jsonl rows survive container kill via dir-fallback"). Mechanism (SessionEnd tombstone or equivalent) is Claude's discretion; the outcome is locked: clean-ended sessions stay gone.
- **D-07:** The flip must preserve, with equivalent post-flip tests: (1) aliases keyed by container identity — survive `/clear` (quick 260730-kgw); test Goal6d is REWRITTEN on a state-file fixture, not dropped; (2) the multi-monitor fix; (3) the deliberate 60s threshold. These behaviors are load-bearing daily fixes — regressing any of them fails FLIP-02's "equivalent coverage" bar.
- **D-08:** Shadow-mode machinery is removed from the code: `diff_verdicts`, `filter_divergence_events`, `write_divergences`, divergence logging, and the shadow double-compute in the tick loop. `select_render_sessions()` remains the seam but now serves only the state engine + fallbacks. On the Windows machine (execution time, not from the devbox): delete `~/.claude/monitor-divergence.log`; sweep the orphan tmp file (`c1eb55f7-….json.tmp.13252`) and add a stale-`.tmp` sweep to the engine so atomic-write leftovers can't accumulate. `~/.claude/monitor-state/` is NOT deleted — post-flip it is the primary data source (02-UAT's `rm -rf` line was shadow-era rollback guidance, superseded by the flip). Also: remove the dead `project_name()` helper (monitor.py:282 — verify it is still dead at execution time).
- **D-09:** Shadow mode keeps RUNNING on the Windows machine until Phase 3 execution flips it there. Nothing is torn down from the devbox. The raw divergence log stays machine-local and uncommitted.
- **D-10:** `hooks/install.sh`, `hooks/settings-snippet.json` and README document the hook-driven architecture well enough to onboard a new container/user. Lightweight promotion folded from the recertification todo: TEST-MATRIX.md + the verification runbook get promoted out of `.planning/` into repo docs as the per-version recertification reference. The full campaign machinery (per-version fixtures, smoke checklist automation) stays deferred — planner may veto the promotion split at plan review if it balloons.
- **D-11:** Remote devbox state + mobile notifications are OUT OF SCOPE (separate milestone after v1.0, user decision 2026-08-06). Phase 3 must not close doors: the `hostname` field stays in state files; state files remain per-machine `~/.claude/monitor-state/*.json` so a future aggregator only needs to transport them. No aggregator/transport work in this phase.
- **D-12:** Live UAT of the flip happens on the WINDOWS machine (where shadow mode runs and real sessions live). Plans must structure verification accordingly: code + unit tests run anywhere; the flip's live validation and machine-side teardown are user-assisted UAT on Windows, mirroring the 01-UAT/02-UAT runbook convention (date, CC version, outcome).

### Claude's Discretion

- Rendering details for paused/kept sessions (D-05) within "no new colors/notifications".
- Ghost-suppression mechanism for D-06 (tombstone vs alternative).
- Fate of the `--state-files` flag once it is the default (no-op, removed, or diagnostic alias) — there is no `--legacy` escape hatch, since the legacy engine is deleted (rollback = git revert, D-01).
- Internal refactor shape of `monitor.py` after the deletions, as long as observable behavior matches the matrix and preserved fixes.
- Exact split of README vs docs/ content for FLIP-03.

### Deferred Ideas (OUT OF SCOPE)

- **Remote devbox aggregation + mobile notifications** — separate milestone after v1.0 (D-11). Only door-keeping in this phase.
- **V2-02 explicit "no data" UI for hookless sessions** — the D-02c bridge is the v1 answer; hard startup refusal re-evaluated then.
- **Recertification campaign machinery** (per-version fixtures, smoke checklist automation) — only the matrix/runbook doc promotion lands now (D-10).
- **V2-01** (rebuild badges from PostToolUse payloads) — superseded in substance by the unified ◉N badge; formally still v2.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FLIP-01 | After shadow validation, the state-file engine becomes the default and dead legacy parsing paths are removed | §Architecture Patterns (call graph), §Common Pitfalls #1 ("scan() is not fully legacy-only"), §Runtime State Inventory |
| FLIP-02 | `test_monitor.py` covers the state-file engine (equivalent coverage; state-file fixtures replace jsonl fixtures where legacy code was removed) | §Architecture Patterns (test inventory), §Common Pitfalls #6/#7 |
| FLIP-03 | `hooks/install.sh`, the settings snippet, and README document the new architecture and hook requirements | §Architecture Patterns (hooks/ changes), §Code Examples (install.sh sweep pattern) |
</phase_requirements>

## Summary

This phase is a deletion and re-grounding exercise, not new-feature work: `monitor.py` (2437 lines), `test_monitor.py` (2199 lines), `shell_tracker.py` (247 lines), and `hooks/install.sh` all need surgical edits, not a rewrite. The single most important correction this research makes to the phase description's framing is: **`scan()` (the legacy jsonl engine, monitor.py:922-1080) does NOT get deleted.** It survives, modified, as the engine backing all three hybrid fallbacks — D-02c's hookless bridge needs it verbatim (scan_state_files() already calls it internally, monitor.py:701-702), and D-02a's Esc-interrupt recovery is best implemented by reusing data `scan()` *already computes every tick* (its `working_locked` field and per-session jsonl `mtime`), not by writing a second parallel jsonl reader. What *does* get deleted is `shell_tracker.py` in full (D-03) and its four call sites inside `scan()` (monitor.py:27-32, 952-955, contributing to the WORKING-decision OR-chain at 1031-1033 and the `bg`/`monitors`/`agents` row fields at 1062-1064), plus the shadow-diff machinery (`diff_verdicts`, `filter_divergence_events`, `write_divergences`, monitor.py:717-882) and the shadow double-compute in `MonitorApp.refresh()` (monitor.py:2110-2126).

A second load-bearing finding: D-02b's "active Monitor/agent evidence" for the hook-silence pin is currently produced ONLY by `shell_tracker.count_active_monitors`/`count_active_agents` — the exact module D-03 deletes wholesale. There is no existing hook-native replacement signal that distinguishes "a Monitor tool is running" from "any tool is running." The closest hook-native substitute is the working-lock file itself (already tool-agnostic — `PreToolUse` re-arms it for every tool, not just Bash, per `hooks/settings-snippet.json`'s unmatched `PreToolUse` entry) plus its much longer `WORKING_LOCK_MAX_AGE_SEC` (3600s) ceiling, which already covers the observed divergence-class-6 episode lengths (max ~50 min = 3000s < 3600s). This is flagged as an open tension between two locked decisions (D-02b vs D-03) for the planner to resolve explicitly, not silently drop.

Test-file research confirms the phase description's own file/class inventory is directionally right but incomplete: of `test_monitor.py`'s ~30 test classes, only 3 (`Goal2h_BgShellBadgeOnly`, `Goal2i_ManualBgShellDetected`, and the shell_tracker-touching parts of `Goal2_ClaudeActivelyWorking`) are shell_tracker-only and delete outright; 3 more (`Goal14_DivergenceRecords`, `Goal15_DivergenceEpisodes`, `Goal16_DivergenceLogGuard`) are shadow-machinery-only and delete outright; the rest — including `Goal1e_AuqLockOverride`, `Goal2g_WorkingLockOverride`, `Goal3_Robustness`, `Goal4_CertainlyWorkingMatrix`, `Goal13_HooklessFallback`, `Goal6e_AliasKeyParityAcrossEngines` — exercise the surviving `scan()`/bridge/fallback code and must stay (most already use state-file fixtures where they test `scan_state_files()`). `Goal6d_AliasKeyedByContainer` is the one class D-07 explicitly calls out for rewrite: its container-alias-survives-`/clear` assertions currently run only against `scan()`'s jsonl fixtures; the flip needs the equivalent assertion run against `scan_state_files()`'s state-file fixtures (largely already covered by `Goal6e`, but the specific "sessionId rotation, same hostname, same alias_key" scenario is not yet duplicated there and is the concrete gap to close).

**Primary recommendation:** Do not treat this as "delete `scan()`, keep `scan_state_files()`." Treat it as "delete `shell_tracker.py` and the shadow-diff machinery; keep `scan()` as a permanently-running, always-on sibling function whose output now feeds three specific things instead of one: the D-02c hookless bridge (unchanged), a new jsonl-advance signal for the D-02a Esc-recovery window, and (optionally, pending the D-02b/D-03 tension above) a `working_locked`-based hook-silence pin." Budget the plan's waves accordingly: Wave 1 = shell_tracker deletion + scan() trim (mechanical, testable in isolation), Wave 2 = shadow-machinery deletion + tick-loop simplification, Wave 3 = the two NEW fallback behaviors (Esc-recovery jsonl-advance, hook-silence pin) which are genuinely new logic, not deletion, Wave 4 = hooks/install.sh + docs (FLIP-03), Wave 5 = test rewrite pass (FLIP-02) run last so it locks in whatever the waves above actually produced.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Session state derivation (working/waiting/needs_input) | Hook Scripts (`state-writer.sh`) | Monitor Engine (`scan_state_files()`) | Hooks write the verdict at the source event; the engine only reads and applies staleness/fallback logic — it never re-derives state from content. |
| Esc-interrupt recovery (D-02a) | Monitor Engine (`scan_state_files()`, new logic) | Hook Scripts (`working-lock.sh`) evidence, `scan()`'s jsonl mtime | Hooks are silent on Esc by design (no event fires); the engine must synthesize recovery from working-lock + jsonl-advance data `scan()` already computes. |
| Hook-silence pin (D-02b) | Monitor Engine (`scan_state_files()`, new logic) | Hook Scripts (`working-lock.sh`) evidence | Same shape as Esc-recovery: the engine reads lock evidence to avoid a false WAITING during a long silent tool call. |
| Hookless bridge (D-02c) | Monitor Engine (`scan()`, unchanged) | — | `scan()` IS the fallback for a container with no hooks installed; no new code, just continued reliance on the existing function. |
| Bg/Monitor/Agent badge (◉N) | Hook Scripts (`state-writer.sh`'s `background_tasks_count`) | Monitor Engine (row rendering only) | Post-flip this is a pure read of a hook-captured count; no jsonl regex parsing anywhere in the badge path. |
| Container/session label mapping, aliasing | Monitor Engine (`scan_containers()`, `derive_alias_key()`) | Docker CLI (external boundary) | Unaffected by the flip — this machinery is engine-agnostic and shared by both `scan()` and `scan_state_files()` already. |
| Staleness / container-liveness cross-check | Monitor Engine (`scan_state_files()`) | Docker CLI (`docker inspect`, external boundary) | Unaffected by the flip — already implemented for the state engine in Phase 2. |
| Overlay rendering, notifications, toasts, Telegram | Monitor Engine / UI (`MonitorApp`, Tk) | — | Consumes whatever `select_render_sessions()` returns; post-flip that is unconditionally the state engine's output, no branch on a flag needed for rendering logic itself. |
| Hook installation / teardown | Hook Scripts (`hooks/install.sh`) | — | `--remove-*` sweep pattern is the established idiom; auq-lock retirement reuses it (D-04). |
| Docs (README, TEST-MATRIX promotion) | Docs (`README.md`, promoted `docs/`) | — | FLIP-03; no runtime code. |

## Standard Stack

No new dependencies. The project's own constraint is explicit and load-bearing: **Python 3.10+ stdlib only, monitor-side; bash + jq, hook-side** [VERIFIED: .planning/phases/03-flip-to-default-cleanup/03-CONTEXT.md:102 — "Zero-dependency constraint: Python 3.10+ stdlib only monitor-side; bash+jq hook-side."]. Nothing in this phase's scope (deletion, test rewrite, doc rewrite) requires adding a package. `python3 --version` in this environment reports 3.11.2, `jq --version` reports jq-1.6 [VERIFIED: tool output this session].

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`json`, `pathlib`, `unittest`, `subprocess`, `tkinter`) | 3.10+ (3.11.2 in this env) | Everything — engine, tests, UI | Project's own zero-dependency constraint; no exceptions carved out for this phase |
| bash + jq | jq 1.6 in this env | Hook scripts | Established pattern in every existing hook (`state-writer.sh`, `working-lock.sh`, `auq-lock.sh`, `event-logger.sh`) |

### Supporting / Alternatives Considered
Not applicable — this phase adds no new capability that would need a library choice; it deletes code.

**Installation:** none.

## Package Legitimacy Audit

Not applicable. This phase installs no external packages (Python stdlib + bash/jq only, per the zero-dependency constraint quoted above). No `npm view`/`pip index versions`/`cargo search` verification is required.

## Architecture Patterns

### System Architecture Diagram — post-flip data flow

```
Claude Code process (per session, possibly inside a Docker container)
        │  emits lifecycle events (hooks)
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ Hook scripts (bash+jq) — ~/.claude/hooks/, shared bind-mount        │
│                                                                       │
│  state-writer.sh ──writes──▶ ~/.claude/monitor-state/<sid>.json     │
│    (10 events: SessionStart, UserPromptSubmit, PostToolUse,         │
│     PostToolUseFailure, PostToolBatch, PermissionRequest,           │
│     Notification, Stop, SubagentStop, SessionEnd)                   │
│                                                                       │
│  working-lock.sh ──touches/removes──▶ ~/.claude/working-locks/<sid> │
│    (UserPromptSubmit/PreToolUse=set, Stop=clear) — STAYS (D-04)     │
│                                                                       │
│  auq-lock.sh ─ ─ ─ RETIRES (D-04, UAT-gated) ─ ─▶ ~/.claude/auq-locks/│
│                                                                       │
│  event-logger.sh (Phase 1 diagnostic, unaffected by this phase)     │
└───────────────────────────────────────────────────────────────────┘
        │  files on shared 9p mount, readable from the Windows host
        ▼
┌───────────────────────────────────────────────────────────────────┐
│ monitor.py — MonitorApp.refresh() tick loop (every REFRESH_MS=5000) │
│                                                                       │
│  scan_containers() ──▶ container_info (hostname_to_label/status,    │
│                          sessionid_to_hostname), label_map            │
│                                                                       │
│  scan() [ALWAYS RUNS, not deleted] ──▶ legacy_sessions list          │
│    still parses ~/.claude/projects/*.jsonl — now feeds THREE things: │
│      1. D-02c hookless bridge (unchanged use)                        │
│      2. D-02a Esc-recovery jsonl-advance signal (NEW use)            │
│      3. (tension, see Pitfall #2) D-02b hook-silence pin evidence    │
│                                                                       │
│  scan_state_files(legacy_sessions=...) [PRIMARY ENGINE]              │
│    reads ~/.claude/monitor-state/*.json, applies staleness/pause     │
│    guard, folds in legacy_sessions for sessions with no state file   │
│    ──▶ render_sessions (single list, no more shadow diff)            │
│                                                                       │
│  select_render_sessions() [seam kept or simplified, discretion]      │
│    ──▶ MonitorApp rendering / notifications / Telegram               │
└───────────────────────────────────────────────────────────────────┘
```

The pre-flip diagram (for contrast, what's being torn out): `refresh()` computed `sessions = scan(...)` AND `shadow_sessions = scan_state_files(..., legacy_sessions=sessions)`, ran `diff_verdicts(sessions, shadow_sessions, tick)` → `filter_divergence_events(...)` → `write_divergences(...)` every tick, and `select_render_sessions(sessions, shadow_sessions, self.state_files_mode)` picked `sessions` (legacy) unless `--state-files` was passed [VERIFIED: monitor.py:2102-2131 — the exact `refresh()` body read this session]. Post-flip, the diff/filter/write calls disappear and the seam either always returns the state-engine output or is removed entirely (discretion).

### Recommended Project Structure

No directory changes. File-level scope:

```
monitor.py              # shrinks: shell_tracker import/calls removed, shadow-diff
                         # functions removed, project_name() removed, tick loop
                         # simplified; scan() KEPT (trimmed), scan_state_files()
                         # gains the two new fallback behaviors
shell_tracker.py         # DELETED entirely (D-03)
hooks/install.sh         # auq-lock stops being installed by default (D-04);
                         # gains a --remove-auq-lock teardown mode mirroring
                         # the existing --remove-state-writer pattern
hooks/settings-snippet.json  # auq-lock entries removed or moved behind an
                         # opt-in path, per the install.sh change above
test_monitor.py          # Goal2h/2i deleted, Goal14/15/16 deleted, Goal6d
                         # rewritten on state-file fixtures (D-07), everything
                         # else audited but structurally intact
README.md                # Setup step 4 rewritten from "recommended" to
                         # reflecting hooks as the PRIMARY state source
docs/ (new or existing)  # TEST-MATRIX.md + runbook promoted per D-10
```

### Pattern 1: `scan()` survives as a permanent sibling, not a legacy relic

**What:** `scan_state_files()` already has an internal escape hatch: when called with `legacy_sessions=None` it runs `scan(label_map, sessionid_to_label, container_info=container_info)` itself [VERIFIED: monitor.py:701-702 — `if legacy_sessions is None:\n        legacy_sessions = scan(label_map, sessionid_to_label, container_info=container_info)`]. `MonitorApp.refresh()` never actually relies on that internal call in the normal (non-diagnostic) path — it always computes `sessions = scan(...)` itself first and passes it in as `legacy_sessions` [VERIFIED: monitor.py:2103-2119].

**When to use:** Keep this exact shape post-flip. `refresh()` should keep calling `scan()` every tick and pass its output into `scan_state_files(..., legacy_sessions=sessions)` — not because the legacy verdict is rendered anymore (it isn't), but because three separate downstream needs consume pieces of that same `sessions` list: the D-02c bridge (whole entries, keyed by session_id absent from the state-file set), the D-02a jsonl-mtime-advance signal (the `mtime` field on entries present in both lists), and potentially the D-02b working-lock evidence (the `working_locked` field, already computed per-entry). Computing `scan()` once and reading three fields off its output is cheaper and less error-prone than writing new, parallel jsonl-reading code for each fallback.

**Example (today's shape, keep this call structure):**
```python
# Source: monitor.py:2102-2119 (MonitorApp.refresh(), read this session)
sessions = scan(self._cached_label_map, self._sessionid_to_label,
                 container_info=self._cached_container_info,
                 hostname_to_name=self._cached_hostname_to_name)
...
shadow_sessions = scan_state_files(
    self._cached_label_map, self._sessionid_to_label,
    container_info=self._cached_container_info,
    legacy_sessions=sessions,
)
```
Post-flip, rename `shadow_sessions` to something like `render_sessions` and delete only the `diff_verdicts`/`filter_divergence_events`/`write_divergences` calls that currently sit between these two blocks (monitor.py:2122-2126).

### Pattern 2: The stale-lock guard is the reusable primitive for D-02a

**What:** Legacy's `working_locked` computation already implements exactly the "jsonl advance releases the lock early" behavior D-02a needs — it is not something to invent, it is something to read off an already-computed field.

**Example:**
```python
# Source: monitor.py:1014-1022 (scan(), read this session) — the exact
# stale-lock-guard mechanism UAT C1 found makes legacy recover at ~90s
working_locked = False
if session_id:
    try:
        wlock_mtime = (WORKING_LOCK_DIR / session_id).stat().st_mtime
        working_locked = (now - wlock_mtime) < WORKING_LOCK_MAX_AGE_SEC
        if working_locked and latest_mtime > wlock_mtime + 5:
            working_locked = False
    except OSError:
        pass
```
`latest_mtime` here is the jsonl's own mtime (`scan()`'s per-candidate `latest_mtime`, monitor.py:949). This is precisely "working-lock stale-lock guard + jsonl advance" from the phase description's own framing of fallback (a). **Recommendation (my synthesis, [ASSUMED] — not literally specified in CONTEXT.md, which locks the outcome not the mechanism):** in `scan_state_files()`'s staleness-recovery block, when a WORKING state-file record is past its heartbeat window, look up the matching entry (by `session_id`/`key`) in `legacy_sessions` and treat `legacy_entry.get("working_locked") is False` as an *additional* early-recovery trigger (alongside the existing `container_status != "paused"` guard at monitor.py:674). This produces the "recovers faster than the flat 600s window when the jsonl itself shows the interrupt" behavior without re-implementing lock-mtime-vs-jsonl-mtime comparison a second time.

### Pattern 3: `install.sh`'s idempotent sweep pattern, reused for auq-lock retirement

**What:** The installer already has two independent teardown modes with the exact shape D-04's auq-lock retirement needs.

**Example:**
```bash
# Source: hooks/install.sh:72-86 (read this session) — the pattern to clone
# for a new --remove-auq-lock mode
if [ "$mode" = "--remove-state-writer" ]; then
  if [ ! -f "$SETTINGS" ]; then
    echo "nothing to do: $SETTINGS does not exist"
    exit 0
  fi
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  jq '
    def has_state_writer: [.hooks[]?.command] | any(. // "" | test("state-writer\\.sh"));
    .hooks = ((.hooks // {}) | with_entries(.value |= map(select(has_state_writer | not))))
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "removed: state-writer.sh entries from $SETTINGS (backup at $SETTINGS.bak.*)"
  exit 0
fi
```
For the default install path, the merge block that currently installs auq-lock unconditionally needs its `install -m 0755 "$HERE/auq-lock.sh" ...` line and its jq merge entries for `PreToolUse`/`PostToolUse`/`Notification`/`Stop` (matcher `AskUserQuestion`, or the auq-lock command test) removed from the default path [VERIFIED: hooks/install.sh:89-90, 108-121 — the exact `install`/`jq --slurpfile snip` block that installs and registers auq-lock.sh today]. A `--remove-auq-lock` mode cloned from the block above gives existing installs (that already have auq-lock registered from a prior `install.sh` run) a clean way to retire it without hand-editing `settings.json`.

### Anti-Patterns to Avoid

- **Writing a brand-new jsonl parser for the Esc-recovery fallback:** `scan()` already computes everything needed (session_id, latest_mtime, working_locked) every tick. A second, parallel "targeted jsonl peek" function would duplicate `tail_last_line`/`_extract_session_id` logic that already exists and is already tested (Goal3_Robustness, Goal2b_ContainerIdentification).
- **Assuming jsonl filename equals session_id:** it does not, structurally — `scan()` always derives `session_id` by reading and parsing the tail line (`_extract_session_id`, monitor.py:443-451), never from the filename. Any new code that needs "this session's jsonl mtime" must go through the same tail-read path (or through `scan()`'s already-computed output), not a filename-based shortcut.
- **Silently keeping `shell_tracker.py`'s Monitor/Agent counting "just for the pin":** this directly contradicts D-03's "shell_tracker.py deleted" and reintroduces jsonl regex parsing NOTES.md's refactor goal explicitly tries to eliminate. See Pitfall #2 for the recommended resolution.
- **Deleting `auq_locked` from `scan()` in the same pass as `shell_tracker`:** these are unrelated. `auq_locked` reads `AUQ_LOCK_DIR`, a different mechanism than shell_tracker's jsonl regex scanning, and its removal is gated by D-04's UAT confirmation, not bundled with the mechanical shell_tracker deletion.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting Esc-interrupt / stale-jsonl-advance | A second jsonl tail reader | `scan()`'s already-computed `working_locked` + `mtime` fields (Pattern 2 above) | Avoids duplicating `tail_last_line`/`_extract_session_id`, already tested and correct |
| Teardown of a hook's settings.json entries | Hand-written jq from scratch | Clone the `--remove-state-writer` block (hooks/install.sh:72-86) | Idempotent, JSON-validated (`python3 -c "import json; json.load(...)"`), backs up before mutating — established, tested pattern |
| Atomic state-file writes | A new tmp+rename implementation | The pattern `state-writer.sh` already uses (tmp in same dir, `mv -f`) — no monitor.py change needed, the stale-`.tmp` sweep (D-08) is a `glob` + age-check addition to `scan_state_files()`'s existing prune loop | `state-writer.sh` already guarantees this; the sweep only needs to also glob `*.json.tmp.*` next to the existing `*.json` prune loop (monitor.py:637-649) |

**Key insight:** almost nothing in this phase is genuinely new engineering — it is either subtraction (shell_tracker, shadow machinery, dead code) or recombination of code that already exists and is already tested (`scan()`'s `working_locked`/`mtime`, `install.sh`'s sweep pattern). Treat any task that proposes writing more than ~20 new lines of monitor.py logic as a signal to re-check whether an existing function already computes the needed value.

## Runtime State Inventory

This phase deletes/retires live, already-installed runtime state on the user's real Windows machine — the canonical question applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `~/.claude/monitor-state/*.json` (state files) — **NOT deleted**, becomes the primary data source post-flip (D-08 explicitly reverses 02-UAT's teardown guidance). `~/.claude/monitor-divergence.log` (343 records, 137KB, machine-local, uncommitted) — **deleted** at execution time on Windows (D-08, D-09). One known orphan tmp file `c1eb55f7-….json.tmp.13252` — **swept** by the new stale-`.tmp` cleanup, not a one-off manual delete. | Code edit (add sweep logic) + one-time manual delete of the divergence log, both happen at Windows execution time per D-12, not from this planning/code environment. |
| Live service config | `~/.claude/settings.json` on the Windows machine already has `auq-lock.sh` registered (4 entries, per 02-UAT.md Setup verification: "working-lock 3, auq-lock 4") [VERIFIED: .planning/phases/02-state-writer-shadow-mode/02-UAT.md:414 — "PASS — state-writer 10, working-lock 3, auq-lock 4, event-logger intact"]. Re-running `install.sh` after the flip will not remove those 4 entries by itself unless a `--remove-auq-lock` mode is added and explicitly invoked. | Code change (new install.sh mode) + a manual invocation step on Windows, UAT-gated per D-04 — this is NOT automatic on a plain re-run of `install.sh`. |
| OS-registered state | None found — this tool has no OS-level task/service registration (no Task Scheduler, no pm2, no systemd). `monitor.bat`/`monitor-debug.bat` are plain launchers, not registered services. | None. |
| Secrets/env vars | None affected — `.env` (Telegram credentials) is untouched by this phase; no key renames. | None. |
| Build artifacts | None — pure-Python stdlib project, no compiled artifacts, no packaging step in scope (README's "Development" section only runs `python3 -m unittest`). | None. |

**Nothing found in category:** OS-registered state, secrets/env vars, build artifacts — verified by reading `README.md`, `monitor.bat`/`monitor-debug.bat` file names (no service-registration content found), and the `.env`-loading code path (`load_env()`, monitor.py:149-164, unrelated to this phase's scope).

## Common Pitfalls

### Pitfall 1: Treating `scan()` as delete-target instead of trim-target
**What goes wrong:** A plan task titled "delete legacy jsonl parsing" that removes `scan()` wholesale breaks the D-02c hookless bridge (which literally calls `scan()` internally as its fallback source, monitor.py:701-702) and removes the data source Pattern 2 above needs for D-02a.
**Why it happens:** The phase description's own framing ("Legacy-only code to delete or shrink to targeted fallbacks: `tail_last_line`, `parse_last_action`, `user_tail_kind`, `is_certainly_working`, `scan()`") groups `scan()` with pure-legacy helpers, but `scan()` calls all four of those helpers internally and none of them can be removed while `scan()` survives.
**How to avoid:** Frame the deletion target precisely as: shell_tracker import + 4 call sites inside `scan()`, plus the 3 shadow-diff functions, plus `project_name()`. `scan()` itself, `tail_last_line`, `parse_last_action`, `user_tail_kind`, `is_certainly_working` all survive (trimmed of shell_tracker references only).
**Warning signs:** Any task whose acceptance criterion is "scan() no longer exists" or "`test_monitor.py` no longer imports `scan`" — both would break `Goal13_HooklessFallback` and `Goal6e_AliasKeyParityAcrossEngines`, which explicitly `from monitor import ... scan` and call it directly (test_monitor.py:1627, 1637, 1648, 1664, 1724, 1736 — verified this session).

### Pitfall 2: D-02b names a signal that D-03 deletes
**What goes wrong:** D-02b locks "active Monitor/agent evidence + working-lock evidence" as what must keep a session pinned WORKING through a long hook-silent tool call. The ONLY existing source of "Monitor/agent evidence" specifically (as opposed to "any tool in flight") is `shell_tracker.count_active_monitors`/`count_active_agents`, which D-03 unconditionally deletes.
**Why it happens:** D-02b and D-03 were both written from the same divergence-review data (class 6 vs class 3) but describe different, only partially-overlapping mechanisms; the CONTEXT.md consolidation did not explicitly reconcile them.
**How to avoid:** Recommend implementing the hook-silence pin using working-lock evidence ALONE (a fresh `~/.claude/working-locks/<sid>` file, checked against `WORKING_LOCK_MAX_AGE_SEC` = 3600s rather than the shorter `STATE_HEARTBEAT_STALE_SEC` = 600s window) as the sole pin mechanism. This is hook-native (no jsonl regex parsing revived), and empirically sufficient: the worst observed class-6 episode was ~50 min = 3000s [VERIFIED: .planning/phases/02-state-writer-shadow-mode/02-DIVERGENCE-REVIEW.md:19 — "Episode duration: median 3 ticks (~15s); p90 75 ticks; max 595 ticks (~50 min, class 6)."], comfortably under the 3600s working-lock ceiling. Flag this substitution explicitly to the user/discuss-phase rather than silently either (a) reviving shell_tracker's monitor/agent counters (contradicts D-03) or (b) dropping the pin behavior (contradicts D-02b, regresses class 6 to the old false-WAITING problem).
**Warning signs:** A plan task that re-adds any import from `shell_tracker` after it's been deleted, or a plan that has no task at all addressing D-02b's pin (silently regressing class 6).

### Pitfall 3: Auq-lock's "reversible" language inviting an incomplete removal
**What goes wrong:** D-04 says auq-lock retirement is "reversible — re-adding a hook entry restores it," which could be misread as "no urgency, leave the code alone." But `auq_locked` in `scan()` (monitor.py:993-1006, 1029-1030, 1074) still actively reads `AUQ_LOCK_DIR` every tick even after the hook stops being installed — it just silently stops finding lock files. That's harmless but leaves dead-weight code contradicting the "file shrinks by half" expectation, and more importantly leaves ambiguity about whether `install.sh`'s DEFAULT path should still install auq-lock during a transition window.
**Why it happens:** The UAT gate ("confirm `needs_input` parity live on the Windows machine before `install.sh` stops installing it") sits awkwardly against D-12's constraint that live UAT can only happen on Windows, later — this environment cannot complete that gate.
**How to avoid:** Ship BOTH halves in Phase 3's code: (1) `install.sh`'s default path stops installing/registering auq-lock.sh, (2) a `--remove-auq-lock` teardown mode is added for existing installs, (3) a `03-UAT.md` (mirroring `01-UAT.md`/`02-UAT.md`'s runbook convention per D-12) is created with an explicit needs_input-parity checkpoint the user completes on Windows before actually invoking `--remove-auq-lock` there. Do NOT leave `install.sh` still installing auq-lock by default "until UAT passes" — that contradicts D-01's expectation that the flip actually ships, and D-12 already establishes that code ships now while live validation happens after, on Windows.
**Warning signs:** A plan that either (a) leaves `install.sh` installing auq-lock unconditionally with no removal path at all, or (b) deletes `auq_locked` from `scan()` in the same task as the shell_tracker removal (bundling two independently-gated decisions).

### Pitfall 4: `working-lock.sh`/`auq-lock.sh` lack the path-traversal guard `state-writer.sh` has
**What goes wrong:** `state-writer.sh` validates `session_id` against `^[A-Za-z0-9._-]+$` before using it in a filesystem path (`case "$sid" in *[!A-Za-z0-9._-]*) exit 0 ;; esac`) [VERIFIED: hooks/state-writer.sh:82-88, quoted verbatim]. `working-lock.sh` and `auq-lock.sh` do NOT have this guard — they go straight from `sid=$(cat | jq -r '.session_id // empty' ...)` to `touch "$lock_dir/$sid"` / `rm -f "$lock_dir/$sid"` [VERIFIED: hooks/working-lock.sh:25-32, hooks/auq-lock.sh:18-25, both read in full this session].
**Why it happens:** `working-lock.sh` and `auq-lock.sh` predate `state-writer.sh`; the path-traversal guard was added later as part of the Phase 2 state-writer hardening and never backported.
**How to avoid:** Not required by any locked decision in this phase, but worth a one-line note or small task since Phase 3 already touches `hooks/install.sh` and the hook set: `session_id` here is Claude-Code-controlled, not directly attacker-controlled in the normal case, but the ASVS input-validation posture (see Security Domain below) argues for consistency — a session_id containing `../` would currently let `working-lock.sh` touch/remove a file outside `~/.claude/working-locks/`. Low severity, cheap fix, natural to bundle if `working-lock.sh` is touched for any other reason this phase (it should NOT be touched otherwise — it stays per D-04 — so this is genuinely optional/discretionary, not a phase requirement).
**Warning signs:** N/A — this is an FYI-level finding, not a blocker. Do not let it expand scope; it is not in FLIP-01/02/03 and CONTEXT.md does not mention it.

### Pitfall 5: `select_render_sessions()` and `state_files_mode()` becoming dead weight if not consciously resolved
**What goes wrong:** Post-flip, `select_render_sessions(legacy, shadow, state_files_mode)` (monitor.py:884-892) has no meaningful branch left — there's only one engine to render. If the flag/seam is left as-is unexamined, the code keeps a two-argument abstraction for a one-path reality, working against the "file shrinks by half" goal and confusing future readers about which engine is "real."
**Why it happens:** CONTEXT.md explicitly defers this to Claude's discretion ("Fate of the `--state-files` flag... no-op, removed, or diagnostic alias"), so it's easy for a plan to simply not address it and let it sit unchanged.
**How to avoid:** Make an explicit plan task/decision, not a silent default. Recommendation: keep `select_render_sessions()` as a one-line identity function (documents the "this is the single seam" intent for future readers, matches D-08's "select_render_sessions() remains the seam" instruction) but repoint `state_files_mode()`/`--state-files` to a genuinely useful diagnostic (e.g., "render only fallback-bridged/legacy_origin sessions" or simply keep it as a no-op alias that always returns the same list either way) — pick one and document the choice in the plan, since three existing tests (`Goal17_StateFilesMode`) assert specific behavior for both.
**Warning signs:** `Goal17_StateFilesMode.test_select_render_sessions_identity_reasserted` (test_monitor.py:1978-1982) currently asserts the function returns different objects for `True`/`False` — if the flag becomes a true no-op, this specific test needs an explicit update, not an accidental break.

### Pitfall 6: FLIP-02's "equivalent coverage" silently regressing on deletion-adjacent tests
**What goes wrong:** Deleting `Goal2h_BgShellBadgeOnly`/`Goal2i_ManualBgShellDetected` (shell_tracker-dependent) removes the ONLY tests asserting "a live background shell never pins WORKING by itself" — a real, user-facing, recently-fixed behavior (quick 260731-an2 rev.2). Post-flip this guarantee is now provided by hook-native `background_tasks_count` logic in `state-writer.sh`/`scan_state_files()`, but if no NEW test is written for the state-file path, the guarantee has zero test coverage after this phase, silently failing FLIP-02.
**Why it happens:** It's easy to treat "these tests use `shell_tracker` fixtures, shell_tracker is deleted" as sufficient justification to delete the tests without asking "is there an equivalent state-file-fixture test for the same user-facing guarantee."
**How to avoid:** Before deleting any shell_tracker-dependent test class, confirm there is (or add) a `StateFileTestBase`-style equivalent for the same guarantee: `background_tasks_count > 0` at `Stop` → badge true / state stays working per the D-08-verdict mapping already in `state-writer.sh`'s header comment; `background_tasks_count == 0` at `Stop` → waiting, badge false. Some of this may already exist in `test_state_writer.py`'s `Goal6_TurnEndSemantics` (`test_stop_with_one_running_entry_produces_working_and_count_one`, etc., test_state_writer.py:480-503) — audit for gaps specifically at the `scan_state_files()`/rendering layer (does the badge actually light up correctly reading `background_tasks_count` from the state file?), not just the hook-writer layer.
**Warning signs:** A deletion-only diff for `Goal2h`/`Goal2i` with no corresponding addition anywhere in `test_monitor.py` or `test_state_writer.py`.

### Pitfall 7: The `Goal6d` rewrite is narrower than it looks
**What goes wrong:** D-07 says "Goal6d is REWRITTEN on a state-file fixture, not dropped" — but `Goal6e_AliasKeyParityAcrossEngines` (test_monitor.py:1672-1756) already covers MOST of the same ground against state-file fixtures (`test_state_file_row_alias_key_from_hostname`, `test_parity_legacy_and_state_file_rows_share_alias_key`, etc., verified this session). A plan that duplicates all of Goal6d's assertions wholesale into a new class wastes effort and produces near-duplicate tests.
**Why it happens:** The two classes were written in different plans (02-03 wrote Goal6d against `scan()`, likely 02-04/03-planning added Goal6e against `scan_state_files()`) without cross-referencing.
**How to avoid:** Diff Goal6d's assertions against Goal6e's before writing new tests. The one gap actually confirmed missing: Goal6d's `test_sessionid_rotation_keeps_same_alias_key` (test_monitor.py:1087-1101) proves that TWO DIFFERENT session_ids sharing the same container hostname (simulating a `/clear` sessionId rotation) resolve to the SAME `alias_key` — this exact two-record, same-hostname scenario is not present in Goal6e and is the concrete state-file-fixture test to add (write two `STATE_DIR` records with different session_ids but the same `hostname`, assert both resolve to `host:<hostname>`).
**Warning signs:** A plan task for Goal6d that says "rewrite the whole class" rather than "add the one missing rotation-parity case against state-file fixtures."

## Code Examples

### The event-to-state mapping the state engine is already built on (unchanged by this phase, quoted for planner reference)
```
# Source: hooks/state-writer.sh:41-64, quoted verbatim this session
#   UserPromptSubmit                         -> working
#   PostToolUse / PostToolUseFailure /
#     PostToolBatch (heartbeats)             -> working
#   PermissionRequest / Notification         -> needs_input
#   SessionStart (source != compact)         -> idle
#   SessionStart (source == compact)         -> no write (case 11)
#   Stop                                     -> waiting when
#     background_tasks_count == 0, working when > 0 (case 17)
#   SubagentStop                             -> no write, deliberate no-op (case 12)
#   SessionEnd                               -> removes the state file,
#     unconditionally, for every `reason` value (cases 10/11/14)
#   any other/unregistered event name        -> no write
```
This mapping is NOT in scope to change this phase — it's Phase 2's already-shipped, already-tested design. Quoted here so the planner doesn't re-derive it while designing the two new fallback behaviors.

### The registered event set (verbatim, for install.sh/settings-snippet/README accuracy)
```json
// Source: hooks/state-writer-events.json, read in full this session
["SessionStart", "UserPromptSubmit", "PostToolUse", "PostToolUseFailure",
 "PostToolBatch", "PermissionRequest", "Notification", "Stop",
 "SubagentStop", "SessionEnd"]
```

### The staleness-recovery block that needs the D-02a/D-02b extensions
```python
# Source: monitor.py:666-675, read this session — the exact block to extend
if status == "WORKING":
    window = (STATE_PROMPT_STALE_SEC if last_event == "UserPromptSubmit"
              else STATE_HEARTBEAT_STALE_SEC)
    if age > window:
        container_status = None
        if container_info and hostname:
            container_status = container_info.get(
                "hostname_to_status", {}).get(hostname)
        if container_status != "paused":
            status, dot, color, rank = "WAITING", "●", "#4ade80", 1
```
`STATE_HEARTBEAT_STALE_SEC = 600` and `STATE_PROMPT_STALE_SEC = 90` [VERIFIED: monitor.py:91, 98, quoted verbatim in-context above]. This is the single place to add: (1) the D-02a early-recovery check (matching legacy `working_locked is False` → recover even before `age > window`), and (2) the D-02b pin extension (a fresh working-lock file → do NOT recover even though `age > window`, alongside the existing `paused` exception).

## State of the Art

| Old Approach (pre-flip, Phase 2) | New Approach (post-flip, Phase 3) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `scan()` (jsonl) is the ONLY rendered/notified engine; `scan_state_files()` runs shadow-only | `scan_state_files()` is the ONLY rendered/notified engine; `scan()` runs as a data-source sibling, never rendered directly | This phase (Phase 3) | Overlay/notifications/Telegram now driven by hook-derived verdicts; jsonl format changes can no longer silently break the primary UX (only the 3 named fallbacks touch jsonl at all) |
| Two engines computed every tick, diffed, logged (`diff_verdicts`/`filter_divergence_events`/`write_divergences`) | One engine computed and rendered; `scan()` still runs but only 3 of its fields are consumed (bridge entries, mtime, working_locked) | This phase | Removes ~250 lines of shadow-diff machinery (monitor.py:717-882) and the divergence log entirely |
| bg/Monitor/Agent badges from `shell_tracker`'s jsonl regex parsing (⚙+◉ pair) | Single ◉N badge from `state-writer.sh`'s hook-captured `background_tasks_count` | Decided 2026-07-29/31 (TEST-MATRIX case 18, quick 260731-an2 rev.2), shipped this phase | Deletes `shell_tracker.py` (247 lines) and its 12 regex patterns entirely; badge can never disagree with the state that fed it (same count feeds both) |
| `auq-lock.sh` is the `needs_input` source | `state-writer.sh`'s `PermissionRequest`/`Notification` → `needs_input` mapping is the source; `auq-lock.sh` retires | TEST-MATRIX case 6 (live-confirmed 2026-07-29: AUQ emits `PreToolUse`+`PermissionRequest`, contradicting the research-only prediction it was hook-silent), UAT section F confirmed parity | Removes one of the two original "corrective patch" hooks the whole refactor was framed around (NOTES.md's opening framing) |

**Deprecated/outdated:**
- `shell_tracker.py`'s entire regex-based jsonl scanning approach — superseded by `background_tasks_count` already present in every hook payload (`Stop`/`SubagentStop`), captured once by `state-writer.sh` via a deny-list jq filter (`select((.status // "running") != "completed" and (.status // "running") != "failed")`) [VERIFIED: hooks/state-writer.sh:109-113, quoted].
- The shadow-mode divergence log format/review protocol (D-02 of 02-CONTEXT.md) — its job (validate the new engine before trusting it) is done; 02-DIVERGENCE-REVIEW.md is the durable record, the machinery that produced it is deleted.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The D-02a Esc-recovery fallback should be implemented by reusing `scan()`'s already-computed `working_locked`/`mtime` fields rather than writing new jsonl-reading code | Architecture Patterns, Pattern 2 | Low-medium — this is a design recommendation (my synthesis of the UAT C1 finding + existing code), not a literal instruction in CONTEXT.md. If wrong, the planner designs a different (possibly more duplicative) mechanism; behavior outcome (recover ~90s) is still the locked target either way. |
| A2 | The D-02b hook-silence pin should be implemented using working-lock evidence alone (not shell_tracker's monitor/agent-specific counters) | Common Pitfalls #2 | Medium — if the user actually wants Monitor/Agent-specific evidence preserved (contradicting D-03's blanket shell_tracker deletion), this recommendation under-delivers on D-02b's literal wording. Flagged explicitly as a tension for discuss-phase/planner confirmation, not silently resolved. |
| A3 | jsonl filenames under `~/.claude/projects/<encoded-dir>/*.jsonl` do NOT equal the session_id (must be extracted from tail-parsed content) | Anti-Patterns to Avoid | Low — if actually true that filename==session_id in current Claude Code versions, a cheaper jsonl-mtime lookup (stat by filename, no tail parse) would be possible. Codebase never assumes this (verified: `scan()` always extracts session_id via `_extract_session_id(tail_last_line(...))`, never from `f.name`), so treating it as unverified is the safe default. |
| A4 | `install.sh`'s default path should stop installing auq-lock.sh in Phase 3's shipped code (not deferred until live UAT completes) | Common Pitfalls #3 | Medium — D-04's exact UAT-gate wording could be read the opposite way (code change deferred until UAT passes). Recommendation follows D-12's "code ships now, live validation happens after on Windows" framing, but this is an interpretation, not a verbatim instruction. |
| A5 | `select_render_sessions()` should be kept as a one-line identity function rather than removed outright | Common Pitfalls #5 | Low — purely a code-shape recommendation within an explicitly discretionary decision; either choice satisfies D-08's instruction that "select_render_sessions() remains the seam." |

**If this table is empty:** N/A — five assumptions logged above, all flagged inline at point of use.

## Open Questions

1. **Does D-02b's "active Monitor/agent evidence" require reviving any part of `shell_tracker.py`, or is working-lock evidence alone sufficient?**
   - What we know: Divergence class 6 (9 events/week, max ~50 min episodes) is what D-02b targets; working-lock's 3600s max-age comfortably covers the observed episode lengths; shell_tracker is the only current source of Monitor/Agent-*specific* (as opposed to any-tool) evidence.
   - What's unclear: Whether the user's intent behind naming "Monitor/agent evidence" specifically (rather than just "working-lock evidence") requires distinguishing a Monitor/Agent tool call from an ordinary long Bash call, or whether "any tool in flight, however long" is an acceptable behavioral proxy.
   - Recommendation: Surface this explicitly at plan-review or discuss-phase before implementation — it's a two-locked-decisions tension (D-02b vs D-03), not something the planner should resolve unilaterally in either direction.

2. **What is the actual, final behavior of `--state-files`/`state_files_mode()` post-flip?**
   - What we know: CONTEXT.md defers this fully to discretion; three existing tests assert specific current behavior.
   - What's unclear: Whether any diagnostic value remains in the flag once there's only one engine, or whether it should be removed to reduce surface area (matching the "shrinks by half" goal).
   - Recommendation: Pick one of {no-op-but-kept, removed-with-argv-still-accepted-and-ignored, repurposed-as-a-bridge-only-diagnostic} explicitly in the plan; don't leave it unaddressed.

3. **Where exactly should the promoted TEST-MATRIX.md + runbook land (`docs/` vs README-inline)?**
   - What we know: D-10 explicitly gives the planner veto power ("planner may veto the promotion split at plan review if it balloons") and defers the exact split to Claude's discretion.
   - What's unclear: Whether `docs/` already has an established convention in this repo (a `docs/` directory exists — confirmed via `ls /workspace` — but its current contents (screenshots: `demo.gif`, `standard-mode.png`, `compact-mode.png`) are asset-only, no existing markdown-doc convention to follow).
   - Recommendation: Keep the promoted doc as a single `docs/TEST-MATRIX.md` (or similar) with a short README pointer, rather than restructuring `docs/` wholesale — matches D-10's explicit anti-scope-creep framing.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.10+ | Everything (engine, tests) | ✓ | 3.11.2 | — |
| jq | Hook scripts, `install.sh` | ✓ | jq-1.6 | — |
| bash | Hook scripts, `install.sh` | ✓ | (sandbox default shell available) | — |
| Docker CLI (`docker`) | `scan_containers()`'s live container introspection; NOT required for unit tests, which already mock/skip it | ✗ (not installed in this sandbox) | — | Existing test suite already handles this gracefully — `scan_containers()` returns empty structures when `shutil.which("docker")` is `None` (monitor.py:1174-1176), and `Goal6d`'s `test_scan_containers_docker_absent_container_info_has_all_three_maps` (test_monitor.py:1105-1112) explicitly exercises this path by monkeypatching `shutil.which`. No plan task should assume live Docker is available in this execution environment; live container-liveness/paused-guard behavior (B1/B2/C3/C4 in 02-UAT.md) can only be verified on the Windows machine per D-12. |
| tkinter | `MonitorApp`/UI code, not exercised by `test_monitor.py` (stubbed at import time) | N/A in this sandbox, irrelevant to test execution | — | `test_monitor.py` stubs `sys.modules["tkinter"]` before importing `monitor` (test_monitor.py:26-28) specifically so headless/Linux CI (this environment) can run the suite without a display. No plan task should try to launch `MonitorApp` itself in this environment. |

**Missing dependencies with no fallback:** none — Docker's absence has an established, already-tested fallback path; tkinter's "absence" is a deliberate test-harness design, not a real gap.

**Missing dependencies with fallback:** Docker (mocked/skipped in unit tests, live verification deferred to Windows UAT per D-12).

## Security Domain

### Applicable ASVS Categories

This is a local, non-network-facing desktop tool (a Tk overlay reading local files and a local Docker socket, with an optional outbound Telegram push using credentials from a gitignored `.env`). Most ASVS categories (authentication, session management, access control) don't apply — there is no login, no multi-user access boundary, no server. The categories below are the ones with real surface area, using ASVS 4.0's numbering (the widely-deployed version; ASVS 5.0 renumbers "File Handling" to V5 and folds general input validation elsewhere — version not pinned in `.planning/config.json`, so this table uses the 4.0 numbering as the more commonly referenced baseline) [CITED: OWASP ASVS overview, WebSearch this session — the 4.0-vs-5.0 renumbering distinction; exact 5.0 requirement text not independently confirmed this session].

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No login surface |
| V3 Session Management | No | "Session" here means a Claude Code session, not a web/auth session |
| V4 Access Control | No | Single-user local tool, no access boundaries |
| V5 Input Validation | Yes (narrow) | `session_id` from hook payloads is used to build filesystem paths in three hook scripts. `state-writer.sh` already validates it against `^[A-Za-z0-9._-]+$` before path use [VERIFIED: hooks/state-writer.sh:82-88, quoted in Pitfall #4]. `working-lock.sh`/`auq-lock.sh` do NOT have this guard (Pitfall #4) — low-severity gap, optional fix, not phase-blocking since neither script is edited by any locked decision this phase. |
| V6 Cryptography | No | No crypto in scope; Telegram push uses HTTPS via `urllib.request` to the standard Bot API endpoint, no custom crypto |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via a malformed `session_id` in a hook payload (e.g. `../../etc/passwd`) reaching a filesystem path build | Tampering | Regex allowlist before path construction — `state-writer.sh` already does this; `working-lock.sh`/`auq-lock.sh` do not (Pitfall #4, optional/discretionary fix) |
| Divergence log / state file content leaking prompt text or tool I/O onto the shared 9p mount | Information Disclosure | Already enforced and tested — `state-writer.sh`'s header comment explicitly lists what's "Deliberately NOT captured" (prompt, tool_input, tool_response, message bodies) [VERIFIED: hooks/state-writer.sh:25-30, quoted], and `test_monitor.py`'s `test_no_legacy_evidence_contains_raw_prompt_or_tool_input_text` (test_monitor.py:1943, part of the Goal16 class being DELETED this phase) currently asserts this for the divergence log specifically — since that log and its content-leak test are both deleted together, no regression is introduced, but the underlying `legacy_evidence` string-building code being tested is also deleted alongside it, so there's nothing left needing this guarantee post-flip. |

## Sources

### Primary (HIGH confidence — direct file reads this session)
- `/workspace/monitor.py` (full file, 2437 lines) — every architectural claim about `scan()`, `scan_state_files()`, `select_render_sessions()`, the shadow-diff functions, `MonitorApp.refresh()`, constants, and line ranges cited above
- `/workspace/shell_tracker.py` (full file, 247 lines) — regex patterns, four public functions and their exact call sites in `monitor.py`
- `/workspace/test_monitor.py` (class/method inventory via grep, plus full reads of lines 1-260, 333-845, 1023-1113, 1323-1450, 1586-1786, 1783-1800, 1967-2000) — test class categorization
- `/workspace/test_state_writer.py` (class/method inventory via grep)
- `/workspace/hooks/state-writer.sh`, `/workspace/hooks/install.sh`, `/workspace/hooks/settings-snippet.json`, `/workspace/hooks/working-lock.sh`, `/workspace/hooks/auq-lock.sh`, `/workspace/hooks/state-writer-events.json`, `/workspace/hooks/hook-events.json` (all read in full)
- `/workspace/README.md` (full file)
- `.planning/phases/03-flip-to-default-cleanup/03-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/NOTES.md`, `.planning/TEST-MATRIX.md`, `.planning/phases/02-state-writer-shadow-mode/02-DIVERGENCE-REVIEW.md`, `.planning/phases/02-state-writer-shadow-mode/02-UAT.md`, `.planning/phases/02-state-writer-shadow-mode/02-CONTEXT.md` (all read in full)

### Secondary (MEDIUM confidence)
- OWASP ASVS category overview (WebSearch this session, general — not a specific requirement ID confirmed)

### Tertiary (LOW confidence)
- None used unqualified — the five items in the Assumptions Log are the only claims not grounded in a direct file read or locked CONTEXT.md decision, and each is flagged individually.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero-dependency constraint is explicit and verified against actual `python3`/`jq` versions in this environment
- Architecture (call graph, what survives/deletes): HIGH — every function/line-range claim was verified by reading the actual file this session, not inferred from the phase description
- New-logic design (D-02a/D-02b implementation approach): MEDIUM — grounded in existing, already-tested code (`working_locked`, `mtime`), but the specific wiring recommendation is original synthesis (Assumptions A1/A2), not a literal spec
- Pitfalls: HIGH — each is backed by a specific line citation or a specific documented tension between two locked CONTEXT.md decisions
- Test inventory: HIGH — full class/method list obtained via grep and cross-checked against the actual test bodies for the classes most relevant to this phase

**Research date:** 2026-08-06
**Valid until:** Should remain valid for the duration of Phase 3's execution (this is a closed, self-contained refactor of code already in the repo — no external ecosystem drift risk). Re-verify line numbers cited above if any other change lands on `monitor.py`/`test_monitor.py`/`hooks/` before this phase's plans are executed.
