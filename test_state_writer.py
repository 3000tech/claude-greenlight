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
import shutil
import subprocess
import sys
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


if __name__ == "__main__":
    unittest.main()
