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
| 5 | Permission granted → resumes | Approve the prompt in #4 | working | next `PostToolUse`? `PreToolUse`? | Window between approval and next event where state is stale | |
| 6 | ⚠ AskUserQuestion modal | Ask Claude to use AskUserQuestion | needs_input | **unknown — THE open question** | Known: no jsonl write until answered (2.1.132); if no hook either → auq-lock stays | |
| 7 | AUQ answered → resumes | Answer the modal in #6 | working | `UserPromptSubmit`? `PostToolUse`? | | |
| 8 | User interrupt (Esc mid-turn) | Esc during a long turn | waiting | `Stop`? | `Stop` may not fire on interrupt → stale `working` | |
| 9 | ⚠ Session killed mid-turn | `docker kill` / close terminal during a turn | stale file detected | none (by definition) | Staleness design: heartbeat silence ~10 min + `docker ps` cross-check | |
| 10 | `/resume` of a past session | Resume an ended session | working on next prompt | `SessionStart` (source=resume) | Old session's leftover state file; session_id continuity | |
| 11 | `/clear` and `/compact` | Run mid-session | no spurious notify | `SessionStart` (source=clear/compact) | Must not look like a fresh "turn ended" → false green + toast | |
| 12 | Foreground subagent (Agent tool) | Task that spawns gsd-* agent | working (parent) | `SubagentStop` must be IGNORED | Subagent end mistaken for turn end → premature green (the "yuno case") | |
| 13 | Background agent / bg bash completes and re-invokes Claude | `run_in_background` task finishing while idle | working during re-invoked turn | `UserPromptSubmit`? (probably NOT — no user prompt) | If no event: turn invisible until first `PostToolUse` | |
| 14 | Clean session exit | Exit Claude Code normally | session disappears | `SessionEnd` | Fires on crash too? (overlap with #9) | |
| 15 | Multi-container, sessions in parallel | 2-3 containers, same host `.claude` | independent per-session states | one state file per session_id | session_id collisions; cwd→label mapping from hook payload | |
| 16 | Two sessions, same project dir | Two terminals in one repo | both visible, distinct | per-session file (id ≠ path) | Legacy parsing had the "killed sibling steals label" bug — must not regress | |

## Verdict to extract

After filling the table, answer:

1. **Hooks-only viable?** Only if #6 (AUQ) and #8 (interrupt) have a hook
   signal. Current suspicion (matches past analysis): **no** → hybrid model,
   hooks as primary source + targeted fallbacks (auq-lock-style) for the
   silent cases.
2. **Which fallbacks survive?** For each ⚠ row without a hook signal, name
   the minimal fallback (existing lock file, jsonl peek, docker cross-check).
3. **Notification timing** (#2): if `Stop` fires post-render, drop the
   debounce idea from NOTES.md entirely.

Findings feed the migration plan in [NOTES.md](NOTES.md) (shadow mode phase).
