---
phase: 04-notification-truth
reviewed: 2026-08-19T10:53:28Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - hooks/state-writer.sh
  - monitor.py
  - test_state_writer.py
  - test_monitor.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-08-19T10:53:28Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the idle_prompt writer-guard (`hooks/state-writer.sh`, 04-01) and the
host-label notification build (`monitor.py`, 04-02), plus their test suites.
The fail-safe direction the context locks (`idle_prompt` is the ONLY ignored
value; missing/empty/non-string/object `notification_type` all still write
`needs_input`) is implemented correctly in the shell script and is exercised
by `Goal10_IdlePingNeverPages`, including the tricky jq edge cases (object
and numeric `notification_type` both correctly fall through to
`needs_input` because `jq -r` on a compound value errors to empty stdout
under `2>/dev/null`, which the test suite pins). Shell quoting in the
Notification branch is safe — `notification_type` is only ever used inside
a quoted `[ "$notification_type" = "idle_prompt" ]` comparison, never
interpolated into a command or path.

The `host` kwarg threaded through `notification_text()` /
`notification_record()` / `_notify()` / `_check_transitions()` is
consistent: every one of the five `log_notification(notification_record(...))`
call sites in `_check_transitions` was updated to pass `host=`, all three
`Fake` test doubles for `_notify()` were updated to the 4-tuple shape, and
`host` never rides through `**extra`/`**detail` (both of which are keyed on
`group`/`background_tasks_count`/`blocked_by`, never `host`), so there is no
silent field collision on `record.update(extra)`. `notification_host()`'s
sanitisation (control-char strip + 32-char cap) is applied at the one point
every title-bound value passes through, and Telegram's `urlencode()` body
means no header-injection vector exists regardless.

The main substantive issue is in `local_machine_name()`'s fallback chain,
which can reproduce the exact "container id shown instead of a machine
name" confusion NOTIF-03/D-03 was written to eliminate, in a deployment
scenario (headless/devbox) this same phase's own UAT plan exercises. See
WR-01.

## Warnings

### WR-01: `local_machine_name()` falls back to a container ID on any headless/devbox deployment without manual config

**File:** `monitor.py:1451-1476`
**Issue:** The resolution order is `config["machine_name"]` → `COMPUTERNAME`
env var → first segment of `socket.gethostname()`. The docstring and
`04-CONTEXT.md` decision 3 are explicit that the point of this feature is
"container hostnames map to the machine that runs them (the PC's sessions
show the PC's name, not the container id)" — and the code deliberately
avoids reading `$HOSTNAME` for exactly that reason (container id trap).
But `socket.gethostname()` is not actually a safe substitute: inside a
Docker/devcontainer, `gethostname()` returns the *same* container-id-shaped
value as `$HOSTNAME` (they're sourced from the same `/etc/hostname` by
default). The README's own supported target is native Windows (where this
is fine — the monitor process itself isn't containerized), but this
project also ships `scripts/headless-linux.sh` for "headless Linux
container / devcontainer" use, and the devbox referenced throughout
`04-CONTEXT.md` and `04-UAT.md` as this phase's live-verification vehicle
runs exactly that way. The phase's own 04-02-SUMMARY.md documents this by
demonstration ("`local_machine_name(None)` resolves to `4d61c415ee08` in
this execution environment... a container-id-shaped string") and waves it
off as harmless for the dev sandbox specifically — but the same fallback
chain fires identically on the devbox unless an operator remembers to set
`machine_name` in config. Nothing enforces or even flags that requirement:
README lists `machine_name` as an optional "override," not as required
setup for any non-Windows-native deployment, so the default outcome for a
container-hosted monitor is silently reproducing the bug this phase exists
to fix — with no error, no warning, just a wrong-looking title character
for character indistinguishable from correct output.
**Fix:** Either (a) document in README/04-UAT.md that `machine_name` is
**required**, not optional, for any container/headless deployment (devbox
included), or (b) add a heuristic guard in `local_machine_name()` that
refuses to trust `socket.gethostname()` when it looks like a Docker
container ID (12 lowercase-hex chars is the default Docker short-ID shape)
and falls back to `""` (today's no-host title) instead of silently
displaying it:
```python
_DOCKER_ID_RE = re.compile(r"^[0-9a-f]{12}$")
...
hostname = socket.gethostname()
if hostname:
    first = hostname.split(".")[0]
    if not _DOCKER_ID_RE.match(first):
        return first
return ""
```

### WR-02: `notification_host()` can silently drop the host label for a control-char-only `origin_host`, deviating from the documented "falls back to local_name" contract

**File:** `monitor.py:1479-1497`
**Issue:** The blank-check (`isinstance(origin, str) and origin.strip()`)
uses Python's `str.strip()`, which only treats whitespace as trimmable —
control characters such as `\x01`, `\x02`, `\x07` (BEL) are not
whitespace, so a hypothetical `origin_host` value consisting solely of
control characters (e.g. `"\x01\x02"`) passes the truthiness check and is
selected over `local_name`. It is then sanitised by the trailing
`re.sub(r"[\x00-\x1f\x7f]", "", host)`, which strips those same control
characters and yields `""`. The function returns `""` instead of falling
back to `local_name` as the docstring promises ("A non-string or blank
`origin_host` falls back to `local_name` too"). Downstream, `notification_text()`'s
`if host:` check treats `""` as falsy, so today this only degrades to "no
host shown" rather than a malformed title — not a crash or injection, but
a real deviation from the documented fallback contract. `origin_host` is
not written by any producer yet (Phase 5 seam), so this path is currently
unreachable in production, but the test suite (`test_notification_host_falls_back_on_non_string_or_blank_origin`)
does not cover this case, and Phase 5 will make it reachable.
**Fix:** Sanitise before the blank check rather than after, so a
control-chars-only value is recognised as blank and correctly falls back
to `local_name`:
```python
def notification_host(session: dict, local_name: str) -> str:
    origin = session.get("origin_host") if isinstance(session, dict) else None
    origin = re.sub(r"[\x00-\x1f\x7f]", "", origin).strip() if isinstance(origin, str) else ""
    host = origin if origin else local_name
    if not isinstance(host, str):
        host = ""
    sanitized = re.sub(r"[\x00-\x1f\x7f]", "", host).strip()
    return sanitized[:32]
```

## Info

### IN-01: `--test-notify` self-test never exercises the new host suffix

**File:** `monitor.py:3019`
**Issue:** `app.root.after(400, lambda: app._notify("test", 600))` calls
`_notify()` without the new `host` kwarg, so the manual `--test-notify`
smoke-test tool (the developer's own way to sanity-check what a real
notification looks like) will always render the pre-phase-4 title
(`Claude ready — test`), never the host-suffixed form the rest of the
codebase now sends on every real notification. Anyone using this flag to
verify NOTIF-03 will see a false negative for "the host isn't showing."
**Fix:** Pass a resolved host through, matching production:
```python
app.root.after(400, lambda: app._notify(
    "test", 600, host=monitor.notification_host({}, monitor.local_machine_name(app.config))))
```

### IN-02: `host` bypassing `**extra` is enforced only by convention, not by structure

**File:** `monitor.py:1541-1582`
**Issue:** `notification_record()`'s docstring explicitly calls out that
`host` must stay a declared parameter because `record.update(extra)` at the
end would silently let a same-named key in `**extra`/`**detail` clobber it.
This is correctly true today (no caller's `extra`/`detail` dict carries a
`host` key), but the safety depends entirely on every future caller
remembering not to add one — `record.update(extra)` runs unconditionally
after the explicit fields are set, so nothing would catch a regression
until a notification silently showed the wrong host.
**Fix:** Low priority given the current call sites are all in this same
file and already audited, but consider asserting the invariant defensively,
e.g. `assert "host" not in extra` before the `record.update(extra)` call,
so a future caller passing `host` through `**extra` fails loudly in tests
instead of silently overwriting the composed value.

---

_Reviewed: 2026-08-19T10:53:28Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
