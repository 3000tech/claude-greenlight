"""Tests for the Phase 1 hook-coverage diagnostic instrument
(hooks/event-logger.sh + hooks/install.sh's logger registration/teardown).

Organised by user-facing goal, not by function, matching test_monitor.py's
convention. Every test runs the real shell scripts via subprocess with HOME
overridden to a TemporaryDirectory — never the real $HOME, since this suite
runs inside the user's live container and the real ~/.claude is the shared
bind mount driving their monitor.

Run with:  python3 -m unittest test_event_logger.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
HOOKS_DIR = HERE / "hooks"
INSTALL_SH = HOOKS_DIR / "install.sh"
EVENT_LOGGER_SH = HOOKS_DIR / "event-logger.sh"
SETTINGS_SNIPPET = HOOKS_DIR / "settings-snippet.json"
HOOK_EVENTS_JSON = HOOKS_DIR / "hook-events.json"

LOCK_PATTERN = r"working-lock\.sh|auq-lock\.sh"
LOGGER_PATTERN = r"event-logger\.sh"


def setUpModule() -> None:
    # unittest special-cases SkipTest raised from setUpModule (reported as a
    # clean module-level skip, exit 0). Raising the same SkipTest at bare
    # module-import time is NOT special-cased — it propagates as an ordinary
    # exception through __import__ and aborts the whole run with a
    # traceback and exit code 1. Keep the guard here, not at import time.
    if shutil.which("jq") is None:
        raise unittest.SkipTest("jq is required to run hooks/event-logger.sh and is not on PATH")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _base_env(home: Path) -> dict:
    """A minimal, real environment with HOME pinned to the temp dir and any
    stray GREENLIGHT_LOG_RAW from the caller's shell stripped."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("GREENLIGHT_LOG_RAW", None)
    return env


def _run_install(home: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_SH), *args],
        env=_base_env(home),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_logger(payload: str, home: Path, raw: bool = False) -> subprocess.CompletedProcess:
    env = _base_env(home)
    if raw:
        env["GREENLIGHT_LOG_RAW"] = "1"
    return subprocess.run(
        ["bash", str(EVENT_LOGGER_SH)],
        input=payload,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _payload(event: str = "Stop", session_id: str = "s1", cwd: str = "/workspace", **extra) -> str:
    obj = {"hook_event_name": event, "session_id": session_id, "cwd": cwd}
    obj.update(extra)
    return json.dumps(obj)


def _log_path(home: Path) -> Path:
    return home / ".claude" / "hook-events.log"


def _log_text(home: Path) -> str:
    p = _log_path(home)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _read_log_lines(home: Path) -> list[dict]:
    """Parse every well-formed JSON line in the log; skip malformed ones,
    matching the "reader tolerates partial lines" design (RESEARCH.md
    Pitfall 5)."""
    lines: list[dict] = []
    for raw_line in _log_text(home).splitlines():
        if not raw_line.strip():
            continue
        try:
            lines.append(json.loads(raw_line))
        except json.JSONDecodeError:
            continue
    return lines


def _settings_path(home: Path) -> Path:
    return home / ".claude" / "settings.json"


def _load_settings(home: Path) -> dict:
    return json.loads(_settings_path(home).read_text(encoding="utf-8"))


def _hook_events() -> list[str]:
    return json.loads(HOOK_EVENTS_JSON.read_text(encoding="utf-8"))


def _commands_matching(settings: dict, pattern: str) -> list[str]:
    """Flatten every hook `command` string across all event keys in a
    settings.json-shaped dict, filtered by regex."""
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
# GOAL 1 — A well-formed hook payload becomes one correctly-shaped log line
# ---------------------------------------------------------------------------

class Goal1_LogLineShape(_HomeTestCase):
    def test_wellformed_payload_produces_one_correctly_shaped_line(self):
        result = _run_logger(
            _payload(event="SessionStart", session_id="s1", cwd="/workspace", source="startup"),
            self.home,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = _read_log_lines(self.home)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        for key in ("ts", "ts_ms", "event", "session_id", "cwd", "keys"):
            self.assertIn(key, line)
        self.assertEqual(line["event"], "SessionStart")
        self.assertEqual(line["session_id"], "s1")
        self.assertEqual(line["cwd"], "/workspace")
        self.assertIsInstance(line["ts_ms"], (int, float))
        self.assertIsInstance(line["keys"], list)

    def test_keys_reports_every_top_level_field_including_uncaptured_ones(self):
        payload = _payload(
            event="PostToolUse", session_id="s2", cwd="/w",
            tool_name="Bash",
            tool_input={"command": "echo hi"},
            tool_response={"stdout": "hi"},
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertIn("tool_input", line["keys"])
        self.assertIn("tool_response", line["keys"])
        self.assertIn("tool_name", line["keys"])
        # Uncaptured content-bearing fields are named in `keys` but never
        # present as top-level keys in the log line itself.
        self.assertNotIn("tool_input", line)
        self.assertNotIn("tool_response", line)

    def test_is_interrupt_and_duration_ms_captured_by_value(self):
        payload = _payload(
            event="PostToolUseFailure", session_id="s3", cwd="/w",
            tool_name="Bash",
            is_interrupt=True,
            duration_ms=1234,
            error="command aborted",
            tool_input={"command": "sleep 60"},
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertIs(line["is_interrupt"], True)
        self.assertEqual(line["duration_ms"], 1234)
        # error stays keys-only: it can echo command/content text.
        self.assertIn("error", line["keys"])
        self.assertNotIn("error", line)

    def test_background_tasks_logged_as_count_only(self):
        payload = _payload(
            event="Stop", session_id="s4", cwd="/w",
            background_tasks=[
                {"id": "t1", "command": "sleep 60 && deploy.sh --secret"},
                {"id": "t2", "command": "tail -f log"},
            ],
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertEqual(line["background_tasks_count"], 2)
        # The array itself (task descriptors can carry command text) stays
        # keys-only.
        self.assertIn("background_tasks", line["keys"])
        self.assertNotIn("background_tasks", line)


# ---------------------------------------------------------------------------
# GOAL 2 — Secrets in tool payloads never land on the shared mount by value
# ---------------------------------------------------------------------------

class Goal2_SecretExclusionAndRawOptIn(_HomeTestCase):
    def test_content_bearing_fields_excluded_by_default(self):
        payload = _payload(
            event="PostToolUse", session_id="s3", cwd="/w",
            tool_name="Bash",
            tool_input={"command": "export API_KEY=hunter2-secret"},
            tool_response={"stdout": "hunter2-secret"},
            prompt="my prompt contains hunter2-secret too",
            last_assistant_message="hunter2-secret",
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        raw_text = _log_text(self.home)
        self.assertNotIn("hunter2-secret", raw_text)
        [line] = _read_log_lines(self.home)
        for field in ("tool_input", "tool_response", "prompt", "last_assistant_message"):
            self.assertNotIn(field, line)

    def test_raw_optin_adds_full_payload_under_raw_key(self):
        payload_obj = {
            "hook_event_name": "PreToolUse", "session_id": "s4", "cwd": "/w",
            "tool_name": "Bash", "tool_input": {"command": "echo hunter2-secret"},
        }
        result = _run_logger(json.dumps(payload_obj), self.home, raw=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertIn("raw", line)
        self.assertEqual(line["raw"], payload_obj)

    def test_raw_key_absent_without_the_opt_in_env_var(self):
        payload = _payload(event="PreToolUse", session_id="s5", cwd="/w", tool_name="Bash")
        result = _run_logger(payload, self.home, raw=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertNotIn("raw", line)

    def test_long_notification_message_truncated_to_200_chars_by_default(self):
        long_message = "a" * 300
        payload = _payload(
            event="Notification", session_id="s6", cwd="/w",
            notification_type="permission_prompt", message=long_message,
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertIn("message", line)
        self.assertLessEqual(len(line["message"]), 220)
        self.assertTrue(line["message"].startswith("a" * 200))
        self.assertNotEqual(line["message"], long_message)

    def test_short_notification_message_passes_through_untruncated(self):
        payload = _payload(
            event="Notification", session_id="s7", cwd="/w",
            notification_type="permission_prompt", message="short message",
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertEqual(line["message"], "short message")

    def test_raw_optin_preserves_full_untruncated_message(self):
        long_message = "b" * 300
        payload = _payload(
            event="Notification", session_id="s8", cwd="/w",
            notification_type="permission_prompt", message=long_message,
        )
        result = _run_logger(payload, self.home, raw=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertEqual(line["message"], long_message)


# ---------------------------------------------------------------------------
# GOAL 3 — A logger failure can never break or slow a Claude Code session
# ---------------------------------------------------------------------------

class Goal3_NeverBreakTheSession(_HomeTestCase):
    def test_empty_stdin_exits_zero_and_writes_nothing(self):
        result = _run_logger("", self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_log_lines(self.home), [])

    def test_nonjson_stdin_exits_zero_and_writes_nothing(self):
        result = _run_logger("not json at all", self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_log_lines(self.home), [])

    def test_truncated_json_stdin_exits_zero_and_writes_nothing(self):
        result = _run_logger('{"hook_event_name":', self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_log_lines(self.home), [])

    def test_partial_payload_without_event_name_exits_zero_and_writes_nothing(self):
        result = _run_logger("{}", self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_log_lines(self.home), [])


# ---------------------------------------------------------------------------
# GOAL 4 — Appends never overwrite, and the log cannot grow unbounded
# ---------------------------------------------------------------------------

class Goal4_AppendAndSizeGuard(_HomeTestCase):
    def test_two_invocations_append_two_lines(self):
        r1 = _run_logger(_payload(session_id="first"), self.home)
        r2 = _run_logger(_payload(session_id="second"), self.home)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        lines = _read_log_lines(self.home)
        self.assertEqual(len(lines), 2)
        self.assertEqual({lines[0]["session_id"], lines[1]["session_id"]}, {"first", "second"})

    def test_oversized_log_truncated_before_next_append_and_still_parses(self):
        claude_dir = self.home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        log = _log_path(self.home)
        # Pre-fill well past the 5MB threshold.
        with open(log, "w", encoding="utf-8") as f:
            f.write("x" * (6 * 1024 * 1024) + "\n")

        result = _run_logger(_payload(session_id="after-truncate"), self.home)
        self.assertEqual(result.returncode, 0, result.stderr)

        raw_lines = [ln for ln in _log_text(self.home).splitlines() if ln.strip()]
        # Truncation drops the oversized filler; only the marker + new line remain.
        self.assertEqual(len(raw_lines), 2)
        marker = json.loads(raw_lines[0])
        self.assertEqual(marker["event"], "_truncated")
        appended = json.loads(raw_lines[1])
        self.assertEqual(appended["session_id"], "after-truncate")

    def test_concurrent_invocations_racing_the_size_guard_lose_no_lines(self):
        """Regression test for WR-03: many event-logger.sh invocations firing
        at once against an already-oversized log must not have their lines
        wiped by a second, racing truncation. flock serializes the
        check-truncate-append critical section."""
        claude_dir = self.home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        log = _log_path(self.home)
        with open(log, "w", encoding="utf-8") as f:
            f.write("x" * (6 * 1024 * 1024) + "\n")

        n = 20
        procs = [
            subprocess.Popen(
                ["bash", str(EVENT_LOGGER_SH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=_base_env(self.home),
                text=True,
            )
            for _ in range(n)
        ]
        for i, p in enumerate(procs):
            p.stdin.write(_payload(session_id=f"race-{i}"))
            p.stdin.close()
        for p in procs:
            self.assertEqual(p.wait(timeout=15), 0, p.stderr.read())
            p.stderr.close()

        lines = _read_log_lines(self.home)
        session_ids = {ln.get("session_id") for ln in lines if "session_id" in ln}
        expected = {f"race-{i}" for i in range(n)}
        self.assertEqual(session_ids, expected)


# ---------------------------------------------------------------------------
# GOAL 5 — install.sh registers the logger on every event, idempotently
# ---------------------------------------------------------------------------

class Goal5_InstallRegistrationAndIdempotency(_HomeTestCase):
    def test_fresh_home_registers_one_logger_entry_per_event_and_lands_locks(self):
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)

        settings = _load_settings(self.home)
        events = _hook_events()
        logger_cmds = _commands_matching(settings, LOGGER_PATTERN)
        self.assertEqual(len(logger_cmds), len(events))

        snippet = json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8"))
        snippet_lock_count = len(_commands_matching(snippet, LOCK_PATTERN))
        merged_lock_count = len(_commands_matching(settings, LOCK_PATTERN))
        self.assertEqual(merged_lock_count, snippet_lock_count)
        self.assertGreater(snippet_lock_count, 0)

    def test_unrecognized_argument_errors_and_does_not_install(self):
        result = _run_install(self.home, "--remove-logge")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)
        self.assertFalse((self.home / ".claude" / "hooks").exists())
        self.assertFalse(_settings_path(self.home).exists())

    def test_running_install_twice_yields_one_logger_entry_per_event(self):
        _run_install(self.home)
        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)

        settings = _load_settings(self.home)
        events = _hook_events()
        logger_cmds = _commands_matching(settings, LOGGER_PATTERN)
        self.assertEqual(len(logger_cmds), len(events))

    def test_registered_command_string_actually_produces_a_log_line(self):
        _run_install(self.home)
        settings = _load_settings(self.home)
        cmds = _commands_matching(settings, LOGGER_PATTERN)
        self.assertTrue(cmds)
        cmd = cmds[0]

        result = subprocess.run(
            ["bash", "-c", cmd],
            input=_payload(event="Stop", session_id="live-check"),
            env=_base_env(self.home),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = _read_log_lines(self.home)
        self.assertTrue(any(ln.get("session_id") == "live-check" for ln in lines))


# ---------------------------------------------------------------------------
# GOAL 6 — Existing settings.json content is never clobbered
# ---------------------------------------------------------------------------

class Goal6_PreservationOfLocksAndUnrelatedSettings(_HomeTestCase):
    def setUp(self) -> None:
        super().setUp()
        _run_install(self.home)

    def test_existing_settings_preserves_unrelated_top_level_key_and_hook_entry(self):
        settings = _load_settings(self.home)
        settings["someUnrelatedTopLevelKey"] = {"nested": True}
        settings.setdefault("hooks", {}).setdefault("SessionStart", []).append(
            {"hooks": [{"type": "command", "command": "bash /opt/other-tool.sh", "timeout": 2}]}
        )
        _settings_path(self.home).write_text(json.dumps(settings), encoding="utf-8")

        result = _run_install(self.home)
        self.assertEqual(result.returncode, 0, result.stderr)

        merged = _load_settings(self.home)
        self.assertEqual(merged.get("someUnrelatedTopLevelKey"), {"nested": True})
        session_start_cmds = [
            h["command"]
            for group in merged["hooks"].get("SessionStart", [])
            for h in group.get("hooks", [])
        ]
        self.assertIn("bash /opt/other-tool.sh", session_start_cmds)

    def test_lock_entries_survive_a_second_install_at_the_snippet_count(self):
        _run_install(self.home)
        snippet = json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8"))
        snippet_lock_count = len(_commands_matching(snippet, LOCK_PATTERN))
        merged = _load_settings(self.home)
        merged_lock_count = len(_commands_matching(merged, LOCK_PATTERN))
        self.assertEqual(merged_lock_count, snippet_lock_count)


# ---------------------------------------------------------------------------
# GOAL 7 — The instrument is fully removable in one command
# ---------------------------------------------------------------------------

class Goal7_RemovalPath(_HomeTestCase):
    def setUp(self) -> None:
        super().setUp()
        _run_install(self.home)
        settings = _load_settings(self.home)
        self.snippet_lock_count = len(_commands_matching(
            json.loads(SETTINGS_SNIPPET.read_text(encoding="utf-8")), LOCK_PATTERN,
        ))
        self.assertGreater(len(_commands_matching(settings, LOGGER_PATTERN)), 0)

    def test_remove_logger_strips_all_logger_entries(self):
        result = _run_install(self.home, "--remove-logger")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(len(_commands_matching(settings, LOGGER_PATTERN)), 0)

    def test_remove_logger_preserves_lock_entries(self):
        result = _run_install(self.home, "--remove-logger")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(len(_commands_matching(settings, LOCK_PATTERN)), self.snippet_lock_count)


class Goal7b_RemovalPathOnUnpopulatedSettings(_HomeTestCase):
    """`--remove-logger` must no-op cleanly (exit 0) on a settings.json that
    has never had any hooks registered at all — i.e. no `hooks` key yet.
    Regression test for WR-01: with_entries on a null .hooks crashed jq."""

    def test_remove_logger_on_settings_without_hooks_key_exits_zero(self):
        claude_dir = self.home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        _settings_path(self.home).write_text("{}", encoding="utf-8")

        result = _run_install(self.home, "--remove-logger")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(_commands_matching(settings, LOGGER_PATTERN), [])

    def test_remove_logger_on_settings_with_unrelated_keys_but_no_hooks(self):
        claude_dir = self.home / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        _settings_path(self.home).write_text(
            json.dumps({"someUnrelatedTopLevelKey": {"nested": True}}), encoding="utf-8",
        )

        result = _run_install(self.home, "--remove-logger")
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = _load_settings(self.home)
        self.assertEqual(settings.get("someUnrelatedTopLevelKey"), {"nested": True})


# ---------------------------------------------------------------------------
# GOAL 8 — background_tasks descriptor SHAPE is sampled by name and enum
# value only, never by content, and never breaks the count/absent contract
# ---------------------------------------------------------------------------

class Goal8_BackgroundTaskDescriptorShapeSampling(_HomeTestCase):
    def test_two_entry_payload_shape_lists_each_entrys_own_field_names(self):
        payload = _payload(
            event="Stop", session_id="s1", cwd="/w",
            background_tasks=[
                {"id": "t1", "type": "shell", "status": "running", "command": "sleep 60"},
                {"id": "bg_2", "type": "agent", "agent_type": "gsd-planner", "status": "running", "prompt": "do it"},
            ],
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        shape = line["background_tasks_shape"]
        self.assertEqual(len(shape), 2)
        self.assertEqual(set(shape[0]["keys"]), {"id", "type", "status", "command"})
        self.assertEqual(set(shape[1]["keys"]), {"id", "type", "agent_type", "status", "prompt"})
        self.assertEqual(shape[0]["id"], "t1")
        self.assertEqual(shape[0]["type"], "shell")
        self.assertEqual(shape[0]["status"], "running")
        self.assertEqual(shape[1]["agent_type"], "gsd-planner")

    def test_sentinel_in_command_and_prompt_values_never_reaches_the_log_text(self):
        sentinel = "SENTINEL-LEAK-i5n"
        payload = _payload(
            event="Stop", session_id="s2", cwd="/w",
            background_tasks=[
                {"id": "t1", "type": "shell", "status": "running", "command": f"deploy.sh {sentinel}"},
                {"id": "bg_2", "type": "agent", "status": "running", "prompt": f"go do {sentinel}"},
            ],
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        raw_text = _log_text(self.home)
        self.assertNotIn(sentinel, raw_text)
        [line] = _read_log_lines(self.home)
        shape = line["background_tasks_shape"]
        self.assertIn("command", shape[0]["keys"])
        self.assertNotIn("command", shape[0])
        self.assertIn("prompt", shape[1]["keys"])
        self.assertNotIn("prompt", shape[1])

    def test_value_shape_guard_drops_whitespace_and_overlong_values_by_value_not_by_name(self):
        payload = _payload(
            event="Stop", session_id="s3", cwd="/w",
            background_tasks=[
                {"type": "has space", "status": "x" * 100},
                {"type": "agent"},
            ],
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        shape = line["background_tasks_shape"]
        self.assertEqual(set(shape[0]["keys"]), {"type", "status"})
        self.assertNotIn("type", shape[0])
        self.assertNotIn("status", shape[0])
        self.assertEqual(shape[1]["type"], "agent")

    def test_absent_and_nonarray_background_tasks_produce_no_shape_key(self):
        result_absent = _run_logger(
            _payload(event="Stop", session_id="s4", cwd="/w"), self.home,
        )
        result_string = _run_logger(
            _payload(event="Stop", session_id="s5", cwd="/w", background_tasks="notarray"),
            self.home,
        )
        self.assertEqual(result_absent.returncode, 0, result_absent.stderr)
        self.assertEqual(result_string.returncode, 0, result_string.stderr)
        lines = _read_log_lines(self.home)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertNotIn("background_tasks_shape", line)

    def test_seven_entries_cap_shape_at_five_while_count_stays_seven(self):
        tasks = [{"id": f"t{i}", "type": "shell"} for i in range(7)]
        payload = _payload(event="Stop", session_id="s6", cwd="/w", background_tasks=tasks)
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertEqual(line["background_tasks_count"], 7)
        self.assertEqual(len(line["background_tasks_shape"]), 5)

    def test_nonobject_entries_produce_empty_keys_lists_and_exit_zero(self):
        payload = _payload(
            event="Stop", session_id="s7", cwd="/w",
            background_tasks=["justastring", 42],
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        [line] = _read_log_lines(self.home)
        shape = line["background_tasks_shape"]
        self.assertEqual(len(shape), 2)
        for entry in shape:
            self.assertEqual(entry["keys"], [])

    def test_empty_array_yields_empty_shape_list_distinct_from_absent_case(self):
        payload = _payload(event="Stop", session_id="s8", cwd="/w", background_tasks=[])
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertIn("background_tasks_shape", line)
        self.assertEqual(line["background_tasks_shape"], [])
        self.assertEqual(line["background_tasks_count"], 0)

    def test_subagentstop_also_carries_shape(self):
        payload = _payload(
            event="SubagentStop", session_id="s9", cwd="/w",
            background_tasks=[{"id": "t1", "type": "shell"}],
        )
        result = _run_logger(payload, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        [line] = _read_log_lines(self.home)
        self.assertIn("background_tasks_shape", line)
        self.assertEqual(line["background_tasks_shape"][0]["type"], "shell")


if __name__ == "__main__":
    unittest.main()
