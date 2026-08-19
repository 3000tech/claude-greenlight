---
phase: 04-notification-truth
gathered: 2026-08-19
status: complete
mode: conversational   # decisions gathered in free-text discussion, per user preference
---

# Phase 4 Context — Notification Truth

## Decisions (locked — do not revisit in planning)

1. **idle_prompt is ignored outright (NOTIF-01).** The `Notification` hook event with
   `notification_type: idle_prompt` ("Claude has been idle 60s") produces NO state change:
   no `needs_input`, no color change, no notification. `needs_input` stays reserved for
   `permission_prompt` and AskUserQuestion. (Option "use it as a liveness heartbeat" was
   offered and declined — plain ignore.)

2. **A held notification releases when background work truly ends (NOTIF-02).** The
   background-tasks hold releases when the session's in-flight background tasks reach zero
   (next state write with `background_tasks_count: 0` while still waiting); if the user (or
   the loop) resumes the session first, the held notification is discarded (`session_resumed`,
   as today). The idle ping is no longer a release path (`gate_cleared` via needs_input must
   disappear for idle pings). Existing max-hold (`NOTIFY_GATE_MAX_HOLD_SEC`) unchanged.

3. **Host name on every notification, uniformly (NOTIF-03).** Title format:
   `Claude ready — {label} @ {host}` for ALL notifications, local and remote alike
   (e.g. `nursy @ macbook-devbox`, `claude-greenlight @ matteo`). Single build site:
   `notification_text()` (monitor.py:1445). Host source: the state file's `hostname` field
   resolved to a friendly machine name where available; container hostnames map to the
   machine that runs them (the PC's sessions show the PC's name, not the container id).

## Evidence base

Devbox notifications.log + hook-events.log, night 2026-08-18→19: 45/45 Notification events
were `idle_prompt`, ~20 pushes sent to a self-resuming loop session (Stop → UserPromptSubmit
12-20 min later, no human). Zero real permission prompts. Code anchors: state-writer.sh:175
(unconditional `PermissionRequest|Notification` → needs_input), monitor.py:1375
(gate refuses only on background_tasks_count), monitor.py:2278 (`gate_cleared` send path).

## Constraints

- Ratified semantics stand: a notification means "Claude is fully idle and needs you"
  (see 03-UAT Section G record; feedback memory notify-fully-idle).
- Live verification: an overnight run on the devbox with the loop session active must
  produce zero illegitimate notifications; real permission prompts must still notify.
- The devbox monitor runs pre-v1.0 code — rollout there is OPS-01 (Phase 6), but the
  overnight verification of THIS phase requires updating+restarting the devbox greenlight
  with the Phase 4 fix (allowed: it is the verification vehicle, documented in the UAT).
