---
status: pending
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

4. **Stop the running pre-v1.0 greenlight process** on the devbox (find it however it was started —
   `ps aux | grep monitor.py` or the terminal/session it's attached to — and stop it).

5. **Relaunch it with the headless launcher:**
   ```bash
   bash scripts/headless-linux.sh
   ```
   Before the real relaunch, run its cheap pre-check:
   ```bash
   bash scripts/headless-linux.sh --self-test
   ```
   Expect `self-test OK`. If it fails, resolve that before proceeding — an overnight run against a
   monitor that never came up produces no data at all, not just a failed test.

6. **Confirm it came up:** the process is running and (if reachable) the overlay renders live
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

**Record:** ______________________________________________

---

## Accepted consequence to watch, not a failure

Idle pings used to refresh the state file every 60 seconds — a side effect nobody relied on, but
one that incidentally kept a long-idle session's record fresh. With idle pings now ignored
outright (D-01), a session that sits waiting with **no events at all** for longer than
`MAX_AGE_SEC` (one hour) ages out of the overlay again — exactly as `MAX_AGE_SEC` intends, and
exactly how the pre-v1.0 monitor behaved before idle pings existed. If you see a long-idle session's
row disappear from the overlay during this run, that is this accepted consequence, not a new bug.
Record whether you observe it, so it is a recorded observation rather than a surprise bug report.

**Observed?** ______________________________________________

---

## Recording format

Same convention as `01-UAT.md`/`02-UAT.md`/`03-UAT.md`: **date, Claude Code version, outcome.**
"No change observed" and "no divergence observed" are valid, valuable outcomes and must be written
explicitly, not left blank — a blank cell is indistinguishable from a section that was never run.

| Section | Date | CC version | Outcome |
|---|---|---|---|
| Setup — PC | | | |
| Setup — devbox | | | |
| A — idle ping changes nothing | | | |
| B — permission prompt still pages | | | |
| C — AskUserQuestion still pages | | | |
| D — the hold does not leak | | | |
| E — the host on both channels | | | |
| F — OVERNIGHT ACCEPTANCE (BLOCKING) | | | |

---

## Tests

<!-- UAT objective: NOTIF-01/02/03 confirmed live on the real machines, and the overnight
acceptance criterion (ROADMAP Phase 4 SC-4) closed with real idle-ping and sent-notification
counts from the devbox loop session — filled in after the live run. -->

### 1. Setup — PC install + baseline
expected: `hooks/install.sh` re-run, monitor restarted, CC version recorded, baseline `needs_input`/`gate_cleared` counts captured
result: pending

### 2. Setup — devbox update
expected: devbox pulled, hooks re-installed, pre-v1.0 process stopped, `headless-linux.sh --self-test` OK, relaunched and confirmed live
result: pending

### 3. Section A — idle ping changes nothing
expected: state file byte-identical across the ping (ts_ms unchanged), overlay colour unchanged, no toast, no push
result: pending

### 4. Section B — permission prompt still pages
expected: needs_input, toast, and Telegram push all fire immediately
result: pending

### 5. Section C — AskUserQuestion still pages
expected: same as Section B, via the PermissionRequest path
result: pending

### 6. Section D — the hold does not leak
expected: an idle ping mid-hold produces no gate_cleared send and no push; hold ends only by genuine release, self-resume, or 30-minute expiry
result: pending

### 7. Section E — the host on both channels
expected: toast title, Telegram message, and logged title are character-for-character identical, all reading `Claude ready — {label} @ {machine}`
result: pending

### 8. Section F — OVERNIGHT ACCEPTANCE (BLOCKING)
expected: sent count 0, idle-ping count > 0, for the overnight loop session; a real permission prompt in the same window still paged
result: pending

## Summary

total: 8
passed: 0
issues: 0
pending: 8
skipped: 0
