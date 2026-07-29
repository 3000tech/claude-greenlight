"""Tests for the Phase 2 state writer (hooks/state-writer.sh) plus its
install.sh registration and the monitor.py shadow-engine seam it feeds
(scan_state_files, diff_verdicts, select_render_sessions).

Organised by user-facing goal, matching test_event_logger.py's convention.
Every hook-script test runs the real script via subprocess with HOME
overridden to a TemporaryDirectory — never the real $HOME, since this suite
runs inside the user's live container and the real ~/.claude is the shared
bind mount driving their production monitor.

Run with:  python3 -m unittest test_state_writer.py
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Stub tkinter so monitor.py can be imported in headless/Linux CI — matches
# test_monitor.py's convention exactly. None of the functions under test
# touch the GUI.
if "tkinter" not in sys.modules:
    import types
    sys.modules["tkinter"] = types.ModuleType("tkinter")

import monitor  # noqa: E402

HOOKS_DIR = HERE / "hooks"
INSTALL_SH = HOOKS_DIR / "install.sh"
STATE_WRITER_SH = HOOKS_DIR / "state-writer.sh"
STATE_WRITER_EVENTS_JSON = HOOKS_DIR / "state-writer-events.json"
SETTINGS_SNIPPET = HOOKS_DIR / "settings-snippet.json"

LOCK_PATTERN = r"working-lock\.sh|auq-lock\.sh"
STATE_WRITER_PATTERN = r"state-writer\.sh"


def setUpModule() -> None:
    # unittest special-cases SkipTest raised from setUpModule (reported as a
    # clean module-level skip, exit 0) — not the same at bare module-import
    # time, so the guard lives here, matching test_event_logger.py.
    if shutil.which("jq") is None:
        raise unittest.SkipTest("jq is required to run hooks/state-writer.sh and is not on PATH")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _base_env(home: Path) -> dict:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env


def _run_state_writer(payload: str, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(STATE_WRITER_SH)],
        input=payload,
        env=_base_env(home),
        capture_output=True,
        text=True,
        timeout=10,
    )


def _run_install(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_SH), *args],
        env=_base_env(home),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _payload(event: str = "Stop", session_id: str = "s1", cwd: str = "/workspace", **extra) -> str:
    obj = {"hook_event_name": event, "session_id": session_id, "cwd": cwd}
    obj.update(extra)
    return json.dumps(obj)


def _state_dir(home: Path) -> Path:
    return home / ".claude" / "monitor-state"


def _settings_path(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _load_settings(home: Path) -> dict:
    return json.loads(_settings_path(home).read_text(encoding="utf-8"))


def _state_writer_events() -> list[str]:
    return json.loads(STATE_WRITER_EVENTS_JSON.read_text(encoding="utf-8"))


def _commands_matching(settings: dict, pattern: str) -> list[str]:
    """Flatten every hook `command` string across all event keys in a
    settings.json-shaped dict, filtered by regex."""
    import re
    out: list[str] = []
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for h in group.get("hooks", []):
                cmd = h.get("command", "")
                if re.search(pattern, cmd):
                    out.append(cmd)
    return out


class _HomeTestCase(unittest.TestCase):
    """A fresh TemporaryDirectory HOME per test, never the real $HOME."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# GOAL 1 — A Stop event becomes a shadow WAITING verdict, end to end
# ---------------------------------------------------------------------------

class Goal1_TracerEndToEnd(_HomeTestCase):
    def test_stop_event_becomes_shadow_waiting_verdict_with_divergence(self):
        sid = "tracer-1"

        # 1. The real hook script writes a complete state file.
        result = _run_state_writer(_payload(event="Stop", session_id=sid, cwd="/workspace"), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

        state_file = _state_dir(self.home) / f"{sid}.json"
        self.assertTrue(state_file.exists())
        obj = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(obj["state"], "waiting")
        for key in ("state", "ts", "ts_ms", "cwd", "hostname", "last_event", "background_tasks_count"):
            self.assertIn(key, obj, f"missing field {key!r} in state file")

        # 2. monitor.scan_state_files() derives a WAITING verdict from it,
        # legacy's exact WAITING colour, without touching any jsonl.
        orig_state_dir = monitor.STATE_DIR
        monitor.STATE_DIR = _state_dir(self.home)
        try:
            shadow = monitor.scan_state_files(sessionid_to_label={sid: "my-label"})
        finally:
            monitor.STATE_DIR = orig_state_dir

        self.assertEqual(len(shadow), 1)
        self.assertEqual(shadow[0]["status"], "WAITING")
        self.assertEqual(shadow[0]["dot_color"], "#4ade80")
        self.assertEqual(shadow[0]["key"], sid)

        # 3. diff_verdicts() emits exactly one record on disagreement.
        legacy_disagreeing = [{
            "key": sid, "session_id": sid, "name": "my-label", "status": "WORKING",
        }]
        records = monitor.diff_verdicts(legacy_disagreeing, shadow, 1785333758.0)
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["legacy_verdict"], "WORKING")
        self.assertEqual(rec["state_file_verdict"], "WAITING")
        self.assertEqual(rec["last_event"], "Stop")
        self.assertEqual(rec["key"], sid)

        # 4. ...and zero records when both sides agree.
        legacy_agreeing = [{
            "key": sid, "session_id": sid, "name": "my-label", "status": "WAITING",
        }]
        self.assertEqual(monitor.diff_verdicts(legacy_agreeing, shadow, 1785333758.0), [])


# ---------------------------------------------------------------------------
# GOAL 2 — Malformed/partial input never blocks the session
# ---------------------------------------------------------------------------

class Goal2_NeverBreakTheSession(_HomeTestCase):
    def _assert_no_state_written(self) -> None:
        state_dir = _state_dir(self.home)
        self.assertFalse(
            state_dir.exists() and any(state_dir.iterdir()),
            "state-writer.sh wrote a file for input it should have rejected",
        )
        # Nothing escaped anywhere under HOME either.
        self.assertEqual([p for p in self.home.rglob("*") if p.is_file()], [])

    def test_empty_stdin_exits_zero_and_writes_nothing(self):
        result = _run_state_writer("", self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self._assert_no_state_written()

    def test_nonjson_stdin_exits_zero_and_writes_nothing(self):
        result = _run_state_writer("not json at all", self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self._assert_no_state_written()

    def test_empty_object_payload_exits_zero_and_writes_nothing(self):
        result = _run_state_writer("{}", self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self._assert_no_state_written()

    def test_missing_session_id_exits_zero_and_writes_nothing(self):
        payload = json.dumps({"hook_event_name": "Stop", "cwd": "/workspace"})
        result = _run_state_writer(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self._assert_no_state_written()

    def test_session_id_with_path_separator_exits_zero_and_writes_nothing(self):
        result = _run_state_writer(_payload(event="Stop", session_id="../evil"), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self._assert_no_state_written()


# ---------------------------------------------------------------------------
# GOAL 3 — install.sh registers state-writer.sh on every event, idempotently
# ---------------------------------------------------------------------------

class Goal3_InstallRegistration(_HomeTestCase):
    def test_fresh_home_registers_one_state_writer_entry_per_event(self):
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)

        settings = _load_settings(self.home)
        events = _state_writer_events()
        cmds = _commands_matching(settings, STATE_WRITER_PATTERN)
        self.assertEqual(len(cmds), len(events))

        self.assertTrue((self.home / ".claude" / "monitor-state").is_dir())

        snippet = json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8"))
        snippet_lock_count = len(_commands_matching(snippet, LOCK_PATTERN))
        merged_lock_count = len(_commands_matching(settings, LOCK_PATTERN))
        self.assertEqual(merged_lock_count, snippet_lock_count)
        self.assertGreater(snippet_lock_count, 0)

    def test_running_install_twice_yields_one_state_writer_entry_per_event(self):
        _run_install(self.home)
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)

        settings = _load_settings(self.home)
        events = _state_writer_events()
        cmds = _commands_matching(settings, STATE_WRITER_PATTERN)
        self.assertEqual(len(cmds), len(events))

        snippet = json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8"))
        snippet_lock_count = len(_commands_matching(snippet, LOCK_PATTERN))
        merged_lock_count = len(_commands_matching(settings, LOCK_PATTERN))
        self.assertEqual(merged_lock_count, snippet_lock_count)


# ---------------------------------------------------------------------------
# GOAL 4 — The atomic write survives a mid-write kill and concurrent writers
# ---------------------------------------------------------------------------

class Goal4_AtomicWriteUnderStress(_HomeTestCase):
    def test_sigkill_during_write_never_corrupts_final_path(self):
        """Direct check of RESEARCH assumption A3 / TEST-MATRIX case 20: a
        writer killed between its temp write and its rename must leave the
        final path either absent or holding a complete, parseable JSON
        document — never zero-byte, never a truncated fragment."""
        state_dir = _state_dir(self.home)
        state_dir.mkdir(parents=True, exist_ok=True)
        sid = "kill-target"
        final = state_dir / f"{sid}.json"
        final.write_text(json.dumps({"state": "waiting", "seed": True}), encoding="utf-8")

        payload = _payload(event="Stop", session_id=sid)
        iterations = 30
        for _ in range(iterations):
            proc = subprocess.Popen(
                ["bash", str(STATE_WRITER_SH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_base_env(self.home),
            )
            proc.stdin.write(payload.encode())
            proc.stdin.close()
            # Vary the kill point across iterations — a few hundred
            # microseconds to a few milliseconds is enough to straddle the
            # jq-build / temp-write / rename sequence on this fast script.
            time.sleep(random.uniform(0, 0.004))
            proc.kill()
            proc.wait(timeout=5)

            if final.exists():
                content = final.read_bytes()
                self.assertGreater(len(content), 0, "final path is zero-byte after a kill")
                obj = json.loads(content.decode("utf-8"))
                self.assertIn("state", obj)

    def test_concurrent_writers_same_session_never_interleave(self):
        state_dir = _state_dir(self.home)
        sid = "concurrent-target"
        n = 5
        payloads = [
            _payload(event="Stop", session_id=sid, cwd=f"/workspace-{i}")
            for i in range(n)
        ]
        procs = []
        for p in payloads:
            proc = subprocess.Popen(
                ["bash", str(STATE_WRITER_SH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=_base_env(self.home),
            )
            proc.stdin.write(p.encode())
            proc.stdin.close()
            procs.append(proc)
        for proc in procs:
            self.assertEqual(proc.wait(timeout=15), 0, proc.stderr.read())
            proc.stderr.close()

        final = state_dir / f"{sid}.json"
        self.assertTrue(final.exists())
        obj = json.loads(final.read_text(encoding="utf-8"))
        self.assertEqual(obj["last_event"], "Stop")
        sent_cwds = {f"/workspace-{i}" for i in range(n)}
        self.assertIn(obj["cwd"], sent_cwds)

        leftover_tmp = list(state_dir.glob(f"{sid}.json.tmp.*"))
        self.assertEqual(leftover_tmp, [], f"leftover temp files: {leftover_tmp}")

    def test_same_cwd_different_session_ids_stay_separate(self):
        """TEST-MATRIX case 15's adjacency problem: two containers mounting
        the same /workspace must not collide in monitor-state/."""
        cwd = "/workspace"
        r1 = _run_state_writer(
            _payload(event="Stop", session_id="sep-a", cwd=cwd,
                     background_tasks=[{"status": "running"}]),
            self.home,
        )
        r2 = _run_state_writer(
            _payload(event="Stop", session_id="sep-b", cwd=cwd,
                     background_tasks=[{"status": "running"}, {"status": "running"}]),
            self.home,
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)

        state_dir = _state_dir(self.home)
        fa = state_dir / "sep-a.json"
        fb = state_dir / "sep-b.json"
        self.assertTrue(fa.exists())
        self.assertTrue(fb.exists())
        obj_a = json.loads(fa.read_text(encoding="utf-8"))
        obj_b = json.loads(fb.read_text(encoding="utf-8"))
        self.assertEqual(obj_a["cwd"], cwd)
        self.assertEqual(obj_b["cwd"], cwd)
        # Deterministic content difference proves these are two independent
        # records, not one file merged/overwritten into the other.
        self.assertEqual(obj_a["background_tasks_count"], 1)
        self.assertEqual(obj_b["background_tasks_count"], 2)

    def test_nonascii_cwd_round_trips_through_json_load(self):
        cwd = "/workspace/café-日本語"
        sid = "nonascii"
        result = _run_state_writer(_payload(event="Stop", session_id=sid, cwd=cwd), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        state_file = _state_dir(self.home) / f"{sid}.json"
        self.assertTrue(state_file.exists())
        obj = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(obj["cwd"], cwd)


# ---------------------------------------------------------------------------
# GOAL 5 — Every in-turn event resolves to the state the live campaign
# prescribes (TEST-MATRIX.md D-08 verdict)
# ---------------------------------------------------------------------------

class Goal5_EventToStateMapping(_HomeTestCase):
    def _write(self, event: str, session_id: str = "s1", **extra) -> dict:
        result = _run_state_writer(_payload(event=event, session_id=session_id, **extra), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        return result

    def _read(self, session_id: str = "s1") -> dict:
        return json.loads((_state_dir(self.home) / f"{session_id}.json").read_text(encoding="utf-8"))

    def test_working_events_produce_last_event_and_working_state(self):
        for event in ("UserPromptSubmit", "PostToolUse", "PostToolUseFailure", "PostToolBatch"):
            with self.subTest(event=event):
                sid = f"working-{event}"
                self._write(event, session_id=sid)
                obj = self._read(sid)
                self.assertEqual(obj["last_event"], event)
                self.assertEqual(obj["state"], "working")

    def test_permission_request_and_notification_produce_needs_input(self):
        for event in ("PermissionRequest", "Notification"):
            with self.subTest(event=event):
                sid = f"needs-input-{event}"
                self._write(event, session_id=sid)
                obj = self._read(sid)
                self.assertEqual(obj["last_event"], event)
                self.assertEqual(obj["state"], "needs_input")

    def test_session_start_with_recognised_and_absent_source_produces_idle(self):
        for source_kwargs in ({"source": "startup"}, {"source": "resume"}, {"source": "clear"}, {}):
            with self.subTest(source=source_kwargs.get("source", "<absent>")):
                sid = f"idle-{source_kwargs.get('source', 'absent')}"
                self._write("SessionStart", session_id=sid, **source_kwargs)
                obj = self._read(sid)
                self.assertEqual(obj["last_event"], "SessionStart")
                self.assertEqual(obj["state"], "idle")

    def test_session_start_compact_on_working_session_leaves_file_byte_identical(self):
        sid = "compact-target"
        self._write("UserPromptSubmit", session_id=sid)
        state_file = _state_dir(self.home) / f"{sid}.json"
        before_bytes = state_file.read_bytes()
        before_mtime = state_file.stat().st_mtime_ns

        self._write("SessionStart", session_id=sid, source="compact")

        after_bytes = state_file.read_bytes()
        after_mtime = state_file.stat().st_mtime_ns
        self.assertEqual(before_bytes, after_bytes)
        self.assertEqual(before_mtime, after_mtime)
        # Confirm the pre-compact write really was `working`, not already `idle`.
        self.assertEqual(json.loads(before_bytes)["state"], "working")

    def test_unregistered_event_name_writes_nothing(self):
        sid = "unregistered-event"
        result = _run_state_writer(_payload(event="SomeFutureEventNameNotInTheMapping", session_id=sid), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((_state_dir(self.home) / f"{sid}.json").exists())


if __name__ == "__main__":
    unittest.main()
