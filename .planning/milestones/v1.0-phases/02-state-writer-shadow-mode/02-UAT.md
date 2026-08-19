---
status: complete
phase: 02-state-writer-shadow-mode
plan: 05
source: [02-02-SUMMARY.md, 02-04-SUMMARY.md, hooks/state-writer.sh, hooks/state-writer-events.json, hooks/install.sh, monitor.py]
prepared: 2026-07-29
mode: complete   # all sections closed live; Section E review concluded 2026-08-06 — see 02-DIVERGENCE-REVIEW.md
verdict: shadow mode validated over a full week; Section E review (2026-08-06) classified all 212 divergences into 6 known classes and concluded GREEN — flip approved, proceed to /gsd-plan-phase 3
---

# Phase 2 Live Runbook — Shadow-Mode Activation

## What this is, and why

This is the activation runbook for Phase 2 of the hook-driven state refactor. `hooks/state-writer.sh`
is now registered on ten lifecycle events (`hooks/state-writer-events.json`) and writes one atomic
JSON verdict file per session to `~/.claude/monitor-state/<session_id>.json`. `monitor.py` runs a
second, independent verdict engine (`scan_state_files()`) on every tick alongside the existing
jsonl-parsing engine (`scan()`), compares the two (`diff_verdicts()`), and logs every disagreement to
`~/.claude/monitor-divergence.log` (`write_divergences()`). **The overlay, toasts, audio, taskbar
flash and Telegram push are still driven exclusively by the legacy engine** — `select_render_sessions()`
is the single seam that enforces this, and it returns the legacy list by identity whenever `--state-files`
is not passed (D-01). This runbook's job is to confirm that absence of change, and that the divergence
log is filling with records worth a later review conversation — **not** to decide the Phase 3 flip.

Everything in Phase 2 so far ran against synthesised payloads on a local filesystem, no Docker. Three
facts this runbook exists to close only exist on the real machine: that `docker inspect` reports the
status enum `scan_state_files()`'s staleness guard branches on, that the writer's tmp+rename is
genuinely atomic on the 9p mount under a mid-write kill, and that the overlay is truly unchanged to a
human eye. Per D-05, this is user-assisted UAT — the agent cannot `docker kill` a live container or
press Esc mid-turn from inside this sandbox.

---

## Setup

Run these once, in order, from inside one container with this repo checked out.

1. **Install the state writer (alongside the existing hooks).**
   ```bash
   bash hooks/install.sh
   ```
   This installs `auq-lock.sh`, `working-lock.sh`, `event-logger.sh` and `state-writer.sh` and merges
   all four into `~/.claude/settings.json`. It also creates `~/.claude/monitor-state/`.

2. **Confirm the state writer registered on every event in `state-writer-events.json`.**
   ```bash
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("state-writer\\.sh"))] | length' ~/.claude/settings.json
   jq 'length' hooks/state-writer-events.json
   ```
   Both numbers must match (10: `SessionStart`, `UserPromptSubmit`, `PostToolUse`,
   `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `Notification`, `Stop`,
   `SubagentStop`, `SessionEnd`).

3. **Confirm the existing lock hooks were not disturbed.** `install.sh`'s state-writer registration
   pass is a separate `jq` pass from the lock merge (SW-03) — count entries before/after if you have a
   backup, or just confirm the counts below match the settings-snippet shape:
   ```bash
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("working-lock\\.sh"))] | length' ~/.claude/settings.json   # expect 3
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("auq-lock\\.sh"))] | length' ~/.claude/settings.json       # expect 4
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("event-logger\\.sh"))] | length' ~/.claude/settings.json
   ```
   The `event-logger.sh` count should equal `jq 'length' hooks/hook-events.json` — Phase 1's diagnostic
   logger is unaffected by this plan and stays installed.

4. **Restart the Windows monitor** (or start it if it wasn't running). `settings.json` is read at
   session start, so any Claude Code session already running before step 1 won't have the state
   writer wired up — restart those too.

5. **Confirm the state directory is filling and the divergence log exists.** After a minute or two of
   ordinary use in at least one session:
   ```bash
   ls ~/.claude/monitor-state/          # one <session_id>.json per live session
   jq -c . ~/.claude/monitor-state/*.json   # each file must parse
   ls -la ~/.claude/monitor-divergence.log 2>/dev/null || echo "not yet written — fine, it only appears once the first divergence fires"
   ```

6. **Record the Claude Code version**, same discipline as `01-UAT.md`:
   ```bash
   claude --version
   ```

---

## Section A — Zero visible change (D-01)

A short, honest checklist to run across an ordinary hour of real work. The question to answer is
**"is it different in any way at all"**, not "is it better". D-01 is locked for this phase: an
improvement noticed here is a defect to report, not something to keep.

- [ ] Session labels in the overlay (standard and compact) are identical to before.
- [ ] The grey-to-green flip feels the same — same moments, same latency.
- [ ] The toast, the audio cue and the taskbar flash still fire on the same events, with the same
      wording.
- [ ] The Telegram push (if configured) still fires on the same events, same wording.
- [ ] The `bg`/`monitor`/`agent` badges look exactly as before (`shell_tracker` is untouched this
      phase — the unified `background_tasks_count` badge is a Phase 3 change, not visible now).
- [ ] A session that ends still disappears from the overlay the same way it always has.
- [ ] Docker container section / aliases / config UI are unaffected.

**Record:** anything that looks different, in either direction — including something that looks
better. Per D-01 that goes in the divergence log's evidence trail for the Section E review
conversation, not into a "nice, ship it" pile.

---

## Section B — The two environment assumptions

### B1 — The container-status enum (RESEARCH A1 / ENG-03)

`scan_containers()` builds `hostname_to_status` from one `docker inspect` call per tick:
```bash
docker inspect --format '{{.Config.Labels.project}}\t{{.Config.WorkingDir}}\t{{.State.Status}}\t{{.Config.Hostname}}' <container-id>
```
`scan_state_files()`'s staleness guard reads exactly the third field (`{{.State.Status}}`) and only
treats the literal string `"paused"` as alive-but-frozen (D-06) — anything else lets the heartbeat
staleness recovery proceed. Run the inspect command against three states of the same container and
record the three literal strings returned:

1. **Running:** start (or resume) a container normally, run the command above, record the status string.
2. **Paused:** `docker pause <container-id>`, run the command again, record the status string.
3. **Stopped:** `docker unpause <container-id>` then `docker stop <container-id>`, run the command a
   third time, record the status string (or confirm `docker inspect` still returns a row at all for a
   stopped-but-not-removed container — a removed container won't be in `docker ps` output at all, so
   it never reaches this codepath).

**Pass condition:** the three strings observed are `running`, `paused`, and a third value for stopped
(commonly `exited`) — and the `paused` string exactly matches the literal `"paused"` the guard checks
for. If your Docker reports a different literal for the paused state, that is a real finding for the
Section E review, not something to silently patch around here.

### B2 — Atomicity under a mid-write kill (RESEARCH A3)

1. Start a turn in a container that has the state writer installed (step 1 of Setup).
2. Mid-turn (while a tool call is in flight, so `state-writer.sh` is actively being invoked on
   `PostToolUse`/`PostToolBatch`), kill the container: `docker kill <container-id>`.
3. Immediately after, from the host (or another live container sharing the mount):
   ```bash
   for f in ~/.claude/monitor-state/*.json; do jq -e . "$f" >/dev/null || echo "CORRUPT: $f"; done
   ls ~/.claude/monitor-state/*.tmp.* 2>/dev/null && echo "STALE TMP FILE FOUND" || echo "no stale tmp files"
   ```

**Pass condition:** no `CORRUPT:` lines — the writer's tmp-then-`mv -f` pattern (`state-writer.sh`,
same directory, same filesystem) means a kill can only ever catch the process before the `mv`, never
mid-write to the final path. A leftover `<sid>.json.tmp.<pid>` file is expected and harmless —
`scan_state_files()` globs only `*.json`, which structurally excludes it from ever being picked up
as a session. Repeat 2-3 times across different points in a turn (mid-`PostToolUse`, mid-`Stop`) for
confidence.

---

## Section C — The hook-silent cases

For each case: the trigger, what `~/.claude/monitor-state/<sid>.json` should show, the staleness
window that resolves it, and what `~/.claude/monitor-divergence.log` should (and should not) contain.
Staleness windows are quoted from the constants as shipped: `STATE_HEARTBEAT_STALE_SEC = 600` (10 min,
the default heartbeat window) and `STATE_PROMPT_STALE_SEC = 90` (the shorter window used only when
`last_event` is `UserPromptSubmit`, mirroring legacy's own `USER_PROMPT_WORKING_SEC = 90`).

### C1 — Esc interrupt (TEST-MATRIX case 8)

**Trigger:** press Esc mid-turn, during a tool call.

**Expected state file:** `last_event` frozen at whatever fired last before the interrupt
(`PostToolUse`/`PostToolBatch`/`UserPromptSubmit`), `state` frozen at `"working"` — no event fires on
an interrupt (confirmed live in Phase 1: total hook silence after the last `PreToolUse`).

**Recovery:** `STATE_HEARTBEAT_STALE_SEC` (600s) after the last heartbeat, `scan_state_files()` flips
the shadow verdict WORKING → WAITING (the container is still alive and not `paused`, so the B1 guard
doesn't block recovery).

**Divergence log:** expect a `diverged` record to open (`legacy_verdict=WORKING`,
`state_file_verdict=WAITING`) once the shadow engine recovers — legacy's own `working-lock` can pin
WORKING for up to an hour after an interrupt (`WORKING_LOCK_MAX_AGE_SEC = 3600`, and its stale-lock
guard needs the jsonl mtime to advance, which a genuinely interrupted turn may not do for a while).
This is exactly the kind of "hooks recovers faster" divergence D-04 asks you to weigh, not fix in code.

### C2 — Permission prompt denied (TEST-MATRIX case 5-deny)

**Trigger:** trigger a tool outside the allowlist, then deny the permission prompt.

**Expected state file:** `PermissionRequest` fires instantly, `last_event="PermissionRequest"`,
`state="needs_input"` → shadow status WAITING immediately (D-07: `needs_input` renders identically to
turn-end WAITING, no new colour). Per the live Phase 1 campaign, `PermissionDenied` never fires at all
on this Claude Code version — no further hook event marks the resumption.

**Divergence log:** expect a short-lived `diverged` record (`state_file_verdict=WAITING`,
`legacy_verdict=WORKING`) that opens the moment `PermissionRequest` lands and closes (`resolved`) once
legacy's own `auq-lock` catches up via the `Notification` event, which the Phase 1 campaign measured at
roughly 6 seconds behind. This is the canonical "hooks-right, more timely" divergence D-04 names —
celebrate it in the review conversation, don't treat it as a regression to silence.

### C3 — Container killed mid-turn (TEST-MATRIX case 9)

**Trigger:** `docker kill <container-id>` (or close the terminal) mid-turn, before `Stop` fires.

**Expected state file:** `last_event` frozen at the last heartbeat, `state` frozen at `"working"` — no
`SessionEnd` fires for a kill (confirmed live: kill, a graceful `docker stop`, and `docker pause` are
all hook-silent).

**Recovery:** same 600s/90s window as C1. `hostname_to_status` has no entry at all for a killed
container (it's gone from `docker ps` output entirely), so the paused-guard never blocks recovery here.

**Divergence log:** expect a `diverged` record to open at the 600s/90s mark and to stay open
considerably longer on the legacy side — legacy's `working-lock` (max age 3600s) has no way to notice
the container is dead (its stale-lock guard depends on the jsonl mtime advancing, which a dead
container's jsonl never does again), so legacy can stay WORKING for up to an hour past the point the
shadow engine already recovered. Confirm the `resolved` record's `ticks` field once legacy's own
staleness eventually agrees (or the session ages out of `MAX_AGE_SEC` on both sides and disappears).
The orphaned state file itself is swept by `scan_state_files()`'s `STATE_PRUNE_AGE_SEC` (24h) sometime
after — well past the point either engine would still be showing it.

### C4 — Container paused then unpaused (TEST-MATRIX case 9, D-06)

**Trigger:** mid-turn, `docker pause <container-id>`; wait a few minutes past the heartbeat window;
then `docker unpause <container-id>` and let the turn continue.

**Expected state file while paused:** `last_event`/`state` frozen exactly as in C1/C3, but this time
`hostname_to_status` for this session's hostname reads `"paused"` (confirmed in B1) — D-06 requires the
staleness guard to treat this as alive-but-frozen and **not** flip to WAITING, unlike C1/C3.

**Pass condition:** the shadow verdict stays WORKING for the entire paused window, even well past 600s
— this is the negative case: **no** `diverged` record should open purely from elapsed time while
paused. If one does, that's a real bug (the paused-vs-exited distinction failing), not a divergence to
classify away.

**On unpause:** the session resumes writing heartbeats normally; confirm the state file starts updating
again and nothing needed manual intervention.

### C5 — Abandoned pre-tool prompt (TEST-MATRIX case 19)

**Trigger:** submit a prompt, then kill Claude's process before the first tool call (container stays
alive, terminal stays open).

**Expected state file:** `last_event="UserPromptSubmit"`, `state="working"` — no `PostToolUse`/
`PostToolBatch` heartbeat ever arrives because no tool ever ran.

**Recovery:** the shorter `STATE_PROMPT_STALE_SEC` window (90s) applies specifically because
`last_event == "UserPromptSubmit"` — deliberately identical to legacy's own `USER_PROMPT_WORKING_SEC`
(also 90s), so both engines should recover at roughly the same wall-clock moment.

**Divergence log:** expect little to no meaningful divergence here — at most a very short-lived
`diverged`/`resolved` pair from tick-timing jitter between the two 90s windows. A near-simultaneous
recovery on both sides is itself the confirmation this case is asking for (the matched-window design
decision working as intended), not an absence of anything to check.

### C6 — Container running an image with no hooks installed (TEST-MATRIX case 21)

**Trigger:** run a session from an image (or a container) where `hooks/install.sh` was never run, so
`~/.claude/settings.json` has no `state-writer.sh` entries for that container.

**Expected state file:** none is ever written for that session_id — confirmed absence, not a
degraded one.

**What `scan_state_files()` does instead:** its `legacy_sessions` migration bridge (ENG-05) carries this
session through from the ordinary `scan()` (jsonl) list unchanged, tagged internally with
`legacy_origin: true`. The shadow list therefore contains this session with the SAME verdict legacy
computed for it.

**Divergence log:** expect **no** divergence record for this session's key — `diff_verdicts()` compares
`legacy_verdict` against `state_file_verdict`, and since the shadow side is a direct copy of the legacy
verdict for this session, they agree by construction. Confirm the session is still visible in
`--state-files` diagnostic mode (Section D) rather than silently dropped — that's what "degrades
gracefully" means here.

### C7 — Two containers mounting the same `/workspace` at once (TEST-MATRIX case 15)

**Trigger:** run two containers in parallel, each with its own Claude Code session, both mounting
`/workspace` (the known cwd-collision case — legacy's `cwd`-based label mapping cannot tell them apart
on `cwd` alone).

**Expected state files:** two separate `<session_id>.json` files, each carrying its own container's
`hostname` field (captured by `state-writer.sh` at write time via `$HOSTNAME`) — the collision is
structurally impossible at the state-file layer because files are keyed by `session_id`, never by
`cwd`.

**Pass condition:** both sessions remain visible with **distinct** labels in `--state-files` diagnostic
mode (Section D) — `scan_state_files()` resolves each one's name via `sessionid_to_label` first,
falling back to `container_info["hostname_to_label"]` (built from the same `docker inspect` call as
B1) when `docker exec`-based `sessionid_to_label` can't resolve it (e.g. a paused container). Confirm
neither session's label gets silently overwritten by the other's, reproducing the legacy "killed
sibling steals the label" bug would be a real regression here.

---

## Section D — The diagnostic mode

`monitor.py --state-files` renders and notifies from the shadow engine instead of legacy, for
hands-on verification of the new engine's own view — including its notification behaviour, not just
its labels.

```bash
python monitor.py --state-files
```

**Before running it:** close any normally-running monitor instance first. The monitor holds a
process-wide singleton lock (`SINGLETON_PORT`); a second instance — with or without the flag — started
while one is already running exits silently rather than erroring loudly, so check there's genuinely
nothing running (or check for the expected window) before concluding the flag itself is broken.

**What to expect that's different from the normal run, by design (not a bug):**
- The `bg`/`monitor`/`agent` badge trio is **not** reproduced. `scan_state_files()` hardcodes
  `monitors: 0` and `agents: 0` for every session and derives `bg` purely from
  `background_tasks_count > 0` — this mode previews the single unified background-task signal the
  Phase 3 flip will surface, not today's `shell_tracker`-driven pair. Seeing only one badge signal
  here (or none) is expected, not a defect to report under Section A.
- Labels, colours and staleness feel should otherwise match the normal run — that's the actual thing
  this mode is for confirming, alongside notification timing on `needs_input` (C2).

Close the diagnostic run and restart the normal monitor when done — the normal run is what should be
left active for the rest of the week (per the checkpoint in this plan's Task 2).

---

## Section E — The divergence review protocol

**How review works (D-02):** the user does not read `~/.claude/monitor-divergence.log` directly.
Claude reads and analyzes it in-session, with the user, during a dedicated review conversation. Here
are the triage commands for that conversation, using the field names `diff_verdicts()`/
`filter_divergence_events()` actually emit — `legacy_verdict`, `state_file_verdict`, `key`,
`last_event`, `ts_ms`, `event` (`"diverged"` or `"resolved"`), `since_ts_ms`, `ticks`.

**Count records by verdict pair** (which disagreements are the most common shape):
```bash
jq -r 'select(.event=="diverged") | "\(.legacy_verdict) -> \(.state_file_verdict)"' \
  ~/.claude/monitor-divergence.log | sort | uniq -c | sort -rn
```

**List the distinct `last_event` values involved** (which hook events tend to precede a divergence):
```bash
jq -r 'select(.event=="diverged") | .last_event // "null"' \
  ~/.claude/monitor-divergence.log | sort | uniq -c | sort -rn
```

**Show the longest-lived episodes** (via the `resolved` record's `ticks` count — how many ticks a
disagreement persisted before it closed):
```bash
jq -r 'select(.event=="resolved") | "\(.ticks)\t\(.key)\t\(.since_ts_ms)"' \
  ~/.claude/monitor-divergence.log | sort -rn | head -20
```

**If the log was ever truncated** (past `DIVERGENCE_LOG_MAX_BYTES`, 5MB), an explicit `_truncated`
marker record precedes the gap — filter it out of the triage commands above if needed:
```bash
jq -c 'select(.event != "_truncated")' ~/.claude/monitor-divergence.log | wc -l
```

**Classification (happens during the conversation, not in code):** every persisting divergence gets
one of three labels — **legacy-wrong** (the state-file engine is correct, legacy's inference failed),
**hooks-wrong** (the state-file engine mis-derived the verdict), or **both-defensible** (a genuine
semantic ambiguity, neither is "wrong"). A divergence where the hook engine turns out to be the correct
one — C2's timeliness case is the known example — **is a finding worth keeping, not a regression to
apologize for.**

**Cadence (D-03):** roughly a week of real usage. The exact number of days is agreed together during
the review conversation, not fixed in advance. **There is no automatic flip** — Phase 3 only happens
after this conversation concludes the review window is enough.

---

## Section F — The lock hooks (SW-03)

A short pass confirming `working-lock.sh` and `auq-lock.sh` are unaffected by the state writer running
alongside them — they are still the mechanisms actually driving the overlay during Phase 2 (D-01), not
a legacy fallback being phased out yet.

1. **AskUserQuestion modal:** ask Claude to use `AskUserQuestion`. Confirm the overlay turns GREEN the
   moment the modal appears (via `auq-lock.sh`'s `PreToolUse` `set`, matcher `AskUserQuestion`), and
   confirm `~/.claude/auq-locks/<session_id>` exists while the modal is open:
   ```bash
   ls ~/.claude/auq-locks/
   ```
2. **Tool-permission prompt:** trigger a tool outside the allowlist. Confirm the overlay turns GREEN
   (via `auq-lock.sh`'s `Notification` `set`) and the same lock file appears.
3. **Long tool call:** run a task with a long-running tool (slow Bash, deep research). Confirm the
   overlay stays GREY for the whole duration (via `working-lock.sh`'s `PreToolUse` re-arm), and confirm
   `~/.claude/working-locks/<session_id>` exists and its mtime is advancing while the tool runs:
   ```bash
   ls ~/.claude/working-locks/
   ```

**Pass condition:** all three behave exactly as they did before this phase — SW-03's migration
guarantee (already asserted by `test_state_writer.py`'s `Goal8_MigrationNonRegression`) holding on the
real machine too, not just in the container test suite.

---

## Teardown

**One-command rollback**, usable at any point during the review week, not only at the end:
```bash
bash hooks/install.sh --remove-state-writer
```
This strips every `state-writer.sh` entry from `~/.claude/settings.json`. `working-lock.sh` and
`auq-lock.sh` stay installed either way — they remain load-bearing (they're what actually drives the
overlay, per D-01) until Phase 3, regardless of whether the state writer itself is rolled back.

To fully clean up once shadow mode's job is done (after the Section E review concludes, not before):
```bash
rm -rf ~/.claude/monitor-state
rm -f ~/.claude/monitor-divergence.log
```

---

## Recording format

Write results as: **date, Claude Code version, outcome** — same convention as `01-UAT.md`. "No change
observed" and "no divergence recorded" are valid, valuable outcomes and must be written explicitly,
not left blank.

| Section / Case | Date | CC version | Outcome |
|---|---|---|---|
| Setup (registration counts) | 2026-07-30 | 2.1.220 | PASS — state-writer 10, working-lock 3, auq-lock 4, event-logger intact; state files + divergence log both live |
| A — zero visible change | | | |
| B1 — container-status enum | 2026-07-30 | 2.1.220 | PASS — `running` / `paused` observed; `paused` matches the guard's literal exactly. Stopped state unobservable: containers run with `--rm`, `docker stop` auto-removes (`no such object`) — removed containers never reach the guard's codepath, per this runbook's own note |
| B2 — atomicity under kill | 2026-07-30 | 2.1.220 | PASS — `docker kill` on container aaeacb4c551b mid-session: all 4 state files parse, no stale tmp files. Killed session's file frozen intact at `last_event=UserPromptSubmit` |
| C1 — Esc interrupt | 2026-07-30 | 2.1.220 | PASS with INVERTED divergence vs this runbook's prediction — session a7a22920 (claudia, 3773d4f725d6), Esc mid-python-sleep: state file froze at `PostToolBatch`/`working` (hook silence confirmed). BUT the interrupt DOES advance the jsonl on CC 2.1.220: the stale-lock guard released working-lock, legacy flipped WAITING at ~90s (panel grey→green observed live at 09:33:46). Divergence opened `legacy=WAITING vs shadow=WORKING` — legacy MORE timely here (90s vs shadow's 600s heartbeat window). Episode ran 39 ticks (~3.5 min), closed when the user resumed the session. KEY Section E / Phase 3 finding: the Esc case REQUIRES the hybrid model's jsonl fallback — a pure hook engine would regress interrupt recovery from ~90s to 600s |
| C2 — permission denied | 2026-07-30 | 2.1.220 | PASS — session 774c198d (dev-tools): `PermissionRequest` → `needs_input`/WAITING instantly (legacy still ABSENT at that tick); legacy caught up via auq-lock ~5-10s later, episode auto-resolved. Post-deny hook silence confirmed live: shadow stuck at `needs_input` ~45s (9 ticks) until turn end — the known `PermissionDenied`-never-fires gap, recorded as a Section E finding |
| C3 — container killed | 2026-07-30 | 2.1.220 | PASS with corrected expectation — two live runs (bg-gate variant 254f2027/465baf32639c, canonical mid-turn 7f317b9a/b699f1ddd1f0): NO divergence ever opens, because BOTH engines drop a killed container's session at label-resolution time (shadow: `scan_state_files` name-`continue`; legacy: deliberate stale-sessionId drop, monitor.py ~1000). Session vanishes from the overlay instantly on both sides — identical, symmetric, and correct (a dead session can't need input). This runbook's original prediction (legacy pinned WORKING up to 1h by working-lock) was wrong: the lock exists (verified: lock file present post-kill) but never becomes visible — label resolution discards the session first. Recorded as a Section E finding: the 600s staleness recovery only matters for live-container hook-silent cases (C1/C4), not for kills |
| C4 — container paused/unpaused | 2026-07-30 | 2.1.220 | PASS — session a7a22920 (claudia, 3773d4f725d6) paused 09:37→09:54 (17 min, well past the 600s window): shadow NEVER flipped to WAITING (D-06 paused guard verified live; watch ran to 09:53:29 clean). Bonus finding: LEGACY drops a paused session entirely (docker exec unreachable → name unresolvable → panel row vanishes), while shadow keeps it via `hostname_to_label` — the exact divergence `diff_verdicts()`'s docstring names, logged 09:37:37, held open the whole pause, resolved 09:54:19 within 5s of unpause (heartbeats resumed spontaneously, `Stop`→`waiting`). Panel-visibility idea captured as todo `2026-07-30-show-paused-container-sessions-…` (commit 0808c02) |
| C5 — abandoned pre-tool prompt | 2026-07-30 | 2.1.220 | PASS (reproduced via B2's kill, which landed pre-first-tool): state file frozen at `UserPromptSubmit`/`working`; no divergence record ever opened past the 90s mark — both engines recovered near-simultaneously via their matched 90s windows, exactly the confirmation this case asks for |
| C6 — hookless container | 2026-07-30 | 2.1.220 | N/A on this environment (literal trigger impossible: `~/.claude` is bind-mounted into every container, so hooks are always installed) — BUT the `legacy_origin` bridge C6 exists to prove was exercised live by an equivalent path: session f903ed8f lost its state file (SessionEnd `rm -f`) while its jsonl was still legacy-visible; the bridge carried it through with the identical legacy verdict, visible in the panel, zero divergence records. Bridge behavior also covered by the automated suite (163 green) |
| C7 — two containers, same /workspace | 2026-07-30 | 2.1.220 | PASS — three parallel sessions (claude-greenlight, yunoai, claudia), ALL with cwd `/workspace`, rendered with distinct correct labels in `--state-files` mode; state files keyed by session_id with per-container hostname made the legacy cwd-collision structurally impossible. Corroborated by the whole day's divergence log: labels never crossed between containers |
| D — diagnostic mode (`--state-files`) | 2026-07-30 | 2.1.220 | PASS — normal monitor closed, diagnostic launched on Windows: shadow-engine rendering looked correct to the user (labels, colors); three same-cwd sessions shown distinctly (see C7). Badge caveat understood as by-design. Normal monitor restarted afterwards |
| E — divergence log accumulating | 2026-07-30 | 2.1.220 | PASS — episodic records accumulating and parseable all day; review conversation itself stays scheduled for end of the ~1-week window (D-03) |
| F — lock hooks (AUQ / permission / long tool) | 2026-07-30 | 2.1.220 | PASS — AUQ: card open on claudia → panel green instantly, `auq-locks/a7a22920` fresh (10:06); bonus: shadow state file also flipped `needs_input` via `Notification` — both engines agree on AUQ waits on CC 2.1.220. Permission prompt: green at prompt, grey on deny-and-resume, green at turn end (observed live under C2). Long tool: sessions stayed grey through multi-minute python sleeps with working-lock present and pinned (observed under C1/C3 setup). SW-03 non-regression holds on the real machine |

---

## Tests

<!-- UAT objective: shadow mode confirmed running live, zero visible change, divergence log
accumulating parseable records — filled in during/after this plan's Task 2 checkpoint. -->

### 1. Setup — state writer registered, existing hooks undisturbed
expected: registration counts match (state-writer.sh: 10; working-lock.sh: 3; auq-lock.sh: 4); event-logger.sh count unchanged
result: pass — verified in-session 2026-07-30 (CC 2.1.220): counts 10/3/4 confirmed via jq; state files updating in ~/.claude/monitor-state/; divergence log accumulating episodic records with clean diverged/resolved pairs

### 2. Section A — zero visible change
expected: no perceptible difference across an ordinary hour of use; anything noticed (better or worse) recorded as a defect
result: pass — 2026-08-06: closed by inference over the full review week (2026-07-30 → 2026-08-06) of real daily use with shadow mode active; zero visible differences reported by the user in that window (far exceeding the prescribed single hour)

### 3. Section B1 — container-status enum
expected: three literal docker status strings recorded (running/paused/stopped variant)
result: pass — 2026-07-30 (CC 2.1.220), container `claudia` (b6438f373adf): `running` and `paused` observed live; `paused` exactly matches the D-06 guard literal. Stopped state structurally unobservable on this machine: containers launched with `--rm` are auto-removed on stop (`docker inspect` → `no such object`), so a stopped-but-not-removed container never exists and never reaches the staleness-guard codepath (outcome anticipated by this runbook's B1 step 3 note)

### 4. Section B2 — atomicity under mid-write kill
expected: no corrupt state files after a mid-turn kill; no stale tmp file ever read as a session
result: pass — 2026-07-30 (CC 2.1.220): `docker kill aaeacb4c551b` with session 2c546472 live; every file in ~/.claude/monitor-state/ parses via `jq -e`, zero `*.tmp.*` leftovers. Killed session's file frozen cleanly at `state=working`, `last_event=UserPromptSubmit` (kill landed before the first tool heartbeat — so the 90s prompt-stale window governs recovery, observed under C3)

### 5. Section C1-C7 — hook-silent cases
expected: each case's state file / staleness window / divergence-log behavior matches this runbook's description
result: pass — 2026-07-30 (CC 2.1.220), all seven cases closed live (see table for detail). Two outcomes corrected the runbook's predictions, both recorded as Section E findings: C1 divergence runs INVERTED (Esc advances the jsonl → legacy recovers at 90s, shadow at 600s → the Phase 3 flip REQUIRES the hybrid jsonl fallback for interrupts), and C3 produces NO divergence at all (both engines symmetrically drop killed-container sessions at label resolution). C4 additionally surfaced that legacy loses paused sessions entirely while shadow keeps them (todo captured). C6 closed as N/A-with-indirect-live-evidence

### 6. Section D — diagnostic mode
expected: `--state-files` renders/notifies from the shadow engine; singleton behavior confirmed; badge caveat confirmed as by-design
result: pass — 2026-07-30 (CC 2.1.220): user ran the diagnostic on the real machine with three live sessions; labels and colors correct, three same-cwd sessions distinct (C7), normal monitor restarted after

### 7. Section E — divergence log accumulating
expected: `~/.claude/monitor-divergence.log` non-empty and parseable after a few hours of real use
result: pass — 2026-07-30 (CC 2.1.220): log accumulating clean episodic diverged/resolved pairs across every case exercised today (session-start transients, C1 inverted, C2 canonical, C4 paused-drop); all records parse via jq. REVIEW CONCLUDED 2026-08-06: full-week log (343 records) analyzed and classified in-session per the Section E protocol — verdict GREEN, flip approved. Full classification and Phase 3 carry-forwards in 02-DIVERGENCE-REVIEW.md

### 8. Section F — lock hooks non-regression
expected: AUQ modal, permission prompt, and long tool call all behave exactly as before this phase
result: pass — 2026-07-30 (CC 2.1.220): all three verified live (AUQ green + fresh lock file; permission prompt green/grey/green cycle; long tools grey with working-lock pinned). Bonus finding: the state writer also catches AUQ waits via Notification — shadow and legacy agree on needs_input

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
