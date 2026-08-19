---
status: complete
phase: 03-flip-to-default-cleanup
plan: 04
source: [03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md, 02-DIVERGENCE-REVIEW.md, 03-CONTEXT.md]
prepared: 2026-08-06
updated: 2026-08-19
mode: live-run-complete   # authored here (D-12); performed live on the Windows machine 2026-08-06 → 2026-08-19: Setup + A–I all PASS, Teardown done (11/11, zero issues)
---

# Phase 3 Live Runbook — the flip, on the real machine

## What this is, and why

Shadow mode ran a full week (2026-07-30 → 2026-08-06) on the Windows machine; the Section E
divergence review (`02-DIVERGENCE-REVIEW.md`) came back GREEN and the flip was approved. Plans
03-01 through 03-03 then made the state-file engine the sole rendering source, added the D-02a/
D-02b hybrid fallbacks, closed the ghost-row and orphan-temp-file gaps, made turn-end badge-only,
and retired the AskUserQuestion lock hook — all against unit-test fixtures, in a code-only
execution environment with no Docker and no real Claude Code sessions.

This runbook confirms the flip behaves the same way on the machine that actually runs it, and
performs the machine-side teardown that could not be done from here (D-12): deleting the
divergence log, confirming the orphan temp-file sweep fired on its own, and — gated behind
Section H — removing the retired `auq-lock.sh` from a live install.

Per D-05, this is user-assisted UAT: the agent cannot `docker kill`/`pause` a live container,
press Esc mid-turn, or open a real AskUserQuestion modal from inside this sandbox. Every step
below is written to remove guesswork from what a human has to type and read, mirroring
`01-UAT.md`/`02-UAT.md`'s convention exactly — it is now three phases old and reads fluently.

---

## Setup

Run these once, in order, on the Windows machine, from inside a container with this repo
checked out at the flipped commit.

1. **Pull the flipped code** (this phase's commits) into the container's checkout.

2. **Re-run the installer.**
   ```bash
   bash hooks/install.sh
   ```
   This installs `working-lock.sh`, `event-logger.sh` and `state-writer.sh`, and merges their
   entries into `~/.claude/settings.json`. It does **not** install or register `auq-lock.sh` —
   that hook is retired (D-04) and no longer shipped by the default path.

3. **Record the per-script registration counts** — the expected shape now excludes the retired
   lock:
   ```bash
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("working-lock\\.sh"))] | length' ~/.claude/settings.json   # expect 3
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("state-writer\\.sh"))] | length' ~/.claude/settings.json      # expect 10
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("event-logger\\.sh"))] | length' ~/.claude/settings.json       # expect 22 (hooks/hook-events.json length; was 24 until 2026-08-18 quick-260818-ejg dropped WorktreeCreate/WorktreeRemove — see hooks/install.sh header)
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("auq-lock\\.sh"))] | length' ~/.claude/settings.json           # expect 0 — a FRESH install registers none
   ```
   If this container's `~/.claude/settings.json` carries a pre-flip `auq-lock.sh` registration
   from before this phase, that count will be > 0 here — that is the existing-install case
   Section H's teardown addresses, not a Setup failure.

4. **Confirm state files are still being written.** After a minute or two of ordinary use in at
   least one session:
   ```bash
   ls ~/.claude/monitor-state/
   jq -c . ~/.claude/monitor-state/*.json   # each file must parse
   ```

5. **Confirm the monitor starts without any flag.**
   ```
   monitor.bat
   ```
   No `--state-files` flag, no error, overlay appears and renders live sessions. (The flag is
   retained-but-inert per D-01's discretion — passing it is a no-op, not a requirement.)

6. **Record the Claude Code version**, same discipline as `01-UAT.md`/`02-UAT.md`:
   ```bash
   claude --version
   ```

---

## Sections

### Section A — the flip is live

**Trigger:** run one ordinary session end to end (a short prompt, a tool call, turn end).

**Observe:**
```bash
cat ~/.claude/monitor-state/<session_id>.json
```
Compare the overlay's rendered state against this file's `state` field at each step (working →
waiting). Confirm nothing in the overlay ever corresponds to a jsonl-derived verdict that
disagrees with the state file — there is no second engine left to disagree with it.

**Pass condition:** overlay state matches the state file at every observed point.

---

### Section B — Esc-interrupt recovery (D-02a)

**Trigger:** start a long-running tool call, then press Esc mid-turn. Note the wall-clock time.

**Observe:**
```bash
watch -n 5 'jq -c "{state,last_event}" ~/.claude/monitor-state/<session_id>.json'
```
Time how long the overlay takes to flip from grey to green.

**Pass condition:** recovery lands at roughly 90 seconds (`STATE_PROMPT_STALE_SEC`), not the
600-second heartbeat window (`STATE_HEARTBEAT_STALE_SEC`) — the D-02a early-recovery fallback
reading the legacy jsonl's mtime-advance signal.

---

### Section C — hook-silence pin (D-02b, divergence class 6)

**Trigger:** run a long Monitor-tool invocation or a foreground subagent that runs past 600
seconds without a `PostToolUse`/`PostToolBatch` heartbeat.

**Observe:** watch the overlay continuously across the 600-second mark; confirm no toast, sound,
or taskbar flash fires while the tool/agent is still genuinely running.

**Pass condition:** the session stays WORKING past 600 seconds with no false notification — the
D-02b pin (Monitor/foreground-Agent/async-agent evidence via `_peek_agent_activity()`, or
`working-lock.sh` evidence) holding it there instead of degrading to WAITING at the heartbeat
window.

---

### Section D — the bridge (D-02c)

**Trigger:** run a session from a container/image where `hooks/install.sh` was never run, so its
`~/.claude/settings.json` has no `state-writer.sh` entries.

**Observe:**
```bash
ls ~/.claude/monitor-state/   # confirm no file exists for this session_id
```
Watch the overlay for this session's row.

**Pass condition:** the session with no state file stays visible in the overlay, rendered via the
`legacy_origin` per-session transcript bridge — not dropped, not shown as "unknown".

---

### Section E — ghost suppression (D-06, SessionEnd tombstones)

**Trigger:** end a session cleanly (exit Claude Code normally).

**Observe:**
```bash
ls ~/.claude/monitor-state/*.ended   # tombstone for the ended session_id
```
Confirm the session's row disappears from the overlay immediately. Then restart the monitor
(`monitor.bat`) and confirm the row does not reappear.

**Pass condition:** the ended session's row stays gone both before and after a monitor restart —
the on-disk tombstone (not an in-process set) is what survives the restart.

---

### Section F — paused container

**Trigger:** mid-turn, `docker pause <container-id>`. Wait past the 600-second heartbeat window.

**Observe:** watch the overlay for this session's row throughout the pause.

**Pass condition:** the session stays visible as an ordinary row (no dimming, no new color, per
D-05's "no new colors/notifications" fence) and does **not** degrade to WAITING purely from
elapsed time while paused — the `hostname_to_status == "paused"` guard holding it WORKING.

---

### Section G — badge-only background rule (D-03)

**Trigger:** ask for a background task, let the visible turn end while the background task is
still running.

**Observe:** watch the overlay at the moment the turn ends.

**Pass condition:** the overlay goes green **immediately** at turn end — `background_tasks_count > 0`
no longer holds the state WORKING — while the ◉N badge continues to show the background task's
count until it finishes. The toast is **deliberately held** while background tasks are in flight
(gate reason `background_tasks`) and released only once the session is fully idle; if the user
replies first, the held toast is discarded (`session_resumed`). Semantics decided with the user
2026-08-18: a notification means "Claude is fully idle" — background work in flight is still work,
so no popup yet. The immediate-notify wording this section originally carried predates that
decision and is superseded.

---

### Section H — the retirement gate (D-04) — **BLOCKING**

**This section is the gate D-04 requires.** It must be recorded as passing before the Teardown's
retired-lock removal step (below) is run. Do not run that Teardown step until this section's row
in the Recording format table says PASS.

**Trigger 1 — permission prompt:** trigger a tool outside the allowlist.

**Observe:**
```bash
jq -c '{state,last_event}' ~/.claude/monitor-state/<session_id>.json
```

**Trigger 2 — AskUserQuestion modal:** ask Claude to use `AskUserQuestion`.

**Observe:** same command as above, at the moment the modal appears.

**Pass condition:** both triggers produce the waiting-on-you (`needs_input`) state — via the
state writer's `PermissionRequest`/`Notification` event mapping — on a **fresh install that
already has the retired `auq-lock.sh` absent** (confirm via the Setup step 3 registration count,
which should read 0 on a fresh install). If this container's install is pre-flip and still has
`auq-lock.sh` registered, run this section's triggers first, confirm the state-writer path
independently produces the same `needs_input` verdict, and only then treat the section as passed
before tearing `auq-lock.sh` down.

---

### Section I — preserved fixes (D-07)

**Trigger 1 — alias survives `/clear`:** set an alias for a session, run `/clear` inside it.

**Observe:** check the alias in the overlay/config UI immediately after the `/clear`.

**Pass condition:** the alias is unchanged — aliases are keyed by container identity, not
`session_id`, so a new `session_id` after `/clear` does not orphan it.

**Trigger 2 — multi-monitor toast placement:** with a secondary display attached, trigger a
notification (let a turn end).

**Observe:** watch where the toast renders.

**Pass condition:** the toast lands correctly clamped to a display, no off-screen placement.

**Trigger 3 — 60-second notification threshold:** run a turn that completes in well under 60
seconds of actual work.

**Observe:** watch whether a notification fires.

**Pass condition:** no notification fires for a turn shorter than the 60-second threshold
(`NOTIFY_MIN_WORK_SEC`).

---

## Teardown

Machine-side, explicitly **not** executable from the development environment.

1. **Run the installer's retired-lock teardown mode — only after Section H is recorded as
   passing in the table below:**
   ```bash
   bash hooks/install.sh --remove-auq-lock
   ```
2. **Delete the retired lock script from the live hooks directory, and the now-unused lock
   directory:**
   ```bash
   rm -f ~/.claude/hooks/auq-lock.sh
   rm -rf ~/.claude/auq-locks
   ```
3. **Delete the divergence log** (shadow mode is retired; nothing writes to it anymore):
   ```bash
   rm -f ~/.claude/monitor-divergence.log
   ```
4. **Confirm the known orphan temp file was swept automatically**, rather than deleting it by
   hand — that is the observation this phase's stale-`.tmp` sweep (D-08) exists to produce:
   ```bash
   ls ~/.claude/monitor-state/*.tmp.* 2>/dev/null && echo "STILL PRESENT — sweep did not fire" || echo "swept — none found"
   ```
   (The known leftover from the shadow-mode review, `c1eb55f7-….json.tmp.13252`, is the specific
   file to check for by name if it is still around from before this phase.)
5. **Do NOT delete `~/.claude/monitor-state/`.** Unlike `02-UAT.md`'s shadow-era teardown line,
   the state directory is **not** removed: post-flip it is the primary data source, not a
   diagnostic side-channel. Deleting it would delete every live session's state.

---

## Recording format

Same convention as `01-UAT.md`/`02-UAT.md`: **date, Claude Code version, outcome.** "No change
observed" and "no divergence observed" are valid, valuable outcomes and must be written
explicitly, not left blank — a blank cell is indistinguishable from a section that was never run.

| Section | Date | CC version | Outcome |
|---|---|---|---|
| Setup (registration counts) | 2026-08-06 | 2.1.223 | PASS — working-lock 3, state-writer 10, event-logger 24; auq-lock 4 = the anticipated pre-flip existing-install case (preserved per WR-02, Section H gates removal); all state files parse, this session's file refreshing live; monitor.bat started flag-free; bonus: the known orphan tmp `c1eb55f7-….json.tmp.13252` auto-swept on the flipped monitor's first tick (D-08 observed live) |
| A — the flip is live | 2026-08-06 | 2.1.223 | PASS — full cycle on the working session (cd46dfa1): grey through a 70s foreground tool (PreToolUse 13:41:49 → PostToolUse duration 69.9s), green at Stop 13:43:07 with the >60s notification firing, grey again on the next UserPromptSubmit; overlay matched monitor-state at every observed point; hook-events trail confirms each transition. Bonus: a user Esc at 13:43:3x left no hook event (known silence, Section B's subject) |
| B — Esc-interrupt recovery | 2026-08-06 | 2.1.223 | PASS — 600s-sleep Bash launched 13:44:18Z, user Esc'd mid-run (zero hook events, silence confirmed), overlay GREEN with notification before the user's reply at 13:48:40Z (elapsed 4m22s < the 600s heartbeat window, so only the ~90s D-02a path can explain the green); user confirmed green + notification observed live |
| C — hook-silence pin | 2026-08-06 | 2.1.223 | PASS (thin but real crossing) — foreground Agent (a13aa08e) ran a single 690s Bash: last state write PostToolBatch 13:50:11Z, next write 14:00:27Z → 616s staleness, ~16s (~3 ticks) past the 600s boundary with the D-02b pin holding WORKING via the in-flight foreground-Agent evidence. A failed pin would have produced 3 WAITING ticks > the 2-tick debounce → toast at ~14:00:21; user confirmed no notification fired during the window. Note: harness moved the tool to the agent's background at its own 600s cap — irrelevant to the state-file silence being measured |
| D — the bridge | 2026-08-19 | 2.1.234 | PASS — bridge exercised faithfully by removing a live session's state file: yunoai·poland (46d45c0b) state file moved away 09:20:20→09:20:55Z (~7 monitor ticks), row stayed visible grey throughout (user-confirmed), carried by the legacy_origin jsonl bridge alone; file restored intact. Setup note: the first attempt (uat-hookless container with a copied, hook-stripped ~/.claude, CC 2.1.235) proved structurally unable to exercise the bridge — a container mounting its OWN separate ~/.claude writes its jsonl there too, so the monitor sees neither state file nor transcript; such containers are fully out of the monitor's sight by architecture (and a first rig also lacked the `project` docker label, which gates scan_containers entirely). The bridge's real scope is sessions in the shared ~/.claude whose hooks are absent/silent — exactly what was tested |
| E — ghost suppression | 2026-08-18 | 2.1.234 | PASS — user exited the macbook-devbox session cleanly: tombstone `d9fc4891….ended` written 14:17:08Z in lockstep with the SessionEnd hook event; row disappeared from the overlay immediately and stayed gone across a monitor restart (the on-disk tombstone surviving the restart, as designed) |
| F — paused container | 2026-08-18 | 2.1.234 | PASS — container 57b506855d6e paused mid-turn during a long foreground tool: state file silent from 14:46:25Z to 14:58:44Z (739s, crossing the 600s heartbeat window by ~139s), zero entries in notifications.log for the whole window, and the user confirmed the row stayed grey and visible throughout — the `hostname_to_status == "paused"` guard holding WORKING, no time-based degrade to WAITING. Bonus observation: the harness's own 590s wall-clock timeout moved the frozen tool to background on unpause, with no effect on the monitor verdict |
| G — badge-only background rule | 2026-08-18 | 2.1.234 | PASS — two live runs (09:55Z and 10:04Z): at turn end with a 120s background sleep in flight the row went green immediately with the ◉1 badge (state file `waiting`, `background_tasks_count: 1`); toast held per the gate (`suppressed, reason: background_tasks` in notifications.log). Run 1: toast released 55s later (`gate_cleared`, on the idle Notification). Run 2: user replied before release → held toast correctly discarded (`session_resumed`). User confirmed grey→green+badge live and ratified the held-toast semantics (notification = "fully idle"); pass condition above updated to match |
| H — the retirement gate (BLOCKING) | 2026-08-18 | 2.1.234 | PASS — Trigger 1 (tool permission prompt, manual mode): 13:12:15Z PermissionRequest on a real Bash call → state file sampled live at `needs_input`/`PermissionRequest` for 26 consecutive 1s samples until the user denied; repeated 13:14:10Z (approved, with `Notification permission_prompt` at +6s). Trigger 2 (AskUserQuestion modal): 10:14:26Z PermissionRequest + 10:14:32Z Notification → notifications.log `needs_input → sent`; overlay rendered green (= "your turn"), correct per the July design. This is the pre-flip existing-install case: auq-lock is still registered, but the state FILE is written by state-writer.sh alone, so both verdicts are the state-writer's independent path — the condition the section requires before teardown |
| I — preserved fixes | 2026-08-18 | 2.1.234 | PASS — Trigger 1 (alias vs /clear): label set on the claude-greenlight row survived /clear unchanged (container-keyed aliases). Trigger 2 (multi-monitor toast): monitor window moved to the secondary display, 90s turn ended 14:24:39Z, notification `sent` in the log and user confirmed the toast rendered above the monitor window on the secondary screen, not off-screen (bonus: quick-260818-c9o's virtual-screen geometry fix live in the same restart). Trigger 3 (sub-60s threshold): 8s turn (14:16:06→14:16:14Z), zero entries in notifications.log — below NOTIFY_MIN_WORK_SEC nothing is even armed; user confirmed full silence |
| Teardown | 2026-08-19 | 2.1.234 | DONE (after Section H PASS, per the D-04 gate) — `install.sh --remove-auq-lock` stripped the 4 preserved registrations (settings backup left on disk); `auq-lock.sh` and `auq-locks/` deleted; divergence log deleted; zero orphan `*.tmp.*` (the D-08 sweep had already fired live at Setup); post-checks: working-lock 3, state-writer 10, event-logger 22 (post quick-260818-ejg), auq-lock 0, `monitor-state/` intact and untouched |

---

## Tests

<!-- UAT objective: the flip confirmed live end to end, the retirement gate passed before the
retired lock was removed, and the machine-side teardown completed — filled in after the live run
on the Windows machine. -->

### 1. Setup — registration counts, state files writing, monitor starts flag-free
expected: working-lock 3 / state-writer 10 / event-logger 24 / auq-lock 0 (fresh install); state files parse; monitor.bat starts with no flag
result: pass — 2026-08-06 (CC 2.1.223): counts 3/10/24; auq-lock 4 preserved (pre-flip install, WR-02 behavior confirmed live incl. the informational installer note); state files parse and refresh; monitor flag-free; orphan tmp auto-swept on first tick

### 2. Section A — the flip is live
expected: overlay state matches monitor-state/*.json at every observed point
result: pass — 2026-08-06 (CC 2.1.223): working→waiting→working cycle observed live with the >60s notification; state file and overlay agreed throughout

### 3. Section B — Esc-interrupt recovery
expected: recovery at ~90s, not 600s
result: pass — 2026-08-06 (CC 2.1.223): green + notification within 4m22s of tool launch (mathematically excludes the 600s path); Esc itself hook-silent as researched

### 4. Section C — hook-silence pin
expected: no false notification past 600s during genuine long-running tool/agent work
result: pass — 2026-08-06 (CC 2.1.223): 616s of state-file staleness (600s boundary crossed by ~3 ticks), no false notification, D-02b foreground-Agent pin held; see table note for the exact event timeline

### 5. Section D — the bridge
expected: hookless session stays visible via legacy_origin bridge
result: pending

### 6. Section E — ghost suppression
expected: ended session's row stays gone, including across a monitor restart
result: pending

### 7. Section F — paused container
expected: paused session stays an ordinary visible row, no degrade to WAITING
result: pending

### 8. Section G — badge-only background rule
expected: green + notify immediately at turn end regardless of background_tasks_count; badge still shows the count
result: pending

### 9. Section H — the retirement gate (BLOCKING)
expected: needs_input state produced for both permission prompt and AskUserQuestion on a build without auq-lock.sh
result: pending

### 10. Section I — preserved fixes
expected: alias survives /clear; toast placement correct on secondary display; sub-60s turn does not notify
result: pending

### 11. Teardown
expected: auq-lock.sh removed only after Section H passed; divergence log deleted; orphan temp file confirmed auto-swept; monitor-state/ NOT deleted
result: pending

## Summary

total: 11
passed: 4
issues: 0
pending: 7
skipped: 0
