# Phase 2: State Writer & Shadow Mode - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Hooks write one state file per session (`~/.claude/monitor-state/<session_id>.json`); `monitor.py --state-files` derives every visible session's state from those files as primary source, runs in shadow mode alongside legacy jsonl parsing, and logs every divergence — without changing anything the user sees. Legacy parsing removal is Phase 3, not here.

</domain>

<decisions>
## Implementation Decisions

### Zero UX change (the governing decision)
- **D-01:** The user's experience does not change AT ALL in Phase 2: same labels, same colors, same staleness feel, same notifications. The refactor is entirely under the hood. Every area below was answered "come adesso". — **Reversibility:** reversible — but treat as LOCKED: any visible change in shadow phase is a defect, not an improvement opportunity.

### Shadow mode & flip criterion
- **D-02:** Divergence review is agent-driven: divergences go to a log file; Claude reads and analyzes it in-session with the user (no overlay indicator, no visual debug UI). The user explicitly does NOT want to watch divergences themselves.
- **D-03:** Flip to Phase 3 is decided TOGETHER after N days without unexplained divergences (N flexible, target ~1 week of real usage; the exact number is agreed when reviewing). No automatic flip.
- **D-04:** A divergence is not automatically a new-engine bug — the user expects "divergenze in meglio" (e.g. hook engine sees the AUQ modal instantly where legacy sees it only at answer time). The divergence log MUST carry enough context per entry (session, tick, both verdicts, last hook event, legacy evidence) to judge WHICH side was right. Classification (legacy-wrong vs hooks-wrong vs both-defensible) happens during review, not in code.

### Session labels & container identity
- **D-05:** Labeling works exactly as today (current auto-label mechanism + user-set alias on click). The state-file engine must reproduce today's labels, not invent new ones. — The known cwd collision (`/workspace` in every container) is a Phase 2 *internal* problem: the writer should capture container identity (e.g. `$HOSTNAME` at hook time) as data so the engine can map session→container as reliably as today or better, but the displayed label does not change.

### Staleness policy
- **D-06:** Thresholds and behavior as today (~10 min heartbeat silence + `docker ps` cross-check). Paused containers: rendered like today (no new "frozen" state in UI) — but the engine must not mistake `paused` for `exited` (verdict: paused = alive-but-frozen, never auto-removed as dead). Dead sessions: same visibility/removal behavior as today.

### needs_input semantics
- **D-07:** Permission prompts and AUQ modals stay GREEN, identical to turn-end green — no new color, no distinct notification. `PermissionRequest` improves *timeliness* (instant vs Notification's ~6s lag) but not the rendering.

### Superseded requirement text (planner MUST honor these over stale wording)
- **D-08:** SW-01's event list ("SessionStart, UserPromptSubmit, PostToolUse, Notification, Stop, SessionEnd") predates the live campaign. The writer's event set must follow the verdict in TEST-MATRIX.md instead: include `PermissionRequest` (instant needs_input), `PostToolBatch`/`PostToolUseFailure` (heartbeat), `SubagentStop` (ignore for state), and read `background_tasks_count` from Stop payloads (async-in-flight). Notification becomes optional/secondary.
- **D-09:** ENG-06's "badges intact via shell_tracker" is superseded by the user's 2026-07-29 decision: single unified badge ◉N fed by `background_tasks_count`; the ⚙/◉ pair and shell_tracker are removed. Recorded in PROJECT.md Key Decisions and TEST-MATRIX case 18.

### Claude's Discretion
- State file schema details beyond SW-02's minimum (`state`, `ts`, `cwd`, `last_event`) — e.g. adding `hostname`, `background_tasks_count`, `last_event_ts_ms`.
- Divergence log format/location and the shadow-tick comparison mechanics.
- Orphan state-file cleanup策 (resume-picker ids, /clear old ids, killed sessions) — verdict says these exist; how/when to prune is implementation.
- Exact staleness implementation as long as observable behavior matches today.
- How `--state-files` flag coexists with the default path during shadow (flag naming, config).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The empirical foundation (read FIRST)
- `.planning/TEST-MATRIX.md` — 21 live-verified cases (Verified column, cc 2.1.220) + § "Verdict to extract": the hybrid verdict naming per-case signals and fallbacks. This is the event-to-state mapping's ground truth; it OVERRIDES any conflicting wording in REQUIREMENTS.md (see D-08/D-09).
- `.planning/phases/01-hook-coverage-verification/01-UAT.md` — runbook + how each case was verified.

### Architecture & migration plan
- `.planning/NOTES.md` — target architecture, migration plan (extend hooks → shadow → flip), event-to-state mapping draft.
- `.planning/REQUIREMENTS.md` — SW-01..03, ENG-01..06 (with D-08/D-09 supersedes).

### Existing mechanisms to extend (not replace)
- `hooks/install.sh`, `hooks/settings-snippet.json` — install/merge mechanism; state-writer hooks land the same way, preserving auq-lock/working-lock (SW-03).
- `hooks/event-logger.sh` — reference implementation for safe hook scripting: jq single-pass, always exit 0, flock short-wait, privacy rules, 9p-mount-safe appends.
- `monitor.py` — current engine; `test_monitor.py` (56 tests) defines today's observable behavior that must not regress.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `hooks/event-logger.sh` patterns: atomic-safe writes on the shared 9p mount, flock with 0.5s timeout + never-block fallback, payload parsing via jq only, exit-0-always. The state writer is a sibling of this script.
- `hooks/install.sh` idempotent merge + `--remove-*` teardown pattern — reuse for state-writer registration.
- `~/.claude/hook-events.log` (1600+ real events, cc 2.1.220) — real payload samples for tests/fixtures.
- Overlay row/chip structure in `monitor.py` (`_make_session_row`, `_make_compact_chip`): badge labels `bg`/`monitor` are the elements the unified ◉N badge replaces (at flip, not during shadow).

### Established Patterns
- Locks in `~/.claude/auq-locks/`, `~/.claude/working-locks/` keep working unchanged through Phase 2 (SW-03) — they retire only in Phase 3.
- `test_event_logger.py` style: drive real scripts via subprocess with HOME pinned to a temp dir; never touch real `$HOME`.

### Integration Points
- `monitor.py` tick loop: shadow mode = compute state twice per tick (legacy + state-files), compare, log divergence, render legacy verdict.
- `~/.claude/monitor-state/` — new directory on the shared mount, one JSON per session_id, atomic tmp+rename (case 20 resilience).

</code_context>

<specifics>
## Specific Ideas

- "Per me l'attuale funziona bene, magari troviamo divergenze in meglio" — the user's mental model of shadow mode: it validates the new engine AND may reveal places where the new engine is *more correct* than legacy (AUQ timeliness is the known example). Divergence review should celebrate these, not just hunt regressions.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)
- **Campagna ricertificazione hook per versione Claude Code** (`.planning/todos/pending/2026-07-29-campagna-ricertificazione-hook-per-versione-claude-code.md`) — matched on keywords but belongs to Phase 3 / cleanup: promoting matrix+runbook out of `.planning/`, per-version fixtures, smoke checklist for major bumps. Not Phase 2 scope.

- Badge unificato ◉N rendering — decided (D-09) but the visible swap happens at Phase 3 flip, not during shadow (D-01 zero UX change).

</deferred>

---

*Phase: 2-State Writer & Shadow Mode*
*Context gathered: 2026-07-29*
