---
phase: 04-notification-truth
verified: 2026-08-19T00:00:00Z
status: human_needed
score: 10/10 must-haves verified (code-level); 1 live acceptance item open
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Run .planning/phases/04-notification-truth/04-UAT.md live on the real Windows PC + devbox (Setup, Sections A-F), including the overnight loop-session acceptance (Section F)."
    expected: "Sections A-E confirm the code's behaviour on real Claude Code sessions (idle ping inert, real permission_prompt/AskUserQuestion still page, hold survives an idle ping, host shown on both channels and in the log). Section F — the phase's fourth, BLOCKING success criterion — needs a full overnight run producing a sent-notification count of 0 and an idle-ping count > 0 for the loop session, while a real permission prompt in the same window still paged."
    why_human: "SC-4 is explicitly a live, human-run, overnight verification on real machines (real Claude Code sessions, real Telegram/toast delivery, real elapsed hours) — no unit test or static check can substitute for it. 04-UAT.md's frontmatter still reads status: pending and its Summary table shows 0/8 passed, 8/8 pending; none of Setup/A-F has been executed yet."
---

# Phase 4: Notification Truth Verification Report

**Phase Goal:** A notification means what it claims — the user is genuinely needed — and it says which machine is asking. Self-resuming loop sessions stop paging overnight, the background-tasks hold stops leaking, and origin host is visible on every channel.
**Verified:** 2026-08-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | Session that receives only `idle_prompt` Notifications stays `waiting`, zero pushes; a real `permission_prompt`/AskUserQuestion still turns `needs_input` and pages | ✓ VERIFIED | `hooks/state-writer.sh` Notification branch (lines 185-206): exits 0 without writing only when `notification_type` is exactly `idle_prompt`; `PermissionRequest` untouched (line 182-184). `test_state_writer.py::Goal10_IdlePingNeverPages` (5 tests) replays the real 2026-08-17 episode end to end (writer → state file → `scan_state_files()` → `gate_notification()`) and pins the fail-safe direction (permission_prompt, absent/empty/unrecognised/non-string type, bare PermissionRequest all still write `needs_input`). Ran locally: all 5 tests PASS. |
| SC-2 | A notification held by the background-tasks gate is released only when the session genuinely needs the user or is fully idle; an idle ping mid-hold leaves the hold standing (no `gate_cleared` send) | ✓ VERIFIED | Because an ignored idle ping never rewrites the state file, `gate_notification()`'s existing `background_tasks` refusal (monitor.py) never sees a fabricated `background_tasks_count: 0`. `test_monitor.py::Goal30_IdlePingHoldIntegrity` (5 tests) + `Goal30b_IdlePingDiskReplay` (1 test) pin: hold survives repeated unchanged ticks (zero `_notify` calls, one log record), genuine release still fires, self-resume still discards, max-hold still expires, and a disk replay of the real 2026-08-17 session confirms the refusal. Ran locally: all 6 tests PASS. Zero `monitor.py` changes were needed for this truth — confirmed as a writer-only fix. |
| SC-3 | Every notification title carries its origin host on both toast and Telegram, for local sessions as well as remote ones; `notifications.log` records the identical string | ✓ VERIFIED | `monitor.py`: `local_machine_name()` (1451-1476), `notification_host()` (1479-1501, includes the WR-02 fix — sanitises before the blank-check), `notification_text(label, elapsed, alias, host)` (1504-1527) appends ` @ {host}`, single build site. `_notify()` (2635-2674) builds the title once and passes the identical `toast_title`/`toast_body` to both `_send_telegram()` and `_notify_toast()`. `_check_transitions` (2300-2412) resolves `host` per session at all six `notification_record` call sites (plain send, hold-opens, reason-changed, hold_expired, session_resumed, session_gone-via-snapshot). `test_monitor.py::Goal31_NotificationHostLabel` (20 tests) covers both-channels parity, single-build-site proof (stubbed `notification_text` reaches both `_notify` and the log), log parity for sent AND all three suppressed shapes, the resolver precedence (config → COMPUTERNAME → gethostname, never HOSTNAME), and `machine_name`'s `DEFAULT_CONFIG`/`load_config` round trip. Ran locally: all 20 tests PASS. Manually re-verified the WR-02 fix by direct call: a control-char-only `origin_host` (`"\x01\x02"`) correctly falls back to `local_name` rather than degrading to an empty host. |
| SC-4 | On the real Windows + devbox setup, a full overnight run produces zero illegitimate notifications while real permission prompts still page immediately (live, user-assisted UAT) | ? NOT YET RUN | `.planning/phases/04-notification-truth/04-UAT.md` exists, is structurally complete (Setup for PC + devbox, Sections A-F, Recording table, Tests placeholders), and explicitly carries WR-01's fix operationally (Setup step 4 pins `machine_name` in the devbox config to avoid the container-id fallback). Frontmatter reads `status: pending`; the Summary table reads `total: 8, passed: 0, pending: 8`. No section has been executed yet — this is a live, human-run item by design and cannot be verified from the codebase. |

**Score:** 3/4 ROADMAP success criteria code-verified with passing automated tests (SC-1, SC-2, SC-3); SC-4 is the phase's designed live-verification gate, not yet run.

### Plan-Level Must-Haves (04-01-PLAN.md)

| Must-have | Status | Evidence |
|-----------|--------|----------|
| Truth: idle_prompt leaves state file byte-identical, no write, no push (D-01) | ✓ VERIFIED | `Goal10_IdlePingNeverPages.test_idle_ping_leaves_state_byte_identical_and_gate_still_refuses` — PASS |
| Truth: permission_prompt / absent / empty / unrecognised / non-string type still writes needs_input | ✓ VERIFIED | `Goal10_IdlePingNeverPages` subTests — PASS |
| Truth: AskUserQuestion (PermissionRequest) path untouched | ✓ VERIFIED | `state-writer.sh` line 182-184 unconditional; test — PASS |
| Truth: held notification stays held across an idle ping | ✓ VERIFIED | `Goal30_IdlePingHoldIntegrity.test_hold_survives_repeated_unchanged_idle_ping_ticks` — PASS |
| Truth: held notification still releases on genuine zero, still discards on self-resume, still expires at max hold | ✓ VERIFIED | `Goal30_IdlePingHoldIntegrity` (3 tests) — PASS |
| Artifact: `hooks/state-writer.sh` — Notification branch split, idle_prompt guard, header updated | ✓ VERIFIED | Read in full; branch present at lines 185-206, header mapping table updated lines 46-83 |
| Artifact: `test_state_writer.py` — Goal10_IdlePingNeverPages | ✓ VERIFIED | Class exists (line 1126), 5 tests, all PASS |
| Artifact: `test_monitor.py` — Goal30_IdlePingHoldIntegrity | ✓ VERIFIED | Classes exist (lines 2864, 3025), 6 tests, all PASS |
| Artifact: `docs/TEST-MATRIX.md` — case 4 verdict + revision entry | ✓ VERIFIED | grep confirms idle_prompt in case 4 row and dated revision section |
| Key link: writer Notification branch → state file → scan_state_files → gate_notification → send path | ✓ VERIFIED (WIRED) | Exercised end-to-end by `Goal10`'s tracer test, which runs the real hook script then calls `monitor.scan_state_files()`/`gate_notification()` directly |
| Key link: idle_prompt payload carries no `background_tasks` key, which is what zeroed the count | ✓ VERIFIED | Documented in code comment (state-writer.sh 195-200) and CONTEXT.md evidence base |

### Plan-Level Must-Haves (04-02-PLAN.md)

| Must-have | Status | Evidence |
|-----------|--------|----------|
| Truth: every title reads `Claude ready — {label} @ {host}` on toast AND Telegram (D-03) | ✓ VERIFIED | `Goal31_NotificationHostLabel.test_both_channels_carry_the_same_host_title` — PASS |
| Truth: notifications.log records identical title, sent AND suppressed | ✓ VERIFIED | `Goal31_NotificationHostLabel` log-parity + 3 suppressed-shape tests — PASS |
| Truth: notification_text() stays single build site | ✓ VERIFIED | `Goal31_NotificationHostLabel.test_single_build_site_stubbed_title_reaches_notify_and_log` — PASS; code inspection confirms `_notify`/`_send_telegram`/`_notify_toast` never independently compose a title |
| Truth: per-session alias still disambiguates alongside host | ✓ VERIFIED | `Goal31_NotificationHostLabel.test_text_with_alias_and_host_composes_both` — PASS |
| Truth: machine_name overridable from config, survives load_config | ✓ VERIFIED | `Goal31_NotificationHostLabel.test_machine_name_survives_load_config_round_trip` + `DEFAULT_CONFIG`/`load_config` code (monitor.py:218-246) — PASS |
| Artifact: `monitor.py` — local_machine_name(), notification_host(), host-aware signatures, machine_name in DEFAULT_CONFIG | ✓ VERIFIED | Read in full |
| Artifact: `test_monitor.py` — Goal31_NotificationHostLabel | ✓ VERIFIED | Class exists (line 3297), 20 tests, all PASS |
| Artifact: `README.md` — notification behaviour + machine_name row | ✓ VERIFIED | grep confirms `machine_name` row present |
| Artifact: `.planning/phases/04-notification-truth/04-UAT.md` — live runbook | ✓ VERIFIED (exists, complete) — not yet run (see SC-4 above) |
| Key link: `_check_transitions` → `_notify` → `_notify_toast`/`_send_telegram` (same title object) | ✓ VERIFIED (WIRED) | `_notify()` code read: builds `toast_title`/`toast_body` once via `notification_text()`, passes the same values to both channel senders |
| Key link: `_check_transitions` → `notification_record` → `log_notification` (logged title = displayed title) | ✓ VERIFIED (WIRED) | All six call sites in `_check_transitions` pass `host=` through to `notification_record`, which rebuilds the identical title via the same `notification_text()` call |
| Key link: `notification_host(session, local_name)` → `origin_host` seam for Phase 5 | ✓ VERIFIED | Code + docstring confirm `session.get("origin_host")` is read and falls back to `local_name`; nothing writes `origin_host` yet, as designed |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `hooks/state-writer.sh` | idle_prompt no-write guard | ✓ VERIFIED | Split branch, guard present, comments document D-01/D-02 |
| `monitor.py` | host-aware notification path | ✓ VERIFIED | `local_machine_name`, `notification_host`, host param threaded through `notification_text`/`notification_record`/`_notify`/`_check_transitions` |
| `test_state_writer.py` | Goal10_IdlePingNeverPages | ✓ VERIFIED | 5 tests, PASS |
| `test_monitor.py` | Goal30/Goal30b/Goal31 | ✓ VERIFIED | 26 new tests, PASS |
| `docs/TEST-MATRIX.md` | case 4 verdict + revision | ✓ VERIFIED | Amended, idle_prompt referenced |
| `README.md` | notification behaviour + machine_name | ✓ VERIFIED | Amended |
| `.planning/phases/04-notification-truth/04-UAT.md` | live runbook | ✓ VERIFIED (exists) | Structurally complete; not yet run |

### Code-Review Follow-up (04-REVIEW.md)

| Item | Disposition | Verified |
|------|-------------|----------|
| WR-01 (local_machine_name falls back to container ID inside a devbox/headless deployment without manual config) | Addressed operationally, not in code | ✓ VERIFIED — `04-UAT.md` Setup step 4 (devbox) explicitly pins `machine_name: "macbook-devbox"` in the devbox config before the overnight run, citing WR-01 by name. This is a documented operational mitigation, not a code guard; acceptable per the review's own two listed fix options (a) document as required, or (b) add a heuristic guard — option (a) was taken. |
| WR-02 (notification_host silently drops host for a control-char-only origin_host) | Fixed in code | ✓ VERIFIED — commit `346581d`. `notification_host()` (monitor.py:1492-1501) now sanitises via `_clean()` BEFORE the blank-check, exactly as the review's suggested fix. Re-verified by direct call: `notification_host({"origin_host": "\x01\x02"}, "matteo")` returns `"matteo"` (correct fallback), not `""`. Note: no dedicated regression test pins this exact control-char-only edge case (the existing `test_notification_host_sanitises_control_chars_and_caps_length` test uses a malicious string that still has printable characters left after sanitisation) — a minor test-coverage gap, not a functional one, since the code fix was verified directly. |
| IN-01 (--test-notify smoke tool doesn't exercise host suffix) | Left unfixed (Info-level, non-blocking) | Confirmed unfixed — `monitor.py:3006-3019` calls `_notify("test", 600)` with no host kwarg. Cosmetic gap in a developer-only smoke tool; does not affect production notification paths. |
| IN-02 (host bypassing `**extra` enforced by convention only) | Left unfixed (Info-level, non-blocking) | Confirmed unfixed as documented; low-priority defensive-coding suggestion, no assert added. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full regression suite ends in bare OK | `python3 -m unittest test_monitor test_state_writer` | `Ran 303 tests in 9.020s` / `OK` | ✓ PASS |
| Phase-4-specific test classes pass in isolation | `python3 -m unittest test_state_writer.Goal10_IdlePingNeverPages test_monitor.Goal30_IdlePingHoldIntegrity test_monitor.Goal30b_IdlePingDiskReplay test_monitor.Goal31_NotificationHostLabel -v` | `Ran 31 tests in 0.913s` / `OK` | ✓ PASS |
| WR-02 fix functions correctly at runtime | `monitor.notification_host({"origin_host": "\x01\x02"}, "matteo")` | `'matteo'` | ✓ PASS |
| No debt markers (TBD/FIXME/XXX) in phase-modified files | grep across hooks/state-writer.sh, monitor.py, test_state_writer.py, test_monitor.py, README.md, TEST-MATRIX.md, 04-UAT.md | one false-positive match ("not TBD" prose in TEST-MATRIX.md, not a marker) | ✓ PASS |
| Commits referenced in both SUMMARYs exist in git log | `git log --oneline \| grep -E '^(c570595\|ed9e9e3\|d379067\|0beddfd\|c998b95\|6021d96\|d97165b\|346581d)'` | all 8 commits found | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| NOTIF-01 | 04-01 | idle_prompt never produces needs_input | ✓ SATISFIED | Goal10 suite, code read |
| NOTIF-02 | 04-01 | Held notification not released by idle ping | ✓ SATISFIED | Goal30/Goal30b suite, code read |
| NOTIF-03 | 04-02 | Origin host on every title, both channels | ✓ SATISFIED (code); live confirmation pending | Goal31 suite, code read; 04-UAT.md Section E not yet run |

No orphaned requirements — all three NOTIF-* requirements are claimed by exactly one of the two plans, matching REQUIREMENTS.md's Phase 4 mapping.

### Anti-Patterns Found

None. No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers in any phase-modified file. No stub returns, no hardcoded empty data flowing to rendered output.

## Human Verification Required

### 1. Run 04-UAT.md live (Setup + Sections A-F, including the BLOCKING Section F overnight acceptance)

**Test:** On the real Windows PC and the MacBook devbox (over Tailscale), follow `.planning/phases/04-notification-truth/04-UAT.md` exactly: pull this phase's commits, re-run `hooks/install.sh` on both machines, restart both monitors, set `machine_name` in the devbox config (WR-01 mitigation), then run Sections A through F — culminating in an overnight self-resuming loop session on the devbox.

**Expected:** Sections A-E each confirm one piece of the phase's code-level guarantee against a real session (idle ping inert, real prompts still page, hold survives an idle ping, host shown identically on toast/Telegram/log). Section F — the phase's fourth ROADMAP success criterion — must show a `sent` count of 0 and an `idle_prompt` count > 0 for the overnight loop session, with a real permission prompt elsewhere in the same window still producing a `sent` count > 0.

**Why human:** This is explicitly a live, overnight, user-assisted verification against real Claude Code sessions and real notification delivery (toast + Telegram) on the actual hardware pair — the exact kind of check the ROADMAP itself designates as "live UAT" and that no unit test, grep, or static check can substitute for. The runbook's own frontmatter (`status: pending`) and Summary (`passed: 0, pending: 8`) confirm it has not yet been run.

## Gaps Summary

No code-level gaps. Both plans' must-haves (truths, artifacts, key links) are all VERIFIED against the actual codebase, not just claimed in the SUMMARYs — every test file, class, and test named in both SUMMARYs was independently located and re-run locally (bare `OK`, 303 tests), and the two code-review Warnings were independently checked: WR-02 is fixed in code (re-verified by direct function call) and WR-01 is addressed operationally in the UAT runbook, exactly as 04-REVIEW.md's option (a) permits.

The only open item is the phase's own fourth success criterion (SC-4): a live, human-run overnight acceptance test on the real Windows PC + devbox pair, authored and ready in `04-UAT.md` but not yet executed. This is a designed gate, not a defect — plan 04-02 explicitly scoped the live run outside its own execution ("criterion 4 carried by 04-UAT.md and closed by the live overnight run, not by this execution"). Per the verification decision tree, an unexecuted-but-ready human-verification item routes the overall status to `human_needed`, not `gaps_found`.

Note (non-blocking, informational): `.planning/STATE.md` and `.planning/ROADMAP.md`'s Phase 4 checkboxes/progress table were not observed to reflect the phase's completed plans (STATE.md still reads milestone status `planning`, ROADMAP's Phase 4 progress row still reads `0/2`) — this is a project-bookkeeping staleness issue, not a code or goal-achievement gap, and does not affect this verification's findings.

---

_Verified: 2026-08-19_
_Verifier: Claude (gsd-verifier)_
