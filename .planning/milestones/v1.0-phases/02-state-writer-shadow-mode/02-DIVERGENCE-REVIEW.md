---
status: complete
phase: 02-state-writer-shadow-mode
reviewed: 2026-08-06
window: 2026-07-30 → 2026-08-06 (full week of real use)
log: ~/.claude/monitor-divergence.log on the real machine (343 records, 137KB, all valid JSONL — NOT committed to the repo; raw log stays machine-local)
verdict: GREEN — flip approved. Proceed to /gsd-plan-phase 3
---

# Section E Divergence Review — conclusions

The review conversation prescribed by 02-UAT.md Section E happened 2026-08-06 (in-session analysis,
user approved the verdict). This file is the durable record; the raw log stays on the real machine.

## Headline numbers

- 212 `diverged` records, 131 `resolved`, 81 never resolved (see class 1 — they *can't* resolve).
- Volume: ~75/day on 07-30/31 (before that day's fixes), stable ~15/day after. No records 08-01/02 (machine off).
- Episode duration: median 3 ticks (~15s); p90 75 ticks; max 595 ticks (~50 min, class 6).
- Zero malformed lines, zero truncation markers, 137KB against the 5MB guard.

## Classification (every divergence falls in exactly one class — no unknowns)

| # | Class | Count | Label | Detail |
|---|-------|-------|-------|--------|
| 1 | Sessions invisible to legacy — `ABSENT→WAITING @SessionStart`, state `idle` | 82 (65 orphaned) | **legacy-wrong** | Paused/cleared sessions legacy drops at label resolution; shadow keeps them (UAT C4). The 81 unresolved episodes are almost all here: legacy will never see these sessions, so the episode never closes. Feeds the panel-visibility todo. |
| 2 | Startup latency — `ABSENT→WORKING @UserPromptSubmit` | 51 | **legacy-wrong** (timeliness) | Shadow sees the session working seconds before legacy resolves its label. Auto-resolves in a few ticks. |
| 3 | Bg-shell rule mismatch — `WAITING→WORKING`, `background_tasks_count>0` | 37 | **expected by design** | Shadow still applies `bg>0 → working`; the user decision (quick 260731-an2 rev.2) is bg = badge-only. Predicted in TEST-MATRIX §4. At the flip the hook-native rule becomes badge-only and this class disappears. |
| 4 | **False green during async work** — `WAITING→WORKING`, `bg==0` | 7 | **legacy-wrong — the severe class** | Real false notifications: the 4th jsonl format break (08-03 09:15, `ASYNC_AGENT_LAUNCH_RE` no longer matches), the inter-subagent thinking gap (08-04 08:37 + 2 more), and a fresh one 08-06 09:46 (working-lock AND auq-lock armed but the stale-lock guard overrode both after 520s of jsonl silence). Shadow correct in every episode. |
| 5 | Turn-end timeliness — `WORKING→WAITING`, state file fresh | 16 | **legacy-wrong** (seconds late) | `Stop` (8×) and `PermissionRequest`→`needs_input` (4×) reach the state file before the jsonl flush / auq-lock catch-up. |
| 6 | Hook silence — `WORKING→WAITING`, state file stale (age > ~600s) | 9 | **hooks-wrong** | Long-running Monitor tool / subagents / slow Bash: hooks go silent, shadow degrades to WAITING at the 600s heartbeat window while legacy stays correctly pinned via monitors/agents/working-lock evidence. Longest episodes live here (max ~50 min, key 29acbe20). **This is exactly the class the hybrid model keeps the jsonl fallback for** (UAT C1 finding). 9 events in a week, all covered by the Phase 1 hybrid design. |

## Verdict

**GREEN — flip approved (user + Claude, 2026-08-06).** Rationale:

- The only class where the hook engine is wrong (class 6, 9 events) is precisely what the hybrid
  model already retains legacy jsonl signals for (interrupts + hook-silent long tools).
- Classes 1, 2, 4, 5 (156 events) are legacy defects the flip fixes outright; class 4 produced real
  false "needs you now" notifications during the window.
- Class 3 (37 events) is a known rule-alignment that lands with the flip itself (bg → badge-only).
- Legacy keeps degrading independently: the 4th jsonl format break in the project's history landed
  *during* the review window (08-03), and another false green fired the morning of the review (08-06).

## Carry-forward into Phase 3 planning

1. Hybrid fallback is REQUIRED for: Esc interrupt (C1 — legacy recovers 90s vs hook 600s) and
   hook-silence pins (class 6: active Monitor tool / agents / working-lock evidence).
2. Bg-shell hook rule flips to badge-only (`background_tasks_count` feeds ◉/⚙ badge, never the verdict).
3. Panel visibility for paused/kept sessions (class 1) — legacy drops them, state engine keeps them;
   decide rendering at flip (existing minor todo).
4. Cleanup list: shadow-mode diff/divergence machinery, `monitor-state` orphan tmp files (one found:
   `c1eb55f7-….json.tmp.13252` — atomic-write leftover, add stale-tmp sweep), dead `project_name()`
   helper, `rm -rf ~/.claude/monitor-state` + divergence log teardown per 02-UAT.md.
5. Preserve the 2026-07-30 fixes across the flip (alias container-key, multi-monitor, 60s threshold)
   — pending todo already in STATE.md.
6. **New context (out of scope for Phase 3, next milestone):** Claude sessions now also run in Docker
   on a remote Linux devbox (headless MacBook). The user wants their state in the monitor and
   notifications on mobile. Decision 2026-08-06: separate milestone after the flip. Phase 3 should
   avoid closing doors: state files are per-machine `~/.claude/monitor-state/*.json` with a
   `hostname` field — a remote aggregator only needs to transport those files.
