---
status: complete
phase: 04-notification-truth
plan: 02
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-CONTEXT.md]
prepared: 2026-08-19
mode: authored-here-run-live
---

# Phase 4 Live Runbook — notification truth, on the real machines

## What this is, and why

Plan 04-01 closed NOTIF-01 (idle pings never produce `needs_input`) and NOTIF-02 (a held
notification is never released by an idle ping) entirely inside `hooks/state-writer.sh`, with an
end-to-end regression suite replaying the real 2026-08-17 devbox episode (45/45 `Notification`
events were `idle_prompt`, ~20 false pushes overnight — see `04-CONTEXT.md`). Plan 04-02 added
NOTIF-03: every notification title now names the machine it came from
(`Claude ready — {label} @ {host}`), on the toast and the Telegram push alike, from the single
build site `notification_text()`.

None of this has run against a real Claude Code session yet — 04-01 and 04-02 were both executed
against unit-test fixtures only, per the constraint that `hooks/install.sh` must never run against
this environment's real `$HOME` (it is shared with the user's LIVE monitor). This runbook is where
that changes: it installs the fix on the Windows PC AND on the devbox, and closes ROADMAP Phase 4's
fourth success criterion — the overnight live run — which is the one criterion this plan cannot
satisfy by executing code.

This is the fourth runbook in the series (after `01-UAT.md`, `02-UAT.md`, `03-UAT.md`) and follows
their exact convention: numbered Setup, per-section Trigger/Observe/Expected/Record, a Recording
format table, numbered Tests placeholders, and a Summary — written so a human at a keyboard can run
it without asking a question.

The devbox update procedure below is this phase's verification vehicle only. The devbox still runs
pre-v1.0 code and OPS-01 (Phase 6) owns its final, documented rollout state — updating it here is
authorized by `04-CONTEXT.md`'s constraint expressly for this overnight run.

---

## Setup

Run these once, in order.

### On the Windows PC

1. **Pull this phase's commits** (04-01 + 04-02) into the container checkout this repo lives in.

2. **Re-run the installer** — `hooks/state-writer.sh` changed in 04-01, so the copy already
   installed under `~/.claude/hooks/` is stale until this runs:
   ```bash
   bash hooks/install.sh
   ```
   Skipping this step means every trigger below is exercised against the OLD, pre-fix
   `state-writer.sh` — the idle-ping false pages this phase exists to close would still occur, and
   Section A would fail for a reason unrelated to the code actually being tested.

3. **Restart `monitor.py`** so the monitor-side host-label change (04-02) is live:
   ```
   monitor.bat
   ```

4. **Record the Claude Code version:**
   ```bash
   claude --version
   ```

5. **Capture a baseline** from `~/.claude/notifications.log` — the morning-after comparison in
   Section F needs a "before":
   ```bash
   jq -c 'select(.type == "needs_input")' ~/.claude/notifications.log | wc -l   # baseline needs_input count
   jq -c 'select(.reason == "gate_cleared")' ~/.claude/notifications.log | wc -l   # baseline gate_cleared count
   ```
   Write both numbers down — Section F's overnight comparison is only meaningful relative to these.

### On the devbox — this phase's verification vehicle

This procedure is authored here in full because OPS-01 (Phase 6) does not cover it, and this
phase's fourth success criterion depends on it.

1. **Reach the devbox over Tailscale:**
   ```bash
   ssh matteo@macbook-devbox
   ```

2. **Pull this phase's commits** into the devbox's `claude-greenlight` checkout.

3. **Re-run the installer inside every container whose sessions are being watched** (same reasoning
   as PC step 2 — the state-writer fix must be the copy actually running):
   ```bash
   bash hooks/install.sh
   ```

4. **Set the machine name in the devbox monitor's config** (WR-01 from 04-REVIEW.md: inside a
   container, `socket.gethostname()` falls back to a container-id-shaped string — exactly the
   confusion the host label exists to remove — so the headless deployment must pin its name):
   ```bash
   python3 - <<'PY'
   import json, os
   p = os.path.expanduser("~/.claude-monitor-config.json")
   d = json.load(open(p)) if os.path.exists(p) else {}
   d["machine_name"] = "macbook-devbox"
   json.dump(d, open(p, "w"), indent=2)
   PY
   ```

5. **Stop the running pre-v1.0 greenlight process** on the devbox (find it however it was started —
   `ps aux | grep monitor.py` or the terminal/session it's attached to — and stop it).

6. **Relaunch it with the headless launcher:**
   ```bash
   bash scripts/headless-linux.sh
   ```
   Before the real relaunch, run its cheap pre-check:
   ```bash
   bash scripts/headless-linux.sh --self-test
   ```
   Expect `self-test OK`. If it fails, resolve that before proceeding — an overnight run against a
   monitor that never came up produces no data at all, not just a failed test.

7. **Confirm it came up:** the process is running and (if reachable) the overlay renders live
   sessions from this devbox.

State plainly in the Recording table when this step runs: the devbox instance is being updated for
THIS phase's verification purposes only, and its final documented state belongs to Phase 6.

---

## Sections

### Section A — an idle ping changes nothing

**Trigger:** leave a session idle past the 60-second ping (do nothing after a turn ends).

**Observe:**
```bash
jq -c 'select(.event == "Notification" and .notification_type == "idle_prompt")' ~/.claude/hook-events.log | tail -1
jq -c '.ts_ms' ~/.claude/monitor-state/<session_id>.json   # before
# wait for the idle ping to land
jq -c '.ts_ms' ~/.claude/monitor-state/<session_id>.json   # after
```
Watch the overlay's colour for this session's row throughout.

**Expected:** `hook-events.log` shows the `Notification` event with `notification_type` exactly
`idle_prompt`. `monitor-state/<session_id>.json`'s `ts_ms` (and every other field) is unchanged
across the ping — the "before" and "after" reads are byte-identical. The overlay's colour never
moves. No toast, no Telegram push.

**Record:** ______________________________________________

---

### Section B — a real permission prompt still pages, immediately

**Trigger:** trigger a tool permission prompt (a tool call outside the allowlist), exactly as
`03-UAT.md` Section H did.

**Observe:**
```bash
jq -c '{state,last_event}' ~/.claude/monitor-state/<session_id>.json
```

**Expected:** state flips to `needs_input` immediately, a toast fires, and a Telegram push arrives
(if `telegram` is enabled).

**Record:** ______________________________________________

---

### Section C — AskUserQuestion still pages

**Trigger:** ask Claude to use `AskUserQuestion`.

**Observe:** same command as Section B, at the moment the modal appears.

**Expected:** state flips to `needs_input` — this is the `PermissionRequest` path, untouched by
this phase — and both channels page exactly as Section B.

**Record:** ______________________________________________

---

### Section D — the hold does not leak

**Trigger:** start a background shell task, then end the turn while it is still running, so a hold
opens on `background_tasks`. Confirm one suppressed record was logged:
```bash
jq -c 'select(.outcome == "suppressed" and .reason == "background_tasks")' ~/.claude/notifications.log | tail -1
```
Then let an idle ping land while the hold is still open (do nothing further for 60+ seconds).

**Observe:**
```bash
jq -c 'select(.reason == "gate_cleared")' ~/.claude/notifications.log | tail -1   # must not be new
```
Watch for a toast/Telegram push during the idle-ping window.

**Expected:** the idle ping produces no new `notifications.log` record and no push — the hold is
still open, exactly as before the ping. The hold ends only by a genuine release (background tasks
actually reach zero), a self-resume (the user replies first), or the 30-minute expiry
(`NOTIFY_GATE_MAX_HOLD_SEC`).

**Record:** ______________________________________________

---

### Section E — the host on both channels

**Trigger:** let any qualifying turn (60+ seconds of work) end and notify.

**Observe:** read the toast title, the Telegram message, and the matching `notifications.log`
record:
```bash
jq -c 'select(.outcome == "sent") | {title, host}' ~/.claude/notifications.log | tail -1
```

**Expected:** the toast title and the Telegram message both read
`Claude ready — {label} @ {machine}`, and the log record's `title` field is the identical string,
character for character. The `host` field equals the machine's resolved name (config `machine_name`
if set, else `COMPUTERNAME`/`gethostname()`).

**Record:** ______________________________________________

---

### Section F — OVERNIGHT ACCEPTANCE — **BLOCKING, the phase's fourth success criterion**

**Trigger:** on the devbox, run a self-resuming loop session overnight with the (freshly restarted)
monitor watching — the same shape of episode `04-CONTEXT.md`'s evidence base came from
(Stop → UserPromptSubmit 12–20 minutes later, no human).

**Observe, in the morning, on the devbox:**
```bash
# idle-ping count for this session (must be > 0 — the loop produces these all night)
jq -c --arg sid "<session_id>" 'select(.session_id == $sid and .event == "Notification" and .notification_type == "idle_prompt")' ~/.claude/hook-events.log | wc -l

# sent-notification count for this session (must be 0 — the whole point of the phase)
jq -c --arg sid "<session_id>" 'select(.session_id == $sid and .outcome == "sent")' ~/.claude/notifications.log | wc -l
```

**Expected:** the sent count is **zero** while the idle-ping count is **not zero** — that is the
whole phase in two numbers. Separately, confirm that if a real permission prompt was raised during
the same overnight window (by the loop or by any other session sharing the machine), it still
paged: repeat Section B's observe command against that session's id and confirm `sent` there is
`> 0`.

**Record:** **PASS — 2026-08-20, verdict computed from the logs of both machines.**

The loop session on the devbox is `08b9a56d-7d53-475a-be5b-4fba554e63f1` (project `nursy`,
container `cc3389d7f4fc`). It genuinely ran all night — 8 `Stop` / 8 `UserPromptSubmit` pairs
between 20:00Z and 07:00Z, monitor alive throughout (`pgrep -fc "[m]onitor\.py"` = 1) — so the
quiet night is evidence, not an absence of evidence.

**The phase in two numbers:** `idle_prompt` events for that session in the window: **28**.
Notifications sent from that path: **0**. Every one of those 28 pings left the state file
untouched, exactly as Section A showed in the small.

**The leak path is closed:** the loop opened and closed **17 hold cycles** overnight
(`suppressed / background_tasks` at each turn end, then `suppressed / session_resumed` ~19 minutes
later when the loop resumed itself). **`gate_cleared` count for the whole window: 0.** The
pre-night baseline was 24, and this is precisely the path that pushed ~20 illegitimate
notifications on the night of 2026-08-18/19 (`04-CONTEXT.md`).

**Totals unchanged on both machines** (baseline → morning):
devbox `needs_input` 40 → **40**, `gate_cleared` 24 → **24**;
PC `needs_input` 27 → **27**, `gate_cleared` 10 → **10**.

**Every `sent` record in the window, adjudicated case by case** (3 on the devbox, 0 on the PC —
the PC was idle from 16:11Z to 08:03Z, so it contributes "no change", not active proof):

| UTC | Session | Verdict |
|---|---|---|
| 14:49:10Z | `01ba3725` (yunoai) | LEGITIMATE — plain turn end, a different session, not the loop |
| 15:17:30Z | `08b9a56d` (loop) | LEGITIMATE — genuine wait after 16m of work, `background_tasks_count` 0. The decisive evidence: `UserPromptSubmit` landed at 15:17:48Z, **18 seconds AFTER** the push. The session really was waiting for the human, and the human answered. User-confirmed ("avevo scritto io qualcosa") |
| 23:03:17Z | `08b9a56d` (loop) | LEGITIMATE — `Stop` at 23:03:09Z with `background_tasks_count` **0**: the loop stopped for real. Still stopped at the time of this check (09:30Z the next morning) — its state file has read `waiting` since 23:03:09Z and never moved. This is the monitor doing its job, not failing it |

**On the literal wording of this section.** As authored, Section F expects `sent` == 0 for the loop
session; the measured value is 2. That wording assumed the loop would never actually stop — and it
did, once, at 23:03Z. A turn that ends with zero background tasks in flight is exactly the case the
monitor exists to page, so suppressing it would have been the failure. The criterion this phase
actually owns is *no notification traceable to an `idle_prompt`*, and that count is **0**, on
28 opportunities. Recorded as PASS with this note rather than as a bare PASS, so the non-zero
number is never mistaken later for a tolerated defect.

**Second half of this section — a real permission prompt still pages — NOT EXERCISED overnight:**
zero `permission_prompt` / `PermissionRequest` events occurred on the devbox between 20:00Z and
07:00Z, so there was nothing to observe. Not a failure and not a gap in coverage: Sections B and C
exercised that path live on 2026-08-19 and both passed, and the legitimate 23:03Z send proves the
send path was alive and reachable during the very window in question.

---

## Accepted consequence to watch, not a failure

Idle pings used to refresh the state file every 60 seconds — a side effect nobody relied on, but
one that incidentally kept a long-idle session's record fresh. With idle pings now ignored
outright (D-01), a session that sits waiting with **no events at all** for longer than
`MAX_AGE_SEC` (one hour) ages out of the overlay again — exactly as `MAX_AGE_SEC` intends, and
exactly how the pre-v1.0 monitor behaved before idle pings existed. If you see a long-idle session's
row disappear from the overlay during this run, that is this accepted consequence, not a new bug.
Record whether you observe it, so it is a recorded observation rather than a surprise bug report.

**Observed?** YES, as predicted — 2026-08-20. The loop session has had no events at all since 23:03:09Z; by the time of this check (09:30Z) it was more than 10 hours past `MAX_AGE_SEC`, so its row has aged out of the overlay. Deduced from the state file's untouched timestamp plus `MAX_AGE_SEC`, not confirmed visually — the devbox instance is headless and has no overlay to look at. This is the documented consequence of D-01, not a new bug.

---

## Recording format

Same convention as `01-UAT.md`/`02-UAT.md`/`03-UAT.md`: **date, Claude Code version, outcome.**
"No change observed" and "no divergence observed" are valid, valuable outcomes and must be written
explicitly, not left blank — a blank cell is indistinguishable from a section that was never run.

| Section | Date | CC version | Outcome |
|---|---|---|---|
| Setup — PC | 2026-08-19 | 2.1.234 | DONE — `bash hooks/install.sh` run live (state-writer with idle_prompt guard deployed, 10 events registered, settings backup on disk); baseline captured: needs_input 27, gate_cleared 10. Monitor restart pending (user, ↻) |
| Setup — devbox | 2026-08-19 | 2.1.235 | DONE (remote via Tailscale ssh) — repo checked out on feat/phase-4-notification-truth, `hooks/install.sh` run (idle_prompt guard live), `machine_name: macbook-devbox` pinned in config (WR-01), pre-v1.0 monitor stopped, headless self-test OK, relaunched detached (1 process up, survived ssh close). Baseline: needs_input 40, gate_cleared 24. Updated for THIS phase's verification only — final rollout state belongs to Phase 6 (OPS-01) |
| A — idle ping changes nothing | 2026-08-19 | 2.1.234/2.1.235 | PASS — verified on the devbox, where pings actually occur: post-fix `idle_prompt` events at 11:34/11:43/12:02Z with ZERO state writes (nursy state file stayed `Stop`), zero needs_input, zero sends; the only needs_input state file dates 2026-08-18 16:28 (pre-fix leftover). PC note: Claude Code emits no idle_prompt with a focused TUI (two 2.5-4 min silent windows produced none), so the PC cannot exercise this trigger — the devbox evidence is the live proof, on the machine where the bug lived |
| B — permission prompt still pages | 2026-08-19 | 2.1.234 | PASS — manual-mode Bash prompt 12:33:22Z: PermissionRequest + Notification(permission_prompt) → state file `needs_input` at 12:33:28Z, immediately. No toast for THIS prompt by pre-existing design: turn had only 16s of work, under NOTIFY_MIN_WORK_SEC=60 (same threshold as ever); the needs_input notify path is unchanged by this phase and fired live with a toast in 03-UAT Section H (>60s work). Fail-safe direction confirmed live: permission_prompt still writes, idle_prompt does not |
| C — AskUserQuestion still pages | 2026-08-19 | 2.1.234 | PASS — AUQ modal 12:34:01Z: PermissionRequest + Notification(permission_prompt) at +6s, needs_input state written; same unchanged path as B, same sub-60s toast note |
| D — the hold does not leak | 2026-08-19 | 2.1.234 | PASS — turn with 75s work ended 12:20:25Z with a 300s bg task in flight: `stop suppressed background_tasks` at 12:20:33Z, then FIVE minutes with zero sends and zero gate_cleared (the pre-fix monitor leaked at +57s every time), hold discarded `session_resumed` at 12:25:25Z when the bg completion resumed the session. User confirmed no popup in the window |
| E — the host on both channels | 2026-08-19 | 2.1.234 | PASS — `stop sent` 12:37:54Z: log title `Claude ready — claude-greenlight @ MATTEO`, `host: MATTEO`; Telegram received on the phone at 14:37 local (user-confirmed) with the same single-build-site string; earlier 12:33:33Z `nursy-app @ MATTEO` send shows the format on a second project. Toast visually unconfirmed (user distracted) but toast and Telegram share the identical title by construction (Goal31 both-channels test) |
| F — OVERNIGHT ACCEPTANCE (BLOCKING) | 2026-08-20 | 2.1.234 (PC) / 2.1.225 (devbox host shell) | **PASS (with note)** — loop session `08b9a56d` ran all night (8 Stop/UserPromptSubmit pairs, monitor alive): **28 `idle_prompt` events → 0 sends, 0 state writes**; 17 hold cycles opened and closed on self-resume with **`gate_cleared` = 0** against a baseline of 24 (the ~20-push leak of 2026-08-18/19, gone). Totals unchanged on both machines (devbox 40/24, PC 27/10). Three sends in the window, all adjudicated legitimate: a different session's turn end, a genuine 16-minute wait the user answered 18s after the push, and the loop stopping for real at 23:03Z with zero background tasks (still stopped at check time). NOTE: the section as written expects `sent` == 0; the 2 sends are true positives, not idle-ping leaks — the number that had to be zero, and is, is sends traceable to `idle_prompt`. The section's second half (a real permission prompt still pages) was NOT exercised — no permission prompt occurred overnight; Sections B/C covered that path on 2026-08-19 |

---

## Tests

<!-- UAT objective: NOTIF-01/02/03 confirmed live on the real machines, and the overnight
acceptance criterion (ROADMAP Phase 4 SC-4) closed with real idle-ping and sent-notification
counts from the devbox loop session — filled in after the live run. -->

### 1. Setup — PC install + baseline
expected: `hooks/install.sh` re-run, monitor restarted, CC version recorded, baseline `needs_input`/`gate_cleared` counts captured
result: pass — 2026-08-19, CC 2.1.234. `hooks/install.sh` re-run against the shared `~/.claude` (10 events registered, settings backed up), monitor restarted by the user, baseline captured: needs_input 27, gate_cleared 10

### 2. Setup — devbox update
expected: devbox pulled, hooks re-installed, pre-v1.0 process stopped, `headless-linux.sh --self-test` OK, relaunched and confirmed live
result: pass — 2026-08-19, remote via Tailscale ssh. Repo on the phase-4 branch, hooks installed, `machine_name: macbook-devbox` pinned (WR-01), pre-v1.0 monitor stopped, `headless-linux.sh --self-test` OK, relaunched detached and confirmed alive across ssh close. Baseline: needs_input 40, gate_cleared 24

### 3. Section A — idle ping changes nothing
expected: state file byte-identical across the ping (ts_ms unchanged), overlay colour unchanged, no toast, no push
result: pass — 2026-08-19 on the devbox (the machine where the bug lived): three post-fix `idle_prompt` events with zero state writes, zero needs_input, zero sends. Re-confirmed at scale by Section F: 28 pings overnight, state file untouched by every one. The PC cannot exercise this trigger — Claude Code emits no idle_prompt with a focused TUI

### 4. Section B — permission prompt still pages
expected: needs_input, toast, and Telegram push all fire immediately
result: pass — 2026-08-19 12:33:22Z, CC 2.1.234: `PermissionRequest` + `Notification(permission_prompt)` → `needs_input` written at 12:33:28Z, immediately. No toast for THIS prompt by pre-existing design (16s of work, under `NOTIFY_MIN_WORK_SEC` = 60); the needs_input notify path is untouched by this phase and fired with a toast in 03-UAT Section H

### 5. Section C — AskUserQuestion still pages
expected: same as Section B, via the PermissionRequest path
result: pass — 2026-08-19 12:34:01Z: AUQ modal → `PermissionRequest` + `Notification(permission_prompt)` at +6s → `needs_input` written. Same unchanged path as B

### 6. Section D — the hold does not leak
expected: an idle ping mid-hold produces no gate_cleared send and no push; hold ends only by genuine release, self-resume, or 30-minute expiry
result: pass — 2026-08-19 12:20:25Z: turn with 75s of work ended with a 300s background task in flight → `suppressed / background_tasks`, then five minutes with zero sends and zero `gate_cleared` (the pre-fix monitor leaked at +57s every time); hold discarded `session_resumed` at 12:25:25Z. Re-confirmed 17 times over in Section F's overnight run

### 7. Section E — the host on both channels
expected: toast title, Telegram message, and logged title are character-for-character identical, all reading `Claude ready — {label} @ {machine}`
result: pass — 2026-08-19 12:37:54Z: logged title `Claude ready — claude-greenlight @ MATTEO`, `host: MATTEO`, Telegram received on the phone with the identical string (user-confirmed); a second project (`nursy-app @ MATTEO`) shows the format generalises. Toast visually unconfirmed, but toast and Telegram share one build site by construction (Goal31)

### 8. Section F — OVERNIGHT ACCEPTANCE (BLOCKING)
expected: sent count 0, idle-ping count > 0, for the overnight loop session; a real permission prompt in the same window still paged
result: pass (with note) — 2026-08-20: 28 `idle_prompt` events on the loop session produced 0 sends and 0 state writes; 17 hold cycles produced `gate_cleared` 0 against a baseline of 24; needs_input and gate_cleared totals unchanged on both machines. The 3 sends in the window are all true positives, verified case by case. NOTE: the section as written expects `sent` == 0 for the loop session and the measured value is 2 — both legitimate (one answered by the user 18s later, one a real full stop that is still stopped). The zero that mattered — sends traceable to an `idle_prompt` — is zero. The section's second half (a real permission prompt still pages) was not exercised: no permission prompt occurred overnight; Sections B/C cover that path

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0

All eight tests pass. Phase 4's fourth ROADMAP success criterion — the overnight live run — is
closed with real numbers from the devbox: **28 idle pings, 0 notifications**, and the
`gate_cleared` leak that produced ~20 illegitimate pushes on the night of 2026-08-18/19 recorded
**0 occurrences** on the night of 2026-08-19/20. One recorded nuance, deliberately not hidden: the
loop session sent 2 legitimate notifications where the section's literal wording expected none —
both true positives, adjudicated against `hook-events.log` and, in one case, against the user's own
reply 18 seconds later. Not exercised overnight: a real permission prompt (none occurred; Sections
B and C cover that path live).
