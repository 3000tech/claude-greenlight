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
HOOK_EVENTS_JSON = HOOKS_DIR / "hook-events.json"
WORKING_LOCK_SH = HOOKS_DIR / "working-lock.sh"

LOCK_PATTERN = r"working-lock\.sh"
STATE_WRITER_PATTERN = r"state-writer\.sh"
EVENT_LOGGER_PATTERN = r"event-logger\.sh"
AUQ_LOCK_PATTERN = r"auq-lock\.sh"


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


def _run_working_lock(mode: str, payload: str, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(WORKING_LOCK_SH), mode],
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
    def test_stop_event_becomes_rendered_waiting_verdict(self):
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
        # legacy's exact WAITING colour, without touching any jsonl — and
        # that verdict is what select_render_sessions() renders (D-01/D-08:
        # the state-file engine is the one rendered source; there is no
        # second engine left to disagree with it).
        orig_state_dir = monitor.STATE_DIR
        monitor.STATE_DIR = _state_dir(self.home)
        try:
            rendered = monitor.scan_state_files(sessionid_to_label={sid: "my-label"})
        finally:
            monitor.STATE_DIR = orig_state_dir

        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["status"], "WAITING")
        self.assertEqual(rendered[0]["dot_color"], "#4ade80")
        self.assertEqual(rendered[0]["key"], sid)
        self.assertIs(monitor.select_render_sessions(rendered), rendered)


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


# ---------------------------------------------------------------------------
# GOAL 6 — Turn end respects in-flight background work, subagents cannot
# move the verdict, and session teardown prunes its own state file
# ---------------------------------------------------------------------------

class Goal6_TurnEndSemantics(_HomeTestCase):
    def _stop(self, session_id: str, background_tasks=None) -> subprocess.CompletedProcess:
        kwargs = {} if background_tasks is None else {"background_tasks": background_tasks}
        return _run_state_writer(_payload(event="Stop", session_id=session_id, **kwargs), self.home)

    def _read(self, session_id: str) -> dict:
        return json.loads((_state_dir(self.home) / f"{session_id}.json").read_text(encoding="utf-8"))

    def test_stop_with_empty_or_absent_background_tasks_produces_waiting(self):
        for sid, bg in (("no-key", None), ("empty-array", [])):
            with self.subTest(sid=sid):
                result = self._stop(sid, background_tasks=bg)
                self.assertEqual(result.returncode, 0, result.stderr)
                obj = self._read(sid)
                self.assertEqual(obj["state"], "waiting")
                self.assertEqual(obj["background_tasks_count"], 0)

    def test_stop_with_one_running_entry_produces_waiting_and_count_one(self):
        """D-03/TEST-MATRIX case 17 rev.2: turn-end is badge-only — a
        still-running background task no longer holds the verdict at
        working, it only rides along in background_tasks_count."""
        sid = "one-running"
        result = self._stop(sid, background_tasks=[{"status": "running"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = self._read(sid)
        self.assertEqual(obj["state"], "waiting")
        self.assertEqual(obj["background_tasks_count"], 1)

    def test_stop_with_only_completed_and_failed_entries_produces_waiting_and_count_zero(self):
        sid = "completed-and-failed"
        result = self._stop(sid, background_tasks=[{"status": "completed"}, {"status": "failed"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = self._read(sid)
        self.assertEqual(obj["state"], "waiting")
        self.assertEqual(obj["background_tasks_count"], 0)

    def test_stop_with_running_completed_and_failed_entries_produces_waiting_and_count_one(self):
        """Plan 03-03 Task 1 Test 3: three tasks, one running, one
        completed, one failed — verdict is waiting (badge-only), and the
        deny-list count rule (unchanged) still counts only the running one."""
        sid = "mixed-three"
        result = self._stop(sid, background_tasks=[
            {"status": "running"}, {"status": "completed"}, {"status": "failed"},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = self._read(sid)
        self.assertEqual(obj["state"], "waiting")
        self.assertEqual(obj["background_tasks_count"], 1)

    def test_stop_with_entry_missing_status_key_produces_waiting_and_count_one(self):
        sid = "missing-status"
        result = self._stop(sid, background_tasks=[{"id": "task-1"}])
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = self._read(sid)
        self.assertEqual(obj["state"], "waiting")
        self.assertEqual(obj["background_tasks_count"], 1)

    def test_stop_never_produces_working_regardless_of_background_task_count(self):
        """D-03: no Stop payload, for any background-task count, ever
        produces a working verdict — parameterised over 0, 1 and 5."""
        cases = {
            "count-zero": [],
            "count-one": [{"status": "running"}],
            "count-five": [{"status": "running"} for _ in range(5)],
        }
        for sid, bg in cases.items():
            with self.subTest(sid=sid):
                result = self._stop(sid, background_tasks=bg)
                self.assertEqual(result.returncode, 0, result.stderr)
                obj = self._read(sid)
                self.assertEqual(obj["state"], "waiting")
                self.assertNotEqual(obj["state"], "working")

    def test_subagent_stop_leaves_existing_state_file_byte_identical(self):
        sid = "subagent-target"
        self._stop(sid, background_tasks=[])
        state_file = _state_dir(self.home) / f"{sid}.json"
        before = state_file.read_bytes()
        self.assertEqual(json.loads(before)["state"], "waiting")

        result = _run_state_writer(_payload(event="SubagentStop", session_id=sid), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        after = state_file.read_bytes()
        self.assertEqual(before, after)

    def test_session_end_removes_file_for_every_reason_value(self):
        for reason in ("prompt_input_exit", "resume", "clear"):
            with self.subTest(reason=reason):
                sid = f"end-{reason}"
                self._stop(sid, background_tasks=[])
                state_file = _state_dir(self.home) / f"{sid}.json"
                self.assertTrue(state_file.exists())

                result = _run_state_writer(
                    _payload(event="SessionEnd", session_id=sid, reason=reason), self.home,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(state_file.exists())

    def test_session_end_for_absent_file_exits_zero_without_error(self):
        result = _run_state_writer(
            _payload(event="SessionEnd", session_id="never-existed", reason="prompt_input_exit"), self.home,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_session_end_removes_state_file_and_leaves_a_tombstone(self):
        """Task 3 Test 1 (D-06): SessionEnd removes the state file AND
        leaves a zero-byte tombstone marker named for the same session id."""
        sid = "abc123"
        self._stop(sid, background_tasks=[])
        state_file = _state_dir(self.home) / f"{sid}.json"
        self.assertTrue(state_file.exists())

        result = _run_state_writer(
            _payload(event="SessionEnd", session_id=sid, reason="prompt_input_exit"), self.home,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(state_file.exists())

        state_dir = _state_dir(self.home)
        tombstones = [p for p in state_dir.iterdir() if p.name.startswith(sid)]
        self.assertEqual(len(tombstones), 1, tombstones)
        self.assertEqual(tombstones[0].name, f"{sid}.ended")
        self.assertEqual(tombstones[0].stat().st_size, 0)

    def test_session_end_with_path_traversal_session_id_writes_nothing(self):
        """Task 3 Test 2: a session_id carrying a path separator or a
        dot-dot segment must produce neither a state file, nor a tombstone,
        nor any write outside the state directory — the tombstone write
        sits after the same allowlist guard as the state-file path."""
        result = _run_state_writer(
            _payload(event="SessionEnd", session_id="../evil", reason="prompt_input_exit"), self.home,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        state_dir = _state_dir(self.home)
        self.assertFalse(
            state_dir.exists() and any(state_dir.iterdir()),
            "SessionEnd wrote a file for a path-traversal session_id",
        )
        self.assertEqual([p for p in self.home.rglob("*") if p.is_file()], [])

    def test_background_task_descriptive_text_never_appears_in_state_file(self):
        sid = "no-leak"
        secret_marker = "SUPER-SECRET-COMMAND-rm-dash-rf-slash"
        result = self._stop(sid, background_tasks=[
            {"status": "running", "id": "bg-42", "command": secret_marker, "description": secret_marker},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        state_file = _state_dir(self.home) / f"{sid}.json"
        raw = state_file.read_text(encoding="utf-8")
        self.assertNotIn(secret_marker, raw)
        self.assertNotIn("bg-42", raw)
        obj = json.loads(raw)
        self.assertEqual(obj["background_tasks_count"], 1)

    def test_all_subagent_in_flight_tasks_reach_monitor_as_working_grey(self):
        """Rev.3 (case 17): a Stop whose in-flight background tasks are ALL
        of type "subagent" resolves to working, and that verdict renders
        through the real monitor.scan_state_files() as WORKING/#666/rank 2
        with action "turn end" — the tracer proving the rule end to end.
        Descriptor values (agent_type) are inspected but never captured."""
        sid = "agent-only"
        result = self._stop(sid, background_tasks=[
            {"status": "running", "type": "subagent", "agent_type": "gsd-executor"},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

        state_file = _state_dir(self.home) / f"{sid}.json"
        raw = state_file.read_text(encoding="utf-8")
        self.assertNotIn("gsd-executor", raw)
        self.assertNotIn("subagent", raw)

        obj = json.loads(raw)
        self.assertEqual(obj["state"], "working")
        self.assertEqual(obj["background_tasks_count"], 1)
        self.assertEqual(
            sorted(obj.keys()),
            ["background_tasks_count", "cwd", "hostname", "last_event", "state", "ts", "ts_ms"],
        )

        orig_state_dir = monitor.STATE_DIR
        monitor.STATE_DIR = _state_dir(self.home)
        try:
            rendered = monitor.scan_state_files(sessionid_to_label={sid: "my-label"})
        finally:
            monitor.STATE_DIR = orig_state_dir

        self.assertEqual(len(rendered), 1)
        self.assertEqual(rendered[0]["status"], "WORKING")
        self.assertEqual(rendered[0]["dot_color"], "#666")
        self.assertEqual(rendered[0]["rank"], 2)
        self.assertEqual(rendered[0]["action"], "turn end")


# ---------------------------------------------------------------------------
# GOAL 7 — The state writer is fully removable in one command (SW-03)
# ---------------------------------------------------------------------------

class Goal7_RemovalPath(_HomeTestCase):
    def setUp(self) -> None:
        super().setUp()
        _run_install(self.home)
        self.snippet_lock_count = len(_commands_matching(
            json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8")), LOCK_PATTERN,
        ))
        self.hook_events_count = len(json.loads(HOOK_EVENTS_JSON.read_text(encoding="utf-8")))
        settings = _load_settings(self.home)
        self.assertGreater(len(_commands_matching(settings, STATE_WRITER_PATTERN)), 0)

    def test_remove_state_writer_strips_all_state_writer_entries(self):
        result = _run_install(self.home, "--remove-state-writer")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(len(_commands_matching(settings, STATE_WRITER_PATTERN)), 0)

    def test_remove_state_writer_preserves_lock_and_event_logger_entries(self):
        result = _run_install(self.home, "--remove-state-writer")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(len(_commands_matching(settings, LOCK_PATTERN)), self.snippet_lock_count)
        self.assertEqual(len(_commands_matching(settings, EVENT_LOGGER_PATTERN)), self.hook_events_count)

    def test_remove_state_writer_on_empty_object_settings_exits_zero(self):
        _settings_path(self.home).write_text("{}", encoding="utf-8")
        result = _run_install(self.home, "--remove-state-writer")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(_commands_matching(settings, STATE_WRITER_PATTERN), [])

    def test_remove_state_writer_preserves_unrelated_top_level_key_and_hook_entry(self):
        settings = _load_settings(self.home)
        settings["someUnrelatedTopLevelKey"] = {"nested": True}
        settings.setdefault("hooks", {}).setdefault("SessionStart", []).append(
            {"hooks": [{"type": "command", "command": "bash /opt/other-tool.sh", "timeout": 2}]}
        )
        _settings_path(self.home).write_text(json.dumps(settings), encoding="utf-8")

        result = _run_install(self.home, "--remove-state-writer")
        self.assertEqual(result.returncode, 0, result.stderr)

        merged = _load_settings(self.home)
        self.assertEqual(merged.get("someUnrelatedTopLevelKey"), {"nested": True})
        session_start_cmds = [
            h["command"]
            for group in merged["hooks"].get("SessionStart", [])
            for h in group.get("hooks", [])
        ]
        self.assertIn("bash /opt/other-tool.sh", session_start_cmds)

    def test_unknown_argument_still_errors_without_installing_anything(self):
        with TemporaryDirectory() as fresh_home_name:
            fresh_home = Path(fresh_home_name)
            result = _run_install(fresh_home, "--bogus-flag")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown argument", result.stderr)
            self.assertFalse((fresh_home / ".claude" / "hooks").exists())


# ---------------------------------------------------------------------------
# GOAL 8 — Migration non-regression: the existing lock hooks keep working,
# unchanged, across install / reinstall / teardown (SW-03)
# ---------------------------------------------------------------------------

class Goal8_MigrationNonRegression(_HomeTestCase):
    def _lock_scripts_match_repo(self) -> None:
        """auq-lock.sh is retired (D-04): the default install path no
        longer ships it, so only working-lock.sh's on-disk copy is checked
        here."""
        installed_working = self.home / ".claude" / "hooks" / "working-lock.sh"
        self.assertTrue(installed_working.is_file())
        self.assertEqual(installed_working.read_bytes(), WORKING_LOCK_SH.read_bytes())

    def test_lock_counts_unchanged_across_install_reinstall_and_teardown(self):
        snippet_lock_count = len(_commands_matching(
            json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8")), LOCK_PATTERN,
        ))

        result1 = _run_install(self.home)
        self.assertEqual(result1.returncode, 0, result1.stderr)
        after_install = len(_commands_matching(_load_settings(self.home), LOCK_PATTERN))
        self.assertEqual(after_install, snippet_lock_count)
        self._lock_scripts_match_repo()

        result2 = _run_install(self.home)
        self.assertEqual(result2.returncode, 0, result2.stderr)
        after_reinstall = len(_commands_matching(_load_settings(self.home), LOCK_PATTERN))
        self.assertEqual(after_reinstall, snippet_lock_count)
        self._lock_scripts_match_repo()

        result3 = _run_install(self.home, "--remove-state-writer")
        self.assertEqual(result3.returncode, 0, result3.stderr)
        after_teardown = len(_commands_matching(_load_settings(self.home), LOCK_PATTERN))
        self.assertEqual(after_teardown, snippet_lock_count)
        self._lock_scripts_match_repo()


# ---------------------------------------------------------------------------
# GOAL 9 — D-04: the AskUserQuestion lock hook is retired from the default
# install path, with a validated teardown mode for installs that already
# registered it (T-03-10, T-03-12)
# ---------------------------------------------------------------------------

class Goal9a_WorkingLockSessionIdValidation(_HomeTestCase):
    """T-03-01: hooks/working-lock.sh backports state-writer.sh's session-id
    character allowlist ahead of the lock directory creation and the
    set/clear branch — the same guard, byte-for-byte in shape."""

    def _lock_dir(self) -> Path:
        return self.home / ".claude" / "working-locks"

    def test_path_traversal_session_id_set_creates_no_file(self):
        result = _run_working_lock("set", json.dumps({"session_id": "../evil"}), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.home / "evil").exists())
        if self._lock_dir().exists():
            self.assertEqual(list(self._lock_dir().iterdir()), [])

    def test_path_traversal_session_id_clear_removes_nothing_outside_lock_dir(self):
        outside_target = self.home / "evil"
        outside_target.write_text("do-not-touch", encoding="utf-8")
        result = _run_working_lock("clear", json.dumps({"session_id": "../evil"}), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(outside_target.exists())
        self.assertEqual(outside_target.read_text(encoding="utf-8"), "do-not-touch")

    def test_well_formed_session_id_still_sets_and_clears_the_lock(self):
        sid = "well-formed_1.2"
        result = _run_working_lock("set", json.dumps({"session_id": sid}), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self._lock_dir() / sid).exists())

        result = _run_working_lock("clear", json.dumps({"session_id": sid}), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self._lock_dir() / sid).exists())


class Goal9_AuqLockRetired(_HomeTestCase):
    def test_fresh_install_registers_zero_auq_lock_entries(self):
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(_commands_matching(settings, AUQ_LOCK_PATTERN), [])
        self.assertFalse((self.home / ".claude" / "hooks" / "auq-lock.sh").exists())
        self.assertFalse((self.home / ".claude" / "auq-locks").exists())

    def test_fresh_install_still_registers_working_lock_and_state_writer(self):
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertGreater(len(_commands_matching(settings, LOCK_PATTERN)), 0)
        self.assertGreater(len(_commands_matching(settings, STATE_WRITER_PATTERN)), 0)
        self.assertGreater(len(_commands_matching(settings, EVENT_LOGGER_PATTERN)), 0)

    def test_remove_auq_lock_strips_only_retired_entries_leaving_working_lock_intact(self):
        """A settings.json shaped like a pre-flip install: the retired
        hook's Stop-clear command shares one entry object with
        working-lock.sh's — the teardown must strip the command, not the
        whole entry, or it silently deletes a still-live guarantee."""
        settings = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "AskUserQuestion",
                     "hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" set',
                                "timeout": 2}]},
                    {"hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/working-lock.sh" set',
                                "timeout": 2}]},
                ],
                "PostToolUse": [
                    {"matcher": "AskUserQuestion",
                     "hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" clear',
                                "timeout": 2}]},
                ],
                "Notification": [
                    {"hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" set',
                                "timeout": 2}]},
                ],
                "Stop": [
                    {"hooks": [
                        {"type": "command",
                         "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" clear',
                         "timeout": 2},
                        {"type": "command",
                         "command": 'bash "$HOME/.claude/hooks/working-lock.sh" clear',
                         "timeout": 2},
                    ]},
                ],
            }
        }
        _settings_path(self.home).parent.mkdir(parents=True, exist_ok=True)
        _settings_path(self.home).write_text(json.dumps(settings), encoding="utf-8")

        result = _run_install(self.home, "--remove-auq-lock")
        self.assertEqual(result.returncode, 0, result.stderr)

        merged = _load_settings(self.home)
        self.assertEqual(_commands_matching(merged, AUQ_LOCK_PATTERN), [])
        working_lock_cmds = _commands_matching(merged, LOCK_PATTERN)
        self.assertEqual(len(working_lock_cmds), 2, working_lock_cmds)
        self.assertEqual(merged["hooks"].get("PostToolUse"), [])
        self.assertEqual(merged["hooks"].get("Notification"), [])
        backups = list((self.home / ".claude").glob("settings.json.bak.*"))
        self.assertEqual(len(backups), 1, backups)

    def test_plain_install_preserves_pre_flip_auq_lock_entries_until_gated_removal(self):
        """WR-02 (corrected direction, 03-UAT.md Section H / D-04): D-04's
        auq-lock.sh retirement is GATED — a pre-flip install's auq-lock.sh
        registrations must survive a plain `bash hooks/install.sh` run
        completely untouched (across every event array they live in:
        PreToolUse/PostToolUse/Notification/Stop) until the user has
        confirmed needs_input parity live and explicitly runs
        `--remove-auq-lock`. A default install silently sweeping them would
        defeat that gate. Reuses the same settings.json shape as
        test_remove_auq_lock_strips_only_retired_entries_leaving_working_lock_intact,
        including the co-located Stop entry (auq-lock clear + working-lock
        clear sharing one hooks array), to prove the co-located command
        survives too — not just the entries with no working-lock.sh
        neighbour."""
        settings = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "AskUserQuestion",
                     "hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" set',
                                "timeout": 2}]},
                    {"hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/working-lock.sh" set',
                                "timeout": 2}]},
                ],
                "PostToolUse": [
                    {"matcher": "AskUserQuestion",
                     "hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" clear',
                                "timeout": 2}]},
                ],
                "Notification": [
                    {"hooks": [{"type": "command",
                                "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" set',
                                "timeout": 2}]},
                ],
                "Stop": [
                    {"hooks": [
                        {"type": "command",
                         "command": 'bash "$HOME/.claude/hooks/auq-lock.sh" clear',
                         "timeout": 2},
                        {"type": "command",
                         "command": 'bash "$HOME/.claude/hooks/working-lock.sh" clear',
                         "timeout": 2},
                    ]},
                ],
            }
        }
        _settings_path(self.home).parent.mkdir(parents=True, exist_ok=True)
        _settings_path(self.home).write_text(json.dumps(settings), encoding="utf-8")

        # No --remove-auq-lock flag: this is the plain upgrade command from
        # README step 4.
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("legacy auq-lock entries present", result.stdout)
        self.assertIn("--remove-auq-lock", result.stdout)

        merged = _load_settings(self.home)
        # All 4 original auq-lock.sh commands, including the one co-located
        # with a working-lock.sh command in the same Stop entry, survive
        # completely untouched.
        self.assertEqual(len(_commands_matching(merged, AUQ_LOCK_PATTERN)), 4)
        # working-lock.sh is still installed/registered as usual alongside
        # the surviving auq-lock.sh entries.
        self.assertGreater(len(_commands_matching(merged, LOCK_PATTERN)), 0)

        # The explicit, gated teardown still removes every auq-lock.sh
        # entry across every array it lives in — that breadth is preserved
        # from the original WR-02 fix.
        result2 = _run_install(self.home, "--remove-auq-lock")
        self.assertEqual(result2.returncode, 0, result2.stderr)
        merged2 = _load_settings(self.home)
        self.assertEqual(_commands_matching(merged2, AUQ_LOCK_PATTERN), [])
        self.assertGreater(len(_commands_matching(merged2, LOCK_PATTERN)), 0)

    def test_remove_auq_lock_on_missing_settings_exits_zero(self):
        result = _run_install(self.home, "--remove-auq-lock")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to do", result.stdout)

    def test_unknown_argument_lists_all_valid_modes(self):
        result = _run_install(self.home, "--nope")
        self.assertNotEqual(result.returncode, 0)
        for mode in ("--remove-logger", "--remove-state-writer", "--remove-auq-lock"):
            self.assertIn(mode, result.stderr)


if __name__ == "__main__":
    unittest.main()
