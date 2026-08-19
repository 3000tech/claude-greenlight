---
phase: 03-flip-to-default-cleanup
plan: 04
subsystem: docs
tags: [documentation, oss-readme, hook-verification, uat, recertification]

# Dependency graph
requires:
  - phase: 03-flip-to-default-cleanup
    provides: "03-01/03-02/03-03's shipped hook-driven architecture (single-engine render seam, D-02a/D-02b/D-02c hybrid fallbacks, badge-only turn-end, retired auq-lock) — this plan documents exactly what they shipped, nothing more"
provides:
  - "README.md describes the hook-driven architecture as it ships: hooks are a setup requirement (not a recommendation), Setup step 4 names the per-session state file + working lock instead of 'tiny lock files', the honest degradation note names the per-session transcript fallback instead of 'still works, some cases misread', the Development section lists all three test suites, and a docs pointer links the promoted matrix + new runbook"
  - "docs/TEST-MATRIX.md — the 21-case hook verification matrix promoted out of .planning/ with git history intact (git log --follow shows commits predating this phase), framed as the per-version recertification reference, all 21 case rows and the Verdict to extract section byte-identical to their pre-move content"
  - "docs/RECERTIFICATION.md — the reduced-scope recertification runbook (D-10): when to re-run the matrix, the install/exercise/compare/teardown loop, what a failure looks like, and the date/CC-version/outcome recording convention; deliberately excludes the deferred campaign machinery (per-version fixtures, automated smoke checklist)"
  - "03-UAT.md — the live flip validation runbook for the Windows machine (D-12): Setup + sections A-I covering every behavior this phase shipped, a BLOCKING Section H (D-04's needs_input parity gate) that must pass before the Teardown's --remove-auq-lock step runs, and a Teardown that deletes the divergence log, confirms the orphan .tmp sweep fired automatically, and explicitly does NOT delete monitor-state/"
  - "COVERAGE.md — the phase's API coverage declaration: no external API/SDK/service, Python stdlib + bash/jq only, Claude Code hooks are a local file/process interface not a remote API"
  - "FLIP-03 marked Complete in REQUIREMENTS.md — the last of the three Phase 3 requirements"
affects: []

# Actuals (#2632)
actuals:
  tokens: 11379
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Docs promotion at authorized scale (D-10): a single docs/TEST-MATRIX.md move plus one companion runbook, not a restructured docs/ tree — the planner's veto against ballooning stayed unexercised because the promotion never grew past what D-10 authorized"

key-files:
  created:
    - docs/RECERTIFICATION.md
    - .planning/phases/03-flip-to-default-cleanup/03-UAT.md
    - .planning/phases/03-flip-to-default-cleanup/COVERAGE.md
  modified:
    - README.md
    - docs/TEST-MATRIX.md
    - .planning/PROJECT.md
    - .planning/NOTES.md
    - .claude/CLAUDE.md
    - .planning/todos/pending/2026-07-29-campagna-ricertificazione-hook-per-versione-claude-code.md

key-decisions:
  - "The README's feature-list hooks bullet was already generic enough (no script named) that only its framing needed tightening, not a rewrite — 'lightweight hooks catching X' became 'a session waiting on you never shows as working' to state the outcome the state writer's event mapping now produces"
  - "Fixed two referrers the plan's action text didn't explicitly name (.planning/NOTES.md's own markdown link to TEST-MATRIX.md, and the mirrored .claude/CLAUDE.md project section) because both are genuine clickable links that would 404 after the move, unlike the historical prose mentions in STATE.md/ROADMAP.md and settled phase 1-3 PLAN/SUMMARY docs that the plan explicitly said to leave alone — 'fix the referrers' was read as 'fix broken links,' not 'touch every file that mentions the old path'"
  - "docs/TEST-MATRIX.md's two remaining internal links to the phase 1 runbook (the intro paragraph and the 'Verdict to extract' section header) were both repointed, even though the plan's action text used the singular 'the file's own internal link' — both occurrences are pointer sentences, not the recorded case rows/outcomes the plan protects as historical evidence, so repointing both stays within 'do not rewrite the 21 case rows... those are historical evidence'"
  - "03-UAT.md's Section H is the literal implementation of D-04's parity gate: it is written as blocking in both the section body and the Teardown's dependency line, matching the plan's acceptance criteria exactly rather than leaving the gate as a soft recommendation"

patterns-established:
  - "UAT runbooks for this project stay structurally identical across phases (Setup / lettered sections with trigger+observe / Teardown / Recording format table / Tests / Summary) — 03-UAT.md is the third instance of the convention 01-UAT.md established, unchanged"

requirements-completed: [FLIP-03]

coverage:
  - id: D1
    description: "README.md documents the shipped hook-driven architecture: hooks required (not recommended), per-session state file + working lock named instead of 'tiny lock files', honest per-session transcript fallback instead of an overstated 'still works' claim, all three test suites listed, docs/TEST-MATRIX.md and docs/RECERTIFICATION.md linked"
    requirement: "FLIP-03"
    verification:
      - kind: other
        ref: "python3 link/content check (task 1 <verify>): no 'auq-lock', no '--state-files', all three suite names present, both docs paths present, every relative link resolves"
        status: pass
      - kind: other
        ref: "bash hooks/install.sh <mode> for every mode named in README/docs — all accepted, no unknown-argument error"
        status: pass
    human_judgment: false
  - id: D2
    description: "docs/TEST-MATRIX.md promoted from .planning/ with git history intact and its recorded evidence untouched; docs/RECERTIFICATION.md written as the reduced-scope recertification runbook; all referrers (PROJECT.md, NOTES.md, CLAUDE.md, the folded todo) repointed to the new location"
    requirement: "FLIP-03"
    verification:
      - kind: other
        ref: "git log --follow --oneline -- docs/TEST-MATRIX.md (22 commits, oldest predates this phase); 21/21 case rows + Verdict to extract section present; docs/RECERTIFICATION.md 70 lines (<100)"
        status: pass
      - kind: other
        ref: "python3 link-resolution check across docs/TEST-MATRIX.md, docs/RECERTIFICATION.md, .planning/PROJECT.md — all relative links resolve"
        status: pass
    human_judgment: false
  - id: D3
    description: "03-UAT.md authored as the machine-side live validation runbook (D-12) with a blocking Section H parity gate ahead of the auq-lock removal, and COVERAGE.md's no-external-API declaration filed"
    requirement: "FLIP-03"
    verification:
      - kind: other
        ref: "python3 structure check (task 3 <verify>): Setup/Teardown/Recording format headings present, Section A-I present, 'monitor-divergence.log' named, 'blocking' present"
        status: pass
    human_judgment: true
    rationale: "Per D-12, the live flip validation this runbook describes must be performed on the Windows machine with real Docker containers and real Claude Code sessions — outside this execution sandbox's reach. Automated checks confirm the runbook's required structure and that every installer mode it names is accepted, but whether the flip actually behaves correctly live (the runbook's actual purpose) is a human/machine-side judgment this plan cannot make."

# Metrics
duration: 9min
completed: 2026-08-06
status: complete
---

# Phase 3 Plan 4: README, docs promotion, and the live flip runbook Summary

**README now documents hooks as required (not recommended) and names the real architecture; the 21-case TEST-MATRIX.md moved to docs/ with history intact alongside a new RECERTIFICATION.md runbook; and 03-UAT.md/COVERAGE.md give the Windows machine a live-validation runbook with a blocking D-04 parity gate — FLIP-03 closed, all three Phase 3 requirements complete.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-08-06T12:19:52Z (approx., inherited from prior plan's session timestamp)
- **Completed:** 2026-08-06T12:28:49Z
- **Tasks:** 3
- **Files modified:** 9 (3 created, 6 modified)

## Accomplishments

- **Task 1 — README.** Setup step 4's heading changed from "recommended" to "required"; its body now describes what installing actually does (a per-session state file on Claude Code's own lifecycle events, plus a working lock) instead of the pre-flip "tiny lock files" framing, and states the honest degradation case (a hookless session stays visible via a per-session transcript fallback, less accurate — not "still works, some cases misread"). The feature-list hooks bullet restates the outcome (a session waiting on you never shows as "working") without naming any script. The Development section now lists all three suites: `test_monitor.py`, `test_state_writer.py`, `test_event_logger.py`. A docs pointer links `docs/TEST-MATRIX.md` and `docs/RECERTIFICATION.md` alongside the existing `.planning/NOTES.md` design-notes link.
- **Task 2 — Docs promotion.** `git mv .planning/TEST-MATRIX.md docs/TEST-MATRIX.md` preserved history (`git log --follow` shows 22 commits, the oldest predating this phase). A framing paragraph was added stating the file is the per-version hook verification reference and a version bump is the re-run trigger; the 21 case rows and the "Verdict to extract" section are untouched — same recorded outcomes, byte-identical. The file's three internal links to the phase 1 runbook and NOTES.md were repointed to resolve from the new location. `docs/RECERTIFICATION.md` (70 lines) was written as the reduced-scope runbook D-10 authorizes: when to re-run, the install/exercise/compare/teardown loop (naming the installer's real modes), what a failure looks like, and the recording convention — with the deferred campaign machinery (per-version fixtures, automated smoke checklist) explicitly named as out of scope. Referrers fixed: `.planning/PROJECT.md`, `.planning/NOTES.md`, the mirrored `.claude/CLAUDE.md` project section, and the folded recertification todo's `related-files` list. Prose mentions in `STATE.md`/`ROADMAP.md` and settled phase 1-3 PLAN/SUMMARY docs were left untouched per the plan's explicit instruction.
- **Task 3 — Live runbook and coverage.** `03-UAT.md` mirrors `02-UAT.md`'s structure: Setup (registration counts now excluding the retired `auq-lock.sh`, state-file writing confirmation, flag-free monitor start), sections A through I each with a concrete trigger and observation command covering every behavior this phase shipped (the live render seam, D-02a Esc recovery, D-02b hook-silence pin, the D-02c bridge, D-06 ghost suppression, D-05 paused-container visibility, D-03 badge-only turn-end, and the D-07 preserved fixes), a **blocking** Section H implementing D-04's needs_input parity gate, and a Teardown that runs `--remove-auq-lock` only after Section H passes, deletes the divergence log, confirms the orphan `.tmp` sweep fired automatically (not a manual delete), and explicitly does **not** delete `monitor-state/` — correcting `02-UAT.md`'s shadow-era `rm -rf` guidance now that the directory is the primary data source. `COVERAGE.md` declares no external API/SDK/service integration, with the supporting reasoning (Python stdlib monitor, bash+jq hooks, local file/process hook interface, pre-existing untouched Telegram integration).
- `requirements.mark-complete` run for FLIP-03 — all three Phase 3 requirements (FLIP-01, FLIP-02, FLIP-03) are now Complete in REQUIREMENTS.md.

## Task Commits

Each task was committed atomically:

1. **Task 1: README describes the architecture that ships** - `7925126` (docs)
2. **Task 2: Promote the verification matrix and write the recertification runbook** - `fa067b7` (docs)
3. **Task 3: The live flip runbook and the coverage declaration** - `4c4ce23` (docs)

**Plan metadata:** (this commit, docs)

## Files Created/Modified

- `README.md` - Setup step 4 rewritten (required, not recommended; names the real mechanism; honest degradation note); feature-list hooks bullet restated as outcome; Development section lists all three suites; docs pointer added
- `docs/TEST-MATRIX.md` - Moved from `.planning/TEST-MATRIX.md` (history preserved); framing paragraph added; internal links repointed; 21 case rows and Verdict to extract section untouched
- `docs/RECERTIFICATION.md` - New: the per-version recertification loop, failure signs, and recording convention (70 lines)
- `.planning/PROJECT.md` - Matrix link repointed to `../docs/TEST-MATRIX.md`
- `.planning/NOTES.md` - Matrix link repointed to `../docs/TEST-MATRIX.md`
- `.claude/CLAUDE.md` - Mirrored project-section matrix link repointed to stay in sync with PROJECT.md
- `.planning/todos/pending/2026-07-29-campagna-ricertificazione-hook-per-versione-claude-code.md` - `related-files` list updated to the new docs/ paths
- `.planning/phases/03-flip-to-default-cleanup/03-UAT.md` - New: the live flip validation and machine-side teardown runbook
- `.planning/phases/03-flip-to-default-cleanup/COVERAGE.md` - New: the no-external-API coverage declaration

## Decisions Made

See `key-decisions` in frontmatter. The most consequential: two referrers not explicitly named in the plan's action text (`.planning/NOTES.md`'s own markdown link, and the mirrored `.claude/CLAUDE.md`) were fixed anyway because they are genuine clickable links that would 404 post-move — distinct from the historical prose mentions in `STATE.md`/`ROADMAP.md` and settled phase docs that the plan explicitly protected from churn.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `git mv`'s automatic staging pulled the bare file rename into Task 1's commit**
- **Found during:** Task 1, staging for commit
- **Issue:** `git mv .planning/TEST-MATRIX.md docs/TEST-MATRIX.md` (run at the start of Task 2's work) stages both sides of the rename immediately. When Task 1 was committed with `git add README.md` alone, git's index still carried that already-staged rename (with zero content diff at that point, since the framing-paragraph/link edits for Task 2 came after), so Task 1's commit ended up including a content-free file rename that belongs to Task 2's scope.
- **Fix:** No corrective action taken — the rename itself carries zero content change (confirmed via `git diff HEAD -- docs/TEST-MATRIX.md` immediately after Task 1's commit, which showed only the subsequent Task 2 edits as pending). History preservation (`git log --follow`) is unaffected either way. Re-ordering to avoid it would require either an interactive rebase (prohibited) or delaying the `git mv` until immediately before Task 2's own commit, which isn't necessary since no functional harm resulted.
- **Files modified:** none (informational only)
- **Verification:** `git show HEAD --stat` on Task 1's commit confirmed the rename carried 0 insertions/deletions; `git log --follow -- docs/TEST-MATRIX.md` after Task 2's commit still shows the full 22-commit history.
- **Committed in:** `7925126` (Task 1 commit, artifact only — no content attributable to Task 1)

---

**Total deviations:** 1 auto-fixed (Rule 1 — informational git-staging artifact, no content or history impact)
**Impact on plan:** None on correctness or scope. The rename's zero-diff nature means Task 1's and Task 2's actual deliverables remain exactly as scoped; only the bare rename's commit attribution is imprecise.

## Issues Encountered

- The task 1 `<verify>` command's link-resolution check necessarily fails if run in isolation before Task 2 creates `docs/TEST-MATRIX.md`/`docs/RECERTIFICATION.md` — anticipated explicitly by the plan's own action text ("Task 2 creates those files; write the pointer here and confirm both paths resolve once task 2 lands"). Resolved by executing Task 2 immediately after Task 1 in the same session and re-running Task 1's full `<verify>` command afterward, which then passed clean.
- The plan's Task 2 action text said "repoint the file's own internal link" (singular) but `docs/TEST-MATRIX.md` actually contains two occurrences of the same phase-1-runbook pointer sentence (the intro paragraph and the "Verdict to extract" section header) plus a third link to `NOTES.md`. All three were repointed since leaving any unfixed would break the task's own link-resolution acceptance criterion.

## User Setup Required

None - no external service configuration required. `03-UAT.md`'s live validation and teardown steps are performed by the user on the Windows machine per D-12, not part of this plan's automated scope.

## Next Phase Readiness

- FLIP-03 is closed; all three Phase 3 requirements (FLIP-01, FLIP-02, FLIP-03) are now Complete in REQUIREMENTS.md.
- Phase 3's code-and-docs scope is done. What remains is exclusively the machine-side live validation: the user runs `03-UAT.md` on the Windows machine, fills in its Recording format table, and — gated behind Section H passing — performs the `--remove-auq-lock` teardown, the divergence-log deletion, and confirms the orphan `.tmp` sweep. `monitor-state/` is explicitly preserved (not deleted) since it is now the primary data source.
- No blockers for phase closure at the docs/code level; the open item is the live UAT run itself, which this plan could not perform from this execution environment (D-12).

---
*Phase: 03-flip-to-default-cleanup*
*Completed: 2026-08-06*

## Self-Check: PASSED

All created files confirmed present on disk (`docs/RECERTIFICATION.md`, `.planning/phases/03-flip-to-default-cleanup/03-UAT.md`, `.planning/phases/03-flip-to-default-cleanup/COVERAGE.md`); `.planning/TEST-MATRIX.md` confirmed absent (moved to `docs/TEST-MATRIX.md`). All three task commit hashes (`7925126`, `fa067b7`, `4c4ce23`) confirmed present in `git log --oneline --all`.
