# Live test matrix — hook coverage verification

Goal: before (and during) the hook-driven refactor, verify for each real-world
case **which hook event fires** and whether it is enough to derive the correct
state — or whether jsonl/lock fallback remains necessary (hybrid model).

How to use: run each case live (Windows host + container sessions), observe
`~/.claude/` for hook side effects (add a temporary logging hook that appends
every event + payload to `~/.claude/hook-events.log`), fill in the last two
columns. Cases marked ⚠ are the ones that historically broke transcript
parsing — they decide the hybrid question.

Expected states: `working` (grey), `waiting` (green, notify), `needs_input`
(green, notify — permission/AUQ).

| # | Case | How to trigger | Expected state | Candidate hook signal | Suspected gap / fallback | Verified (date, CC version, outcome) |
|---|------|----------------|----------------|----------------------|--------------------------|--------------------------------------|
| 1 | Turn start | Submit any prompt | working | `UserPromptSubmit` | — | |
| 2 | Normal turn end (text reply) | Short Q&A prompt | waiting | `Stop` | Verify `Stop` fires AFTER rendering (would fix early-notify by construction) | |
| 3 | ⚠ Long multi-tool turn (10+ min) | Big task, many tool calls | working throughout | `PostToolUse` heartbeat | Gaps > heartbeat window during pure thinking/generation stretches? | |
| 4 | ⚠ Permission prompt | Tool not in allowlist (e.g. dangerous rm) | needs_input | `Notification` | Does it fire for ALL prompt types (Bash, MCP, file writes)? | |
| 5 | Permission answered → resumes | Approve the prompt in #4; also test DENY (Claude continues with a refusal message) | working | next `PostToolUse`? `PreToolUse`? | Window between approval and next event where state is stale; deny path has no tool execution at all | |
| 6 | ⚠ AskUserQuestion modal | Ask Claude to use AskUserQuestion | needs_input | **unknown — THE open question** | Known: no jsonl write until answered (2.1.132); if no hook either → auq-lock stays | |
| 7 | AUQ answered → resumes | Answer the modal in #6 | working | `UserPromptSubmit`? `PostToolUse`? | | |
| 8 | User interrupt (Esc mid-turn) | Esc during a long turn; also the "yuno" variant: Esc right after a foreground agent returns | waiting | `Stop`? | `Stop` may not fire on interrupt → stale `working` | |
| 9 | ⚠ Session killed mid-turn | `docker kill` / close terminal during a turn | stale file detected | none (by definition) | Staleness design: heartbeat silence ~10 min + `docker ps` cross-check | |
| 10 | `/resume` of a past session | Resume an ended session | working on next prompt | `SessionStart` (source=resume) | Old session's leftover state file; session_id continuity | |
| 11 | `/clear` and `/compact` | Run mid-session | no spurious notify | `SessionStart` (source=clear/compact) | Must not look like a fresh "turn ended" → false green + toast | |
| 12 | Foreground subagent (Agent tool) | Task that spawns gsd-* agent | working (parent) | `SubagentStop` must be IGNORED | Subagent end mistaken for turn end → premature green (the "yuno case") | |
| 13 | Background agent / bg bash completes and re-invokes Claude | `run_in_background` task finishing while idle | working during re-invoked turn | `UserPromptSubmit`? (probably NOT — no user prompt) | If no event: turn invisible until first `PostToolUse` | |
| 14 | Clean session exit | Exit Claude Code normally | session disappears | `SessionEnd` | Fires on crash too? (overlap with #9) | |
| 15 | Multi-container, sessions in parallel | 2-3 containers, same host `.claude` | independent per-session states | one state file per session_id | session_id collisions; cwd→label mapping from hook payload | |
| 16 | Two sessions, same project dir | Two terminals in one repo | both visible, distinct | per-session file (id ≠ path) | Legacy parsing had the "killed sibling steals label" bug — must not regress | |
| 17 | ⚠ Turn ends with async work in flight (bg shell / Monitor / async agent) | Ask for a bg task, let the turn end | **grey, no notify** (current design: in-flight async work = working) | `Stop` fires at turn end → would flip green | **Design divergence**, not just detection: hooks-only notifies while work is still running. Decide: keep current semantics (needs shell_tracker) or accept green-on-Stop | |
| 18 | Bg shell / Monitor badges (🔧 count, ⏳) | Bg bash, Monitor tool, KillShell/TaskStop | badge appears/disappears correctly | none in state-file design — `shell_tracker` stays jsonl-based per NOTES.md | "Zero jsonl parsing" is not literally true unless badges are dropped or rebuilt from `PostToolUse` payloads (tool_input/response carry shell/task ids) | |
| 19 | ⚠ Abandoned prompt (no tool ever runs) | Submit prompt, kill Claude's process before first token, keep terminal open | working briefly, then green (today: dedicated prompt-expiry window) | `UserPromptSubmit` only — heartbeat starts at first `PostToolUse`, i.e. never | Staleness design assumes tool-call heartbeats; a turn that dies pre-tool has none. `docker ps` cross-check misses it (container alive) | |
| 20 | Corrupt / partially-written state file | Kill a hook mid-write (or truncate a file by hand) | session unaffected or worst-case shown idle — never crash | — | Hooks must write atomically (tmp + rename); monitor must tolerate garbage, like today's malformed-jsonl tests | |
| 21 | Container without hooks installed | Run a session from an old image, no `settings.json` hooks | visible with degraded state (or explicit "unknown") — not invisible | none, by definition | Migration/hybrid question: fall back to legacy parsing per-session, or require hooks and show "no data"? | |

## Verdict to extract

After filling the table, answer:

1. **Hooks-only viable?** Only if #6 (AUQ) and #8 (interrupt) have a hook
   signal, AND the #17/#18 design question (async work + badges) is resolved
   without jsonl. Current suspicion (matches past analysis): **no** → hybrid
   model, hooks as primary source + targeted fallbacks (auq-lock-style,
   shell_tracker) for the silent cases.
2. **Which fallbacks survive?** For each ⚠ row without a hook signal, name
   the minimal fallback (existing lock file, jsonl peek, docker cross-check).
3. **Notification timing** (#2): if `Stop` fires post-render, drop the
   debounce idea from NOTES.md entirely.

Findings feed the migration plan in [NOTES.md](NOTES.md) (shadow mode phase).
