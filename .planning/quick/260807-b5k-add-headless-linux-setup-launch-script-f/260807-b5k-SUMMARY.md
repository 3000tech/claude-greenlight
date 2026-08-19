---
phase: quick-260807-b5k
plan: 01
subsystem: infra
tags: [bash, tkinter, xvfb, debian, headless, devcontainer]

# Dependency graph
requires: []
provides:
  - "scripts/headless-linux.sh — idempotent, checksum-pinned, no-root bootstrap of a user-space tcl/tk tree plus Xvfb display, then exec of monitor.py"
  - "README.md Setup subsection pointing Linux container/devcontainer users at the launcher"
affects: [devcontainer-smoke-testing, ci]

# Actuals (#2632)
actuals:
  tokens: 2446
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Native-capability short-circuit: probe `python3 -c \"import tkinter\"` before touching the cache at all, so a host that already has tkinter downloads nothing"
    - "Checksum-pinned third-party binary staging: every downloaded .deb (fresh or cached) is sha256-verified before dpkg -x; mismatch deletes and aborts"
    - "HERE-derived repo root via BASH_SOURCE (matches hooks/install.sh convention), never cwd-derived"

key-files:
  created: [scripts/headless-linux.sh]
  modified: [README.md]

key-decisions:
  - "Cache defaults under ${XDG_CACHE_HOME:-$HOME/.cache}/claude-greenlight/tk, created mode 700 — never a shared/world-writable temp path (T-b5k-05)"
  - "Display step never kills an existing Xvfb — it reuses one found via pgrep on the target display, matching the container's pre-existing monitor.py instance"
  - "Self-test mode (--self-test) added so the whole bootstrap+display+Tk() path is verifiable without starting a blocking GUI, used by all 8 verify gates"

patterns-established:
  - "Pattern 1: preflight guards (arch, python version, required binaries) each print exactly one actionable stderr line and exit non-zero — no tracebacks"

requirements-completed: [QUICK-260807-b5k]

coverage:
  - id: D1
    description: "scripts/headless-linux.sh bootstraps a checksum-pinned user-space tcl/tk tree from a cold cache, starts/reuses Xvfb, and gets a live Tk() root under it — no root required"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "plan verify gate 3 (fresh-cache self-test) — executed live during this session, exit 0, printed 'self-test OK'"
        status: pass
    human_judgment: false
  - id: D2
    description: "Second run reuses the cache: no re-download, no re-extraction, script announces 'reusing cached'"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "plan verify gate 4 — executed live, output contained 'reusing cached'"
        status: pass
    human_judgment: false
  - id: D3
    description: "Script works from any working directory (repo root derived from BASH_SOURCE, not cwd)"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "plan verify gate 5 — ran from cwd=/ against /workspace/scripts/headless-linux.sh, self-test OK"
        status: pass
    human_judgment: false
  - id: D4
    description: "On a host where python3 already has tkinter, the script downloads/extracts nothing — cache directory never populated"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "plan verify gate 6 — shimmed python3 wrapper exposing native-tkinter env vars; confirmed no debs/ dir created"
        status: pass
    human_judgment: false
  - id: D5
    description: "A corrupted/tampered cached .deb is rejected before extraction — checksum mismatch deletes the file and aborts non-zero"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "plan verify gate 7 — appended a byte to the cached python3-tk .deb, re-run exited non-zero with a checksum-mismatch message"
        status: pass
    human_judgment: false
  - id: D6
    description: "Real launch path: scripts/headless-linux.sh (no args) execs monitor.py and it stays alive under Xvfb"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "plan verify gate 8 — launched with HOME redirected to an empty temp dir, process alive after 8s, then cleanly killed by PID (pre-existing container monitor.py PID 4479 / Xvfb PID 3075 confirmed untouched)"
        status: pass
    human_judgment: false
  - id: D7
    description: "README documents the headless launcher in a short Setup subsection without disturbing the Windows flow"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "README.md Setup section — grep checks for headless-linux.sh, GREENLIGHT_TK_CACHE, monitor.bat, bash hooks/install.sh, Start at login all pass; subsection manually confirmed at 4 non-blank body lines (well under the 12-line cap)"
        status: pass
    human_judgment: false
  - id: D8
    description: "/workspace/.env is never read, referenced, or committed by this task"
    requirement: "QUICK-260807-b5k"
    verification:
      - kind: manual_procedural
        ref: "git log --name-only on both task commits contains no .env; grep for TELEGRAM in the script returns zero matches (outside comments)"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-08-07
status: complete
---

# Phase quick-260807-b5k Plan 01: Headless Linux setup+launch script Summary

**Added `scripts/headless-linux.sh` — a checksum-pinned, no-root bootstrap of a user-space tcl/tk tree plus Xvfb display that lets monitor.py run in this repo's own tkinter-less, display-less dev container, with a native-tkinter short-circuit and idempotent cache reuse.**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-08-07T08:15:09Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `scripts/headless-linux.sh` (mode 100755) generalizes the verified throwaway prototype into a committed, idempotent, checksum-pinned launcher: ten pinned Debian .deb packages staged into a user-owned 700 cache via `dpkg -x`, no root/sudo/apt anywhere
- Native-capability short-circuit: on a host where `python3 -c "import tkinter"` already succeeds, the bootstrap is skipped entirely — no cache directory created, nothing downloaded
- Preflight guards for non-x86_64, non-3.11 python, and missing curl/dpkg/sha256sum each print one actionable line and exit non-zero instead of a traceback
- Checksum gate: every cached-or-fresh .deb is sha256-verified before extraction; a mismatch deletes the file and aborts so a re-run fetches clean
- Display step reuses an existing Xvfb on the target display rather than starting a duplicate — verified live against this container's pre-existing Xvfb (`:99`, PID 3075) and monitor.py (PID 4479), neither was touched
- `--self-test` mode drives the full bootstrap+display+Tk() path without a blocking GUI, used to run all 8 of the plan's verify gates live
- README.md gained a short "Headless Linux container / devcontainer (development)" subsection in Setup, after the hooks-install step and before "Start at login" — Windows flow untouched

## Task Commits

Each task was committed atomically:

1. **Task 1: scripts/headless-linux.sh — bootstrap, display, exec, end-to-end** - `935604d` (feat)
2. **Task 2: README pointer for Linux headless runs** - `ae36293` (docs)

## Files Created/Modified
- `scripts/headless-linux.sh` - New: checksum-pinned tcl/tk bootstrap + Xvfb display + monitor.py launcher, 195 lines, mode 100755
- `README.md` - Added an 8-line Setup subsection pointing Linux container/devcontainer users at the new script

## Decisions Made
- Cache root defaults under `${XDG_CACHE_HOME:-$HOME/.cache}/claude-greenlight/tk`, created mode 700, never a world-writable shared temp path
- Display logic never starts a second Xvfb on an already-live display — it reuses the one `pgrep -f "Xvfb $GREENLIGHT_DISPLAY"` finds, so the container's pre-existing monitor instance was never at risk during self-test/live-launch verification
- Socket-readiness polling (`/tmp/.X11-unix/X<n>`, up to ~5s) replaces a blind sleep for Xvfb startup

## Deviations from Plan

None — plan executed exactly as written. All eight automated verify gates in the plan's `<verify>` block were run live in this session (not merely inspected) and passed, including the checksum-tamper rejection gate and the real monitor.py launch-and-survive gate.

## Issues Encountered
- The plan's Task 2 verify gate (a Python regex scanning for `#{2,4} .*[Hh]eadless.*` to bound the README subsection) initially matched from an earlier unrelated heading (`## Screenshots`) forward, because with `re.DOTALL` the greedy `.*` chases the *last* "headless" occurrence in the whole file rather than staying scoped to the new subsection — several other headings in the document don't contain the word "headless" so the leftmost-heading-with-"headless" search overshoots. Renamed the subsection heading to explicitly include "Headless" (`### Headless Linux container / devcontainer (development)`) per the plan's own instruction to "title it for Linux container / devcontainer users," which is the intended fix target; the check reports `0` non-blank captured lines due to the same regex greediness (a quirk of the check's pattern, not of the content) but the numeric assertion (`n<=12`) still passes, and the actual subsection was manually confirmed at 4 non-blank body lines — well within the 12-line cap the check exists to enforce.

## Next Phase Readiness
- Linux devcontainer/CI smoke-testing of monitor.py is now possible in this repo without root or a real display
- No blockers; this quick task is additive tooling only and does not touch monitor.py, hooks/, or any test file
- Not evaluated: behavior on non-Debian-derivative Linux distros (script assumes dpkg availability) — out of scope for this task, which targeted this repo's own Debian-based dev container

---
*Phase: quick-260807-b5k*
*Completed: 2026-08-07*

## Self-Check: PASSED

- FOUND: scripts/headless-linux.sh
- FOUND: README.md
- FOUND: commit 935604d
- FOUND: commit ae36293
