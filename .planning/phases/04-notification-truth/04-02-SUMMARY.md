---
phase: 04-notification-truth
plan: 02
subsystem: infra
tags: [python, unittest, notifications, telegram, tkinter, monitor.py]

# Dependency graph
requires:
  - phase: 04-notification-truth
    plan: 01
    provides: "hooks/state-writer.sh idle_prompt guard (NOTIF-01/NOTIF-02) — the on-disk record notification_host() and the gate now read is trustworthy"
provides:
  - "monitor.py: local_machine_name(config) — config machine_name -> COMPUTERNAME -> socket.gethostname() first segment, never HOSTNAME"
  - "monitor.py: notification_host(session, local_name) — the origin_host seam for Phase 5, sanitised per T-04-05"
  - "monitor.py: notification_text()/notification_record()/_notify() extended with a host parameter, still the single build site"
  - "monitor.py: machine_name added to DEFAULT_CONFIG (empty string default) so it survives load_config's allow-list copy"
  - "test_monitor.py: Goal31_NotificationHostLabel (20 tests) covering both channels, single-build-site, log parity, all suppressed-decision shapes, and the resolver precedence"
  - "README.md: notification bullet describes the host in the title; mid-turn bullet records the idle-vs-real-request distinction; machine_name config row"
  - ".planning/phases/04-notification-truth/04-UAT.md: the fourth live runbook — Setup (PC + devbox), Sections A-F, the accepted-consequence note, Recording table, Tests placeholders"
affects: [04-UAT-live-run, phase-5-remote-notifications]

# Actuals (#2632)
actuals:
  tokens: 11750
  tasks: 3
  commits: 4

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config-file override with a three-tier environment fallback (config -> platform env var -> generic env/library call), with an explicit documented exclusion of the one env var that would be wrong (HOSTNAME inside a container) — same shape as any future 'trust the override, then the OS, never the ambient value that lies in this deployment' resolver"
    - "Declared keyword parameter threaded through a title-builder -> record-builder -> two-channel-sender chain, never via **extra/kwargs merge, so a field that must reach the user-visible text can't silently land in the log only"

key-files:
  created:
    - .planning/phases/04-notification-truth/04-UAT.md
  modified:
    - monitor.py
    - test_monitor.py
    - README.md

key-decisions:
  - "host resolved once per tick via local_machine_name(), then per-session via notification_host() at the same two call sites alias is already resolved (WORKING branch's self-resume discard, WAITING branch's send/hold logic) — not once per session unconditionally, matching the plan's 'next to where alias is already resolved' instruction exactly"
  - "host stored in the hold dict (alongside alias/elapsed/snapshot) when a hold opens or its reason changes, and read back from the hold — not recomputed — in the vanish sweep, since the session dict no longer exists by the time session_gone is logged"
  - "notification_host() sanitises (strip control chars/newlines, cap at 32 chars) unconditionally, regardless of whether the resolved value came from origin_host or local_name — T-04-05's mitigation covers a pathological machine_name config value too, not just a future origin_host"
  - "TDD gate followed literally as two separate commits: test_monitor.py's Goal31 class (plus the Goal8/Goal27/Goal30 Fake _notify signature updates needed for _check_transitions to call them with the new host= keyword) committed first, confirmed RED by temporarily reverting monitor.py to HEAD and rerunning (18 failures/errors — TypeErrors on the old 2-arg notification_text signature, AttributeErrors on the not-yet-existing resolvers, missing '@ host' in logged titles), then monitor.py's implementation committed as the GREEN follow-up"

patterns-established: []

requirements-completed: [NOTIF-03]

coverage:
  - id: D1
    description: "notification_text(label, elapsed, alias, host) appends ' @ {host}' after label/alias when host is non-empty, and is byte-identical to the pre-phase title when host is empty (compatibility proof) — including the alias-plus-host composition"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_text_with_host_appends_at_host"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_text_with_alias_and_host_composes_both"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_text_with_empty_host_is_byte_identical_to_pre_phase4"
        status: pass
    human_judgment: false
  - id: D2
    description: "local_machine_name(config) resolves config machine_name (stripped) -> COMPUTERNAME env -> first dot-segment of socket.gethostname() -> '' , and never reads HOSTNAME (the container-id trap)"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel (5 precedence/HOSTNAME-exclusion/empty tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "notification_host(session, local_name) prefers a non-blank string origin_host, falls back to local_name for absent/non-string/blank origin_host, and sanitises the result (strip control chars/newlines, cap 32 chars) per T-04-05"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel (4 origin_host/sanitisation tests)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Both channels carry the identical host-suffixed title from one build site: Goal28's Fake driving the real MonitorApp._notify captures the same title in calls['toast'] and calls['telegram']"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_both_channels_carry_the_same_host_title"
        status: pass
    human_judgment: false
  - id: D5
    description: "Single build site proven structurally: patching monitor.notification_text with a sentinel and driving a full send through _check_transitions shows the sentinel in BOTH the real _notify's toast call and the logged notifications.log record"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_single_build_site_stubbed_title_reaches_notify_and_log"
        status: pass
    human_judgment: false
  - id: D6
    description: "notifications.log carries the identical title the user saw, plus a host field, for a sent record and for all three suppressed-decision shapes (hold-opens, session_resumed, session_gone via the vanish sweep's stored snapshot host)"
    requirement: "NOTIF-03"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel (4 log-parity/suppressed-shape tests)"
        status: pass
    human_judgment: false
  - id: D7
    description: "machine_name survives load_config's DEFAULT_CONFIG allow-list copy (round trip) and a non-string value normalises to empty string"
    verification:
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_machine_name_survives_load_config_round_trip"
        status: pass
      - kind: unit
        ref: "test_monitor.py#Goal31_NotificationHostLabel.test_machine_name_non_string_value_normalises_to_empty"
        status: pass
    human_judgment: false
  - id: D8
    description: "README documents the host-in-title behaviour, the idle-vs-real-request distinction, and the machine_name config key"
    verification:
      - kind: other
        ref: "grep -q machine_name README.md"
        status: pass
    human_judgment: false
  - id: D9
    description: "04-UAT.md authored: Setup (PC + devbox), Sections A-F, the accepted-consequence note, Recording table, Tests placeholders — the live overnight acceptance run itself is NOT executed by this plan"
    verification: []
    human_judgment: true
    rationale: "Phase 4's fourth success criterion (SC-4) is explicitly a live, human-run overnight verification on the real Windows PC + devbox — no automated test can substitute for it. This plan's job was authoring a complete, unambiguous runbook; running it is out of this execution's scope by design."

# Metrics
duration: 13min
completed: 2026-08-19
status: complete
---

# Phase 4 Plan 2: Notification Truth — Host On Every Title Summary

**Every "Claude ready" notification now names its machine — `Claude ready — {label} @ {host}` — on the toast and the Telegram push alike, built from one resolver chain (`local_machine_name()` → `notification_host()` → `notification_text()`) and logged character-for-character identical in `notifications.log`, for sent and suppressed decisions both.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-08-19T10:33:09Z (approx., immediately after 04-01)
- **Completed:** 2026-08-19T10:45:54Z
- **Tasks:** 3
- **Files modified:** 4 (1 created)

## Accomplishments
- `local_machine_name(config)` resolves this machine's friendly label with a documented, tested precedence: a non-empty `machine_name` from config, then `COMPUTERNAME`, then the first dot-separated segment of `socket.gethostname()` — and explicitly never `HOSTNAME`, which is the container id on every machine this project runs on today (the exact confusion D-03 exists to remove; a dedicated test proves it isn't read even when set to a real container-id shape).
- `notification_host(session, local_name)` is the Phase 5 seam: it reads `session["origin_host"]` when a future remote-session producer sets it, else falls back to `local_name` — every session this phase produces takes that fallback, since nothing writes `origin_host` yet. It sanitises whatever it returns (T-04-05): control characters and newlines stripped, result capped at 32 characters, so neither a crafted `origin_host` nor a pathological `machine_name` config value can inject a line into a Telegram message or unbound a toast.
- `notification_text()` gained a `host=""` parameter, appending ` @ {host}` after the label/alias and staying byte-identical to the pre-phase title when host is empty — the compatibility proof Goal26's existing no-host assertions confirm untouched. `notification_record()` and `_notify()` both take `host` as a declared parameter (never through `**extra`, which would land the value in the log without ever reaching the title) and pass it straight to `notification_text()` — still the single build site.
- `_check_transitions` resolves `local_machine_name()` once per tick and `notification_host()` per session at the same two spots `alias` is already resolved, threading `host` into the `_notify` call and all six `notification_record` call sites: the plain send, hold-opens, reason-changed, hold_expired, session_resumed, and the vanish sweep's `session_gone` (which now reads `host` back from the hold's stored snapshot, since the session dict no longer exists by then).
- `machine_name` added to `DEFAULT_CONFIG` (empty string) with the same non-string normalisation pattern as `local`/`telegram` — load-bearing, since `load_config()` copies only keys already present in `DEFAULT_CONFIG` and silently drops anything else.
- README's notification bullet now states the host appears in every title; the mid-turn bullet records the other half of Phase 4's truth (idle never pages, only a real prompt/AskUserQuestion does); a `machine_name` row was added to the Configuration table.
- `.planning/phases/04-notification-truth/04-UAT.md` authored: the fourth live runbook, PC + devbox Setup, Sections A-F including the BLOCKING overnight acceptance (Section F) that closes ROADMAP Phase 4's fourth success criterion, plus the accepted-consequence note about `MAX_AGE_SEC` row aging now that idle pings no longer refresh state files.

## Task Commits

Each task was committed atomically, following the plan's `tdd="true"` RED→GREEN discipline for Task 1:

1. **Task 1 RED: host-aware notification title tests** - `0beddfd` (test)
2. **Task 1 GREEN: host on every notification title, one build site, both channels** - `c998b95` (feat)
3. **Task 2: README notification behaviour + machine_name** - `6021d96` (docs)
4. **Task 3: author 04-UAT.md** - `d97165b` (docs)

_Note: Task 1's RED phase was confirmed by temporarily reverting `monitor.py` to HEAD (`git checkout -- monitor.py`, restored from a scratchpad backup afterward — never `git stash`) and rerunning the suite: 18 failures/errors, all the expected symptoms (TypeError on the old 2-arg `notification_text` signature, AttributeError on the not-yet-existing resolvers, missing `"@ matteo"` in logged titles). GREEN restored the implementation and reran to a bare `OK`._

## Files Created/Modified
- `monitor.py` - `local_machine_name()`, `notification_host()` added; `notification_text()`, `notification_record()`, `_notify()` extended with `host`; `machine_name` added to `DEFAULT_CONFIG` + `load_config()` normalisation; `_check_transitions` wired to resolve and thread `host` through the send path and all six `notification_record` call sites
- `test_monitor.py` - New `Goal31_NotificationHostLabel` class (20 tests); `Goal8_NotificationDebounce`, `Goal27_NotificationGateWiring`, `Goal30_IdlePingHoldIntegrity`'s Fake `_notify` doubles updated to accept and capture the new `host` keyword (their `_check_transitions` calls now pass it)
- `README.md` - Notification bullet describes the host in the title; mid-turn bullet records idle-vs-real-request; `machine_name` row added to the Configuration table
- `.planning/phases/04-notification-truth/04-UAT.md` - New file: the fourth live runbook

## Decisions Made
- `host` resolved once per tick (`local_machine_name`) then per session at the exact two spots `alias` is already resolved, not once per session unconditionally — matches the plan's wiring instruction precisely and keeps the change minimal against the existing branch structure.
- `notification_host()` sanitises unconditionally (both the `origin_host` path and the `local_name` fallback path) rather than only sanitising a value that came from `origin_host` — a pathological `machine_name` config entry is exactly as untrusted as a future `origin_host` from T-04-05's threat model perspective.
- The `Goal8_NotificationDebounce` and `Goal30_IdlePingHoldIntegrity` Fake `_notify` doubles needed the same signature update as `Goal27`'s (the plan named explicitly) since all three drive the real `_check_transitions`, which now calls `self._notify(..., host=host)` unconditionally — leaving them unpatched would have broken 2 previously-passing tests with `TypeError: unexpected keyword argument 'host'`, an in-scope Rule 1 fix required to keep the existing suite green, not a scope expansion.
- The "single build site" test used a purpose-built Fake with a REAL (not stubbed) `_notify` (`_notify = monitor.MonitorApp._notify` as a class attribute) rather than literally reusing `Goal27_NotificationGateWiring`'s Fake, whose `_notify` is a stub that never calls `notification_text()` internally — the stubbed version can't prove the single-build-site claim (patching `monitor.notification_text` wouldn't be observable through a `_notify` double that never calls it). The custom Fake keeps the same attribute shape (`_prev_status`, `_working_since`, `_pending_notify`, `_notify_hold`, `_session_aliases`, `config`) `_check_transitions` needs, plus the toast/audio/flash/telegram stubs `_notify` needs, so the patched sentinel title is provably captured on both the toast path and the logged record from one patch point.

## Deviations from Plan

None beyond the two auto-fixes below (Rule 1, in-scope to keep the existing suite green after the signature change) — no scope expansion.

### Auto-fixed Issues

**1. [Rule 1 - Bug] `Goal8_NotificationDebounce`'s 3-value tuple unpack broke after the Fake `_notify` signature changed to a 4-tuple**
- **Found during:** Task 1, after updating all three Fake `_notify` doubles to accept `host=""`
- **Issue:** `label, elapsed, key = app.notifications[0]` (line 1139, pre-phase) raises `ValueError: too many values to unpack` once the Fake appends `(label, elapsed, key, host)` instead of a 3-tuple
- **Fix:** Updated the unpack to `label, elapsed, key, _host = app.notifications[0]`
- **Files modified:** test_monitor.py
- **Verification:** Full suite green (303 tests)
- **Committed in:** `0beddfd` (Task 1 RED commit — test-only change)

**2. [Rule 1 - Bug] `Goal8_NotificationDebounce` and `Goal30_IdlePingHoldIntegrity`'s Fake `_notify` doubles needed the same `host` keyword the plan named only for `Goal27`**
- **Found during:** Task 1, while wiring `_check_transitions` to call `self._notify(..., host=host)` unconditionally
- **Issue:** Both classes drive `_check_transitions` through a bare double with its own stubbed `_notify(self, label, elapsed, key=None)` — without the new keyword, every test in both classes would raise `TypeError: _notify() got an unexpected keyword argument 'host'`
- **Fix:** Extended both Fakes' `_notify` signatures to `(self, label, elapsed, key=None, host="")`, appending `host` to the captured tuple, in the same shape as `Goal27`'s update
- **Files modified:** test_monitor.py
- **Verification:** Full suite green (303 tests)
- **Committed in:** `0beddfd` (Task 1 RED commit — test-only change)

---

**Total deviations:** 2 auto-fixed (both Rule 1, both required to keep the pre-existing suite passing after the signature change the plan itself specified)
**Impact on plan:** None on scope — both fixes are the direct, necessary consequence of the plan's own instruction to extend `_notify`'s signature; the plan named only one of the three affected Fakes explicitly but the fix is identical in shape and mechanical to find via the first test run.

## Issues Encountered
None.

## Observations

**`group_gate` config key finding (Task 2, confirmed, explicitly left unfixed):** `docs/monitor` — actually README.md — documents `group_gate` as a config key ("set `false` to disable the same-project notification wait"), and it IS read at `_group_gate_enabled()` (`monitor.py`, `config.get("group_gate", True)`). But `group_gate` is **not** a key in `DEFAULT_CONFIG`, and `load_config()` copies only `{k: v for k, v in data.items() if k in DEFAULT_CONFIG}` from the on-disk file into the config dict the app actually uses. The practical effect: a user who sets `"group_gate": false` in `~/.claude-monitor-config.json` sees it silently dropped on load — `self.config` never carries the key, `_group_gate_enabled()`'s `.get("group_gate", True)` always falls through to its default `True`, and the documented escape hatch has no effect. Confirmed by reading `load_config()` (monitor.py, the `DEFAULT_CONFIG.update`/allow-list copy) against `DEFAULT_CONFIG`'s literal key set (`mode`, `standard`, `compact`, `local`, `telegram`, `aliases`, and now `machine_name` — no `group_gate`).

This is flagged as a candidate **`[minor/general]` todo** — recorded here, not fixed. It is not NOTIF-01, NOTIF-02, nor NOTIF-03, and the plan's task explicitly scoped this to "confirm and record, do not fix" to keep this phase's diff to what D-01/D-02/D-03 require.

**Resolved machine name on the executing host (this sandbox):** `local_machine_name(None)` resolves to `4d61c415ee08` in this execution environment — the sandbox's `socket.gethostname()` value, reached via the `COMPUTERNAME` → `gethostname()` fallback chain (no `machine_name` config set here, no `COMPUTERNAME` env var present). Note this sandbox is itself a container with no distinguishing "PC name" the way the real Windows host or the devbox have — `gethostname()` here happens to return a container-id-shaped string, which is expected and harmless for this dev sandbox (it never sends a live notification), but is exactly the class of value `local_machine_name()`'s docstring warns a real deployment must avoid getting from `HOSTNAME` — confirming by demonstration why that env var is excluded on purpose.

**Phase 4's fourth success criterion remains open.** ROADMAP Phase 4 SC-4 (the overnight live run on the real Windows PC + devbox, with the loop session active) is carried by `.planning/phases/04-notification-truth/04-UAT.md`'s Section F, authored but not executed by this plan — it requires a human to run `hooks/install.sh` against the real `$HOME` on both machines and let a session run overnight, which this execution environment is explicitly constrained never to do. The runbook is complete and ready; the live run itself is the next step.

## User Setup Required
None from this plan directly. The NEXT step — running `.planning/phases/04-notification-truth/04-UAT.md` live — requires the user to run `hooks/install.sh` on the Windows PC and (over Tailscale) on the devbox, restart both monitors, and let an overnight loop session run; none of that is executable from this environment.

## Next Phase Readiness
- Phase 4's code is complete: NOTIF-01, NOTIF-02 (plan 04-01) and NOTIF-03 (this plan) are all implemented and unit-tested — `python3 -m unittest test_monitor test_state_writer` ends in a bare `OK` at 303 tests (283 baseline + 20 new Goal31 tests).
- `.planning/phases/04-notification-truth/04-UAT.md` is ready to run live; its Section F is the phase's remaining blocking gate.
- Phase 5 (remote/devbox notifications) inherits `origin_host` as a proven, tested seam on the session dict and `notification_host()` as the resolver that already honors it — no remote host map, hostname→machine table, or transport was built here, per this plan's explicit scope discipline.
- The `group_gate`/`DEFAULT_CONFIG` discrepancy is recorded above as a candidate `[minor/general]` todo for a future milestone/quick-task, not carried into this phase's code.

---
*Phase: 04-notification-truth*
*Completed: 2026-08-19*

## Self-Check: PASSED

- `monitor.py` — FOUND
- `test_monitor.py` — FOUND
- `README.md` — FOUND
- `.planning/phases/04-notification-truth/04-UAT.md` — FOUND
- `.planning/phases/04-notification-truth/04-02-SUMMARY.md` — FOUND
- Commit `0beddfd` — FOUND in git log
- Commit `c998b95` — FOUND in git log
- Commit `6021d96` — FOUND in git log
- Commit `d97165b` — FOUND in git log
- `python3 -m unittest test_monitor test_state_writer` — bare `OK`, 303 tests
