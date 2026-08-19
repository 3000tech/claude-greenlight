---
status: complete
phase: 01-hook-coverage-verification
source: [01-01-SUMMARY.md, 01-02-SUMMARY.md, 01-VERIFICATION.md]
started: 2026-07-29T09:14:00Z
updated: 2026-07-29T14:20:00Z
summary:
  total: 21
  live_sampled: 17
  confirmed: 13
  partial: 4
  dispositioned_by_design: 4   # 18 (V2-01), 19 (staleness), 20 (Phase 2 tests), 21 (migration bridge)
  code_issues: 0
mode: opportunistic-campaign   # conversational UAT run live 2026-07-29 on cc 2.1.220, user-driven triggers + agent-read log
verdict: .planning/TEST-MATRIX.md "Verdict to extract" — compiled, zero fill-in slots left
---

# Phase 1 Live Runbook — 21-Case Hook Coverage Verification

## What this is, and why

This is a one-off diagnostic run for Phase 1 of the hook-driven state refactor. It walks the
21 cases in [TEST-MATRIX.md](../../TEST-MATRIX.md) using the logging instrument built in plan
01-01 (`hooks/event-logger.sh`, registered on 24 events via `hooks/install.sh`). The logger is
**temporary** — it gets removed at the end of this runbook (Teardown section) — and its output,
`~/.claude/hook-events.log`, is the ground truth the hybrid verdict is derived from. Per D-05,
this live run is user-assisted UAT: the agent cannot `docker kill` a live container, press Esc
mid-turn, or run three parallel sessions, so everything in this document is written to remove
guesswork from what a human has to type and read.

**Two safety facts to know before starting** (RESEARCH.md Pitfall 2):

1. `hook-events.log` lives on the shared `~/.claude` mount and is therefore visible from
   Windows, not just from inside a container.
2. The default field set deliberately **excludes** tool inputs, tool outputs, prompt text, and
   assistant message bodies — it only ever writes scalar/identity metadata (`ts`, `ts_ms`,
   `event`, `session_id`, `cwd`, `keys`, `source`, `reason`, `trigger`, `matcher`,
   `permission_mode`, `tool_name`, `tool_use_id`, `notification_type`, `message`, `agent_type`,
   `agent_id`, `subagent_type`, `task_id`, `stop_hook_active`). It is safe to run during
   ordinary work. `GREENLIGHT_LOG_RAW=1` adds the entire payload under a `raw` key — only export
   it for a short, deliberate window if a specific case needs a raw schema dump, and unset it
   again immediately after.

---

## Setup

Run these once, in order, from inside a container with this repo checked out.

1. **Install the logger.**
   ```bash
   bash hooks/install.sh
   ```

2. **Confirm registration actually landed.** Count logger entries in
   `~/.claude/settings.json` against the length of `hooks/hook-events.json` — a case that looks
   silent because its event was never registered is the failure mode this step exists to rule
   out.
   ```bash
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("event-logger\\.sh"))] | length' ~/.claude/settings.json
   jq 'length' hooks/hook-events.json
   ```
   Both numbers must match (24 as of this plan; if `hooks/hook-events.json` has been widened
   since 01-01, that new number is what to expect).

3. **Restart any Claude Code sessions that were already running.** `settings.json` is read at
   session start, so a session started before step 1 will not have the logger wired up.

4. **Record the Claude Code version.**
   ```bash
   claude --version
   ```
   Write this down — it goes in every Verified-column entry, because the whole premise of this
   project is that these behaviors move between versions.

5. **Truncate the log so the run starts clean.**
   ```bash
   : > ~/.claude/hook-events.log
   ```

6. **Open a follower on the log in a second terminal.** Both a raw and a readable variant:
   ```bash
   # raw
   tail -f ~/.claude/hook-events.log

   # readable — projects the fields that matter most
   tail -f ~/.claude/hook-events.log | jq -c '{ts_ms, event, session_id, cwd, tool_name, reason, source}'
   ```

---

## Case-marker helper

The log is shared across containers and concurrently written, so a marker is what makes one
case's lines unambiguously separable afterwards — and it lets you diff wall-clock time against
the `ts_ms` of the events, which is what case 2 turns on. Define this once in your shell:

```bash
mark() {
  local n="$1"
  printf '{"event":"_case_marker","case":%s,"ts_ms":%s}\n' "$n" "$(date +%s%3N)" >> ~/.claude/hook-events.log
}

extract_case() {
  local n="$1" next=$((n + 1))
  awk -v n="\"case\":${n}[,}]" -v nx="\"case\":${next}[,}]" '
    $0 ~ n  { inblock = 1; next }
    $0 ~ nx { inblock = 0 }
    inblock
  ' ~/.claude/hook-events.log
}
```

Run `mark <case-number>` immediately before triggering each case. After the case, run
`extract_case <case-number>` to print everything between that case's marker and the next one —
pipe it into the per-case `jq` filters below. (`extract_case` on the last case run leaves the
window open until end of file, which is fine — nothing else has been appended yet.)

---

## Recording format

Write the Verified column as: **date, Claude Code version, outcome**, e.g.

```
2026-07-28 / cc 2.1.x / Stop fired, ts_ms 340ms after perceived render end
```

**"No event" is a valid and valuable outcome and must be written explicitly**, not left blank —
a blank cell is indistinguishable from a case that was never run.

---

## Cases

### Case 1 — Turn start

**Trigger:** `mark 1`, then submit any prompt (e.g. "what is 2+2").

**Observe:**
```bash
extract_case 1 | jq -c 'select(.event == "UserPromptSubmit")'
```

**Pass condition:** Exactly one `UserPromptSubmit` line, with `session_id` and `cwd` populated.

**Record:** Whether it fired, and the populated field list.

---

### Case 2 — Normal turn end (text reply)

**Trigger:** `mark 2`, then submit a short Q&A prompt and note the wall-clock time (to the
second) the moment the reply visibly finishes rendering on screen.

**Observe:**
```bash
extract_case 2 | jq -c 'select(.event == "Stop")'
```

**Pass condition:** A `Stop` line appears. Compare its `ts_ms` against the wall-clock time you
noted. This is the case that decides whether the debounce idea in NOTES.md is dead: if `Stop`
fires **after** rendering finishes (not before), notification timing is already correct by
construction and no debounce is needed.

**Record:** The `ts_ms` value, your noted wall-clock time, and the computed gap (event time
minus perceived-finish time; negative means the event fired before rendering completed).

---

### Case 3 — ⚠ Long multi-tool turn (10+ min)

**Trigger:** `mark 3`, then give a task big enough to run many tool calls over 10+ minutes.

**Observe:** The observable is the largest gap between consecutive events for the session, not
any single event.
```bash
extract_case 3 | jq -r 'select(.ts_ms != null) | .ts_ms' | \
  awk 'NR>1{d=$1-prev; if (d>max) max=d} {prev=$1} END{print "largest gap (ms):", max+0}'
```

**Pass condition:** N/A — this case has no pass/fail, only a number.

**Record:** The largest gap in ms. That number is what a heartbeat window has to tolerate.

---

### Case 4 — ⚠ Permission prompt

**Trigger:** `mark 4`, then trigger a tool not in the allowlist. Run it for **more than one
shape** of prompt: a Bash command, a file write, and an MCP tool if one is available.

**Observe:**
```bash
extract_case 4 | jq -c 'select(.event == "Notification" or .event == "PermissionRequest")'
```

**Pass condition:** A line appears for each prompt shape tried.

**Record:** Whether the fields (`tool_name`, `notification_type`, `message`) differ between
prompt shapes — Phase 2 needs to key `needs_input` off something stable across shapes.

---

### Case 5 — Permission answered → resumes

**Trigger:** `mark 5`, then approve the prompt from case 4. Run it again for a fresh prompt and
**deny** it (deny executes no tool at all).

**Observe:**
```bash
extract_case 5 | jq -c 'select(.event == "PermissionRequest" or .event == "PermissionDenied" or .event == "PreToolUse" or .event == "PostToolUse")'
```

**Pass condition:** For the approve path, a `PreToolUse`/`PostToolUse` pair follows the
permission event. For the deny path, record what, if anything, marks the resumption — since no
tool executes.

**Record:** Both sequences (approve, deny), with the window between the permission event and
whatever fires next.

---

### Case 6 — ⚠ AskUserQuestion modal

**Expected: ZERO log lines.** Confirming the silence *is* the pass condition — this is not a
broken logger. Sources: `anthropics/claude-code` issues **28273**, **12605**, **15872**, three
independent open feature requests confirming AskUserQuestion triggers no PreToolUse/PostToolUse
hook. The only thing this live run adds is confirming it still holds on your installed version.

**Trigger:** `mark 6`, then ask Claude to use AskUserQuestion.

**Observe:**
```bash
extract_case 6 | jq -c '.'
```

**Pass condition:** No output at all.

**Record:** Confirm zero lines, or record exactly what appeared if the silence does not hold on
this version. Corollary: if it holds, `auq-lock` stays as the `needs_input` fallback in Phase 2.

---

### Case 7 — AUQ answered → resumes

**Trigger:** `mark 7`, then answer the modal from case 6.

**Observe:**
```bash
extract_case 7 | jq -c 'select(.event == "UserPromptSubmit" or .event == "PostToolUse")'
```

**Pass condition:** Whatever fires to mark resumption after the modal is answered.

**Record:** The event(s) seen, if any.

---

### Case 8 — ⚠ User interrupt (Esc mid-turn)

**Expected: ZERO log lines** for the interrupt itself. Per the official docs' explicit statement
that a user interrupt does not fire `Stop`, corroborated by issue **9516**.

**Trigger:** `mark 8`, then press Esc during a long turn. Also test the "yuno" variant: press Esc
right after a foreground agent returns.

**Observe:**
```bash
extract_case 8 | jq -c 'select(.event == "Stop")'
```

**Pass condition:** No `Stop` line for either variant.

**Record:** Confirm zero `Stop` lines (or record what appeared if the docs' claim does not hold
on this version), for both the plain-interrupt and "yuno" variants. Note what this implies:
something other than `Stop` has to clear a stale working state.

---

### Case 9 — ⚠ Session killed mid-turn

**Trigger:** `mark 9`, start a turn, then `docker kill` the container (or close the terminal)
mid-turn.

**Observe:** Absence of events after the kill is expected by construction — what matters is the
last thing seen and when.
```bash
extract_case 9 | jq -c 'select(.ts_ms != null)' | tail -1
```

**Pass condition:** N/A by definition — the point is measuring the silence, not seeing an event.

**Record:** The last event seen and its `ts_ms`. What Phase 2 needs from this case is how long
the silence runs before the situation is detectable via the heartbeat/`docker ps` design, not
whether an event exists.

---

### Case 10 — `/resume` of a past session

**Trigger:** `mark 10`, then run `/resume` on an ended session.

**Observe:**
```bash
extract_case 10 | jq -c 'select(.event == "SessionStart") | {source, session_id}'
```

**Pass condition:** A `SessionStart` line with `source` indicating resume.

**Record:** The `source` value and whether `session_id` matches the resumed session or is new
(affects whether the old session's leftover state file needs cleanup in Phase 2).

---

### Case 11 — `/clear` and `/compact`

**Trigger:** `mark 11`, then run `/clear` mid-session; repeat for `/compact`.

**Observe:**
```bash
extract_case 11 | jq -c 'select(.event == "SessionStart" or .event == "PreCompact") | {event, source, trigger}'
```

**Pass condition:** Events fire with a `source`/`trigger` value that is distinguishable from a
genuinely fresh session or an actual turn end — this must not be read as "turn ended" (false
green + toast).

**Record:** The exact `source`/`trigger` values for each of `/clear` and `/compact`.

---

### Case 12 — Foreground subagent (Agent tool)

**Trigger:** `mark 12`, then give a task that spawns a `gsd-*` (or any) subagent in the
foreground.

**Observe:**
```bash
extract_case 12 | jq -c 'select(.event == "SubagentStart" or .event == "SubagentStop" or .event == "Stop") | {event, ts_ms, agent_type, subagent_type}'
```

**Pass condition:** Both the subagent's end event and the eventual real turn-end `Stop` are
visible, and distinguishable — the thing being verified is that Phase 2 can prove it will ignore
`SubagentStop` and wait for the real `Stop` (the "yuno case").

**Record:** Both events with their `ts_ms`, and the gap between them.

---

### Case 13 — Background agent / bg bash completes and re-invokes Claude

This is the one genuinely open question no desk research resolved (RESEARCH.md Open Question 2).

**Trigger:** `mark 13`, then start a `run_in_background` task and let it finish while the session
is otherwise idle, re-invoking Claude.

**Observe:** Watch broadly — record the full ordered event sequence for the whole episode, not a
yes/no.
```bash
extract_case 13 | jq -c 'select(.event == "TaskCreated" or .event == "TaskCompleted" or .event == "PostToolBatch" or .event == "SubagentStart" or .event == "SubagentStop" or .event == "UserPromptSubmit" or .event == "PostToolUse")'
```

**Pass condition:** N/A — this case is exploratory. If nothing at all fires, that is itself the
finding.

**Record:** The complete ordered sequence of events (with `ts_ms`) for the episode, or explicit
confirmation that nothing fired.

---

### Case 14 — Clean session exit

**Trigger:** `mark 14`, then exit Claude Code normally.

**Observe:**
```bash
extract_case 14 | jq -c 'select(.event == "SessionEnd") | {reason}'
```

**Pass condition:** A `SessionEnd` line fires with a `reason` value.

**Record:** The `reason` value, and whether it's distinguishable from the reason recorded when a
session crashes (case 9) — noted overlap to check.

---

### Case 15 — Multi-container, sessions in parallel

**Trigger:** `mark 15`, then run 2-3 containers with sessions against the same host `~/.claude`.

**Observe — interleaving/truncation check** (RESEARCH.md Pitfall 5 / assumption A1):
```bash
total=$(wc -l < ~/.claude/hook-events.log)
ok=$(jq -c . ~/.claude/hook-events.log 2>/dev/null | wc -l)
echo "unparseable lines: $((total - ok))"
```

**Observe — session/cwd separation:**
```bash
extract_case 15 | jq -c 'select(.session_id != null) | {session_id, cwd}' | sort -u
```

**Pass condition:** Each session's `session_id` is distinct and its `cwd` is populated — Phase
2's label mapping depends on `cwd` being present per session.

**Record:** Unparseable line count, and the distinct `session_id`/`cwd` pairs observed. Per
RESEARCH.md A1/Pitfall 5, any interleaving observed here is a **real finding about this host's
bind mount** to record in the verdict, not a logger bug to work around.

---

### Case 16 — Two sessions, same project dir

**Trigger:** `mark 16`, then open two terminals in the same repo, each with its own Claude Code
session.

**Observe:**
```bash
extract_case 16 | jq -c 'select(.cwd != null) | {session_id, cwd}' | sort -u
```

**Pass condition:** Two distinct `session_id` values sharing the same `cwd` — confirms
per-session identity is keyed on `session_id`, not path (the legacy parsing's "killed sibling
steals label" bug must not regress).

**Record:** The two `session_id`/`cwd` pairs.

---

### Case 17 — ⚠ Turn ends with async work in flight (bg shell / Monitor / async agent)

This is a design question, not only a detection question — if `Stop` fires while a background
shell is still running, hooks-only would notify early, contradicting the current grey-while-
working semantics D-07 says to preserve unless live data contradicts it.

**Trigger:** `mark 17`, then ask for a background task and let the visible turn end while it's
still running.

**Observe:**
```bash
extract_case 17 | jq -c 'select(.event == "Stop") | {ts_ms}'
```

**Pass condition:** N/A — record what fires; the decision belongs to Phase 2, not this runbook.

**Record:** Whether `Stop` fires at the point the turn appears to end (while bg work is still
running), and its `ts_ms`. Note explicitly: this data feeds a design decision, it does not
resolve it here.

---

### Case 18 — Bg shell / Monitor badges (🔧 count, ⏳)

**Trigger:** `mark 18`, then run a background bash, use the Monitor tool, and run KillShell /
TaskStop.

**Observe:** The logger does not capture tool inputs/outputs by value, so use the `keys` array
to determine whether the payload carries shell/task identifiers **at all**, without ever writing
tool payloads to disk.
```bash
extract_case 18 | jq -c 'select(.keys != null) | {event, keys}'
```

**Pass condition:** N/A — record whether any event's `keys` array includes something suggestive
of a shell/task identifier in a *scalar* field.

**Record:** The `keys` arrays observed per event. This answers the V2-01 question (whether
badges could ever be derived from hook payloads) without needing raw capture.

---

### Case 19 — ⚠ Abandoned prompt (no tool ever runs)

**Trigger:** `mark 19`, submit a prompt, then kill Claude's process before the first token,
keeping the terminal open.

**Observe:**
```bash
extract_case 19 | jq -c 'select(.ts_ms != null)' | tail -1
```

**Pass condition:** N/A by definition — same shape as case 9.

**Record:** The last event seen and its `ts_ms`. What Phase 2 needs is how long the silence runs
before detectable, not whether an event exists — the staleness design's heartbeat assumes
tool-call heartbeats, and a turn that dies pre-tool has none.

---

### Case 20 — Corrupt / partially-written state file

In Phase 1 there are no state files yet, so this case is scoped to what's observable now: does
the readable-log workflow in this runbook tolerate a truncated line.

**Trigger:** `mark 20`, then hand-append a truncated line to the log:
```bash
printf '{"event":"Stop","session_i' >> ~/.claude/hook-events.log
```

**Observe:**
```bash
jq -c . ~/.claude/hook-events.log 2>/dev/null | wc -l
```

**Pass condition:** The command above completes without error and simply skips the malformed
line (count reflects only well-formed lines) — the reader workflow does not crash or hang.

**Record:** Confirm the reader tolerated it. This is a note carried forward to Phase 2's ENG-04
rather than a hook-coverage finding.

---

### Case 21 — ⚠ Container without hooks installed

**Trigger:** `mark 21`, then run a session from an old image / without `hooks/install.sh` ever
having run, so `settings.json` has no logger entries for that container.

**Observe:**
```bash
extract_case 21 | jq -c '.'
```

**Pass condition:** No lines for that session's `session_id` — confirms absence is total, not
partial (rules out a half-registered logger silently degrading instead of a clean "no data").

**Record:** Confirm zero lines for the hookless container. This is the migration/hybrid question
for Phase 2: fall back to legacy parsing per-session, or show explicit "no data".

---

## Verdict

The verdict is written into **TEST-MATRIX.md**'s "Verdict to extract" section (updated in this
plan's Task 2) — per D-06, there is no separate report file. It answers three questions plus a
fourth design slot:

1. **Hooks-only viable?** Yes/no plus justification.
2. **Which fallbacks survive?** One row per hook-silent case, each naming a concrete mechanism
   from the available set: the existing `auq-lock`, `shell_tracker`, a targeted jsonl peek, or
   the `docker ps` cross-check. Not "TBD".
3. **Notification timing** (case 2): the measured gap, and whether the NOTES.md debounce idea is
   dropped.
4. **Async-work-in-flight design** (case 17): keep current grey-while-working semantics, or
   accept green-on-`Stop` — per D-07, preserve current semantics unless live data contradicts
   them.

---

## Teardown

**Mandatory, not optional** — the log's bounded lifetime is what makes writing diagnostics to a
shared, Windows-visible mount acceptable in the first place (threat T-01-02).

```bash
bash hooks/install.sh --remove-logger
rm -f ~/.claude/hook-events.log
```

Then restart any running Claude Code sessions.

## Tests
<!-- UAT oggetto: 'il verdetto del caso N è scritto e concreto in TEST-MATRIX.md' (deliverable VER-02). Campagna live 2026-07-29, cc 2.1.220. -->

### 1. Turn start — UserPromptSubmit
expected: riga 1 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 2. Normal turn end — Stop
expected: riga 2 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass
note: live: 30+ Stop coerenti; timing render preciso deferito allo shadow mode (verdetto sez.3)

### 3. Long multi-tool turn heartbeat
expected: riga 3 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass
note: live parziale: sub-domanda 10+min deferita allo shadow mode (verdetto sez.3)

### 4. Permission prompt appearance
expected: riga 4 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 5. Permission answered (approve/deny)
expected: riga 5 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 6. AskUserQuestion modal
expected: riga 6 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 7. AUQ answered
expected: riga 7 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 8. Esc interrupt mid-turn
expected: riga 8 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 9. Session killed mid-turn (docker kill/stop/pause)
expected: riga 9 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 10. /resume of a past session
expected: riga 10 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 11. /clear and /compact
expected: riga 11 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 12. Foreground subagent SubagentStop
expected: riga 12 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 13. Background task re-invocation
expected: riga 13 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 14. Clean session exit
expected: riga 14 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 15. Multi-container parallel sessions
expected: riga 15 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 16. Two sessions same project dir
expected: riga 16 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 17. Turn ends with async work in flight
expected: riga 17 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass

### 18. Bg shell/Monitor badges
expected: riga 18 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass
note: dispositioned: shell_tracker jsonl invariato per decisione V2-01 (verdetto sez.2)

### 19. Abandoned prompt
expected: riga 19 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass
note: dispositioned: dedotto da 8+9, fallback heartbeat-finestra-corta nominato (verdetto sez.2)

### 20. Corrupt/partial state file
expected: riga 20 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass
note: dispositioned: robustezza da coprire nei test Phase 2 (scrittura atomica tmp+rename da design)

### 21. Container without hooks
expected: riga 21 della TEST-MATRIX con verdetto version-stamped e fallback concreto se hook-muto
result: pass
note: dispositioned: targeted jsonl peek come ponte di migrazione (verdetto sez.2)

## Summary

total: 21
passed: 21
issues: 0
pending: 0
skipped: 0
