# Requirements — Hook-Driven State Refactor

## v1 Requirements

### Instrumentation & Live Verification

- [x] **VER-01**: A logging hook records every Claude Code hook event (name + relevant payload fields + timestamp + session_id) to `~/.claude/hook-events.log`, installable alongside the existing hooks without disturbing them
- [x] **VER-02**: TEST-MATRIX.md verification columns are filled from live runs and a written hybrid verdict names, per hook-silent case, the fallback that covers it (user-assisted UAT for the live runs)

### State Writer (hooks side)

- [x] **SW-01**: Hooks write one state file per session (`~/.claude/monitor-state/<session_id>.json`) atomically (tmp + rename) on `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Notification`, `Stop`, `SessionEnd`
- [x] **SW-02**: Each state file carries `state`, `ts`, `cwd`, `last_event`, so the monitor can derive label mapping and staleness without reading the jsonl
- [x] **SW-03**: Existing working-lock / auq-lock hooks keep functioning unchanged while the state writer is rolled out (no regression during migration)

### Monitor Engine (Windows side)

- [x] **ENG-01**: `monitor.py --state-files` derives session state from `monitor-state/` as primary source
- [x] **ENG-02**: Shadow mode runs the state-file engine alongside legacy parsing and logs every divergence (session, tick, legacy verdict vs state-file verdict) without changing UI behavior
- [ ] **ENG-03**: Stale sessions are detected via heartbeat silence plus `docker ps` cross-check; a killed container never leaves a forever-grey session
- [ ] **ENG-04**: Corrupt, partial, or missing state files never crash the monitor; the session degrades to fallback or idle
- [ ] **ENG-05**: Sessions from hookless containers remain visible via per-session legacy parsing fallback
- [x] **ENG-06**: Verified hook-silent cases (per VER-02 verdict) are covered by targeted fallbacks; current async-work semantics (grey while bg shells/Monitors/agents run, badges intact) are preserved via shell_tracker

### Flip & Cleanup

- [ ] **FLIP-01**: After shadow validation, the state-file engine becomes the default and dead legacy parsing paths are removed
- [ ] **FLIP-02**: `test_monitor.py` covers the state-file engine (all behaviors that had tests keep equivalent coverage; state-file fixtures replace jsonl fixtures where legacy code was removed)
- [ ] **FLIP-03**: `hooks/install.sh`, the settings snippet, and README document the new architecture and hook requirements

## v2 Requirements

- [ ] **V2-01**: Rebuild bg-shell/Monitor badges from `PostToolUse` payloads instead of shell_tracker jsonl parsing
- [ ] **V2-02**: Explicit "no data" UI treatment for hookless sessions (instead of silent legacy fallback)

## Out of Scope

- Notification UX changes (debounce/timing) — early notify is by design; `Stop`-based detection improves it for free, nothing more
- Packaging / `src/` layout — separate backlog item
- Non-Windows hosts — outside the tool's niche

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| VER-01 | Phase 1 | Complete |
| VER-02 | Phase 1 | Complete |
| SW-01 | Phase 2 | Complete |
| SW-02 | Phase 2 | Complete |
| SW-03 | Phase 2 | Complete |
| ENG-01 | Phase 2 | Complete |
| ENG-02 | Phase 2 | Complete |
| ENG-03 | Phase 2 | Pending |
| ENG-04 | Phase 2 | Pending |
| ENG-05 | Phase 2 | Pending |
| ENG-06 | Phase 2 | Complete |
| FLIP-01 | Phase 3 | Pending |
| FLIP-02 | Phase 3 | Pending |
| FLIP-03 | Phase 3 | Pending |
