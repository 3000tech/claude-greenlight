# Phase 3: Flip to Default & Cleanup - Context

**Gathered:** 2026-08-06
**Status:** Ready for planning

<domain>
## Phase Boundary

The state-file engine becomes the monitor's default (no `--state-files` flag required); legacy jsonl parsing is deleted except for three named hybrid fallbacks; bg shells become badge-only; `test_monitor.py` reaches equivalent coverage on state-file fixtures; `hooks/install.sh`, the settings snippet and README document the shipped architecture; shadow-mode machinery is torn down. Requirements: FLIP-01, FLIP-02, FLIP-03.

This context was NOT gathered via interview: the discussion already happened as the Section E divergence review (2026-08-06, verdict GREEN, flip approved by user). This file consolidates the decisions recorded in the repo documents listed in `<canonical_refs>`. One open conflict was resolved with the user on 2026-08-06 (D-02c below).

</domain>

<decisions>
## Implementation Decisions

### The flip itself
- **D-01:** FLIP APPROVED (Section E review GREEN, user + Claude 2026-08-06). The state-file engine is the default and only primary engine; dead legacy jsonl-parsing paths are removed from `monitor.py`. Expectation from NOTES.md: the file shrinks substantially. — **Reversibility:** costly — undo means reverting large deletions across `monitor.py`, `shell_tracker.py`, tests and hooks; recoverable only via git history, and the README/install docs would describe an architecture that no longer exists.
- **D-02:** Exactly THREE jsonl/legacy consumers survive the flip (the hybrid model) — no other legacy path may remain:
  - **(a) Esc-interrupt recovery** — targeted legacy signal so an interrupted turn recovers in ~90s instead of the 600s heartbeat window (UAT C1: legacy was MORE timely; a pure hook engine would regress interrupt recovery).
  - **(b) Hook-silence pins** — during long-running Monitor tool / subagents / slow Bash (divergence class 6, 9 events/week), active Monitor/agent evidence + working-lock evidence keeps the session pinned WORKING instead of degrading to WAITING at 600s.
  - **(c) `legacy_origin` bridge** — sessions with no state file (hookless containers per ENG-05, or state file already removed) stay visible via per-session legacy parsing. **User-confirmed 2026-08-06** as the third surviving fallback (resolves the conflict with the stricter "only Esc + hook-silence" wording in the handoff). Replacement with an explicit "no data" UI stays deferred to V2-02.
- **D-03:** Bg shells are badge-only, NEVER a state verdict: `background_tasks_count` feeds the single unified ◉N badge and nothing else (TEST-MATRIX §4 revision, quick task 260731-an2 rev.2 — the earlier 15-min-cap idea is dead). The ⚙/◉ badge pair and `shell_tracker.py` are deleted; jsonl badge parsing ends (Phase 2 D-09). At the flip, divergence class 3 (37 events) disappears by construction.

### Lock hooks fate
- **D-04:** `working-lock` hooks STAY — they are named evidence for the hook-silence pins (D-02b) and drive the ~90s Esc recovery via the stale-lock guard (UAT C1). `auq-lock` RETIRES: AUQ is hook-native on cc 2.1.220 (`PreToolUse`/`PermissionRequest` → `needs_input` via the state writer; TEST-MATRIX case 6, UAT section F showed both engines agree). Retirement ships with an UAT gate: confirm `needs_input` parity live on the Windows machine before `install.sh` stops installing it. — **Reversibility:** reversible — re-adding a hook entry restores it.

### Sessions the state engine keeps (divergence class 1)
- **D-05:** Paused/kept sessions become VISIBLE in the overlay at the flip (folded todo 2026-07-30; UAT C4: legacy dropped paused containers, shadow keeps them via `hostname_to_label`). 82 events/week of class 1 divergences are legacy-wrong. Rendering detail (normal vs dimmed row) is Claude's discretion; no new state colors, no new notification types.
- **D-06:** A session the state engine KNOWS ended (SessionEnd removed its state file) must NOT be resurrected by the D-02c bridge while its ghost jsonl row survives (folded todo 2026-07-30 "ghost jsonl rows survive container kill via dir-fallback"). Mechanism (SessionEnd tombstone or equivalent) is Claude's discretion; the outcome is locked: clean-ended sessions stay gone.

### Preserve the 2026-07-30 fixes (folded MAJOR todo)
- **D-07:** The flip must preserve, with equivalent post-flip tests: (1) aliases keyed by container identity — survive `/clear` (quick 260730-kgw); test Goal6d is REWRITTEN on a state-file fixture, not dropped; (2) the multi-monitor fix; (3) the deliberate 60s threshold. These behaviors are load-bearing daily fixes — regressing any of them fails FLIP-02's "equivalent coverage" bar.

### Teardown & cleanup (per 02-UAT.md §Teardown + carry-forward #4)
- **D-08:** Shadow-mode machinery is removed from the code: `diff_verdicts`, `filter_divergence_events`, `write_divergences`, divergence logging, and the shadow double-compute in the tick loop. `select_render_sessions()` remains the seam but now serves only the state engine + fallbacks. On the Windows machine (execution time, not from the devbox): delete `~/.claude/monitor-divergence.log`; sweep the orphan tmp file (`c1eb55f7-….json.tmp.13252`) and add a stale-`.tmp` sweep to the engine so atomic-write leftovers can't accumulate. `~/.claude/monitor-state/` is NOT deleted — post-flip it is the primary data source (02-UAT's `rm -rf` line was shadow-era rollback guidance, superseded by the flip). Also: remove the dead `project_name()` helper (monitor.py:282 — verify it is still dead at execution time).
- **D-09:** Shadow mode keeps RUNNING on the Windows machine until Phase 3 execution flips it there. Nothing is torn down from the devbox. The raw divergence log stays machine-local and uncommitted.

### Docs & matrix promotion (FLIP-03)
- **D-10:** `hooks/install.sh`, `hooks/settings-snippet.json` and README document the hook-driven architecture well enough to onboard a new container/user. Lightweight promotion folded from the recertification todo: TEST-MATRIX.md + the verification runbook get promoted out of `.planning/` into repo docs as the per-version recertification reference. The full campaign machinery (per-version fixtures, smoke checklist automation) stays deferred (see Deferred Ideas) — planner may veto the promotion split at plan review if it balloons.

### Scope fences
- **D-11:** Remote devbox state + mobile notifications are OUT OF SCOPE (separate milestone after v1.0, user decision 2026-08-06). Phase 3 must not close doors: the `hostname` field stays in state files; state files remain per-machine `~/.claude/monitor-state/*.json` so a future aggregator only needs to transport them. No aggregator/transport work in this phase.
- **D-12:** Live UAT of the flip happens on the WINDOWS machine (where shadow mode runs and real sessions live). Plans must structure verification accordingly: code + unit tests run anywhere; the flip's live validation and machine-side teardown are user-assisted UAT on Windows, mirroring the 01-UAT/02-UAT runbook convention (date, CC version, outcome).

### Claude's Discretion
- Rendering details for paused/kept sessions (D-05) within "no new colors/notifications".
- Ghost-suppression mechanism for D-06 (tombstone vs alternative).
- Fate of the `--state-files` flag once it is the default (no-op, removed, or diagnostic alias) — there is no `--legacy` escape hatch, since the legacy engine is deleted (rollback = git revert, D-01).
- Internal refactor shape of `monitor.py` after the deletions, as long as observable behavior matches the matrix and preserved fixes.
- Exact split of README vs docs/ content for FLIP-03.

### Folded Todos
- **Preserve today's fixes across the Phase 3 flip** (major) → D-07.
- **Show paused-container sessions in overlay** (minor) → D-05.
- **Ghost jsonl rows / SessionEnd tombstones** (minor) → D-06.
- **Startup check: refuse to start when hooks not installed** (minor) → NOT folded as a hard refusal: with the D-02c bridge kept, hookless sessions remain visible, so a hard startup refusal contradicts ENG-05. Folded in reduced form: a startup WARNING when hooks are missing is acceptable at Claude's discretion; hard-fail behavior is deferred to V2-02's "no data" decision.
- **Remove dead `project_name()` helper** (cosmetic) → D-08.
- **Campagna ricertificazione hook** (minor/testing) → partially folded into D-10 (doc/matrix promotion only); campaign machinery deferred.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The flip's empirical justification (read FIRST)
- `.planning/phases/02-state-writer-shadow-mode/02-DIVERGENCE-REVIEW.md` — GREEN verdict, 6 divergence classes (343 records, week of real use), and the 6-item Phase 3 carry-forward list this context encodes.
- `.planning/phases/02-state-writer-shadow-mode/02-UAT.md` — §Teardown (D-08/D-09 source) and the C1–C7 live findings: C1 Esc = jsonl fallback REQUIRED; C3 kill symmetry; C4 paused-session visibility; C6 `legacy_origin` bridge exercised live.

### Design & event mapping
- `.planning/NOTES.md` §"Refactor: fully hook-driven architecture" — target architecture, event→state mapping, migration plan step 3 (this phase).
- `.planning/TEST-MATRIX.md` — 21 live-verified cases (cc 2.1.220), §"Verdict to extract" (which fallbacks survive, per case) and §4 rev.2 (bg badge-only rule, D-03). Overrides any stale REQUIREMENTS.md wording.
- `.planning/REQUIREMENTS.md` — FLIP-01..03 (this phase), ENG-05 (bridge survives, D-02c), V2-01/V2-02 (explicitly NOT this phase).

### Prior decisions still binding
- `.planning/phases/02-state-writer-shadow-mode/02-CONTEXT.md` — Phase 2 decisions D-05 (labels), D-06 (staleness/paused), D-07 (needs_input rendering), D-08/D-09 (event set, unified badge) carry into the flip unchanged except where this file supersedes them.
- `.planning/STATE.md` — Pending Todos + 2026-08-06 decisions (flip approved; remote = separate milestone).

### Code that changes
- `monitor.py` — legacy engine, state engine, shadow seam (`select_render_sessions`), shadow machinery to delete.
- `shell_tracker.py` — deleted at the flip (D-03).
- `test_monitor.py`, `test_state_writer.py`, `test_event_logger.py` — FLIP-02 coverage target.
- `hooks/install.sh`, `hooks/settings-snippet.json`, `hooks/state-writer.sh`, `hooks/working-lock.sh`, `hooks/auq-lock.sh` — FLIP-03 + D-04.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `select_render_sessions()` (monitor.py:884) — the single seam through which either engine reaches rendering (Phase 2 D-01 enforcement point). The flip happens here: shadow verdict becomes the rendered verdict, legacy double-compute goes away.
- `scan_state_files()` (monitor.py:575) — already the complete state engine, including the internal `legacy_sessions` migration bridge (Phase 02-03 decision: bridge lives inside the scanner, so `--state-files` diagnostics got identical behavior). D-02c keeps this bridge.
- `hooks/install.sh` `--remove-*` sweep pattern — reuse for auq-lock retirement (D-04) and any settings cleanup.
- Existing state-file fixtures in `test_state_writer.py` (656 lines) — the fixture style FLIP-02 extends to replace jsonl fixtures.

### Established Patterns
- Legacy-only code to delete or shrink to targeted fallbacks: `tail_last_line`, `parse_last_action`, `user_tail_kind`, `is_certainly_working`, `scan()` (monitor.py:922), plus shadow machinery `diff_verdicts`/`filter_divergence_events`/`write_divergences` (monitor.py:717–882).
- `test_monitor.py` (2199 lines, 163 green pre-flip) defines today's observable behavior; FLIP-02 = equivalent coverage, state-file fixtures where legacy was removed, Goal6d rewritten not dropped (D-07).
- Zero-dependency constraint: Python 3.10+ stdlib only monitor-side; bash+jq hook-side. OSS repo (MIT) — README is a user-facing deliverable, not an afterthought.

### Integration Points
- `monitor.py` tick loop: post-flip computes ONE verdict (state engine + three fallbacks) per tick.
- `~/.claude/monitor-state/` — primary data source post-flip; gets the stale-`.tmp` sweep (D-08).
- `~/.claude/working-locks/` — stays as pin evidence (D-04); `~/.claude/auq-locks/` goes away with auq-lock retirement.

</code_context>

<specifics>
## Specific Ideas

- NOTES.md expectation: "the file shrinks by half" — deletion is a feature; the planner should treat net code reduction as a success signal for FLIP-01.
- The review's framing: classes 1/2/4/5 (156 events) are legacy defects the flip FIXES — the flip is not risk-neutral cleanup, it removes real false "needs you now" notifications (class 4 included the 4th jsonl format break, landed mid-review).
- UAT record convention: date, CC version, outcome — same as 01/02-UAT.

</specifics>

<deferred>
## Deferred Ideas

- **Remote devbox aggregation + mobile notifications** — separate milestone after v1.0 (D-11). Only door-keeping in this phase.
- **V2-02 explicit "no data" UI for hookless sessions** — the D-02c bridge is the v1 answer; hard startup refusal re-evaluated then.
- **Recertification campaign machinery** (per-version fixtures, smoke checklist automation) — only the matrix/runbook doc promotion lands now (D-10).
- **V2-01** (rebuild badges from PostToolUse payloads) — superseded in substance by the unified ◉N badge; formally still v2.

### Reviewed Todos (not folded)
- None remaining — all six pending todos were folded (fully or in reduced form, see Folded Todos).

</deferred>

---

*Phase: 3-Flip to Default & Cleanup*
*Context gathered: 2026-08-06 (document-driven; Section E review = the discussion)*
