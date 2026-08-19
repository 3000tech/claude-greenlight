# Requirements — v1.1 Remote Notifications

## v1.1 Requirements

### NOTIF — notification correctness

- [ ] **NOTIF-01**: An `idle_prompt` Notification event never produces the `needs_input` state — `needs_input` is reserved for real permission prompts (`permission_prompt`) and AskUserQuestion modals. A session that merely sits idle after a turn stays `waiting`. (User outcome: self-resuming loop sessions no longer page the user overnight — devbox log 2026-08-19 showed 45/45 overnight Notifications were `idle_prompt`, ~20 pushes sent, zero real requests.)
- [ ] **NOTIF-02**: A notification held by the background-tasks gate is released only when the session genuinely needs the user (real `needs_input`) or becomes fully idle per the ratified semantics — an idle ping no longer bypasses the hold (`gate_cleared` leak fixed).
- [ ] **NOTIF-03**: Every notification title carries the origin host — e.g. "Claude ready — nursy @ macbook-devbox" — on both the toast and the Telegram push, for local and remote sessions alike.

### REMOTE — devbox sessions on the PC overlay

- [ ] **REMOTE-01**: The PC overlay shows sessions running on the MacBook devbox alongside local ones, driven by the devbox's `~/.claude/monitor-state/*.json` (transport approach decided in the phase design discussion; state files already carry `hostname`; all devices share a tailnet).
- [ ] **REMOTE-02**: Remote sessions render with host-distinct identity and correct staleness: an unreachable or sleeping devbox never produces a false "ready", a false notification, or a ghost row.
- [ ] **REMOTE-03**: Each session has exactly one notification owner — no duplicate pushes from the PC monitor and the devbox headless monitor for the same event (coordination model decided in the design discussion).

### MOBILE — panel from the phone

- [ ] **MOBILE-01**: The user can open a read-only panel from the phone's browser over the private tailnet (stable Tailscale name, no external hosting, no public exposure) showing the same sessions and states as the desktop overlay.

### OPS — devbox maintenance

- [ ] **OPS-01**: The devbox greenlight installation runs current code (the live process predates v1.0) — updated and restarted with a documented procedure, or retired entirely if REMOTE-01's design makes the headless instance unnecessary.

## Future Requirements

- Alternative mobile push channels (ntfy, native push) — Telegram already reaches the phone
- V2-02: explicit "no data" UI treatment for hookless sessions (carried from v1.0)

## Out of Scope

- **Public/external hosting** of any panel — everything stays on the private tailnet by explicit user decision (2026-08-19)
- **Native mobile app** — browser page over Tailscale is the target
- **Packaging / pyproject / pipx** — still waiting for external-interest signal (backlog)
- **Local host (non-container) session visibility** — deferred at v1.0 close, unchanged
- **Monitor startup hook-presence check** — deferred at v1.0 close, unchanged

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| NOTIF-01 | Phase 4 | Pending |
| NOTIF-02 | Phase 4 | Pending |
| NOTIF-03 | Phase 4 | Pending |
| REMOTE-01 | Phase 5 | Pending |
| REMOTE-02 | Phase 5 | Pending |
| REMOTE-03 | Phase 5 | Pending |
| MOBILE-01 | Phase 6 | Pending |
| OPS-01 | Phase 6 | Pending |
