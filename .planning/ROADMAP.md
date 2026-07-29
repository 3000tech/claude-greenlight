# Roadmap: Claude Greenlight — Hook-Driven State Refactor

## Overview

The monitor moves from *inferring* session state by parsing Claude Code's internal jsonl files to *reading* state that hooks write on official lifecycle events. This can't be done in one leap: hook coverage has unknowns (does AskUserQuestion fire anything? does `Stop` really fire after rendering?) that only the real Windows + Docker environment can answer. So the work runs in three phases that mirror the migration plan in NOTES.md — verify hook coverage live, build the state-writer and run it in shadow mode next to the current parser, then flip the default and delete the old path. Phase 1's live matrix run is the input Phase 2's fallback design depends on: the hybrid verdict decides which hook-silent cases (AUQ, interrupt, async work, badges) need a fallback and what that fallback is.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Hook Coverage Verification** - Live-verify what each Claude Code hook event tells us and produce a hybrid verdict naming the fallback for every hook-silent case
- [ ] **Phase 2: State Writer & Shadow Mode** - Hooks write per-session state files; the monitor derives state from them and cross-checks against legacy parsing without changing what the user sees
- [ ] **Phase 3: Flip to Default & Cleanup** - State-file engine becomes the default, legacy jsonl parsing is removed, tests and docs updated

## Phase Details

### Phase 1: Hook Coverage Verification

**Goal**: Every hook event relevant to state detection is verified live against TEST-MATRIX.md, producing a written hybrid verdict that names, per hook-silent case, the exact fallback that covers it — the input Phase 2's state-writer and fallback design depend on.
**Depends on**: Nothing (first phase)
**Requirements**: VER-01, VER-02
**Success Criteria** (what must be TRUE):

  1. A logging hook is installed alongside the existing hooks and, during real sessions, every Claude Code hook event (name, relevant payload fields, timestamp, session_id) appears in `~/.claude/hook-events.log` without disturbing current monitor behavior.
  2. All 21 cases in TEST-MATRIX.md have been run live in the real Windows + container environment, with the "Verified" column filled in (date, CC version, outcome) for each — this step is user-assisted UAT, not agent-executable.
  3. A written hybrid verdict states whether hooks-only coverage is viable and, for every confirmed hook-silent case (candidates: AskUserQuestion, Esc interrupt, bg-task re-invocation, abandoned prompt, async work in flight), names the specific fallback mechanism that will cover it in Phase 2.

**Plans**: 2/2 plans executed

Plans:

- [x] 01-01-PLAN.md — Build `hooks/event-logger.sh` and register it on every documented hook event via `hooks/install.sh`, with removal path and tests (VER-01)
- [x] 01-02-PLAN.md — Write the 21-case live runbook `01-UAT.md` and make TEST-MATRIX.md ready to receive the verdict (VER-02, completed at human UAT)

### Phase 2: State Writer & Shadow Mode

**Goal**: Hooks become the primary source of session state — writing one atomic state file per session on every lifecycle event — while the monitor runs a state-file engine in shadow mode next to the current parser, proving trustworthiness before anything user-visible changes.
**Depends on**: Phase 1 (the hybrid verdict determines which hook-silent cases need fallback coverage here, and how)
**Requirements**: SW-01, SW-02, SW-03, ENG-01, ENG-02, ENG-03, ENG-04, ENG-05, ENG-06
**Success Criteria** (what must be TRUE):

  1. Hooks write one state file per session (`~/.claude/monitor-state/<session_id>.json`) atomically (tmp + rename) on `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Notification`, `Stop`, and `SessionEnd`, each carrying `state`, `ts`, `cwd`, and `last_event`.
  2. The existing working-lock and auq-lock hooks keep functioning unchanged while the state writer runs alongside them — no regression during the migration.
  3. Running `monitor.py --state-files` derives every visible session's state from `monitor-state/` as the primary source; stale sessions are caught via heartbeat silence plus a `docker ps` cross-check (a killed container never leaves a session stuck grey forever), and corrupt, partial, or missing state files degrade gracefully instead of crashing the monitor.
  4. Shadow mode runs the state-file engine alongside legacy parsing during real usage and logs every divergence (session, tick, legacy verdict vs. state-file verdict) without changing what the user sees in the overlay.
  5. Sessions from hookless containers stay visible via per-session legacy-parsing fallback, and every hook-silent case named in Phase 1's verdict is covered by its designated fallback — including current async-work semantics (grey while bg shells/Monitors/agents run) and shell_tracker badges staying intact.

**Plans**: TBD

### Phase 3: Flip to Default & Cleanup

**Goal**: The state-file engine is trusted enough to be the default — legacy jsonl parsing is deleted, tests are rewritten against state files, and the docs describe the architecture that actually ships.
**Depends on**: Phase 2 (shadow-mode divergence logs over real usage are what justify the flip)
**Requirements**: FLIP-01, FLIP-02, FLIP-03
**Success Criteria** (what must be TRUE):

  1. `monitor.py` runs on the state-file engine by default — no `--state-files` flag required — and the dead legacy jsonl-parsing code paths are removed.
  2. `test_monitor.py` covers the state-file engine at equivalent coverage to before, with state-file fixtures replacing jsonl fixtures wherever legacy code was removed.
  3. `hooks/install.sh`, the settings snippet, and the README document the new architecture and hook requirements clearly enough that a new container/user can be onboarded correctly.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Hook Coverage Verification | 2/2 | In Progress|  |
| 2. State Writer & Shadow Mode | 0/TBD | Not started | - |
| 3. Flip to Default & Cleanup | 0/TBD | Not started | - |
