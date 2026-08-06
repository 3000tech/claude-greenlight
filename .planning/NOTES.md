# claude-monitor — technical notes

## Idea: WORKING→WAITING debounce (try if "early notify" becomes annoying)

**Context.** The notification fires as soon as the session jsonl shows the last `assistant` block as `text` (or the WORKING evidence disappears), but terminal rendering finishes later (markdown, scroll, Stop hook). Result: the notification can precede the "perceived end" by a few seconds.

Current behavior: by design. See commits `a62bcd5` (default GREEN, flip GREY only on proven working signals) and `057ff02` (REFRESH_MS 10s → 5s).

**Reopening trigger.** Only if the annoyance becomes recurring (several consecutive sessions with a noticeable gap).

**Proposed change.**
- File: `monitor.py`, function `_check_transitions` (~line 753)
- Track `consecutive_waiting_ticks` per session in the existing per-session state (see `_first_docker_done` & co. around lines 614-620)
- Fire `_notify(...)` only on the **2nd consecutive** WAITING tick (≈5-10s after the first green signal, given `REFRESH_MS = 5000`)
- Reset the counter when the session goes back to WORKING
- Update `test_monitor.py` to cover the new behavior

**Costs/benefits.**
- Cost: +1 `REFRESH_MS` cycle = a well-defined ~5s delay
- Benefit: terminal rendering almost always finishes within those 5s

**Discarded alternatives.**
- Mtime quiescence — the jsonl is not rewritten during terminal rendering, it wouldn't discriminate.
- Long debounce (10-15s) — worsens latency for sessions that are genuinely done.
- Integrating with Claude Code's Stop hook — overkill for this problem.

## Refactor: fully hook-driven architecture (state from hooks, zero jsonl parsing)

**Context.** Today the monitor infers session state by parsing the session
jsonl files (`~/.claude/projects/*.jsonl`), with working-lock and auq-lock
acting as *corrective patches* for the cases where parsing gets it wrong
(long turns, batched writes, permission prompts). Every internal Claude Code
change to jsonl format/timing is a potential breakage — it has already
happened three times. Idea borrowed from TaulantSela/claude-semaphore (seen
2026-07-28): invert the hierarchy — hooks become the ONLY source of state,
and jsonl disappears from the monitor entirely.

**Target architecture.**
- Hooks write one state file per session:
  `~/.claude/monitor-state/<session_id>.json` containing
  `{"state": "...", "ts": ..., "cwd": "...", "last_event": "..."}`.
  (`cwd` feeds the existing session→project-label mapping.)
- Event → state mapping:
  - `SessionStart` → `idle` (creates the file)
  - `UserPromptSubmit` → `working`
  - `PostToolUse` → touch the file (heartbeat, see staleness below)
  - `Notification` (permission prompt) → `needs_input`
  - `Stop` → `waiting` (TRUE end of turn: fixes the early-notify issue from
    the debounce section above by construction — Stop fires after rendering
    has finished)
  - `SessionEnd` → removes the file
  - `SubagentStop` → ignored
- `monitor.py` reads ONLY `monitor-state/`: no more jsonl parsing.
  Unchanged: container/label mapping (docker ps + labels), toasts, WAV,
  tray, shell_tracker, config. The debounce likely becomes unnecessary.
- Hooks live in `~/.claude/settings.json` → shared by all containers via the
  bind mount, like working-lock today. Update `hooks/install.sh` and
  `hooks/settings-snippet.json`.

**Staleness (container killed mid-turn).** A kill leaves `state=working`
forever. A flat TTL is not enough: a legitimate turn can run 20+ minutes.
Two-level solution:
1. heartbeat via `PostToolUse` (tool calls are frequent during long turns):
   no touch for ~10 min ⇒ suspect;
2. cross-check against container liveness (`docker ps`, mapping already in
   monitor.py): container dead ⇒ session dead, file removed/ignored.

**Open question: AskUserQuestion.** AUQ does not trigger the `Notification`
hook (see the 2.1.132 note: the AUQ assistant block only appears in the
jsonl when the user's answer arrives). BEFORE the refactor, verify on current
Claude Code versions whether AUQ emits ANY hook event; if not, the current
auq-lock stays on as an additional source for the `needs_input` state
(consistent with the new model: it is already a hook writing a file).

**Migration plan (3 phases, never big-bang).**
1. Extend the current hooks into a single state-writer that populates
   `monitor-state/` (working-lock/auq-lock keep existing as long as needed).
2. `monitor.py` gains a `--state-files` mode to run in shadow mode alongside
   the legacy parsing, logging divergences over a few days of real usage
   (multi-container, long turns, permissions, AUQ, /resume, mid-turn kill).
   The concrete case list lives in [TEST-MATRIX.md](../docs/TEST-MATRIX.md).
3. Flip the default, delete the jsonl parsing code (expectation: the file
   shrinks by half). Rewrite `test_monitor.py` against state files — much
   easier to fixture than jsonl.

**Costs/benefits.**
- Cost: hook rewrite + shadow mode + live test matrix.
- Benefit: (near) total immunity to Claude Code internal changes; early
  notify fixed at the root; much smaller monitor; today's "patches" become
  the design.

**Discarded alternatives.**
- Adopting claude-semaphore instead of the monitor — no notifications, no
  per-session view (single aggregate light), very young single-maintainer
  project (as of 2026-07); and in the container setup its tray app would
  still need manual install on Windows.
- Keeping the current mixed model — it works, but every Claude Code release
  is a roulette spin on the jsonl format; the maintenance cost has already
  been paid three times.
