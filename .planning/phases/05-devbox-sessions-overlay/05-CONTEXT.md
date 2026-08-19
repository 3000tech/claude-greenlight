---
phase: 05-devbox-sessions-overlay
gathered: 2026-08-19
status: complete
mode: conversational   # design discussion held with the user before planning, per REMOTE-01's "transport TBD"
---

# Phase 5 Context — Devbox Sessions on the PC Overlay

The transport, ownership and serving model REMOTE-01/03 and MOBILE-01 deliberately left open
were decided with the user on 2026-08-19, in a design discussion held before planning.
These are LOCKED decisions — planning implements them, it does not revisit them.

## D-05-01 — Peer-to-peer, not hub-and-spoke (REMOTE-01)

Every participating machine runs the SAME optional component: a small read-only HTTP
endpoint exposing ITS OWN session state, plus a config list naming the peers it wants to
see. No "primary" and no "remote" role, no central aggregator.

Rejected alternatives, with reasons:
- **PC pulls over ssh per tick** — works, but needs per-pair key management and yields
  nothing reusable for MOBILE-01.
- **Devbox pushes to the PC** — an extra always-running sender that must know where the PC
  is; fails exactly when the PC (not the sender) is down.
- **Hub-and-spoke with the PC as hub (user's "Strada 1")** — the user's always-on machine is
  the devbox, not the PC; a PC-centred hub means no phone panel whenever the PC is off.
- **Asymmetric 1:1 (user's "Strada 2")** — the phone page served by the devbox would show
  only devbox sessions, failing MOBILE-01's "same sessions as the desktop overlay"; completing
  it collapses into D-05-01 anyway.

## D-05-02 — The endpoint binds to the private network only, read-only, state-only

- Binds to the machine's **Tailscale address** by default (peers reach it by MagicDNS name,
  e.g. `macbook-devbox:<port>`); it is not reachable from the internet, needs no router
  port-forwarding, and no external hosting is involved (hard user constraint, v1.1 scope).
- LAN fallback for users without a tailnet, documented honestly in the README as
  "exposed to your local network — trust it or put Tailscale in front".
- **Read-only**: it answers with data; it exposes no endpoint that DOES anything.
- **State only**: session state, timestamps, project label, machine name — never transcript
  or conversation content.
- Auth beyond tailnet membership (shared token) is explicitly a FUTURE option, not v1.1 scope.

## D-05-03 — Plug-and-play is preserved (user's OSS concern — a first-class constraint)

- A single-machine user changes NOTHING: clone, `monitor.bat`, done. No new required config,
  no ports, no daemons in the default path.
- Enabling remote costs exactly two gestures: one command on the machine that exposes
  (start the endpoint script, same shape as the existing optional `scripts/headless-linux.sh`)
  and one config line on the machine that watches (`"remotes": ["macbook-devbox"]`).
- The monitor core must NOT learn networking: it keeps consuming session state from a source,
  gaining only (a) additional sources, (b) the origin machine label (the `origin_host` seam
  from Phase 4), (c) unreachable-peer handling. The transport stays a separable, replaceable
  piece — a user syncing state files by any other means must still work.
- Standard library only (the project's zero-dependency promise holds).

## D-05-04 — Notification ownership (REMOTE-03)

- **Visual channels (toast, taskbar flash): the panel you are looking at.** The PC monitor
  raises toasts for every session it displays, including remote ones.
- **Telegram: only the session's home machine.** A session running on the devbox gets its
  Telegram push from the devbox instance, never from the PC. The PC therefore must STOP
  pushing Telegram for sessions whose origin is not itself — a local filter, not an
  inter-machine negotiation.
- Consequences accepted: no duplicates by construction; phone pushes keep working while the
  PC is off (the devbox is always on); a user with no always-on machine loses remote pushes
  when everything is off — documented in the README, not solved in code.

## D-05-05 — OPS-01 resolved in advance: the devbox instance stays

The headless greenlight on the devbox is NOT retired. Its role is now explicit: run the state
logic for its own sessions, own their Telegram pushes, and host the endpoint. Phase 6 documents
its final installation/rollout state.

## D-05-06 — Mobile serving follows for free (MOBILE-01, Phase 6)

Any machine running the endpoint can also serve the read-only phone page; because each machine
lists its peers, the page served by the always-on devbox shows the whole fleet. Phase 6 builds
the page; Phase 5 must not preclude it (same component, same data).

## Staleness and honesty (REMOTE-02)

An unreachable peer (asleep, off, tailnet down) must render as explicitly unreachable — never
as a stale-but-plausible row, never as a false "ready", never as a ghost. Existing v1.0
semantics (tombstones, heartbeat staleness, paused-container guard) must keep holding for
local sessions unchanged.
