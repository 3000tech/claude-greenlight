# Roadmap: Claude Greenlight

## Overview

v1.0 made hooks the primary source of session state. v1.1 makes the *notification* built on that state trustworthy, and extends the monitor's reach beyond the Windows PC. Three phases, in dependency order. First the notification lies get fixed: `idle_prompt` stops masquerading as `needs_input` (the overnight devbox log of 2026-08-19 was 45/45 idle pings, ~20 pushes, zero real requests), the background-tasks gate stops leaking on those pings, and every notification says which host it came from — small, self-contained, and it kills the nightly noise immediately. Then devbox sessions land in the PC overlay over the private tailnet, with staleness that never fakes a "ready" and exactly one notification owner per session; the transport and the ownership model are deliberately undecided here and get settled in that phase's design discussion. Last, the remote host's story closes: a read-only panel reachable from the phone over the tailnet, and the devbox greenlight installation brought to its final documented state — updated and restarted, or retired, depending on what the Phase 5 design decided about the headless instance.

## Milestones

- ✅ **v1.0 Hook-Driven State Refactor** — SHIPPED 2026-08-19 (3 phases, 11 plans, UAT 11/11, 313 tests) — [archive](milestones/v1.0-ROADMAP.md)
- 🔵 **v1.1 Remote Notifications** — in progress (phases 4-6)

## Phases

**Phase Numbering:**

- Integer phases (4, 5, 6): Planned milestone work — numbering continues from v1.0 (phases 1-3)
- Decimal phases (5.1, 5.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 4: Notification Truth** - Notifications fire only when the user is genuinely needed, and every one names the host it came from
- [ ] **Phase 5: Devbox Sessions on the PC Overlay** - The PC overlay shows tailnet-remote sessions with honest staleness and exactly one notification owner per session
- [ ] **Phase 6: Phone Access & Devbox Rollout** - A read-only panel reachable from the phone over the tailnet, and the devbox installation in its final documented state

## Phase Details

### Phase 4: Notification Truth

**Goal**: A notification means what it claims — the user is genuinely needed — and it says which machine is asking. Self-resuming loop sessions stop paging overnight, the background-tasks hold stops leaking, and origin host is visible on every channel.
**Depends on**: Nothing (first phase of v1.1; builds on the shipped v1.0 hook engine)
**Requirements**: NOTIF-01, NOTIF-02, NOTIF-03
**Success Criteria** (what must be TRUE):

  1. A session that receives only `idle_prompt` Notification events (self-resuming loop, no real request) stays `waiting` and produces zero pushes — replaying the devbox's overnight 2026-08-19 events yields no notification — while a real `permission_prompt` or AskUserQuestion still turns the session `needs_input` and pages the user as it does today.
  2. A notification held by the background-tasks gate is released only when the session genuinely needs the user or is fully idle per the ratified semantics; an idle ping arriving mid-hold leaves the hold standing (`notifications.log` shows the hold persisting, not a `gate_cleared` send).
  3. Every notification title carries its origin host on both channels — toast and Telegram — e.g. "Claude ready — nursy @ macbook-devbox", for local sessions as well as remote ones, and `notifications.log` records the same string the user saw.
  4. On the real Windows + devbox setup, a full overnight run produces zero illegitimate notifications while real permission prompts still page immediately (user-assisted UAT runbook authored in-phase, performed live).

**Plans**: 2 plans

Plans:
- [x] 04-01-PLAN.md — idle_prompt stops writing needs_input at the source, and the background-tasks hold stops leaking (NOTIF-01, NOTIF-02)
- [x] 04-02-PLAN.md — origin host on every notification title, toast and Telegram, from one build site; README + live UAT runbook (NOTIF-03)

### Phase 5: Devbox Sessions on the PC Overlay

**Goal**: The PC overlay becomes the single truthful view of every session on the tailnet, devbox included — remote rows are identifiable, an unreachable devbox can never fake a "ready", and each session has exactly one machine responsible for paging the user.
**Depends on**: Phase 4 (host-labeled, non-lying notifications are the precondition for letting remote sessions page at all)
**Requirements**: REMOTE-01, REMOTE-02, REMOTE-03
**Success Criteria** (what must be TRUE):

  1. Sessions running on the MacBook devbox appear in the PC overlay alongside local ones, driven by the devbox's `~/.claude/monitor-state/*.json` carried over the private tailnet — the transport is chosen in this phase's design discussion and recorded as a decision with its rejected alternatives, not presupposed here.
  2. A remote session is visibly remote: its row carries the origin host, so a devbox `nursy` and a local `nursy` are never mistaken for each other in the overlay, in compact mode, or in a notification.
  3. When the devbox is asleep, offline, or otherwise unreachable, the overlay never shows a false "ready", never fires a notification from stale data, and never leaves a ghost row — remote sessions age out on a documented rule, the same way container liveness works today.
  4. Any single session pages the user exactly once: no duplicate toast or Telegram push for the same event from the PC monitor and any devbox-side instance (coordination model decided in the design discussion).
  5. Live UAT on the real pair (Windows PC + devbox running real sessions) confirms 1-4 across a devbox sleep/wake cycle, user-assisted, same discipline as v1.0.

**Plans**: TBD

### Phase 6: Phone Access & Devbox Rollout

**Goal**: The user can check what every session is doing from the phone, over the private tailnet only, and the devbox greenlight installation ends the milestone in a known, documented state — running current code or deliberately retired.
**Depends on**: Phase 5 (its design decides which host aggregates state and owns notifications, which in turn decides where the panel is served from and whether the headless devbox instance survives)
**Requirements**: MOBILE-01, OPS-01
**Success Criteria** (what must be TRUE):

  1. From the phone's browser, using a stable Tailscale name and no external hosting, the user opens a read-only panel showing the same sessions and states as the desktop overlay.
  2. The panel is read-only and private: it exposes no control actions, is unreachable with the tailnet off (verified, not assumed), and shows an honest stale/no-data marker rather than a stale green when its source stops updating.
  3. The devbox greenlight installation matches Phase 5's decision — either updated to current code and restarted via a procedure documented in the repo, or retired with its teardown documented — and the chosen outcome survives a devbox reboot.
  4. Live UAT: the user watches a real session go ready on the phone panel while the desktop overlay agrees, and confirms the devbox comes back in its documented state after a reboot.

**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 4. Notification Truth | 2/2 | Complete | 2026-08-20 |
| 5. Devbox Sessions on the PC Overlay | 0/TBD | Not started | - |
| 6. Phone Access & Devbox Rollout | 0/TBD | Not started | - |

## Requirement Coverage

| Requirement | Phase |
|-------------|-------|
| NOTIF-01 | Phase 4 |
| NOTIF-02 | Phase 4 |
| NOTIF-03 | Phase 4 |
| REMOTE-01 | Phase 5 |
| REMOTE-02 | Phase 5 |
| REMOTE-03 | Phase 5 |
| MOBILE-01 | Phase 6 |
| OPS-01 | Phase 6 |

All 8 v1.1 requirements mapped, no orphans, no duplicates.
