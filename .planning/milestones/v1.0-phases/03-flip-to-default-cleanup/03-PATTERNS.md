# Phase 3: Flip to Default & Cleanup - Pattern Map

**Mapped:** 2026-08-06
**Files analyzed:** 6 (all existing, modified-in-place; one deleted)
**Analogs found:** 6 / 6 (this phase is self-referential — every "new" pattern is a variant of code already living in the same files)

## File Classification

This phase is deletion + surgical rewrite in existing files, not new-file creation. There is no external codebase to search for analogs — the analogs are other regions of the *same* files (the surviving hybrid seam, the existing teardown mode, the existing fixture base class). RESEARCH.md already did exhaustive line-level analysis of these files; this map translates that into copy-paste-ready sources for the planner.

| Modified/Deleted File | Role | Data Flow | Closest Analog (same repo) | Match Quality |
|---|---|---|---|---|
| `monitor.py` — `MonitorApp.refresh()` tick loop simplification | controller (event loop) | request-response (poll/tick) | `monitor.py:2102-2131` (its own pre-flip body — trim in place) | exact (self) |
| `monitor.py` — `scan_state_files()` gains D-02a/D-02b fallback logic | service (state derivation) | CRUD (read state, derive verdict) | `monitor.py:666-675` (existing staleness-recovery block) + `monitor.py:1014-1022` (`scan()`'s stale-lock guard) | exact (self) |
| `monitor.py` — deletion of `shell_tracker` call sites, shadow-diff functions, `project_name()` | utility (dead-code removal) | transform | N/A — pure subtraction, no analog needed | n/a |
| `shell_tracker.py` | service | event-driven (jsonl regex scan) | DELETED — no replacement file; logic superseded by `state-writer.sh`'s `background_tasks_count` (already implemented, hook-side) | n/a (deletion) |
| `hooks/install.sh` — new `--remove-auq-lock` mode + default-path stops installing auq-lock | config/installer (idempotent CLI) | file-I/O (settings.json mutation) | `hooks/install.sh:72-86` (`--remove-state-writer` block) and `:60-69` (`--remove-event-logger`... wait see excerpt below) | exact |
| `test_monitor.py` — Goal6d rewrite on state-file fixtures; Goal2h/2i/14/15/16 deletion | test | CRUD (fixture-driven assertions) | `test_monitor.py:1323-1354` (`StateFileTestBase` + `_write_state`) and its sibling classes `Goal9_StateFileVerdicts`/`Goal10_StateFileRobustness` (1357-1447) | exact |
| `README.md` — Setup step 4 rewrite (hooks as primary) | docs | n/a | Existing README setup section (read at plan time) — no code excerpt needed | n/a |

## Pattern Assignments

### `monitor.py` — tick-loop simplification (controller, request-response)

**Analog:** its own current body, `MonitorApp.refresh()`

**Current shape to trim** (monitor.py:2102-2131, quoted in RESEARCH.md):
```python
sessions = scan(self._cached_label_map, self._sessionid_to_label,
                 container_info=self._cached_container_info,
                 hostname_to_name=self._cached_hostname_to_name)
...
shadow_sessions = scan_state_files(
    self._cached_label_map, self._sessionid_to_label,
    container_info=self._cached_container_info,
    legacy_sessions=sessions,
)
# diff_verdicts(...) / filter_divergence_events(...) / write_divergences(...) — DELETE these calls
render_sessions = select_render_sessions(sessions, shadow_sessions, self.state_files_mode)
```

**Target shape:** keep the two-call structure (`scan()` then `scan_state_files(..., legacy_sessions=sessions)`) — RESEARCH.md Pattern 1 explicitly recommends NOT collapsing this to one call, because `scan()`'s output still feeds three things (bridge entries, jsonl-advance signal, working-lock pin evidence). Delete only the diff/filter/write calls in between. Rename `shadow_sessions` → `render_sessions` (or similar) since it's no longer "shadow," it's primary.

---

### `monitor.py` — `scan_state_files()` staleness-recovery extension (service, CRUD)

**Analog A — the block to extend** (monitor.py:666-675):
```python
if status == "WORKING":
    window = (STATE_PROMPT_STALE_SEC if last_event == "UserPromptSubmit"
              else STATE_HEARTBEAT_STALE_SEC)
    if age > window:
        container_status = None
        if container_info and hostname:
            container_status = container_info.get(
                "hostname_to_status", {}).get(hostname)
        if container_status != "paused":
            status, dot, color, rank = "WAITING", "●", "#4ade80", 1
```

**Analog B — the stale-lock guard primitive to reuse for D-02a/D-02b** (monitor.py:1014-1022, inside `scan()`):
```python
working_locked = False
if session_id:
    try:
        wlock_mtime = (WORKING_LOCK_DIR / session_id).stat().st_mtime
        working_locked = (now - wlock_mtime) < WORKING_LOCK_MAX_AGE_SEC
        if working_locked and latest_mtime > wlock_mtime + 5:
            working_locked = False
    except OSError:
        pass
```

**Copy-from guidance:** Do not write a new jsonl reader. Look up the matching `legacy_sessions` entry by `session_id`/`key` inside the staleness block above and read its already-computed `working_locked` field: `working_locked is False` → early WAITING recovery (D-02a, Esc-interrupt); a fresh `~/.claude/working-locks/<sid>` file within `WORKING_LOCK_MAX_AGE_SEC` (3600s) → suppress the WAITING transition even past `age > window` (D-02b pin), alongside the existing `container_status != "paused"` exception. See RESEARCH.md Pattern 2 and Pitfall 2 for the full reasoning and the D-02b/D-03 tension to flag.

---

### `monitor.py` — the surviving hybrid bridge, unchanged (service, CRUD)

**Analog:** `scan_state_files()`'s internal legacy-merge tail, monitor.py (read this session, immediately following the per-file loop):
```python
if legacy_sessions is None:
    legacy_sessions = scan(label_map, sessionid_to_label, container_info=container_info)
seen_keys = {s["key"] for s in sessions}
for legacy in legacy_sessions:
    if legacy["key"] in seen_keys:
        continue
    carried = dict(legacy)
    carried["legacy_origin"] = True
    sessions.append(carried)
```
This IS the D-02c bridge. It needs no new code — just confirm it survives byte-for-byte and that D-06's tombstone/ghost-suppression mechanism (Claude's discretion) hooks in here (e.g., checking a SessionEnd marker before carrying a `legacy_origin` entry through).

---

### `hooks/install.sh` — new `--remove-auq-lock` teardown mode (config, file-I/O)

**Analog:** the existing `--remove-state-writer` mode, hooks/install.sh:72-86 (verbatim):
```bash
if [ "$mode" = "--remove-state-writer" ]; then
  if [ ! -f "$SETTINGS" ]; then
    echo "nothing to do: $SETTINGS does not exist"
    exit 0
  fi
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  jq '
    def has_state_writer: [.hooks[]?.command] | any(. // "" | test("state-writer\\.sh"));
    .hooks = ((.hooks // {}) | with_entries(.value |= map(select(has_state_writer | not))))
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "removed: state-writer.sh entries from $SETTINGS (backup at $SETTINGS.bak.*)"
  exit 0
fi
```
A near-identical `--remove-event-logger` mode exists immediately above it (lines ~60-69) using `has_logger` / `event-logger\\.sh` — second confirming instance of the exact same idiom, in case the planner wants two independent references.

**Clone shape for `--remove-auq-lock`:** same skeleton, swap the regex to `test("auq-lock\\.sh")`, same backup-then-atomic-jq-then-validate-then-mv sequence.

**Default-install-path change (D-04, "stops installing auq-lock by default"):** currently the default path unconditionally does:
```bash
install -m 0755 "$HERE/auq-lock.sh" "$CLAUDE_DIR/hooks/auq-lock.sh"
echo "installed: $CLAUDE_DIR/hooks/auq-lock.sh"
```
and the settings-merge jq block registers it via `drop_auq` / `$snip[0].hooks...` entries for `Notification` and `Stop` (hooks/install.sh, the `jq --slurpfile snip` block, ~lines 96-108). Both need to be removed/gated per D-04 + Pitfall 3 (ship both the default-path removal AND the `--remove-auq-lock` teardown mode in the same phase, per RESEARCH.md's explicit recommendation).

---

### `test_monitor.py` — Goal6d rewrite / new state-file fixture tests (test, CRUD)

**Analog:** `StateFileTestBase` + `_write_state`, test_monitor.py:1323-1354 (verbatim):
```python
class StateFileTestBase(unittest.TestCase):
    """Wire a temp STATE_DIR into the monitor module for each test."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_state_dir = monitor.STATE_DIR
        monitor.STATE_DIR = self.root

    def tearDown(self) -> None:
        monitor.STATE_DIR = self._orig_state_dir
        self._tmp.cleanup()

    def _write_state(self, session_id: str, mtime: float | None = None,
                      omit: tuple[str, ...] = (), **fields) -> Path:
        record = {
            "state": "waiting",
            "ts": "2026-07-29T00:00:00Z",
            "ts_ms": int(time.time() * 1000),
            "cwd": "/workspace",
            "hostname": "container-1",
            "last_event": "Stop",
            "background_tasks_count": 0,
        }
        record.update(fields)
        for key in omit:
            record.pop(key, None)
        f = self.root / f"{session_id}.json"
        f.write_text(json.dumps(record), encoding="utf-8")
        if mtime is not None:
            os.utime(f, (mtime, mtime))
        return f
```

**Sibling test-class style to imitate** (test_monitor.py:1357-1391, `Goal9_StateFileVerdicts`):
```python
class Goal9_StateFileVerdicts(StateFileTestBase):

    def test_working_state_maps_to_working(self):
        self._write_state("a", state="working")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual((s["status"], s["dot_color"], s["rank"]), ("WORKING", "#666", 2))
```

**Copy-from guidance for the Goal6d rewrite (D-07):** per RESEARCH.md Pitfall 7, do NOT duplicate all of Goal6d — only port the one confirmed-missing case, `test_sessionid_rotation_keeps_same_alias_key` (test_monitor.py:1087-1101, legacy/jsonl version), onto `StateFileTestBase`: write two `_write_state(...)` records with *different* `session_id`s but the *same* `hostname`, assert both resolve to the same `alias_key` (`host:<hostname>`) via `scan_state_files()`. `Goal6e_AliasKeyParityAcrossEngines` (test_monitor.py:1672-1756) already covers the rest of the ground and should be read alongside to avoid re-deriving assertions it already makes.

**Deletion-adjacent coverage gap to close (Pitfall 6):** before deleting `Goal2h_BgShellBadgeOnly`/`Goal2i_ManualBgShellDetected` (shell_tracker-dependent), confirm or add a `StateFileTestBase` case asserting `background_tasks_count > 0` at `Stop` → badge on / status stays WORKING, and `== 0` → WAITING / badge off, exercised through `scan_state_files()` (not just `state-writer.sh`'s own `test_state_writer.py:Goal6_TurnEndSemantics`, lines 480-503, which already covers the hook-writer layer but not necessarily the monitor-side read/render layer).

---

## Shared Patterns

### Idempotent settings.json teardown (install.sh)
**Source:** `hooks/install.sh:72-86` (`--remove-state-writer`) and the sibling `--remove-event-logger` block immediately above it.
**Apply to:** the new `--remove-auq-lock` mode.
**Shape:** backup (`cp ... .bak.$(date +%s)`) → jq filter removing entries whose `.command` matches the target script regex → `python3 -c "import json; json.load(...)"` validation → atomic `mv`. Every teardown mode in this file follows this exact four-step sequence; do not invent a new one.

### Temp-STATE_DIR test fixture wiring
**Source:** `test_monitor.py:1323-1334` (`StateFileTestBase.setUp`/`tearDown`) — identical wiring pattern also appears in `test_state_writer.py`'s `_HomeTestCase` (lines 127-165, using `monitor.STATE_DIR = _state_dir(self.home)`).
**Apply to:** all FLIP-02 test rewrites that need to feed `scan_state_files()` fixture data instead of jsonl.

### The hybrid seam itself (do-not-touch pattern)
**Source:** `scan_state_files()`'s `if legacy_sessions is None: legacy_sessions = scan(...)` + legacy-merge loop (see excerpt above, monitor.py ~701-712).
**Apply to:** any file/task touching D-02a/b/c — this is the one piece of "legacy" code that must NOT be deleted; RESEARCH.md Pitfall 1 is the canonical warning against treating `scan()` as a delete-target.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| D-02a/D-02b new fallback logic (jsonl-advance early recovery, working-lock pin) | service, CRUD | Genuinely new ~20-line logic, not a pure copy — but built entirely from two existing fields (`working_locked`, `mtime`) already computed by `scan()`; treat Pattern 2 above (monitor.py:1014-1022 + 666-675) as the closest thing to an analog, per RESEARCH.md's explicit "Don't Hand-Roll" guidance (a new jsonl tail reader would be the wrong move). |
| `docs/TEST-MATRIX.md` promotion (D-10, FLIP-03) | docs | No existing `docs/*.md` convention in this repo (`docs/` currently holds only image assets: `demo.gif`, `standard-mode.png`, `compact-mode.png` — confirmed via `ls`). No analog; RESEARCH.md recommends a single new `docs/TEST-MATRIX.md` + a short README pointer. |

## Metadata

**Analog search scope:** `monitor.py`, `test_monitor.py`, `test_state_writer.py`, `hooks/install.sh` — all read in full or via targeted `sed`/`grep` this session; cross-referenced against RESEARCH.md's exhaustive line-level citations (already HIGH confidence, independently verified this session at the specific ranges quoted above).
**Files scanned:** 4 source files directly re-verified (monitor.py:560-720, hooks/install.sh:60-130, test_monitor.py:1323-1453, test_state_writer.py:1-60) + full RESEARCH.md/CONTEXT.md cross-check.
**Pattern extraction date:** 2026-08-06
</content>
