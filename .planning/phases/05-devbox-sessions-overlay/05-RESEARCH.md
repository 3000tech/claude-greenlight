# Phase 5: Devbox Sessions on the PC Overlay - Research

**Researched:** 2026-08-19
**Domain:** Tailscale-based state transport between two Python/tkinter monitor instances (stdlib only)
**Confidence:** MEDIUM — the codebase-facing findings are HIGH (read source this session); the Tailscale/OS-interaction findings are MEDIUM/LOW and explicitly flagged for live confirmation, since this container has no Tailscale daemon and no Windows/macOS to test against.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-05-01 — Peer-to-peer, not hub-and-spoke (REMOTE-01)**
Every participating machine runs the SAME optional component: a small read-only HTTP
endpoint exposing ITS OWN session state, plus a config list naming the peers it wants to
see. No "primary" and no "remote" role, no central aggregator.
Rejected: PC-pulls-via-ssh (key management, no reuse for mobile), devbox-pushes-to-PC
(fails when PC is down), hub-and-spoke on the PC (PC isn't the always-on machine),
asymmetric 1:1 (fails MOBILE-01's "same sessions" requirement).

**D-05-02 — The endpoint binds to the private network only, read-only, state-only**
Binds to the machine's Tailscale address by default (peers reach it by MagicDNS name,
e.g. `macbook-devbox:<port>`); not reachable from the internet, no port-forwarding, no
external hosting. LAN fallback for users without a tailnet, documented honestly as
"exposed to your local network — trust it or put Tailscale in front." Read-only: answers
with data, does nothing. State only: session state, timestamps, project label, machine
name — never transcript or conversation content. Auth beyond tailnet membership is a
FUTURE option, not v1.1 scope.

**D-05-03 — Plug-and-play is preserved (a first-class constraint)**
A single-machine user changes NOTHING: clone, `monitor.bat`, done. No new required
config, no ports, no daemons in the default path. Enabling remote costs exactly two
gestures: one command on the machine that exposes (start the endpoint script, same shape
as the existing optional `scripts/headless-linux.sh`) and one config line on the machine
that watches (`"remotes": ["macbook-devbox"]`). The monitor core must NOT learn
networking: it keeps consuming session state from a source, gaining only (a) additional
sources, (b) the origin machine label (the `origin_host` seam from Phase 4), (c)
unreachable-peer handling. The transport stays a separable, replaceable piece — a user
syncing state files by any other means must still work. Standard library only.

**D-05-04 — Notification ownership (REMOTE-03)**
Visual channels (toast, taskbar flash): the panel you are looking at fires for every
session it displays, including remote ones. Telegram: only the session's home machine —
the PC must STOP pushing Telegram for sessions whose origin is not itself (a local
filter, not inter-machine negotiation). No duplicates by construction; phone pushes keep
working while the PC is off; a user with no always-on machine loses remote pushes when
everything is off (documented, not solved in code).

**D-05-05 — OPS-01 resolved in advance: the devbox instance stays**
The headless greenlight on the devbox is NOT retired; it runs the state logic for its own
sessions, owns their Telegram pushes, and hosts the endpoint.

**D-05-06 — Mobile serving follows for free (MOBILE-01, Phase 6)**
Any machine running the endpoint can also serve the read-only phone page. Phase 5 must
not preclude it (same component, same data).

**Staleness and honesty (REMOTE-02)**
An unreachable peer (asleep, off, tailnet down) must render as explicitly unreachable —
never a stale-but-plausible row, never a false "ready", never a ghost. Existing v1.0
semantics (tombstones, heartbeat staleness, paused-container guard) must keep holding for
local sessions unchanged.

### Claude's Discretion
Not enumerated as a separate section in 05-CONTEXT.md — everything not explicitly locked
above (exact wire schema, exact timeout values, exact unreachable-grace-period length,
exact module layout) is open for this research to recommend and the planner to decide.

### Deferred Ideas (OUT OF SCOPE)
- Auth beyond tailnet membership (shared token) — explicitly future, not v1.1 (D-05-02).
- Public/external hosting of any panel (REQUIREMENTS.md "Out of Scope").
- Native mobile app (REQUIREMENTS.md "Out of Scope").
- Packaging / pyproject / pipx (backlog, REQUIREMENTS.md "Out of Scope").
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REMOTE-01 | PC overlay shows devbox sessions over the tailnet, driven by `~/.claude/monitor-state/*.json` | Q1 (address discovery/reachability), Q3 (endpoint architecture), Q6 (payload shape) |
| REMOTE-02 | Host-distinct identity, correct staleness; unreachable peer never fakes ready/notification/ghost | Q4 (non-blocking fetch), Q5 (error-to-verdict mapping), Q6 (age computed at origin) |
| REMOTE-03 | Exactly one notification owner per session; no duplicate pushes | Q6 (origin_host on the wire, feeds the existing D-05-04/Phase-4 filter — no new logic needed in this research, confirmed in Summary) |
</phase_requirements>

## Summary

This phase adds exactly one new capability to a codebase that already has the shape for
it: `scan_state_files()` already reads a per-session JSON verdict from
`~/.claude/monitor-state/*.json` (verified: `monitor.py:654-908`), and `notification_host()`
already has a **dormant** `origin_host` seam (verified: `monitor.py:1479-1501`, docstring:
"nothing writes it today, so every session this phase produces resolves to `local_name`").
Phase 5's whole job is: (a) get a second machine's state-file JSON onto the local machine
over Tailscale, (b) stamp it with `origin_host`, (c) feed it into the exact same rendering/
notification pipeline local sessions already use, and (d) make "peer unreachable" a first-
class, honest state — never a stale green dot.

The riskiest technical unknown is **not** the HTTP server (stdlib `http.server` in a daemon
thread is a well-worn, boring pattern) — it is **address discovery**: `tailscale` the CLI
binary is not reliably on `PATH` on Windows or on the macOS App Store build (both confirmed
via search this session), so the endpoint script needs a discovery fallback chain rather
than a bare `subprocess.run(["tailscale", "ip", "-4"])`. A pure-stdlib, no-subprocess
fallback exists (the classic "connect a UDP socket to a well-known peer, read back
`getsockname()`" trick, applied to Tailscale's fixed `100.100.100.100` MagicDNS address)
and should be the primary or co-primary method, not a last resort.

The second finding worth flagging early: `monitor.py` does `import tkinter as tk`
unconditionally at module scope (verified: `monitor.py:24`), while D-05-03 requires the
endpoint be "usable on machines that run no GUI monitor." A standalone endpoint script must
**not** `import monitor.py` directly — it would drag in a tkinter dependency the devbox
doesn't have natively (the whole reason `scripts/headless-linux.sh` exists is to bootstrap
tcl/tk there). The clean fix is extracting the tkinter-free state-reading logic
(`scan_state_files`, `scan`, `scan_containers`, and their constants — all module-level
functions living in lines 1-1784, before `class MonitorApp` starts at line 1785) into a
shared, dependency-free module both `monitor.py` and the new endpoint script import.

**Primary recommendation:** ship a standalone `scripts/session-endpoint.py`, sibling to
`scripts/headless-linux.sh` in spirit, built on `http.server.ThreadingHTTPServer` in the
main thread (it's a whole separate process — no tkinter, no daemon-thread needed there),
serving a small normalized JSON view read from a state module extracted out of
`monitor.py`'s current top of file; have `monitor.py` fetch peers via `urllib.request` in a
daemon thread mirroring `_kick_docker_query()`'s inflight-flag pattern exactly, with a
short (~2-3s) timeout well under the existing 5000ms tick; and treat every distinct
`urllib`/`socket` failure mode as one rendering verdict — "unreachable" — while logging the
distinct cause for debugging.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-session state verdict (working/waiting/needs_input) | Origin machine (state engine) | — | Only the origin machine has its own jsonl + docker evidence (D-02a/D-02b pinning); this can never be recomputed remotely without shipping transcript data, which D-05-02 forbids. |
| Serving state over the tailnet | Origin machine (endpoint script, new) | — | D-05-01: every machine runs the same optional component for its own state. |
| Peer discovery / config | Local machine (config file) | — | `"remotes": [...]` is user-supplied, read locally; no service discovery in v1.1. |
| Fetching + reconciling peer data | Watching machine (monitor.py, new fetch layer) | — | D-05-03: the monitor core gains "additional sources," not new server responsibilities. |
| Rendering / dot color / staleness aging | Watching machine (existing render pipeline) | Origin machine (pre-computed status) | Origin computes the per-session verdict; watching machine layers peer-reachability staleness on top (Q5/Q6). |
| Notification dispatch — visual (toast/flash) | Watching machine (whoever is looking) | — | D-05-04: fires per panel, not per origin. |
| Notification dispatch — Telegram | Origin machine only | — | D-05-04: local filter on the watching machine drops Telegram for non-self `origin_host`; the origin's own instance is what actually sends it. |

## Q1 — Tailscale address discovery, cross-platform

### Binary availability (the CLI is NOT reliably on PATH)

- **Windows:** the MSI installer places `tailscale.exe` under `C:\Program Files\Tailscale\`
  (confirmed via Tailscale's own docs/community reports in search results this session); it
  is **not** guaranteed to be added to the system `PATH` — several independent sources
  describe needing the full path or a manual `PATH` edit. `[CITED: tailscale.com/docs/install/windows/msi`
  and corroborating community reports]`
- **macOS:** there are three install variants (verified via search — "Three ways to run
  Tailscale on macOS," Tailscale docs). The **App Store / GUI variant** bundles the CLI
  inside the app bundle at `/Applications/Tailscale.app/Contents/MacOS/Tailscale` and does
  **not** put it on `PATH` by default — this is the variant most non-technical macOS users
  install. A **Homebrew** install (`brew install tailscale`) *does* land a `tailscale`
  symlink on `PATH` (typically `/opt/homebrew/bin` or `/usr/local/bin`). `[CITED: tailscale.com/docs/concepts/macos-variants]`
- **Linux:** package-manager installs (`apt`, etc.) put `tailscale` on `PATH` normally.
  `[ASSUMED — standard packaging convention, not independently re-verified this session]`

**Conclusion:** `shutil.which("tailscale")` will silently fail for a meaningful slice of
real users (any non-Homebrew Mac, plus any Windows user who didn't add it to PATH by hand).
A discovery chain that depends on the CLI as its *only* method is fragile precisely on the
two platforms this phase's live UAT will run against (Windows PC + MacBook devbox — see
`05-CONTEXT.md`'s explicit machine pairing).

### Fallback chain (recommended)

1. **`shutil.which("tailscale")` (and `"tailscale.exe"` on Windows) → `tailscale ip -4`**,
   `subprocess.run(..., timeout=3)`, parse the single line of stdout. Cheapest, most
   direct, when it works.
2. **Probe known fixed install paths** per OS when step 1 finds nothing:
   `C:\Program Files\Tailscale\tailscale.exe` (Windows),
   `/Applications/Tailscale.app/Contents/MacOS/Tailscale` (macOS App Store/GUI variant).
   `[ASSUMED — paths corroborated by multiple search snippets this session, not verified
   against an official "installed file layout" doc page]`
3. **Pure-stdlib UDP-connect trick, no subprocess dependency at all** — the classic idiom
   for "what's my outbound-facing local IP for destination X" (connecting a `SOCK_DGRAM`
   socket sends no packets, it only makes the kernel pick a route/source address):
   ```python
   import socket
   def tailnet_self_ip() -> str | None:
       # 100.100.100.100 is Tailscale's fixed MagicDNS resolver address, served on the
       # tailscale0/utun interface whenever tailscaled is up and routing the tailnet CGNAT
       # range — so the kernel's route lookup for it always resolves through the tailnet
       # interface, and getsockname() reports that interface's own 100.x address back.
       try:
           s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
           s.connect(("100.100.100.100", 80))
           ip = s.getsockname()[0]
           s.close()
           return ip if ip.startswith("100.") else None
       except OSError:
           return None
   ```
   `[ASSUMED — this is applied networking reasoning about Tailscale's documented fixed
   MagicDNS address (100.100.100.100 is CITED: tailscale.com/docs/features/magicdns), not a
   pattern independently verified against an official Tailscale doc recommending it. Needs
   live confirmation on a real tailnet-joined machine before being trusted as the primary
   method.]`
4. **Bind `0.0.0.0` and skip self-IP discovery for the bind call entirely** — this is
   explicitly the documented LAN fallback in D-05-02 ("LAN fallback for users without a
   tailnet, documented honestly... exposed to your local network"), not a failure mode to
   hide — the endpoint script should print which mode it ended up in.
5. **Interface enumeration via raw stdlib `socket`** was considered and is **not**
   recommended as a step in this chain: pure-stdlib Python has no cross-platform "list all
   interfaces with their assigned IPs" primitive (no `getifaddrs` wrapper, no `ipconfig`/`
   ip addr` parsing without external processes) — building one would mean re-implementing
   a chunk of what `netifaces`/`psutil` do, both third-party and both banned by the
   zero-dependency promise. Steps 1-4 above cover the realistic cases without it.

### Reaching a peer (MagicDNS vs raw IP)

MagicDNS integrates with the **OS resolver**, not with the application: once enabled,
Tailscale is always the first entry in the machine's DNS search domains, and unqualified
names resolve through the normal OS stub resolver `[CITED: tailscale.com/docs/features/magicdns]`.
Python's `socket.getaddrinfo()` (which `urllib.request` calls internally) goes through that
same OS resolver — **no Tailscale-aware code is needed in Python** to resolve
`macbook-devbox` from a tailnet-joined Windows box, as long as MagicDNS is actually working
at the OS level. One documented exception surfaced in search: **domain-joined Windows
machines with "Override DNS servers" enabled** can fail to prioritize the tailnet search
domain correctly `[CITED: github.com/tailscale/tailscale#18712]` — an edge case unlikely to
affect a personal devbox pairing but worth a one-line README caveat.

**Recommendation:** support both `"remotes": ["macbook-devbox"]` (MagicDNS short name, the
CONTEXT.md example) and a literal `100.x.x.x` IP in the same config field — both flow
through the same `urllib`/`getaddrinfo` code path with no branching required, so supporting
the IP form costs nothing and is the escape hatch for the domain-joined-Windows edge case.
Discover the **local** bind address with the chain above (steps 1-4); do **not** try to
discover peer IPs — always resolve peers by whatever string the user put in `"remotes"`.

## Q2 — Windows firewall reality check

**Needs live confirmation** — this container has no Windows host to test against. Based on
search this session:

- Tailscale's own Windows adapter is categorized **"Private"** network by default
  (confirmed indirectly: there is an open feature request asking Tailscale to *allow*
  installing as "public network," implying "private" is the shipped default)
  `[CITED: github.com/tailscale/tailscale#14708]`.
- Windows Firewall's "allow this app" prompt is scoped by **(executable, network profile)**,
  not by which specific IP/interface a listen socket is bound to — general Windows
  networking knowledge, corroborated by search results describing the prompt firing "when a
  Python application first attempts to bind a socket to a port accessible from the
  network." This means: **binding to the specific Tailscale IP instead of `0.0.0.0` does
  NOT, by itself, avoid the prompt** — the prompt is driven by the fact the listen is
  reachable on a non-loopback address within a given profile (here, Private), not by which
  specific address string was passed to `bind()`. `[ASSUMED — reasoned from general Windows
  Filtering Platform behavior, not independently verified against a live Windows box this
  session.]`
- If the same executable (`python.exe`, or a future packaged `monitor.exe`) has *already*
  been granted a "Private networks" firewall exception for some other reason (e.g. earlier
  LAN use), Windows Firewall rules are typically **profile-scoped, not adapter-scoped** — so
  a new bind on the Tailscale adapter (also categorized Private) would likely reuse that
  existing exception rather than trigger a second prompt. This is the mechanism, if true,
  behind a plausible "two gestures, no configuration" experience — but this specific claim
  is the one most in need of live confirmation, since it depends on exact WFP rule scoping
  that varies by how the exception was originally granted (per-app vs per-port vs
  per-profile). `[ASSUMED]`

**Recommendation:** write the README section honestly — "the first time you start the
endpoint script, Windows will likely show one firewall prompt; choose 'Private networks',
never 'Public'" — and treat the "no second prompt on a fresh machine" claim as unverified
until the user tests it live on the real Windows PC, per the task's own instruction to flag
Windows behavior for live confirmation rather than guess. Do not promise zero prompts.

## Q3 — stdlib HTTP server pattern

`http.server.ThreadingHTTPServer` is a small, boring stdlib class (`HTTPServer` +
`socketserver.ThreadingMixIn`) — appropriate for this job: read-only, low request volume
(a handful of tick-driven peers polling every few seconds), no need for anything heavier.
Key setup points, all standard library documented behavior:

- `HTTPServer.allow_reuse_address` is `1` by default (inherited from
  `socketserver.TCPServer`, overridden true specifically on `HTTPServer`), so a
  restart-after-crash doesn't hit `OSError: [Errno 98] Address already in use` from a
  lingering `TIME_WAIT` socket — no extra code needed. `[ASSUMED — standard, well-known
  library behavior; not re-verified against the exact cpython source line this session.]`
- `ThreadingMixIn.daemon_threads = True` should be set explicitly so per-request handler
  threads don't block process exit.
- One slow/hanging client must not stall others: `ThreadingHTTPServer` already handles each
  connection on its own thread, so this is inherent — but the **handler itself** should set
  a socket timeout on accepted connections (`self.request.settimeout(N)` in the handler, or
  `BaseServer.timeout`) so a client that connects and never sends a request doesn't pin a
  thread forever. Given this is a *read-only, no-auth* endpoint on a private network, a
  generous but bounded timeout (e.g. 10s) is sufficient defense.
- Clean shutdown: run `serve_forever()` on its own thread/process (see below), call
  `server.shutdown()` (thread-safe, stops `serve_forever()`'s loop) followed by
  `server.server_close()` (releases the listening socket) on the way out.

### Standalone script vs. embedding in monitor.py

**D-05-03 already locks this as a standalone script** ("start the endpoint script, same
shape as the existing optional `scripts/headless-linux.sh`") — this section documents *why*
that's also the technically correct choice, not just the mandated one:

- **Verified blocker for embedding:** `monitor.py` does `import tkinter as tk`
  unconditionally at module scope (`monitor.py:24`), even though the module-level state-
  reading functions (`scan_state_files`, `scan`, `scan_containers`, `load_config`, and the
  constants block) are all defined *before* `class MonitorApp` starts at `monitor.py:1785`
  and never touch tkinter themselves. Any script that does `import monitor` to reuse those
  functions inherits the tkinter import — which fails or requires the same tcl/tk
  bootstrap `scripts/headless-linux.sh` exists specifically to provide on a headless box
  like the devbox. This directly conflicts with D-05-03's "usable on machines that run no
  GUI monitor."
- **Recommendation:** extract the tkinter-free logic (state constants, `scan_state_files`,
  `scan`, `scan_containers`, `load_config`/`DEFAULT_CONFIG`, `notification_host`,
  `local_machine_name`, `session_display_name`, `derive_alias_key`, and their supporting
  helpers) into a new module — e.g. `session_state.py` — with **zero** tkinter, zero GUI
  imports. `monitor.py` imports from it (no behavior change, pure move); the new endpoint
  script imports from it too, and never imports `monitor.py`. This is a mechanical
  extraction of existing, already-well-tested logic — not a rewrite — and is the concrete
  shape of D-05-03's "the transport stays a separable, replaceable piece."
- The endpoint script itself needs no threading trick: it's a dedicated process, so
  `server.serve_forever()` can run directly on its main thread (optionally after a
  `signal.signal(SIGINT/SIGTERM, ...)` handler calls `server.shutdown()` from a second
  thread, since `shutdown()` must not be called from the same thread running
  `serve_forever()`).

## Q4 — Client side without freezing the UI

`_kick_docker_query()` (`monitor.py:2676-2701`) is the exact pattern to mirror:

```python
# monitor.py:2676-2701, verified this session
def _kick_docker_query(self) -> None:
    if self._docker_query_inflight:
        return
    self._docker_query_inflight = True
    def worker() -> None:
        try:
            rows, label_map, sid_map, container_info, hostname_to_name = scan_containers()
        except Exception:
            self._first_docker_done = True
            self._docker_query_inflight = False
            return
        self._cached_containers = rows
        # ... caches assigned ...
        self._first_docker_done = True
        self._docker_query_inflight = False
    threading.Thread(target=worker, daemon=True).start()
```

`refresh()` (`monitor.py:2703` on, tkinter `after(REFRESH_MS, self.refresh)`-driven, where
`REFRESH_MS = 5000` — verified `monitor.py:139`) calls `_kick_docker_query()` unconditionally
every tick; the inflight flag makes repeated calls a no-op while a worker is still running,
and the **tick always renders from whatever is already cached**, never blocking on the
worker. This is precisely the shape a peer-fetch needs.

**Recommended mirror, per peer:**
```python
def _kick_peer_fetch(self, host: str) -> None:
    if self._peer_fetch_inflight.get(host):
        return
    self._peer_fetch_inflight[host] = True
    def worker() -> None:
        try:
            with urllib.request.urlopen(f"http://{host}:{PEER_PORT}/sessions",
                                         timeout=PEER_FETCH_TIMEOUT_SEC) as r:
                data = json.loads(r.read())
            self._peer_cache[host] = (time.time(), data, None)   # (fetched_at, payload, error)
        except Exception as e:
            self._peer_cache[host] = (time.time(), None, e)
        finally:
            self._peer_fetch_inflight[host] = False
    threading.Thread(target=worker, daemon=True).start()
```
called once per configured `"remotes"` entry, every `refresh()` tick, same as
`_kick_docker_query()` — no new poll-interval machinery needed.

**Timeouts:** `urllib.request.urlopen(req, timeout=N)` sets a single socket timeout applied
to the connection attempt *and* to each subsequent blocking read — it is not a separate
connect-vs-read pair, and it is not a hard wall-clock budget across retries (Python does not
retry urlopen automatically). `[ASSUMED — standard, well-documented urllib/http.client
behavior.]` Recommend `PEER_FETCH_TIMEOUT_SEC ≈ 2-3` — comfortably under the 5000ms
(`REFRESH_MS`) tick interval, so a worst-case stalled fetch resolves (success or timeout)
well before the *next* tick would even consider kicking a new one for that peer, and the
inflight flag prevents pile-up regardless. A sleeping/off peer typically fails fast
(connection refused or host-unreachable) rather than hanging the full timeout — see Q5 — so
2-3s is a ceiling, not the common case.

## Q5 — Unreachable-peer semantics (REMOTE-02)

| Exception raised | Meaning | Verdict for this session-set |
|---|---|---|
| `socket.gaierror` (wraps into `urllib.error.URLError`) | hostname doesn't resolve — MagicDNS off/broken locally, tailnet down on the watching machine, or the peer name was mistyped/never joined | Unreachable — "name not found" |
| `ConnectionRefusedError` (subclass of `OSError`, wraps into `URLError`) | peer's IP answered but nothing is listening on the port — endpoint script not running on that machine, or it crashed | Unreachable — "endpoint not running" |
| `socket.timeout` / `TimeoutError` (wraps into `URLError`) | connect attempt got no response inside the budget — peer machine asleep/powered off, or Tailscale route stalled | Unreachable — "not responding" |
| `OSError` for "no route to host" / network unreachable | Tailscale interface down locally, or route to the peer's CGNAT prefix missing | Unreachable — "no route" |
| Non-200 HTTP status (`urllib.error.HTTPError`) | endpoint process alive but returned an error | Unreachable — treat the body as untrustworthy |
| 200 response but `json.JSONDecodeError` / schema check fails | endpoint alive, payload malformed (version skew, partial write caught mid-response) | Unreachable-with-distinct-log-tag — same rendering verdict, but log this case separately from network failures for debugging (it points at a code bug, not sleep/network) |

**Recommendation:** collapse all rows above to **one rendering verdict** — "peer
unreachable" — for REMOTE-02's purposes (never a false ready, never a ghost, never a stale
green dot is the actual requirement; the user doesn't need six different unreachable icons).
Keep the distinct exception class in the log line only, so a real bug (schema drift) is
debuggable separately from ordinary "the devbox is asleep." This directly satisfies
REMOTE-02's phrasing: "an unreachable or sleeping devbox never produces a false 'ready', a
false notification, or a ghost row" — every failure path above produces the same safe,
explicit "unreachable" outcome, never silence and never a stale render.

**Grace period before flipping to explicit-unreachable:** `[ASSUMED — not specified in
05-CONTEXT.md, Claude's-discretion territory]`. Recommend: on the **first** fetch failure
for a peer, keep the last-known-good session rows visible but visually distinct (e.g. a
"last seen HH:MM" annotation, not a fresh green dot) rather than blanking instantly — a
single dropped tick over a flaky tailnet path shouldn't flicker the whole panel. After **2
consecutive** fetch failures for that peer (roughly 10s at the ~5s tick cadence, well short
of the existing `STATE_HEARTBEAT_STALE_SEC = 600` used for same-machine staleness — verified
`monitor.py:78` — because network unreachability is a much stronger and faster signal than
"no heartbeat yet"), replace the peer's rows entirely with one explicit
"`macbook-devbox` unreachable since HH:MM" placeholder row and suppress any notification
sourced from that peer's last-known data. This threshold is a proposal for the planner to
confirm with the user during `/gsd-discuss-phase` follow-up or plan review, not a locked
number.

## Q6 — Payload shape

### What the endpoint returns: a computed view, not the raw state files verbatim

This is the one place this research diverges from the "simplest possible" instinct (ship
the state-file JSON as-is) and the reasoning matters: `scan_state_files()`'s staleness
recovery (the heartbeat/prompt windows, and especially the D-02a/D-02b pinning fallbacks
documented in its own docstring, `monitor.py:654-748`) depends on `legacy_sessions` —
evidence read from **that machine's own jsonl files** (`working_locked`, `agent_activity`,
jsonl `mtime` advancement). D-05-02 forbids shipping transcript/jsonl content over the wire
("state only... never transcript or conversation content"), so that evidence can never
travel to the watching machine. **Therefore the origin machine must run its own full
`scan_state_files()` verdict locally (it already does, every tick) and the endpoint serves
the *already-resolved* `status`/`state` — not the raw per-event fields alone** — because the
watching machine has no way to correctly re-derive the D-02a/D-02b-pinned verdict without
the jsonl evidence it's structurally forbidden from receiving.

### Cross-machine clock skew

`_state_record_age()` (`monitor.py:621-651`) already guards against **container-clock vs.
host-clock** skew on a single machine (`STATE_CLOCK_SKEW_GUARD_SEC`, one-directional). Phase
5 introduces a **new** skew axis that v1.0 never had: two different physical machines' wall
clocks. The fix is the same shape as the existing guard, applied one level up: **the origin
computes `age_sec` using its own clock before serializing**, and the watching machine treats
that number as authoritative rather than diffing a shipped absolute timestamp against its
own `time.time()`. Absolute timestamps (`ts`, `generated_at_ms`) should still ride along for
logging/debugging, but nothing on the watching side should subtract two different machines'
wall-clock values to compute a verdict.

### Key collision

Session IDs are Claude Code-issued UUIDs — two machines colliding on a raw `session_id` is
not a realistic risk. The collision REMOTE-01/ROADMAP SC#2 actually cares about is
**label/grouping** collision: a devbox `nursy` and a local `nursy` sharing the same project
label, and — more subtly — `notification_group_key()` (`monitor.py:1315`, consumes `cwd`)
potentially grouping two *different machines'* sessions together if both happen to run a
container at the same `cwd` (e.g. both mount a project at `/workspace`). **Recommendation:**
fold `origin_host` into the render key and into any grouping/alias key used for remote rows,
so the receiving side's rendering pipeline treats `(origin_host, session_id)` as the true
identity, not `session_id` alone.

### Container-derived display info

Project labels (`name`/`display_name`, resolved today via `launcher_order()` and
`session_display_name()`, which needs `hostname_to_name` from `scan_containers()`'s own
`docker` query) **must travel with the payload, computed at the origin** — the watching
machine has no visibility into the origin's docker daemon at all, so these cannot be
"resolved locally" the way local sessions do. This is: labels travel as opaque display
strings; only rendering (color, layout) happens locally.

### Proposed JSON schema

```json
{
  "schema_version": 1,
  "origin_host": "macbook-devbox",
  "generated_at_ms": 1755612727123,
  "sessions": [
    {
      "session_id": "9f2c1a7e-...",
      "name": "nursy",
      "display_name": "nursy",
      "status": "WAITING",
      "state": "waiting",
      "last_event": "Stop",
      "container_hostname": "e3f1a2b9c7d4",
      "cwd": "/workspace",
      "background_tasks_count": 0,
      "age_sec": 12.4,
      "alias_key": "host:e3f1a2b9c7d4"
    }
  ]
}
```

- `schema_version` — forward-compat field; the watching machine should reject/ignore a
  payload whose `schema_version` it doesn't recognize rather than guess at its shape (fail
  toward "unreachable," per Q5, not toward a garbled render).
- `origin_host` — matches the Phase 4 `origin_host` seam name exactly
  (`notification_host()`, `monitor.py:1479-1501`) so the watching machine's existing
  stamping logic needs no translation layer.
- `container_hostname` — deliberately **renamed** from the in-memory session dict's
  `hostname` key (`monitor.py:889-908`, quoted below) to avoid colliding with the
  top-level `origin_host`/machine-identity concept on the wire; the receiving code maps it
  back to whatever local key name the render pipeline expects.
- Fields deliberately **omitted** from the wire: `dot`, `dot_color`, `rank`, `mtime`,
  `key`, `action`, `encoded_dir` — all are either purely derivable from `status` (recompute
  locally via the same `_state_to_status()`-equivalent logic, DRY) or meaningless off the
  origin machine (`mtime`, `encoded_dir`).

Verbatim source fields this schema is built from — `scan_state_files()`'s session dict,
`monitor.py:889-908`:
```
"key": session_id, "name": name, "session_id": session_id, "encoded_dir": "",
"dot": dot, "dot_color": color, "status": status, "rank": rank, "age": age,
"mtime": mtime, "action": _state_action_label(last_event), "state": state_val,
"last_event": last_event, "hostname": obj.get("hostname"), "cwd": cwd,
"background_tasks_count": bg_count, "alias_key": derive_alias_key(hostname, session_id),
"display_name": session_display_name(name, hostname, hostname_to_name),
```
and the raw state-file record `hooks/state-writer.sh:258-266` writes on disk:
```
{
    state: $state, ts: $ts, ts_ms: $ts_ms, cwd: ($payload.cwd // ""),
    hostname: $hostname, last_event: $last_event,
    background_tasks_count: $background_tasks_count
}
```

### Config shape

`DEFAULT_CONFIG` (`monitor.py:197-221`, verified) currently has no `remotes` key:
```
{
    "mode": "standard", "standard": "", "compact": "", "local": True,
    "telegram": True, "aliases": {}, "machine_name": "",
}
```
This phase adds `"remotes": []` (list of hostnames/IPs) as a new key, following the exact
pattern `load_config()` (`monitor.py:224-256`) already uses for sanitizing/defaulting other
keys (type-check, strip, drop invalid entries) — no new config-loading architecture needed.

## Q7 — Prior art / pitfalls

- **No specific named OSS tool doing exactly this (small Python GUI + stdlib HTTP + Tailscale
  peer state) was found via search this session.** The closest adjacent category is
  "homelab dashboards over Tailscale" (Tailscale Serve/Funnel-fronted services, general
  self-hosted dashboard tools) — none of these are a close enough match to cite as a
  pattern source; this phase's design is closer to novel-but-boring than "follow this
  library." `[LOW confidence — absence of evidence, not evidence of absence; flagging
  honestly rather than fabricating a citation.]`
- **Tailscale Serve vs Funnel — Funnel is out of scope, correctly.** `tailscale serve`
  exposes a local port to tailnet peers only (matches this phase's model exactly — but is a
  `tailscaled`-level feature requiring the Tailscale CLI/daemon to configure, not something
  this project's Python code drives); `tailscale funnel` additionally exposes it to the
  **public internet**, explicitly forbidden by REQUIREMENTS.md's "Out of Scope" section and
  D-05-02. `[CITED: tailscale.com/docs/features/tailscale-serve,
  tailscale.com/docs/features/tailscale-funnel]`. Worth a one-line README mention ("do not
  use `tailscale funnel` on this port") precisely because Funnel is a two-word command away
  from accidentally punching this read-only endpoint onto the public internet.
- **The tkinter-import landmine (Q3) is the single most consequential pitfall found this
  session** — verified via direct source read, not search.
- **Windows Firewall behavior is a genuine known-unknown** (Q2) — the research found
  plausible, internally-consistent reasoning but nothing that substitutes for testing on
  the real Windows PC named in `05-CONTEXT.md`'s own UAT plan.
- **`urllib`'s single timeout parameter** (Q4) is a minor but real gotcha: teams
  accustomed to `requests`' separate `(connect_timeout, read_timeout)` tuple sometimes
  assume stdlib `urllib` has the same, and it does not.

## Package Legitimacy Audit

Not applicable — this phase adds zero external packages by design (D-05-03: "Standard
library only"). No `npm view`/`pip index`/`cargo search` verification was needed; the
Package Legitimacy Gate is satisfied trivially by having nothing to check. If the planner
later considers any third-party convenience (it should not, per the locked constraint),
that would require a fresh legitimacy check at that time.

## Runtime State Inventory

Not applicable — this is new-capability work (a new endpoint script, a new fetch layer, a
new config key), not a rename/refactor/migration phase. No existing runtime state (state
files, config keys, OS registrations) is being renamed or relocated.

## Common Pitfalls

### Pitfall 1: Importing `monitor.py` from the standalone endpoint script
**What goes wrong:** the endpoint process fails to start (or silently requires the tcl/tk
bootstrap) on a headless machine.
**Why it happens:** `monitor.py:24` does `import tkinter as tk` unconditionally at module
scope, even though the functions the endpoint needs (`scan_state_files`, `scan`,
`scan_containers`) never touch tkinter.
**How to avoid:** extract the tkinter-free logic into a shared module (see Q3) before
building the endpoint script; never `import monitor` from it.
**Warning signs:** `ModuleNotFoundError: No module named '_tkinter'` or a hang waiting on a
`DISPLAY` that doesn't exist, on a machine that has no GUI monitor running.

### Pitfall 2: Trusting the remote machine's absolute timestamps directly
**What goes wrong:** staleness math comes out wrong (either always-fresh or always-stale)
whenever the two machines' clocks drift, even slightly.
**Why it happens:** v1.0's `_state_record_age()` clock-skew guard only ever had to reconcile
a container clock against its own host's clock — same machine, small skew. Phase 5
introduces two genuinely independent wall clocks.
**How to avoid:** compute `age_sec` on the origin machine, before serialization (see Q6);
never subtract a remote absolute timestamp from `time.time()` on the watching machine to
derive a verdict.
**Warning signs:** a peer that's actually fine intermittently renders stale, or a genuinely
dead peer's last cached data never ages out.

### Pitfall 3: `tailscale funnel` on the endpoint's port
**What goes wrong:** the read-only, tailnet-only endpoint becomes reachable from the public
internet.
**Why it happens:** `tailscale funnel <port>` is a single, easy-to-run command, and its
name doesn't obviously scream "this is different from `serve`" to a user skimming docs.
**How to avoid:** one explicit README line: never `tailscale funnel` this port.
**Warning signs:** none from inside this codebase — this is a config-time human error, not
something the code can detect. Document it.

## Environment Availability

| Dependency | Required By | Available (this container) | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Tailscale daemon/CLI | Address discovery, MagicDNS resolution | ✗ (this Linux dev container has no Tailscale) | — | LAN-bind fallback (D-05-02); UAT happens live on the real Windows PC + MacBook devbox |
| Windows 10/11 | Firewall-prompt behavior (Q2) | ✗ | — | Live confirmation required; cannot be simulated here |
| macOS | CLI-path variant behavior (Q1) | ✗ | — | Live confirmation required on the MacBook devbox |
| Python 3.10+ stdlib (`http.server`, `urllib`, `socket`) | Everything in this phase | ✓ | Container ships Python 3, README requires 3.10+ | — |

**Missing dependencies with no fallback:** none — every gap above has either a documented
LAN-bind fallback or is explicitly deferred to the live UAT already planned in
`05-CONTEXT.md`/ROADMAP.md's Phase 5 success criterion #5.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Windows MSI installer doesn't reliably add `tailscale.exe` to PATH | Q1 | Low — discovery chain already has fallback steps; worst case, more fallback steps get exercised than expected |
| A2 | macOS App Store/GUI Tailscale variant's CLI isn't on PATH by default | Q1 | Low — same as A1 |
| A3 | UDP-connect-to-100.100.100.100 reliably yields the local tailnet IP | Q1 | Medium — if wrong, this method silently returns a non-tailnet local IP; must be live-tested before being trusted as primary, keep the CLI-based methods as co-primary until confirmed |
| A4 | Windows Firewall exceptions are profile-scoped (Private), not per-adapter, so a Tailscale-adapter bind reuses an existing Private exception | Q2 | Medium — if wrong, every fresh Windows install could show a firewall prompt on first endpoint start; affects the "two gestures, no configuration" promise's honesty, not correctness — worth explicit live UAT confirmation |
| A5 | `urllib.request.urlopen(timeout=N)` applies to connect attempt and each read, not a combined wall-clock budget | Q4 | Low — well-documented stdlib behavior; low risk of being wrong |
| A6 | Grace period of 2 consecutive failed fetches before "explicit unreachable" | Q5 | Low-Medium — a UX tuning choice, not a correctness risk; easy to adjust post-UAT |
| A7 | `HTTPServer.allow_reuse_address` defaults to `1` | Q3 | Low — standard, widely-documented cpython behavior |

**If this table is empty:** N/A — see entries above; every claim not backed by a source
read this session or an official-docs citation is logged here.

## Open Questions

1. **Exact peer-unreachable grace period (A6 above).**
   - What we know: the existing local-staleness precedent is 600s (`STATE_HEARTBEAT_STALE_SEC`), clearly too long for network-reachability detection, which fails much faster and more definitively.
   - What's unclear: whether 2 consecutive ticks (~10s) is the right balance between "don't flicker on one flaky packet" and "don't show stale-looking data too long."
   - Recommendation: ship the 2-tick default, treat it as tunable, confirm during live UAT on the real devbox sleep/wake cycle (already planned per ROADMAP Phase 5 success criterion #5).

2. **Windows Firewall prompt count on a genuinely fresh machine (A4 above).**
   - What we know: general WFP profile-scoping behavior, reasoned but not tested.
   - What's unclear: whether the user's actual Windows PC shows zero, one, or a prompt-per-restart.
   - Recommendation: test explicitly during the phase's live UAT; write the README claim only after that's observed, not before.

## Validation Architecture

### Test Framework

Not yet independently confirmed this session beyond what's visible in the repo layout;
`docs/TEST-MATRIX.md` (referenced by CLAUDE.md) is the project's existing verification
discipline for the state engine, and v1.0's phases each closed with live user-assisted UAT
rather than a Python unit-test suite for the tkinter/OS-integration surface — the same
pattern this phase's design (D-05, ROADMAP success criterion #5: "Live UAT on the real pair")
already commits to. No `pytest`/`unittest` config file was located in this pass; the planner
should confirm during planning whether any exists before assuming none does.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REMOTE-01 | Devbox sessions appear in PC overlay | integration (2-process, same box) | run endpoint script + monitor.py against a fabricated `~/.claude/monitor-state/*.json` fixture, assert the rendered session list includes the remote row | ❌ Wave 0 |
| REMOTE-02 | Unreachable peer never fakes ready/notification/ghost | unit | exercise the fetch-error → verdict mapping (Q5's table) against mocked `urllib` exceptions | ❌ Wave 0 |
| REMOTE-03 | Exactly one notification owner | unit | assert the existing `notification_host()`/Telegram-filter logic drops pushes for non-self `origin_host` once `origin_host` is populated by this phase | ❌ Wave 0 (extends Phase 4's own test additions) |
| REMOTE-01/02 | Live cross-machine behavior | manual/live UAT | real Windows PC + MacBook devbox, sleep/wake cycle | ❌ — inherently manual, already scoped as ROADMAP success criterion #5 |

### Sampling Rate
- Per task commit: run whatever fast unit coverage the plan adds for the fetch-error
  mapping and payload schema validation.
- Per wave merge / phase gate: the live UAT described in ROADMAP Phase 5 success criterion
  #5 is the actual gate — this phase cannot be called done from automated tests alone,
  matching v1.0's precedent (referenced throughout this file as "same discipline as v1.0").

### Wave 0 Gaps
- [ ] A fixture generator for a fabricated remote `monitor-state/*.json` file (or a small
      HTTP mock server) so the fetch/reconcile logic can be tested without a real second
      machine.
- [ ] Unit coverage for the Q5 error-to-verdict mapping table.
- [ ] Unit coverage for the Q6 schema (`schema_version` mismatch handling, `origin_host`
      stamping, `container_hostname` field mapping).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No (explicit v1.1 scope decision) | D-05-02: "Auth beyond tailnet membership... is explicitly a FUTURE option" — tailnet membership itself is the access control boundary for v1.1 |
| V3 Session Management | No | No user sessions; the endpoint is stateless request/response |
| V4 Access Control | Partial | Bind-address selection (Tailscale-only by default, LAN fallback documented) is the access control mechanism, not an app-layer check |
| V5 Input Validation | Yes | The endpoint accepts no input beyond the HTTP request line/headers (read-only, no query params consumed for data selection); the *watching* machine must validate the JSON it receives (`schema_version` check, type-check every field before rendering) per Q6 |
| V6 Cryptography | No | Plain HTTP over the tailnet's own WireGuard-encrypted tunnel; Tailscale provides transport encryption, the app adds none and needs none for v1.1 scope |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/oversized JSON response from a "peer" (compromised or buggy) crashing the watching monitor | Tampering / DoS | `json.loads` wrapped in `try/except`, `schema_version` check, per-field type checks before use — same defensive posture `_read_state_file()` (`monitor.py:556-572`) already uses for on-disk records, applied to network input too |
| A malicious LAN device impersonating a peer hostname (LAN fallback mode, no tailnet) | Spoofing | Out of scope for v1.1 per D-05-02's documented honesty ("exposed to your local network — trust it or put Tailscale in front"); no additional mitigation planned, matches locked scope |
| `tailscale funnel` accidentally exposing the endpoint publicly | Information Disclosure | Documentation only (Pitfall 3 above) — not enforceable from this project's code |
| Endpoint used to fingerprint project names/paths by an unintended tailnet member | Information Disclosure | Tailnet ACLs are the user's own responsibility (out of scope for this project); the endpoint's D-05-02 "state only" rule already minimizes what's exposed (no transcript, no commands) |

## Sources

### Primary (HIGH confidence — read this session)
- `monitor.py` (this repo) — `scan_state_files()` lines 654-935, `select_render_sessions()`
  lines 938-951, `local_machine_name()`/`notification_host()` lines 1451-1501,
  `_send_telegram()` lines 2497-2532, `_kick_docker_query()`/`refresh()` lines 2676-2820,
  `DEFAULT_CONFIG`/`load_config()` lines 197-263, constants lines 71-175, imports lines
  1-25, `class MonitorApp` start line 1785.
- `hooks/state-writer.sh` (this repo) — full file, event-to-state mapping and the state
  record's exact field set (lines 258-266).
- `scripts/headless-linux.sh` (this repo) — full file, the sibling shape D-05-03 asks the
  new endpoint script to match.
- `.planning/phases/05-devbox-sessions-overlay/05-CONTEXT.md`,
  `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md` (this repo).

### Secondary (MEDIUM confidence — official docs via search)
- tailscale.com/docs/features/magicdns, tailscale.com/docs/concepts/macos-variants,
  tailscale.com/docs/install/windows/msi, tailscale.com/docs/features/tailscale-serve,
  tailscale.com/docs/features/tailscale-funnel.
- github.com/tailscale/tailscale issues #18712 (domain-joined Windows MagicDNS search-domain
  precedence) and #14708 (Windows adapter defaults to Private network category).

### Tertiary (LOW confidence — search-only, reasoned/applied, not independently verified)
- Windows Firewall profile-scoping behavior for a Tailscale-adapter bind (Q2) — flagged
  throughout for live confirmation.
- The UDP-connect-to-100.100.100.100 self-IP discovery trick's reliability on a real
  tailnet (Q1, A3).
- Fixed install-path locations for `tailscale.exe`/`Tailscale.app` (Q1) — corroborated by
  multiple independent search snippets but not fetched from a single canonical "file
  layout" doc page.

## Metadata

**Confidence breakdown:**
- Codebase-facing findings (existing seams, patterns, exact field names): HIGH — read
  source directly this session, line-cited.
- Tailscale/OS-interaction findings (discovery chain, firewall behavior): MEDIUM/LOW —
  search-corroborated but explicitly unverified against a live Windows/macOS machine;
  flagged for live UAT per the task's own instruction.
- Wire schema / grace-period proposals: design recommendations grounded in verified
  codebase constraints, not external fact-claims — treat as planner input, not locked
  decisions (05-CONTEXT.md did not lock these specifics).

**Research date:** 2026-08-19
**Valid until:** ~30 days for the codebase-facing findings (stable unless Phase 4 lands
first and changes the `origin_host` seam's exact shape — check against the live file
before planning if time has passed); ~90 days for the Tailscale/OS findings (slower-moving
external platform behavior), but the two explicitly-flagged live-confirmation items (Q1
UDP-connect trick, Q2 firewall prompt) should be confirmed once, live, regardless of date.
