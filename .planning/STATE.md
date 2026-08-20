---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Remote Notifications
status: executing
last_updated: "2026-08-20T09:35:00.000Z"
last_activity: 2026-08-20
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-28)

**Core value:** Keep telling the user "this session needs you now" reliably — stop breaking every time Claude Code changes its internal jsonl format; hook-derived state is correct by construction instead of guessed.
**Current focus:** milestone v1.1 Remote Notifications — Phase 4 (notification truth) COMPLETE and verified live; next: Phase 5 planning (devbox sessions on the PC overlay)

## Current Position

Phase: 4 of 6 (notification-truth) — **COMPLETE 2026-08-20**
Plan: 2 of 2 complete
Status: Verified — 04-VERIFICATION.md `passed` (4/4 success criteria), 04-UAT.md `complete` (8/8 passed). SC-4's overnight live gate closed on the night of 2026-08-19/20: 28 idle pings on the devbox loop session produced 0 notifications and 0 state writes, `gate_cleared` held at its pre-night baseline on both machines (devbox 24, PC 10), and all 3 notifications that did fire were adjudicated true positives. The ~20 illegitimate overnight pushes of 2026-08-18/19 are gone.
Next: Phase 5 — `/gsd-plan-phase 5` (05-CONTEXT.md and 05-RESEARCH.md already on disk, no plans written)
Last activity: 2026-08-20 — Section F recorded, phase closed

## Performance Metrics

**Velocity:**

- Total plans completed: 6
- Average duration: - min
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 2 | - | - |
| 3 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01 | 8min | 3 tasks | 5 files |
| Phase 01 P02 | 6min | 2 tasks | 3 files |
| Phase 02 P01 | 13min | 2 tasks | 5 files |
| Phase 02 P02 | 15min | 3 tasks | 2 files |
| Phase 02 P03 | 14min | 3 tasks | 2 files |
| Phase 02 P04 | 8min | 2 tasks | 2 files |
| Phase 03 P01 | 13min | 2 tasks | 3 files |
| Phase 03 P02 | 19min | 3 tasks | 5 files |
| Phase 03 P03 | 27min | 3 tasks | 6 files |
| Phase 03-flip-to-default-cleanup P04 | 9min | 3 tasks | 9 files |
| Phase quick-260817-i5n P01 | 10min | 3 tasks | 4 files |

## Deferred Items

Items acknowledged and deferred at milestone close on 2026-08-19:

| Category | Item | Status |
|----------|------|--------|
| todo | startup-check-refuse-to-start-with-clear-error-when-hooks-absent | deferred (candidate next milestone) |
| todo | local-host-sessions-are-invisible-to-the-monitor | deferred (known limitation, candidate devbox/mobile milestone) |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [2026-08-06 / Section E review]: FLIP APPROVED — hook engine becomes primary in Phase 3, hybrid jsonl fallback retained ONLY for Esc-interrupt recovery and hook-silence pins (Monitor/agents/working-lock evidence). Bg-shell hook rule becomes badge-only at the flip.
- [2026-08-06]: Remote devbox support (Claude in Docker on the headless MacBook, matteo@192.168.1.139) + mobile notifications = SEPARATE MILESTONE after v1.0's flip, not Phase 3 scope. Phase 3 must not close doors: state files already carry `hostname`; a remote aggregator only needs to transport `~/.claude/monitor-state/*.json`.
- Hybrid model (hooks primary + targeted fallbacks), not hooks-only — pending live verification in Phase 1
- Never big-bang: extend hooks → shadow mode → flip default — 3-phase roadmap follows this exactly
- Preserve current async-work semantics (grey while bg shells/agents run) unless live data says otherwise
- ~~shell_tracker jsonl (V2-01)~~ SUPERSEDED 2026-07-29: badge unificato ◉N da background_tasks_count, shell_tracker eliminato — zero jsonl a regime dopo Phase 3
- [Phase ?]: Used RESEARCH.md's 24-event fallback baseline for hooks/hook-events.json (no live docs fetch available this session); documented provenance + re-check caveat in install.sh header
- [Phase ?]: event-logger.sh writes no line for a payload lacking hook_event_name (e.g. {}), treating it as a partial payload alongside empty/non-JSON/truncated stdin
- [Phase ?]: install.sh --remove-logger sweeps all hooks.<Event> arrays generically rather than scoping to the current hook-events.json list, so it cleans up stale entries from any prior event-list version
- [Phase ?]: [Phase 01-02]: Every jq field/event in 01-UAT.md was grounded against the real hooks/event-logger.sh and hooks/hook-events.json (plan 01-01), not RESEARCH.md doc-fetch prose, and mechanically verified by the plan's <verify> gate
- [Phase ?]: [Phase 01-02]: TEST-MATRIX.md rows 6 (AskUserQuestion) and 8 (Esc interrupt) pre-filled with research-confirmed answers (issues 28273, 12605, 15872, 9516) but Verified column left empty pending live confirmation on the tester's Claude Code version
- [Phase ?]: [Phase 02-01]: background_tasks_count uses a deny-list (not completed/failed) rather than an == running allowlist (RESEARCH assumption A2), so an undocumented status value can't undercount live async work
- [Phase ?]: [Phase 02-01]: Only the Stop event is mapped to a state write this plan; every other registered event exits 0 without writing — remaining D-08 event mapping is plan 02-02's scope
- [Phase ?]: [Phase 02-01]: select_render_sessions() is the single seam through which either engine's output can reach rendering, enforcing D-01 structurally rather than by convention
- [Phase ?]: [Phase 02-02]: background_tasks_count resolved once (deny-list: not completed, not failed) and shared between the Stop gate and the record field so they can never disagree
- [Phase ?]: [Phase 02-02]: SessionStart(source=compact) exits without writing rather than writing idle, since /compact re-fires SessionStart on the SAME session_id mid-turn (TEST-MATRIX case 11)
- [Phase ?]: [Phase 02-02]: SubagentStop is an explicit no-op branch (not a fall-through) since it can arrive after the parent's Stop (TEST-MATRIX case 12)
- [Phase ?]: [Phase 02-02]: install.sh --remove-state-writer was already complete from plan 02-01; this plan only added the Goal7/Goal8 regression tests locking the SW-03 guarantee down
- [Phase ?]: [Phase 02-03]: STATE_PROMPT_STALE_SEC set equal to legacy's USER_PROMPT_WORKING_SEC (90s) so the abandoned-prompt staleness window matches today's behavior exactly
- [Phase ?]: [Phase 02-03]: hostname_to_label is a secondary label resolver (after sessionid_to_label) because docker exec cannot reach a paused container — without it the paused-stays-WORKING staleness branch would be unreachable
- [Phase ?]: [Phase 02-03]: legacy_sessions migration bridge lives inside scan_state_files() itself, not caller-side, so --state-files diagnostic mode gets identical hookless-fallback behavior via an internal scan() call
- [Phase ?]: [Phase 02-04]: legacy_evidence is one compact string, not structured sub-fields, so the T-02-17 content-leak audit is a single substring grep
- [Phase ?]: [Phase 02-04]: a verdict-pair change mid-episode opens a fresh divergence episode (ticks resets to 1) rather than continuing the prior one's count
- [Phase ?]: [Phase 02-04]: filter_divergence_events() is a pure records-in/state-in -> events/next-state-out function, no MonitorApp mutation, so episode collapse is unit-testable without tkinter
- [Phase ?]: [quick-260731-an2]: BG_PIN_MAX_SEC=900s time-caps the legacy bg-shell WORKING pin (status decision only, badge stays uncapped); TEST-MATRIX section 4 records the same cap requirement for the Phase 3 hook-native rule
- [Phase ?]: [quick-260731-c52]: container_display_name() prefix test (name.startswith(project)) is the sole disambiguation rule — anchors displayed text to the row's own project label so a duplicate container is distinguishable without changing sorting/keying/mapping identity
- [Phase ?]: select_render_sessions() narrowed to a 1-arg identity seam (D-08); scan() stays live in refresh() to feed the D-02c bridge and plan 03-02's fallbacks — not dead code
- [Phase ?]: scan_state_files() now stamps display_name via session_display_name()/container_display_name(), closing the duplicate-container regression the flip would have reintroduced (quick 260731-cgg)
- [Phase ?]: Goal16's content-leak test (T-02-17) deleted with its legacy_evidence builder; the must_haves prohibition against reintroducing a prompt/tool-derived string assembler stays flagged, not silently closed
- [Phase ?]: [Phase 03-02]: shell_tracker.py deleted; badge is hook-native (background_tasks_count) — D-02b's Monitor/Agent/async-agent evidence retained as a trimmed single-read in-file peek (_peek_agent_activity), never the bg-shell/badge-driving patterns
- [Phase ?]: [Phase 03-02]: D-02a (Esc-interrupt early recovery) floored at STATE_PROMPT_STALE_SEC — an unfloored age<=window check misfired on same-instant hook/jsonl write-order races at genuine turn start (caught by the plan's own test suite, fixed as Rule 1)
- [Phase ?]: [Phase 03-02]: SessionEnd tombstones use an on-disk marker (STATE_TOMBSTONE_SUFFIX=.ended), not an in-process suppression set, so D-06's ghost-row fix survives a monitor restart; a resumed session deletes its own stale tombstone as its fresh state record is read
- [Phase ?]: [Phase 03-03]: hooks/state-writer.sh's Stop branch now resolves to waiting unconditionally (D-03) — background_tasks_count is badge-only everywhere, divergence class 3 eliminated at its source
- [Phase ?]: [Phase 03-03]: auq-lock.sh retired (D-04) — deleted from repo, no longer installed/registered by default; --remove-auq-lock teardown filters at the individual hooks[].command level (not the whole entry object), after an entry-level filter was caught deleting a co-located working-lock.sh command in a synthetic test
- [Phase ?]: [Phase 03-03]: hooks/working-lock.sh backports state-writer.sh's session-id character allowlist (T-03-01), byte-identical in shape, before either lock branch runs
- [Phase ?]: [Phase 03-03]: FLIP-02 closed with an evidenced deleted-class-to-replacement coverage table; requirements.mark-complete run for FLIP-01/FLIP-02 only — FLIP-03 stays Pending since its README half is explicitly plan 03-04's scope
- [Phase 03-flip-to-default-cleanup]: [Phase 03-04]: README describes hooks as required, names the real per-session state file + working lock mechanism, and the honest degradation note names the per-session transcript fallback rather than overstating that the monitor stops reading transcripts entirely
- [Phase 03-flip-to-default-cleanup]: [Phase 03-04]: docs/TEST-MATRIX.md and docs/RECERTIFICATION.md promoted out of .planning/ at D-10's authorized scale (one move + one short runbook); campaign machinery (per-version fixtures, automated smoke checklist) stays deferred
- [Phase 03-flip-to-default-cleanup]: [Phase 03-04]: 03-UAT.md's Section H (D-04 needs_input parity gate) is written as blocking; the Teardown's --remove-auq-lock step depends on Section H passing first
- [Phase ?]: [quick-260817-i5n]: event-logger.sh samples background_tasks descriptor shape (name allowlist + value-shape guard, capped at 5 entries) — deployed live; real samples show type field discriminates shell vs subagent, recorded as TEST-MATRIX case #17 rev.3 with no verdict change
- [Phase ?]: [quick-260817-i5n]: scripts/bg-task-shape-report.sh aggregates sampled descriptor shapes/values and joins descriptor ids against known agent_id — used to gather rev.3 evidence, no state-writer.sh change shipped

- [Phase 04]: Section F recorded as PASS **with a note** rather than a bare PASS: the section's literal wording expected `sent` == 0 for the overnight loop session and the measured value was 2, both true positives (one answered by the user 18s after the push, one a genuine full stop). The criterion the phase actually owns — notifications traceable to an `idle_prompt` — measured 0 out of 28 opportunities. Recorded explicitly so the non-zero number is never later mistaken for a tolerated defect.
- [Phase 04]: Section F's second half (a real permission prompt still pages) was NOT exercised overnight — no permission prompt occurred on the devbox in the window. Not re-run: Sections B and C exercised that path live the same day and passed.

### Pending Todos

- [major/general] Preserve today's fixes (2026-07-30) across the Phase 3 flip — alias container-key (Goal6d da riscrivere su fixture state-file, non droppare), multi-monitor fix, soglia 60s deliberata
- ~~[major/general] Notifica gated sul gruppo — solo quando tutte le sessioni terminano~~ DONE 2026-08-07 (quick 260807-iz2) — gate hold/release in _check_transitions, regressioni sui due episodi reali 13:14:20Z e 13:28:53Z

- [minor/testing] Campagna ricertificazione hook per versione Claude Code (2026-07-29) — promuovere matrice+runbook fuori da .planning, fixture per versione, smoke ai major bump
- ~~[minor/general] Log su file di tutte le notifiche inviate~~ DONE 2026-08-07 (quick 260807-iz2) — ~/.claude/notifications.log jsonl append-only, logga inviate E soppresse con motivo del gate
- [minor/general] Show paused-container sessions in overlay instead of dropping them (2026-07-30) — idea da UAT C4: il motore state-file le tiene già (D-06), è solo rendering al flip di Phase 3
- [minor/general] Startup check: refuse to start with clear error when hooks are not installed (2026-07-30) — proposta utente in UAT; candidato allo scope Phase 3 (post-flip un monitor senza hook è quasi cieco)
- [minor/general] Ghost jsonl rows survive container kill via dir-fallback — consider SessionEnd tombstones (2026-07-30) — quirk legacy pre-esistente visto in UAT; lo state-writer sa che la sessione è finita ma il ponte legacy_origin ricopia il fantasma
- [minor/general] Local host sessions are invisible to the monitor (2026-08-17) — hook silenti su Windows host (comandi bash/$HOME container-only) E scan() droppa le jsonl con sessionId non-container (monitor.py:1130-1141); decidere se le sessioni host sono in scope, poi hook portabili + liveness check PID
- ~~[cosmetic/general] Remove dead project_name() helper in monitor.py~~ DONE 2026-08-06 (plan 03-01, Task 2) — confirmed zero call sites, deleted

### Blockers/Concerns

- ~~UAT live Phase 1~~ COMPLETATA 2026-07-29 (campagna opportunistica, 17/21 campionati live, 0 issues): verdetto ibrido in TEST-MATRIX.md § 'Verdict to extract' — input diretto di Phase 2/ENG-06.
- ~~Open question AUQ~~ RISOLTA 2026-07-29 live: AUQ emette PreToolUse+PermissionRequest (apertura) e PostToolUse (risposta) su cc 2.1.220 — vedi TEST-MATRIX caso 6.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260730-kgw | Fix session aliases lost on /clear: key aliases by container identity instead of sessionId | 2026-07-30 | e558946 | [260730-kgw-fix-session-aliases-lost-on-clear-key-al](./quick/260730-kgw-fix-session-aliases-lost-on-clear-key-al/) |
| 260731-an2 | Bg shells are badge-only: never pin WORKING (rev.2 dropped the initial 15-min cap) — dev server no longer holds the overlay grey | 2026-07-31 | 9f18b8f | [260731-an2-bg-shell-time-cap-grey-pin-from-backgrou](./quick/260731-an2-bg-shell-time-cap-grey-pin-from-backgrou/) |
| 260731-bu8 | Recognize manually-backgrounded (Ctrl+B) shells in shell_tracker so the ⚙ badge lights up for them | 2026-07-31 | bbb2444 | [260731-bu8-recognize-manually-backgrounded-ctrl-b-s](./quick/260731-bu8-recognize-manually-backgrounded-ctrl-b-s/) |
| 260807-b5k | Add headless Linux setup+launch script for greenlight (user-space tkinter + Xvfb) | 2026-08-07 | 935604d | [260807-b5k-add-headless-linux-setup-launch-script-f](./quick/260807-b5k-add-headless-linux-setup-launch-script-f/) |
| 260731-c52 | Docker rows show the container name when it disambiguates a duplicate project (dev-tools / dev-tools-2), else fall back to the project label | 2026-07-31 | ebb25b0 | [260731-c52-container-rows-show-docker-name-when-it-](./quick/260731-c52-container-rows-show-docker-name-when-it-/) |
| 260731-cgg | Session rows, compact chips and notifications show the disambiguated container name for duplicate-project sessions (display-only; sort/alias/divergence identity untouched) | 2026-07-31 | 1e07ee1 | [260731-cgg-session-rows-and-compact-chips-show-disa](./quick/260731-cgg-session-rows-and-compact-chips-show-disa/) |
| 260807-iz2 | Group-gated notifications (hold/release, no notify while group siblings work) + append-only notifications.log of every sent/suppressed decision | 2026-08-07 | 7961105 | [260807-iz2-group-gated-notifications-sent-notificat](./quick/260807-iz2-group-gated-notifications-sent-notificat/) |
| 260807-k0y | Notification group key includes container identity (hostname) — duplicate-project containers (nursy / nursy-2) page independently | 2026-08-07 | f04478d | [260807-k0y-notification-group-key-includes-containe](./quick/260807-k0y-notification-group-key-includes-containe/) |
| 260817-i5n | Sample background_tasks descriptor shape (agent vs shell) in Stop payloads + TEST-MATRIX case #17 rev.3 — evidence for suppressing agent-only-bg false-positive notifications | 2026-08-17 | 83a2b19 | [260817-i5n-campiona-descrittori-background-tasks-ne](./quick/260817-i5n-campiona-descrittori-background-tasks-ne/) |
| 260817-ixs | Rev.3 Stop verdict implemented: all-subagent in-flight bg tasks → working (no notify), any shell/unknown → waiting; fail-safe + full truth-table tests, deployed live | 2026-08-17 | ec252d9 | [260817-ixs-stop-verdict-rev-3-soli-subagent-in-back](./quick/260817-ixs-stop-verdict-rev-3-soli-subagent-in-back/) |
| 260818-bfm | Local notifications switch mutes audio only — toast and taskbar flash always fire even when muted | 2026-08-18 | d5ac45b | [260818-bfm-local-switch-mutes-audio-only-toast-alwa](./quick/260818-bfm-local-switch-mutes-audio-only-toast-alwa/) |
| 260818-c9o | Saved window position on a secondary screen survives restart — off-screen check now uses the virtual-screen rect | 2026-08-18 | c953cee | [260818-c9o-saved-window-position-on-secondary-scree](./quick/260818-c9o-saved-window-position-on-secondary-scree/) |
| 260818-ejg | Installer no longer attaches event-logger to WorktreeCreate/WorktreeRemove (delegation hooks); guard + prune for existing installs | 2026-08-18 | 4329624 | [260818-ejg-installer-must-not-attach-event-logger-t](./quick/260818-ejg-installer-must-not-attach-event-logger-t/) |
| 11 | x | 2026-08-18 | 14a6b7a | — |
| 15 | Window title renamed to Claude Greenlight | 2026-08-18 | 839f15d | — |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-08-20
Stopped at: Phase 4 closed — Section F (overnight acceptance) recorded PASS-with-note, 04-UAT.md complete, 04-VERIFICATION.md passed, ROADMAP Phase 4 checked off. Ready for Phase 5 planning.
Resume file: none — Phase 4's checkpoint and HANDOFF.json are retired
