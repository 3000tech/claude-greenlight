# Phase 2: State Writer & Shadow Mode - Pattern Map

**Mapped:** 2026-07-29
**Files analyzed:** 7 (new + modified)
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `hooks/state-writer.sh` | hook script (event-keyed writer) | event-driven, file-I/O (overwrite) | `hooks/event-logger.sh` | role-match (append→overwrite delta) |
| `hooks/state-writer-events.json` | config (event registration list) | static data | `hooks/hook-events.json` | exact |
| `hooks/install.sh` (modified) | config/installer | idempotent merge | itself (existing logger + lock registration blocks) | exact |
| `monitor.py::scan_state_files()` | service (state-derivation engine) | CRUD (read+derive), batch | `monitor.py::scan()` | exact |
| `monitor.py::_read_state_file()` | utility (defensive file read) | file-I/O | `monitor.py::tail_last_line()` | exact |
| `monitor.py` shadow-tick + divergence logging (in `refresh()`) | controller/event-driven glue | event-driven, transform | `monitor.py::refresh()` + `_check_transitions()` | role-match |
| `test_state_writer.py` | test | subprocess/integration | `test_event_logger.py` | exact |
| `test_monitor.py` (new test classes for `scan_state_files`) | test | unit | `test_monitor.py` existing `scan()` test classes | exact |

## Pattern Assignments

### `hooks/state-writer.sh` (hook script, event-driven, file-I/O overwrite)

**Analog:** `hooks/event-logger.sh` (146 lines, read in full)

**Header/discipline comment pattern** (lines 1–48 of event-logger.sh): every hook script in this repo opens with a long comment block explaining (a) what it's diagnostic/authoritative for, (b) the never-block/`exit 0`-always guarantee, (c) exactly what fields are captured vs deliberately excluded (privacy), (d) teardown instructions. Reuse this shape for `state-writer.sh`'s header, but the "excluded fields" section is less relevant (state-writer captures scalar fields only, same as event-logger).

**Read stdin + guard pattern** (lines 49–59):
```bash
set -u
LOG_DIR="$HOME/.claude"
payload=$(cat)
if [ -z "$payload" ]; then
  exit 0
fi
```
State-writer additionally must guard on empty `session_id` and empty `hook_event_name` before proceeding (see Code Examples in RESEARCH.md — same shape, two more early-exit guards).

**jq-only parsing, never string-interpolate payload into shell** (lines 61–103): build the entire output object in one `jq -c` pipeline reading `<<<"$payload"`, check `$? -ne 0` then `exit 0`, check `[ -z "$line" ]` then `exit 0`. State-writer's payload→state derivation (event-to-state mapping, background_tasks running-only filter) belongs inside this same jq pipeline or a preceding `jq -r` extraction, never a bash string manipulation of payload content.

**Atomic overwrite — NEW pattern not present in event-logger.sh** (event-logger.sh only appends, lines 114–144 show the append+flock+size-guard pattern which does NOT apply directly). State-writer instead needs the tmp+rename pattern from RESEARCH.md Pattern 2:
```bash
state_dir="$HOME/.claude/monitor-state"
mkdir -p "$state_dir"
tmp="$state_dir/$sid.json.tmp.$$"
printf '%s\n' "$line" > "$tmp" && mv -f "$tmp" "$state_dir/$sid.json"
exit 0
```
Same-directory tmp file is mandatory (cross-filesystem `mv` degrades to copy+delete on the 9p mount, losing atomicity).

**Always exit 0, never emit decision-control stdout** — copy verbatim discipline from event-logger.sh: every branch (`[ -z "$payload" ] && exit 0`, jq failure, empty line) ends in `exit 0`, and the script never writes anything to stdout except via the log/state write itself. This matters MORE for state-writer.sh than event-logger.sh because state-writer is registered on `PermissionRequest`/`PostToolBatch`/`Stop`/`SubagentStop` — blocking-capable events (RESEARCH.md Pitfall 7).

---

### `hooks/state-writer-events.json` (config, static data)

**Analog:** `hooks/hook-events.json` (referenced by `install.sh` as `EVENTS_FILE`, a flat JSON array of event-name strings). Create a sibling file with the D-08 verdict event set: `SessionStart`, `UserPromptSubmit`, `PreToolUse` (if needed, see RESEARCH Open Question 3), `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `Notification` (optional/secondary), `Stop`, `SubagentStop`, `SessionEnd`. Keep it a separate file from `hook-events.json` per RESEARCH's "Recommended Project Structure" — the two scripts' registration lists may diverge over time.

---

### `hooks/install.sh` (modified — installer/config merge)

**Analog:** itself — extend the existing pattern rather than inventing one.

**Install step pattern** (lines 63–69):
```bash
mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/auq-locks" "$CLAUDE_DIR/working-locks"
install -m 0755 "$HERE/auq-lock.sh" "$CLAUDE_DIR/hooks/auq-lock.sh"
echo "installed: $CLAUDE_DIR/hooks/auq-lock.sh"
```
Add a `mkdir -p "$CLAUDE_DIR/monitor-state"` alongside the existing lock-dir creation, and an `install -m 0755 ... state-writer.sh` line following the same shape.

**Registration-loop pattern for a multi-event script** (lines 96–108, the `event-logger.sh` registration pass):
```bash
jq --argjson events "$(cat "$EVENTS_FILE")" --arg cmd "$LOGGER_CMD" '
  def has_logger: [.hooks[]?.command] | any(. // "" | test("event-logger\\.sh"));
  reduce $events[] as $event (.;
    .hooks[$event] = ((.hooks[$event] // []) | map(select(has_logger | not))) + [{"hooks": [{"type": "command", "command": $cmd, "timeout": 2}]}]
  )
' "$SETTINGS" > "$SETTINGS.tmp"
python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
mv "$SETTINGS.tmp" "$SETTINGS"
```
This is the exact pattern to duplicate for `state-writer.sh`'s registration against `state-writer-events.json` — same idempotent dedup-by-`test("state-writer\\.sh")`, same `python3 -c` JSON-validate-before-swap safety check, same `SETTINGS.tmp` → `mv` atomic settings update. Keep it a separate jq pass (own variable names `STATE_WRITER_CMD`, `STATE_WRITER_EVENTS_FILE`) so it doesn't interfere with the existing lock-merge pass (lines 81–93) or the logger pass, per the file's own stated convention ("Kept as a separate jq pass ... so the lock merge's behavior stays byte-for-byte what it was before").

**Backup-before-mutate pattern** (line 75, and line 52 for `--remove-logger`): `cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"` before any mutation of an existing settings.json — apply this before the new state-writer registration pass too (or rely on the single earlier backup already taken in the same invocation — check whether one backup per install.sh run is sufficient or whether each pass needs its own).

**Optional teardown flag** — if a `--remove-state-writer` flag is wanted (mirrors `--remove-logger`, lines 42–61), copy that block's shape: `cp` backup, jq `has_x`/`select(has_x | not)` filter, `python3 -c` validate, `mv`.

---

### `monitor.py::scan_state_files()` (service, CRUD read + derive)

**Analog:** `monitor.py::scan()` (lines 422–555, read in full)

**Function signature & directory-listing pattern** (lines 422–447):
```python
def scan(label_map: dict[str, str] | None = None,
         sessionid_to_label: dict[str, str] | None = None) -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    now = time.time()
    sessions = []
    candidates: list[tuple[Path, Path, float]] = []
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        try:
            for f in proj_dir.glob("*.jsonl"):
                ...
        except OSError:
            continue
```
`scan_state_files()` should mirror this shape exactly, but iterate `STATE_DIR.glob("*.json")` (flat directory, no per-project subdirs) instead of `PROJECTS_DIR.iterdir()` + nested glob — `monitor-state/` is one JSON file per session_id, not per project dir.

**Same-signature convention** — take `label_map`/`sessionid_to_label` as the same two optional dict params `scan()` takes, so the labeling logic threaded through `project_name()` can be reused/shared without duplicating the cwd→label resolution (D-05 requires reproducing today's labels exactly).

**Per-session dot/color/verdict derivation loop shape** (lines 447–520+, the body of the `for proj_dir, latest, latest_mtime in candidates:` loop) — `scan_state_files()`'s per-file loop should produce a `sessions`-shaped dict with the same keys (`key`, `dot`, `dot_color`, `name`, `age`, `bg`, `monitors`, `action`, ...) so the divergence comparator can pair legacy and shadow entries by `key`/`session_id` — see `_make_session_row()`/`_make_compact_chip()` (lines 1537, 1575) for exactly which keys the row-rendering path expects, since the shadow struct should structurally match even though it's never rendered (Pitfall 3 in RESEARCH.md: keep it a lookalike but never feed it into rendering).

**Staleness/lock check pattern to imitate for heartbeat-silence + docker cross-check** (lines 483–520, the `auq_locked`/`working_locked` mtime-based checks):
```python
if session_id:
    try:
        lock_mtime = (AUQ_LOCK_DIR / session_id).stat().st_mtime
        auq_locked = (now - lock_mtime) < AUQ_LOCK_MAX_AGE_SEC
        if auq_locked and latest_mtime > lock_mtime + 5:
            auq_locked = False
    except OSError:
        pass
```
Same defensive `try/except OSError: pass` shape applies to `scan_state_files()`'s heartbeat-silence check (`ts_ms` vs `now`) and to the `docker inspect --format '{{.State.Status}}'` cross-check (extend `scan_containers()`, lines 556–636, rather than adding a second subprocess call — that function already does one `docker inspect` per tick; add the format field there per RESEARCH's Don't Hand-Roll table).

---

### `monitor.py::_read_state_file()` (utility, defensive file-I/O)

**Analog:** `monitor.py::tail_last_line()` (lines 210–233)

**Defensive read pattern** (lines 210–233):
```python
def tail_last_line(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            ...
    except OSError:
        return None
```
`_read_state_file()` follows the identical shape but reads the whole small JSON file and additionally must catch `json.JSONDecodeError` (see RESEARCH.md Code Example, which is itself a paraphrase of this exact codebase idiom):
```python
def _read_state_file(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj
```
This matches `parse_last_action()`/`user_tail_kind()`'s `try: json.loads(...) except (json.JSONDecodeError, ValueError): return ""` idiom (lines 260–266, 300–314) too — the whole file establishes "never let a malformed record raise; degrade to a safe default" as house style.

---

### `monitor.py` shadow-tick + divergence logging (in `refresh()`)

**Analog:** `monitor.py::refresh()` (lines 1358–1491) + `_check_transitions()` (line 1066, referenced from `refresh()` at line 1396)

**Where to hook in** (lines 1374–1396):
```python
containers = self._cached_containers
try:
    sessions = scan(self._cached_label_map, self._sessionid_to_label)
except Exception:
    sessions = []
...
self._check_transitions(sessions)
```
Insert the shadow computation + comparison immediately after `sessions = scan(...)` succeeds, wrapped in the same defensive `try/except Exception: shadow_sessions = []` shape (this codebase always wraps a scan call so one exception can't crash the whole tick loop) — then call a new `self._log_divergences(sessions, shadow_sessions)` as a pure side effect, BEFORE `self._check_transitions(sessions)` (which must keep receiving only the legacy `sessions` list — Pitfall 3).

**CLI flag convention** — this codebase does NOT use `argparse`; flags are checked directly via `"--test-notify" in sys.argv` (lines 1198, 1228, 1646). Add `"--state-files" in sys.argv` the same way, read once (e.g. in `MonitorApp.__init__` or as a module-level constant computed at import time), stored as `self.shadow_enabled` / `self.state_files_mode` boolean(s) — do not introduce `argparse` as a new pattern.

---

### `test_state_writer.py` (test, subprocess/integration)

**Analog:** `test_event_logger.py` (545 lines)

**HOME-pinned subprocess harness pattern** (lines 1–75, esp. `_env()` at line 49 and `_run_logger()` at line 67):
```python
def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env

def _run_logger(payload: str, home: Path, raw: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HOOKS_DIR / "event-logger.sh")],
        input=payload, capture_output=True, text=True, env=_env(home), timeout=5,
    )
```
Write a `_run_state_writer(payload, home)` helper following this exact shape, and a `_HomeTestCase(unittest.TestCase)` base class (line 136) that gives each test a fresh `TemporaryDirectory` HOME — never the real `$HOME`.

**Goal-numbered test class organization** (lines 151, 227, 303, 329, 398, 455, 493, 516 — `Goal1_LogLineShape`, `Goal2_SecretExclusionAndRawOptIn`, `Goal3_NeverBreakTheSession`, `Goal4_AppendAndSizeGuard`, `Goal5_InstallRegistrationAndIdempotency`, `Goal6_PreservationOfLocksAndUnrelatedSettings`, `Goal7_RemovalPath`) — this repo's test-file convention names test classes after acceptance goals, not implementation units. For `test_state_writer.py`, mirror this with goals like `Goal1_StateFileShape`, `Goal2_AtomicWriteUnderKill` (TEST-MATRIX case 20 / A3 spot-check), `Goal3_NeverBlockTheSession` (exit-0 discipline, Pitfall 7), `Goal4_BackgroundTasksRunningOnlyFilter` (Pitfall 2), `Goal5_InstallRegistrationAndIdempotency` (reuse Goal5's exact install.sh-testing shape from event-logger's suite), `Goal6_SessionEndRemovesFile` (orphan pruning, Pitfall 10).

---

### `test_monitor.py` new test classes for `scan_state_files()`

**Analog:** `test_monitor.py`'s existing test classes covering `scan()` (grep the file for the class organizing `scan()`'s tests — same file, same convention: build a temp `PROJECTS_DIR`-equivalent fixture, write jsonl fixtures, call `scan()`, assert on returned dicts). Mirror this exactly but build a temp `monitor-state/` fixture with hand-written JSON files (including deliberately corrupt/partial ones for ENG-04 coverage) instead of jsonl.

---

## Shared Patterns

### Hook script discipline (applies to `state-writer.sh`)
**Source:** `hooks/event-logger.sh` lines 49–113, `hooks/working-lock.sh` lines 23–33, `hooks/auq-lock.sh` lines 16–26
**Apply to:** `hooks/state-writer.sh`
- `set -u` (event-logger.sh) or `set -eu` (the lock scripts) at top.
- Read stdin once via `payload=$(cat)`, guard `[ -z "$payload" ] && exit 0`.
- Parse exclusively through `jq`; never interpolate a payload field into a shell command string (security — RESEARCH.md Known Threat Patterns).
- Every code path ends in `exit 0` — no exceptions, especially on hooks that support decision-control (`PermissionRequest`, `PostToolBatch`, `Stop`, `SubagentStop`).
```bash
sid=$(cat | jq -r '.session_id // empty' 2>/dev/null || true)
[ -z "$sid" ] && exit 0
```
(from `working-lock.sh`/`auq-lock.sh`, lines 25/18 — the minimal-guard idiom for scripts that need just the session_id.)

### Idempotent install.sh merge/registration
**Source:** `hooks/install.sh` lines 81–108
**Apply to:** the `install.sh` modification for `state-writer.sh` registration
- Dedup existing entries by `test("<script-name>\\.sh")` before appending fresh ones from the canonical list — never straight-append (would duplicate on every re-run).
- Validate the merged JSON with `python3 -c "import json; json.load(open(...))"` before the final `mv` — this is the safety net that stops a malformed jq pipeline from corrupting `settings.json` in place.
- Back up `settings.json` (`cp ... .bak.$(date +%s)`) before any mutation of a pre-existing file.

### Defensive read / degrade-not-crash
**Source:** `monitor.py::tail_last_line()` (lines 210–233), `parse_last_action()` (260–297), `user_tail_kind()` (300–323), `is_certainly_working()` (326–364)
**Apply to:** `_read_state_file()`, `scan_state_files()`, any divergence-comparison code
```python
try:
    obj = json.loads(line)
except (json.JSONDecodeError, ValueError):
    return ""   # or None / False — always a safe, non-crashing default
```
Every parse of untrusted/external data in this codebase degrades to a documented safe default rather than raising — extend this uniformly to state-file JSON reads (ENG-04) and to the divergence log write path.

### `docker inspect` extension over new subprocess calls
**Source:** `monitor.py::scan_containers()` lines 596–601 (existing `docker inspect --format '{{.Config.Labels.project}}\t{{.Config.WorkingDir}}' ...` call)
**Apply to:** ENG-03's paused/exited/running cross-check
Add `{{.State.Status}}` to the existing format string (comment says two fields joined by `\t`; make it three) rather than issuing a second `docker inspect` subprocess call per tick — this codebase already treats `docker` subprocess calls as an expensive, timeout-guarded resource (`timeout=2`, `try/except (OSError, subprocess.TimeoutExpired)` around every one).

## No Analog Found

None — every file in scope has a direct or role-matched analog already in the codebase (this phase is explicitly "assembly and extension, not invention" per RESEARCH.md).

## Metadata

**Analog search scope:** `/workspace/hooks/`, `/workspace/monitor.py`, `/workspace/test_monitor.py`, `/workspace/test_event_logger.py`
**Files scanned:** `hooks/event-logger.sh` (146 lines, full read), `hooks/working-lock.sh` (33 lines, full read), `hooks/auq-lock.sh` (26 lines, full read), `hooks/install.sh` (108 lines, full read), `monitor.py` (1680 lines, targeted reads: 210–520, 556–670, 1358–1537, 1611–1680), `test_event_logger.py` (targeted grep + structural read)
**Pattern extraction date:** 2026-07-29
