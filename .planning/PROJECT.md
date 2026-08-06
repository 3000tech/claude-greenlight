# Claude Greenlight — Hook-Driven State Refactor

## What This Is

Refactor of the claude-greenlight monitor's state-detection engine: today session state (working / waiting / needs input) is **inferred** by parsing Claude Code's internal session jsonl files, with three lock-file hooks bolted on as corrective patches. The refactor inverts the hierarchy: **Claude Code hooks become the primary source of state** (one small state file per session written on official lifecycle events), and jsonl parsing shrinks to targeted fallbacks only where hooks are provably silent (hybrid model).

Design and migration plan already exist in [NOTES.md](NOTES.md); the 21-case verification matrix in [TEST-MATRIX.md](../docs/TEST-MATRIX.md) defines what "detected correctly" means.

## Core Value

The monitor must keep telling the user *"this session needs you now"* reliably — but stop breaking every time Claude Code changes its internal jsonl format (already happened three times). Hooks are a documented, stable interface; state derived from them is correct by construction instead of guessed.

## Context

- Existing codebase: `monitor.py` (~2000 lines, tkinter overlay + jsonl parsing + notifications), `shell_tracker.py` (bg shell/Monitor/agent badges from jsonl), `hooks/` (install.sh + settings snippet: working-lock, auq-lock, permission Notification hook), `test_monitor.py` (40+ unit tests, unittest).
- Zero-dependency constraint: Python 3.10+ stdlib only on the Windows side; `bash` + `jq` on the hook side. This is a published OSS tool (github.com/3000tech/claude-greenlight, MIT).
- Monitor runs on the Windows host; sessions run in WSL2/Docker containers that bind-mount the host's `~/.claude`. Hooks execute inside the containers and write to the shared mount — write access is already required today.
- Target architecture, staleness design (PostToolUse heartbeat + docker ps cross-check), and 3-phase migration plan (extend hooks → shadow mode → flip default) are specified in NOTES.md.
- Known hook blind spots that force the hybrid model: AskUserQuestion (no jsonl write until answered — hook behavior unverified), Esc interrupt, bg-task re-invocation, abandoned prompt before first tool call, async work still running at turn end (design divergence: `Stop` would flip green while bg shells/agents run — current semantics keep grey).
- Live verification requires the real Windows+container environment; in-session work can only prepare instrumentation, code, and unit tests. Live matrix runs are user-assisted UAT.

## Requirements

### Validated

- ✓ Overlay (standard/compact) shows every live session with project label and state — existing
- ✓ Notifications (toast, sound, taskbar flash, optional Telegram) on WORKING→WAITING — existing
- ✓ Permission prompts and AUQ modals force green via auq-lock (Notification hook) — existing
- ✓ Long turns stay grey via working-lock (UserPromptSubmit/Stop hooks) — existing
- ✓ Bg shell / Monitor / agent badges from shell_tracker — existing
- ✓ Per-session aliases, config UI, docker container section — existing

### Active

- [ ] Hook event coverage is verified live against TEST-MATRIX.md (logging hook, matrix columns filled, hybrid verdict written)
- [ ] Hooks write per-session state files (`~/.claude/monitor-state/<session_id>.json`) atomically on lifecycle events
- [ ] Monitor derives state from state files as primary source (`--state-files` mode)
- [ ] Shadow mode logs divergences between legacy parsing and state-file engine on real usage
- [ ] Staleness handling: heartbeat silence + docker liveness cross-check; corrupt/partial state files tolerated
- [ ] Documented fallbacks cover the hook-silent cases per the matrix verdict (AUQ, interrupt, async work, badges)
- [ ] State-file engine becomes the default; dead jsonl-parsing paths removed; tests rewritten against state files
- [ ] Hookless containers degrade gracefully (legacy parsing per-session or explicit "no data")

### Out of Scope

- Packaging/`src/` layout, README screenshot work — separate backlog items
- Adopting claude-semaphore or other external tools — evaluated and discarded (NOTES.md)
- Changing notification UX (debounce, timing tweaks) beyond what `Stop`-based detection gives for free — early notify is accepted as by-design today
- Non-Windows monitor ports — niche is Windows host + WSL2/Docker

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Hybrid model (hooks primary + targeted fallbacks), not hooks-only | Matrix cases #6/#8/#13/#17/#18 are suspected hook-silent; user's prior analysis agrees | — Pending live verification |
| Never big-bang: extend hooks → shadow mode → flip default | Monitor is in daily use; divergence logging de-risks the flip | — Pending |
| Preserve current async-work semantics (grey while bg shells/agents run) unless live data says otherwise | Matches existing tests and user expectations; `Stop`-flips-green would notify mid-work | — Pending |
| Badge semplificati: unico contatore ◉N da `background_tasks_count`, shell_tracker jsonl eliminato (supersede V2-01) | Decisione utente 2026-07-29: dei badge guardava solo il contatore bg; il campo hook copre lo scopo originario senza jsonl | ✓ Decisa — entra nel design Phase 2 |
| shell_tracker stays jsonl-based initially | Badges need tool-level payloads; rebuilding from PostToolUse is a later optimization | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-28 after initialization*
