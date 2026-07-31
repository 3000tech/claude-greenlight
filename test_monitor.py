"""Tests for claude-monitor status detection.

Organised by user-facing goal, not by function. Each test documents the
behaviour an end-user relies on; implementation may be refactored freely as
long as the goals hold.

Run with:  python3 -m unittest test_monitor.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Stub tkinter so monitor.py can be imported in headless/Linux CI — none of
# the functions under test touch the GUI.
if "tkinter" not in sys.modules:
    import types
    sys.modules["tkinter"] = types.ModuleType("tkinter")

import monitor  # noqa: E402
from monitor import (  # noqa: E402
    is_certainly_working, load_env, parse_geometry, resolve_alias, scan,
    tail_last_line, user_tail_kind,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _line(obj: dict) -> str:
    return json.dumps(obj)


def _assistant(blocks: list[dict], session_id: str = "s1") -> str:
    return _line({
        "type": "assistant",
        "sessionId": session_id,
        "message": {"content": blocks},
    })


def _user_prompt(text: str, session_id: str = "s1") -> str:
    return _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": text},
    })


def _user_tool_result(tool_use_id: str, session_id: str = "s1") -> str:
    return _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": "ok",
        }]},
    })


def _text_block(body: str = "done") -> dict:
    return {"type": "text", "text": body}


def _async_agent_launch(tool_use_id: str, agent_id: str,
                        session_id: str = "s1") -> list[str]:
    """Two records: the orchestrator's Agent tool_use and the immediate
    `Async agent launched successfully` tool_result that pairs with it.
    The agent itself runs in the background and finishes later via a
    task-notification — see `_task_notification`."""
    use = _line({
        "type": "assistant",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_use", "id": tool_use_id, "name": "Agent",
            "input": {"run_in_background": True, "description": "bg work"},
        }]},
    })
    result_text = (
        f"Async agent launched successfully.\nagentId: {agent_id} "
        "(internal ID - do not mention to user.)"
    )
    res = _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_result", "tool_use_id": tool_use_id,
            "content": result_text,
        }]},
    })
    return [use, res]


def _bg_shell_start(shell_id: str, tool_use_id: str,
                    session_id: str = "s1") -> list[str]:
    """Two records: the assistant's Bash tool_use with run_in_background=True,
    and the immediate tool_result announcing the shell is running in the
    background. shell_tracker.has_active_shells() anchors on a brace-free
    span between "type" and "content" in the tool_result dict, so the key
    order below (type, tool_use_id, content — no nested object in between)
    must be preserved."""
    use = _line({
        "type": "assistant",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_use", "id": tool_use_id, "name": "Bash",
            "input": {"run_in_background": True, "command": "npm run dev"},
        }]},
    })
    result_text = (
        f"Command running in background with ID: {shell_id}. "
        "Output is being written to: /tmp/shell.out"
    )
    res = _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_result", "tool_use_id": tool_use_id,
            "content": result_text,
        }]},
    })
    return [use, res]


def _manual_bg_shell_start(shell_id: str, tool_use_id: str,
                           session_id: str = "s1") -> list[str]:
    """Two records mirroring a live Ctrl+B capture (2026-07-31, cc 2.1.220+):
    the assistant's Bash tool_use with a PLAIN foreground input (no
    run_in_background key — the command started in the foreground and the
    user promoted it), and the tool_result announcing the manual background
    marker. The tool_result's message.content keys are written in the live
    order — tool_use_id, then type, then content, then is_error — to prove
    shell_tracker.BG_START_RE's anchor tolerates tool_use_id preceding type
    (the anchor only constrains the brace-free span from type to content).
    Carries the live toolUseResult shape (backgroundTaskId/backgroundedByUser)
    as documentation of intent, even though the parser doesn't key off it.
    Like _bg_shell_start, the type key must precede the content key with no
    nested object in between, or the fixture silently stops matching."""
    use = _line({
        "type": "assistant",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_use", "id": tool_use_id, "name": "Bash",
            "input": {"command": "npm run dev"},
        }]},
    })
    result_text = (
        f"Command was manually backgrounded by user with ID: {shell_id}. "
        "Output is being written to: "
        f"/tmp/claude-1000/-workspace/session-uuid/tasks/{shell_id}.output"
    )
    res = _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": [{
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": result_text,
            "is_error": False,
        }]},
        "toolUseResult": {
            "stdout": "",
            "stderr": "",
            "interrupted": False,
            "isImage": False,
            "noOutputExpected": False,
            "backgroundTaskId": shell_id,
            "backgroundedByUser": True,
        },
    })
    return [use, res]


def _bg_task_notification(task_id: str, tool_use_id: str, status: str = "completed",
                          session_id: str = "s1") -> str:
    """Live completion shape for a backgrounded shell: a `queue-operation`
    record (not a user message) whose `content` string holds the
    <task-notification> block, with <tool-use-id> and <output-file> lines
    between the task-id and the status — reproducing the ~180-character gap
    the real notification carries, so a future regression in TASK_NOTIF_RE's
    gap allowance would be caught here."""
    output_path = (
        f"/tmp/claude-1000/-workspace/session-uuid/tasks/{task_id}.output"
    )
    body = (
        "<task-notification>\n"
        f"<task-id>{task_id}</task-id>\n"
        f"<tool-use-id>{tool_use_id}</tool-use-id>\n"
        f"<output-file>{output_path}</output-file>\n"
        f"<status>{status}</status>\n"
        "<summary>done</summary>\n"
        "</task-notification>"
    )
    return _line({
        "type": "queue-operation",
        "operation": "task-notification",
        "sessionId": session_id,
        "content": body,
    })


def _task_notification(task_id: str, status: str = "completed",
                       session_id: str = "s1") -> str:
    """Async-agent completion signal: a `<task-notification>` injected as a
    user record with the agent's <task-id> and final <status>."""
    body = (
        f"<task-notification>\n<task-id>{task_id}</task-id>\n"
        f"<status>{status}</status>\n<summary>done</summary>\n</task-notification>"
    )
    return _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": body},
    })


def _tool_use(name: str, tool_id: str) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": {}}


def _thinking() -> dict:
    return {"type": "thinking", "thinking": "…"}


def _write_session(root: Path, encoded_dir: str, lines: list[str],
                   mtime: float | None = None, filename: str = "sess.jsonl") -> Path:
    d = root / encoded_dir
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if mtime is not None:
        os.utime(f, (mtime, mtime))
    return f


class MonitorTestBase(unittest.TestCase):
    """Wire a temp PROJECTS_DIR into the monitor module for each test."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_projects = monitor.PROJECTS_DIR
        monitor.PROJECTS_DIR = self.root

    def tearDown(self) -> None:
        monitor.PROJECTS_DIR = self._orig_projects
        self._tmp.cleanup()

    def _scan(self, label_map: dict[str, str],
              sessionid_to_label: dict[str, str] | None = None) -> list[dict]:
        """Call scan with a sessionid_to_label derived from label_map.

        Test fixtures tag records with sessionId="s1". The monitor's container
        identification now requires sessionIds to map to live container labels
        (the dir-only fallback was removed because it mislabelled stale
        sibling-container jsonls). Default to mapping s1 → the single label in
        label_map so tests keep reading naturally; override for multi-session
        scenarios.
        """
        if sessionid_to_label is None:
            sessionid_to_label = {"s1": next(iter(label_map.values()))}
        return scan(label_map=label_map, sessionid_to_label=sessionid_to_label)


# ---------------------------------------------------------------------------
# GOAL 1 — The user wants to know when Claude is waiting for their input
# ---------------------------------------------------------------------------

class Goal1_ClaudeReadyForInput(MonitorTestBase):
    """Sessions must turn GREEN whenever Claude is idle at the prompt."""

    def test_assistant_finished_with_text_reply_is_waiting(self):
        """G1a: classic end-of-turn — assistant text block → GREEN."""
        _write_session(self.root, "-workspace-app",
                       [_assistant([_text_block("here is your answer")])])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_assistant_opened_ask_user_question_is_waiting(self):
        """G1b: AskUserQuestion modal pending → GREEN (user must answer)."""
        _write_session(self.root, "-workspace-app",
                       [_assistant([_tool_use("AskUserQuestion", "tu_q1")])])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_yuno_case_agent_returned_then_interrupted_is_waiting(self):
        """G1c — the yuno regression.

        Claude calls an Agent; the Agent returns a tool_result; Claude is
        interrupted before writing its next block. Last line is
        user/tool_result, no tool_use is in flight. Session is idle → GREEN.
        Uses a stale mtime past TOOL_RESULT_WORKING_SEC so the extended
        tool_result working window has expired.
        """
        old = time.time() - (monitor.TOOL_RESULT_WORKING_SEC + 60)
        _write_session(self.root, "-workspace-yuno", [
            _assistant([_tool_use("Agent", "tu_agent1")]),
            _user_tool_result("tu_agent1"),
        ], mtime=old)
        [s] = self._scan({"-workspace-yuno": "yuno"})
        self.assertEqual(s["status"], "WAITING")

    def test_abandoned_prompt_session_does_not_stay_grey_forever(self):
        """G1d: any stale user-prompt tail past the freshness window → GREEN.

        Guards against the previous heuristic where a session stuck on
        user/prompt never escaped WORKING.
        """
        stale = time.time() - (monitor.USER_PROMPT_WORKING_SEC + 30)
        _write_session(self.root, "-workspace-old", [
            _user_prompt("hello"),
        ], mtime=stale)
        [s] = self._scan({"-workspace-old": "old"})
        self.assertEqual(s["status"], "WAITING")


# ---------------------------------------------------------------------------
# GOAL 2 — The user wants to know when Claude is actively working
# ---------------------------------------------------------------------------

class Goal2_ClaudeActivelyWorking(MonitorTestBase):
    """Sessions must show GREY whenever Claude is demonstrably mid-turn."""

    def test_assistant_thinking_block_is_working(self):
        """G2a: thinking block → model still generating → GREY."""
        _write_session(self.root, "-workspace-app",
                       [_assistant([_thinking()])])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_assistant_tool_use_awaiting_result_is_working(self):
        """G2b: tool_use without matching tool_result → GREY."""
        _write_session(self.root, "-workspace-app",
                       [_assistant([_tool_use("Bash", "tu_bash1")])])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_fresh_user_prompt_pending_reply_is_working(self):
        """G2c: user just spoke, Claude owes a response → GREY while fresh."""
        fresh = time.time() - 5  # well inside USER_PROMPT_WORKING_SEC
        _write_session(self.root, "-workspace-app", [
            _assistant([_text_block("previous reply")]),
            _user_prompt("now do X"),
        ], mtime=fresh)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_tool_result_tail_stays_working_past_prompt_window(self):
        """G2e — the double-notification regression.

        During a long work loop (deep thinking, slow bash, long web research)
        the tail stays as user/tool_result while Claude generates the next
        assistant turn. The monitor must not flip to GREEN just because the
        mtime crossed the short user-prompt window, otherwise the session
        ping-pongs WORKING→WAITING→WORKING and fires spurious notifications.
        """
        mid = time.time() - (monitor.USER_PROMPT_WORKING_SEC + 180)  # ~4.5 min
        # Sanity: this mtime is inside the tool_result window.
        self.assertLess(
            time.time() - mid, monitor.TOOL_RESULT_WORKING_SEC,
            "fixture must land inside TOOL_RESULT_WORKING_SEC",
        )
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Bash", "tu_bash_done")]),
            _user_tool_result("tu_bash_done"),
        ], mtime=mid)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_foreground_agent_in_flight_is_working(self):
        """G2d: sub-agent not yet returned → GREY regardless of tail shape."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Agent", "tu_agent_live")]),
            # no matching tool_result → count_active_agents == 1
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_async_agent_launched_no_completion_is_working(self):
        """G2f — the gsd-execute-phase regression. Orchestrator dispatches a
        background sub-agent (Agent run_in_background=True), receives the
        synchronous 'Async agent launched successfully' tool_result, then
        narrates 'Wave dispatched. Waiting.' as a text block. Without async
        tracking the tail looks idle (text block, no foreground tool_use,
        no fresh user prompt) and the monitor fires WAITING after 60s — but
        the async agent is still running. Must show WORKING."""
        _write_session(self.root, "-workspace-app", [
            *_async_agent_launch("tu_dispatch", "a63460d33faaf2a4a"),
            _assistant([_text_block("Wave 2 dispatched. Waiting for completion.")]),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_async_agent_with_completion_notif_falls_back_to_idle(self):
        """Once the <task-notification status=completed> arrives for the same
        agentId, the async agent stops counting — if the orchestrator's tail
        is now an idle text block, the session should show WAITING."""
        _write_session(self.root, "-workspace-app", [
            *_async_agent_launch("tu_dispatch", "a63460d33faaf2a4a"),
            _task_notification("a63460d33faaf2a4a", "completed"),
            _assistant([_text_block("Wave 2 complete. All done.")]),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_tool_result_tail_but_agent_still_in_flight_is_working(self):
        """G2d continued: another Agent is still running even if tail is a
        completed tool_result — the stricter working signal must win."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Agent", "tu_done")]),
            _user_tool_result("tu_done"),
            _assistant([_tool_use("Agent", "tu_live")]),
            # tu_live has no tool_result yet; but what if Claude also emitted
            # a tool_result for something else afterwards? Simulate:
            _user_tool_result("tu_live_unrelated"),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        # tu_live Agent has no matching tool_result → still WORKING.
        # (The "unrelated" tool_result uses a different ID, so the Agent
        # matcher must key off toolu-id, not just presence of any tool_result.)
        self.assertEqual(s["status"], "WORKING")


# ---------------------------------------------------------------------------
# GOAL 2h — A live background shell is badge-only: it never pins WORKING by
# itself, at any age. Grey during a re-invoked turn comes from case-13
# (UserPromptSubmit → working-lock), not from the shell itself. Monitor/
# agent/async-agent pins are unaffected.
# ---------------------------------------------------------------------------

class Goal2h_BgShellBadgeOnly(MonitorTestBase):
    """A background shell (dev server, build, anything started with
    run_in_background) must never pin a session grey by itself — once the
    turn has ended, the session goes WAITING immediately regardless of the
    shell's age, while the bg badge keeps reporting the running process."""

    def test_fresh_bg_shell_ended_turn_is_waiting_badge_true(self):
        """G2h-1: fresh jsonl, live bg shell, ended turn → WAITING (not held
        grey by the shell), bg badge still True. The fixture's only tail
        signal is a plain assistant text block — no tool_result/thinking/
        tool_use — so nothing OTHER than the (now-removed) bg pin could have
        held this grey."""
        fresh = time.time() - 5
        _write_session(self.root, "-workspace-app", [
            *_bg_shell_start("shell_1", "tu_bg_start"),
            _assistant([_text_block("dev server started")]),
        ], mtime=fresh)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")
        self.assertTrue(s["bg"])

    def test_stale_bg_shell_ended_turn_is_waiting_badge_true(self):
        """G2h-2: same as G2h-1 but with an old mtime — the shell being
        long-lived changes nothing, since it was never a pin in the first
        place. Confirms there's no lingering age dependency."""
        stale = time.time() - 1800  # 30 min, well inside MAX_AGE_SEC
        _write_session(self.root, "-workspace-app", [
            *_bg_shell_start("shell_1", "tu_bg_start"),
            _assistant([_text_block("dev server started")]),
        ], mtime=stale)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")
        self.assertTrue(s["bg"])

    def test_async_agent_in_flight_still_working_bg_pin_removal_scoped(self):
        """G2h-3: removing the bg-shell pin must not touch the async-agent
        pin — an async agent still in flight (no completion notification)
        keeps the session WORKING, at any age."""
        stale = time.time() - 1800
        _write_session(self.root, "-workspace-app", [
            *_async_agent_launch("tu_dispatch", "a63460d33faaf2a4a"),
            _assistant([_text_block("Wave 2 dispatched. Waiting for completion.")]),
        ], mtime=stale)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")


# ---------------------------------------------------------------------------
# GOAL 2i — A shell the user backgrounded by hand (Ctrl+B) is detected exactly
# like one Claude backgrounded itself. Ground truth: live jsonl capture,
# 2026-07-31, cc 2.1.220+.
# ---------------------------------------------------------------------------

class Goal2i_ManualBgShellDetected(MonitorTestBase):
    """A shell the user backgrounded by hand must be reported by the ⚙ badge
    exactly like one Claude backgrounded itself — the user cannot be expected
    to know which code path put a running shell into the background, so the
    monitor's answer to "is something still running?" must not depend on it."""

    def test_manual_bg_shell_lights_badge_stays_waiting(self):
        """G2i-1: manual-start marker + ended turn → bg badge lights (True)
        and status is WAITING, not WORKING — the badge-only invariant from
        quick 260731-an2 rev.2 survives the widened start detection. The only
        tail signal after the start marker is a plain assistant text block,
        so nothing else could account for either assertion."""
        _write_session(self.root, "-workspace-app", [
            *_manual_bg_shell_start("b0rui8k6c", "tu_manual_start"),
            _assistant([_text_block("noted")]),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")
        self.assertTrue(s["bg"])

    def test_manual_bg_shell_completion_clears_badge(self):
        """G2i-2: the manually-backgrounded shell's completion notification
        clears the badge with no new termination code — TASK_NOTIF_RE already
        matches any task-id regardless of which marker started it. Uses the
        live `queue-operation` shape with the intervening tool-use-id and
        output-file lines that separate the real gap from the pattern's
        allowance."""
        _write_session(self.root, "-workspace-app", [
            *_manual_bg_shell_start("b0rui8k6c", "tu_manual_start"),
            _bg_task_notification("b0rui8k6c", "tu_manual_start"),
            _assistant([_text_block("shell finished")]),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertFalse(s["bg"])

    def test_escaped_echo_of_manual_marker_does_not_spoof_badge(self):
        """G2i-3: an escaped grep/cat echo of a jsonl containing the manual
        marker must NOT light the badge. Observed live in the same session as
        the real marker: a later tool_result whose content is itself a
        fragment of jsonl text with every inner quote escaped
        (\\"type\\":\\"tool_result\\"...), which cannot satisfy a pattern
        requiring unescaped quotes immediately around the type/content keys.
        This is the concrete reason the anchoring exists — if this test fails,
        the anchoring was relaxed and that is the bug, not this test."""
        escaped_echo = (
            '{"type": "user", "sessionId": "s1", "message": {"content": [{'
            '"tool_use_id": "tu_grep", "type": "tool_result", '
            '"content": "grep output:\\n{\\"tool_use_id\\":\\"tu_x\\",\\"type\\":\\"tool_result\\",'
            '\\"content\\":\\"Command was manually backgrounded by user with ID: b0rui8k6c. '
            'Output is being written to: /tmp/x.output\\"}", '
            '"is_error": false}]}}'
        )
        _write_session(self.root, "-workspace-app", [
            _assistant([_text_block("checking logs")]),
            escaped_echo,
            _assistant([_text_block("nothing new")]),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertFalse(s["bg"])


# ---------------------------------------------------------------------------
# GOAL 1e — AskUserQuestion lock overrides the batched-jsonl-flush blind spot
# ---------------------------------------------------------------------------

class Goal1e_AuqLockOverride(MonitorTestBase):
    """Claude Code 2.1.x batches the AskUserQuestion assistant record with the
    user's response, so during the actual wait the jsonl tail still looks like
    a fresh user/tool_result. A PreToolUse hook drops a sentinel in
    ~/.claude/auq-locks/<sid> while the modal is open; the monitor must treat
    that sentinel as a hard WAITING signal, beating fresh_user_tail."""

    def setUp(self) -> None:
        super().setUp()
        self._lock_tmp = TemporaryDirectory()
        self._orig_lock_dir = monitor.AUQ_LOCK_DIR
        monitor.AUQ_LOCK_DIR = Path(self._lock_tmp.name)

    def tearDown(self) -> None:
        monitor.AUQ_LOCK_DIR = self._orig_lock_dir
        self._lock_tmp.cleanup()
        super().tearDown()

    def _touch_lock(self, sid: str, mtime: float | None = None) -> None:
        f = monitor.AUQ_LOCK_DIR / sid
        f.touch()
        if mtime is not None:
            os.utime(f, (mtime, mtime))

    def test_lock_present_flips_grey_tool_result_tail_to_green(self):
        """The bug we shipped this fix for: tool_result tail + fresh mtime
        normally stays GREY for 15 min, but the AUQ lock means Claude is
        actually waiting on the user → must show GREEN."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Bash", "tu_b")]),
            _user_tool_result("tu_b"),  # fresh tool_result tail → would be WORKING
        ])
        self._touch_lock("s1")
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_no_lock_keeps_normal_decision(self):
        """Sanity: without the lock, the existing fresh_user_tail rule still
        keeps the session WORKING — nothing else changed."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Bash", "tu_b")]),
            _user_tool_result("tu_b"),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_stale_lock_is_ignored(self):
        """If PostToolUse never fires (Claude crash, hook timeout) the lock
        could persist forever. Older than AUQ_LOCK_MAX_AGE_SEC → ignore it,
        fall back to the normal decision."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Bash", "tu_b")]),
            _user_tool_result("tu_b"),
        ])
        old = time.time() - (monitor.AUQ_LOCK_MAX_AGE_SEC + 60)
        self._touch_lock("s1", mtime=old)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_lock_ignored_when_jsonl_written_after_lock(self):
        """PostToolUse `clear` can fail silently (2s timeout) and Stop never
        arrives if Claude keeps working post-AUQ — so the lock outlives the
        modal. Once the jsonl flush bumps mtime past lock_mtime, the lock
        is stale and must not pin WAITING."""
        old_lock = time.time() - 60
        f = _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Bash", "tu_b")]),
        ])
        # Lock predates the jsonl by ~60s — flush already happened.
        os.utime(f, (time.time(), time.time()))
        self._touch_lock("s1", mtime=old_lock)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")


# ---------------------------------------------------------------------------
# GOAL 2g — Working lock bridges the prompt→first-flush blind spot
# ---------------------------------------------------------------------------

class Goal2g_WorkingLockOverride(MonitorTestBase):
    """Claude Code batches the first assistant thinking/tool_use record with the
    first tool_result, so during a long first tool call the jsonl tail is still
    the bare user prompt. Past USER_PROMPT_WORKING_SEC that flips the session to
    a false WAITING + notification. A UserPromptSubmit hook drops a sentinel in
    ~/.claude/working-locks/<sid> for the duration of the turn; the monitor must
    treat it as a WORKING signal until the jsonl visibly catches up."""

    def setUp(self) -> None:
        super().setUp()
        self._wlock_tmp = TemporaryDirectory()
        self._orig_wlock_dir = monitor.WORKING_LOCK_DIR
        monitor.WORKING_LOCK_DIR = Path(self._wlock_tmp.name)

    def tearDown(self) -> None:
        monitor.WORKING_LOCK_DIR = self._orig_wlock_dir
        self._wlock_tmp.cleanup()
        super().tearDown()

    def _touch_lock(self, sid: str, mtime: float | None = None) -> None:
        f = monitor.WORKING_LOCK_DIR / sid
        f.touch()
        if mtime is not None:
            os.utime(f, (mtime, mtime))

    def test_lock_keeps_stale_prompt_tail_working(self):
        """The bug this fix shipped for: a user-prompt tail past
        USER_PROMPT_WORKING_SEC normally ages out to WAITING + notification, but
        the lock proves Claude is mid-turn on a slow first tool → WORKING."""
        stale = time.time() - (monitor.USER_PROMPT_WORKING_SEC + 60)
        _write_session(self.root, "-workspace-app", [
            _user_prompt("nuova richiesta del cliente …"),
        ], mtime=stale)
        # Hook touch and the prompt's jsonl write land together at turn start.
        self._touch_lock("s1", mtime=stale)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_lock_keeps_text_reply_tail_working_during_in_flight_tool(self):
        """The yunoai-austria/dev-tools false-green: mid-turn Claude fires a tool
        (e.g. a slow Read), but the assistant tool_use record is batched with its
        tool_result and only lands when the tool FINISHES. While it runs, the
        jsonl tail is the previous assistant `text` reply — is_certainly_working
        is False and there's no fresh user tail, so the session would paint GREEN
        even though a tool is in flight. The PreToolUse-armed lock (mtime ahead of
        the still-stale jsonl) must hold it WORKING."""
        tool_start = time.time()
        # The visible tail predates the in-flight tool — jsonl hasn't flushed.
        f = _write_session(self.root, "-workspace-app", [
            _assistant([_text_block("Let me read that file.")]),
        ], mtime=tool_start - 30)
        # PreToolUse touched the lock at tool start; the flush will only land when
        # the tool ends, so lock_mtime stays ahead of the jsonl → guard holds.
        self._touch_lock("s1", mtime=tool_start)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")

    def test_no_lock_keeps_normal_decision(self):
        """Sanity: without the lock, a stale user-prompt tail still ages out to
        WAITING — nothing else changed."""
        stale = time.time() - (monitor.USER_PROMPT_WORKING_SEC + 60)
        _write_session(self.root, "-workspace-app", [
            _user_prompt("nuova richiesta del cliente …"),
        ], mtime=stale)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_stale_lock_is_ignored(self):
        """If Stop never fires (interrupt, crash, hook timeout) the lock could
        persist forever. Older than WORKING_LOCK_MAX_AGE_SEC → ignore it, fall
        back to the normal decision."""
        stale = time.time() - (monitor.USER_PROMPT_WORKING_SEC + 60)
        _write_session(self.root, "-workspace-app", [
            _user_prompt("hello"),
        ], mtime=stale)
        old = time.time() - (monitor.WORKING_LOCK_MAX_AGE_SEC + 60)
        self._touch_lock("s1", mtime=old)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_lock_ignored_when_jsonl_written_after_lock(self):
        """The stale-lock guard is the handoff: once the jsonl flush bumps mtime
        past lock_mtime the turn has visibly moved on, so the lock must not pin
        WORKING — the normal tail logic decides. (Also the backstop for a Stop
        hook that failed to clear.)"""
        old_lock = time.time() - 60
        f = _write_session(self.root, "-workspace-app", [
            _assistant([_text_block("turn finished")]),
        ])
        # jsonl flushed well after the lock was dropped.
        os.utime(f, (time.time(), time.time()))
        self._touch_lock("s1", mtime=old_lock)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")


# ---------------------------------------------------------------------------
# GOAL 1f — Tool-permission prompt must show WAITING despite the working lock
# ---------------------------------------------------------------------------

class Goal1f_PermissionPromptOverride(MonitorTestBase):
    """The reported nursy bug: a session blocked on a tool-permission prompt
    (the "dangerous rm" confirmation) showed GREY, not GREEN. PreToolUse fires
    BEFORE the prompt and arms the working-lock, and the assistant tool_use:Bash
    record is batched with its (never-arriving) tool_result — so both the working
    lock AND the stale tail scream WORKING while Claude is really blocked on the
    user. A Notification hook drops the auq-lock sentinel; the monitor must let
    it win over the working lock and paint GREEN."""

    def setUp(self) -> None:
        super().setUp()
        self._auq_tmp = TemporaryDirectory()
        self._wlock_tmp = TemporaryDirectory()
        self._orig_auq_dir = monitor.AUQ_LOCK_DIR
        self._orig_wlock_dir = monitor.WORKING_LOCK_DIR
        monitor.AUQ_LOCK_DIR = Path(self._auq_tmp.name)
        monitor.WORKING_LOCK_DIR = Path(self._wlock_tmp.name)

    def tearDown(self) -> None:
        monitor.AUQ_LOCK_DIR = self._orig_auq_dir
        monitor.WORKING_LOCK_DIR = self._orig_wlock_dir
        self._auq_tmp.cleanup()
        self._wlock_tmp.cleanup()
        super().tearDown()

    def _touch(self, base: Path, sid: str, mtime: float | None = None) -> None:
        f = base / sid
        f.touch()
        if mtime is not None:
            os.utime(f, (mtime, mtime))

    def test_permission_prompt_beats_working_lock(self):
        """Both locks armed, jsonl tail is the pre-prompt reply: the Notification
        auq-lock must override the PreToolUse working-lock → WAITING."""
        prompt_shown = time.time()
        # Tail predates the prompt: the assistant text before the tool call, or
        # the previous tool_result — either way the tool_use:Bash isn't flushed.
        f = _write_session(self.root, "-workspace-app", [
            _assistant([_text_block("Let me clean that up.")]),
        ], mtime=prompt_shown - 20)
        # PreToolUse armed the working-lock a moment before the prompt appeared;
        # the Notification hook armed the auq-lock when the prompt rendered.
        self._touch(monitor.WORKING_LOCK_DIR, "s1", mtime=prompt_shown - 1)
        self._touch(monitor.AUQ_LOCK_DIR, "s1", mtime=prompt_shown)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_after_answer_flush_clears_lock_back_to_working(self):
        """User approves → the tool runs and its tool_use+tool_result flush,
        bumping jsonl mtime past both locks. The stale-lock guard drops the
        auq-lock so the session returns to WORKING while the command runs."""
        f = _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Bash", "tu_b")]),
            _user_tool_result("tu_b"),
        ])
        os.utime(f, (time.time(), time.time()))
        # Both locks predate the flush → both guards fire, normal tail decides.
        self._touch(monitor.WORKING_LOCK_DIR, "s1", mtime=time.time() - 60)
        self._touch(monitor.AUQ_LOCK_DIR, "s1", mtime=time.time() - 60)
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WORKING")


# ---------------------------------------------------------------------------
# GOAL 2b — Container identification must survive sibling-container death
# ---------------------------------------------------------------------------

class Goal2b_ContainerIdentification(MonitorTestBase):
    """A killed container's lingering jsonl must not be relabelled under the
    name of a sibling container that happens to share its encoded dir."""

    def test_killed_sibling_jsonl_does_not_steal_survivors_label(self):
        """Regression: dev-tools and newton-thrust both run at /workspace
        (encoded as '-workspace'). User kills dev-tools. Its jsonl still has
        fresh mtime; the dir now has a single running container
        (newton-thrust) so label_map resolves to newton-thrust. Before the
        fix, the freshly-killed dev-tools jsonl was the newest in the dir and
        got labelled 'newton-thrust' via the dir-only fallback, producing a
        phantom newton-thrust row until the mtime aged out.
        """
        now = time.time()
        # newton-thrust is the only container currently running at -workspace.
        label_map = {"-workspace": "newton-thrust"}
        sessionid_to_label = {"s_newton": "newton-thrust"}
        # Dead dev-tools jsonl: fresh mtime, distinct sessionId, not in sid-map.
        _write_session(self.root, "-workspace", [
            _assistant([_text_block("dev-tools reply")], session_id="s_devtools"),
        ], mtime=now - 30, filename="devtools.jsonl")
        # Live newton-thrust jsonl: slightly older mtime (would lose
        # "newest-per-dir" dedup, which is exactly what the old code did).
        _write_session(self.root, "-workspace", [
            _assistant([_text_block("newton reply")], session_id="s_newton"),
        ], mtime=now - 120, filename="newton.jsonl")

        rows = scan(label_map=label_map, sessionid_to_label=sessionid_to_label)
        # Exactly one row, belonging to the live newton-thrust container.
        self.assertEqual(len(rows), 1, f"expected 1 row, got {rows}")
        self.assertEqual(rows[0]["name"], "newton-thrust")
        self.assertEqual(rows[0]["session_id"], "s_newton")


# ---------------------------------------------------------------------------
# GOAL 3 — Robustness: malformed / empty input must never crash the monitor
# ---------------------------------------------------------------------------

class Goal3_Robustness(MonitorTestBase):

    def test_empty_jsonl_file_is_handled(self):
        _write_session(self.root, "-workspace-app", [""])
        rows = self._scan({"-workspace-app": "app"})
        # Empty tail → treated as idle/GREEN; should not raise.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "WAITING")

    def test_malformed_json_line_is_handled(self):
        _write_session(self.root, "-workspace-app",
                       ["{not valid json", _assistant([_text_block()])])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_non_user_assistant_records_are_skipped_when_picking_tail(self):
        """tail_last_line must skip `system`/`attachment`/`file-history-snapshot`."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_text_block("real tail")]),
            _line({"type": "system", "content": "meta"}),
            _line({"type": "file-history-snapshot"}),
            _line({"type": "attachment"}),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertEqual(s["status"], "WAITING")

    def test_pure_functions_accept_none_and_empty(self):
        self.assertFalse(is_certainly_working(None))
        self.assertFalse(is_certainly_working(""))
        self.assertFalse(is_certainly_working("{bad"))
        self.assertEqual(user_tail_kind(None), "")
        self.assertEqual(user_tail_kind(""), "")
        self.assertEqual(user_tail_kind("{bad"), "")
        self.assertEqual(user_tail_kind(_user_prompt("hi")), "prompt")
        self.assertEqual(user_tail_kind(_user_tool_result("tu_x")), "tool_result")
        self.assertEqual(user_tail_kind(_assistant([_text_block()])), "")
        self.assertIsNone(tail_last_line(Path("/nonexistent/file.jsonl")))


# ---------------------------------------------------------------------------
# GOAL 4 — Pure is_certainly_working unit matrix (fine-grained block ordering)
# ---------------------------------------------------------------------------

class Goal4_CertainlyWorkingMatrix(unittest.TestCase):
    """Given the last `assistant` record, decide WORKING correctly.

    The last block in the content array wins; earlier blocks are ignored.
    """

    def test_text_last_is_idle(self):
        self.assertFalse(is_certainly_working(
            _assistant([_thinking(), _text_block()])))

    def test_ask_user_question_last_is_idle(self):
        self.assertFalse(is_certainly_working(
            _assistant([_tool_use("AskUserQuestion", "tu_q")])))

    def test_other_tool_use_last_is_working(self):
        for name in ("Bash", "Edit", "Read", "Agent", "Write"):
            self.assertTrue(
                is_certainly_working(_assistant([_tool_use(name, "tu_x")])),
                msg=f"tool {name!r} should mark WORKING",
            )

    def test_thinking_last_is_working(self):
        self.assertTrue(is_certainly_working(_assistant([_thinking()])))

    def test_user_record_never_working_by_itself(self):
        """is_certainly_working only looks at assistant tails; user tails are
        handled upstream by the fresh-mtime rule."""
        self.assertFalse(is_certainly_working(_user_prompt("hi")))
        self.assertFalse(is_certainly_working(_user_tool_result("tu_x")))


# ---------------------------------------------------------------------------
# GOAL 5 — .env parsing for optional Telegram credentials
# ---------------------------------------------------------------------------


class Goal5_LoadEnv(unittest.TestCase):
    """load_env must tolerate a missing, empty, or commented .env gracefully."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig = monitor.ENV_FILE
        monitor.ENV_FILE = Path(self._tmp.name) / ".env"

    def tearDown(self) -> None:
        monitor.ENV_FILE = self._orig
        self._tmp.cleanup()

    def test_missing_env_returns_empty_dict(self):
        self.assertEqual(load_env(), {})

    def test_parses_key_value_pairs_ignoring_comments_and_quotes(self):
        monitor.ENV_FILE.write_text(
            "# comment\n"
            "\n"
            "TELEGRAM_BOT_TOKEN=123:abc\n"
            'TELEGRAM_CHAT_ID="42"\n'
            "BROKEN_LINE_NO_EQUALS\n",
            encoding="utf-8",
        )
        env = load_env()
        self.assertEqual(env["TELEGRAM_BOT_TOKEN"], "123:abc")
        self.assertEqual(env["TELEGRAM_CHAT_ID"], "42")
        self.assertNotIn("BROKEN_LINE_NO_EQUALS", env)


# ---------------------------------------------------------------------------
# GOAL 6 — Runtime session labels disambiguate same-named sessions
# ---------------------------------------------------------------------------

class Goal6_SessionAlias(unittest.TestCase):
    """Clicking a session row opens a label dialog; resolve_alias maps the raw
    dialog answer to the value the monitor stores. Two `yunoai-france` containers
    can be tagged "RAM" / "GSD" to tell them apart."""

    def test_cancel_keeps_previous(self):
        """The dialog returns None when the user cancels — must not wipe the
        label the user set earlier."""
        self.assertEqual(resolve_alias(None, "RAM"), "RAM")
        self.assertEqual(resolve_alias(None, ""), "")

    def test_empty_or_whitespace_clears(self):
        """Submitting a blank field is the explicit 'clear it' gesture."""
        self.assertEqual(resolve_alias("", "RAM"), "")
        self.assertEqual(resolve_alias("   ", "RAM"), "")

    def test_non_empty_is_stored_stripped(self):
        self.assertEqual(resolve_alias("  GSD ", "RAM"), "GSD")
        self.assertEqual(resolve_alias("RAM", ""), "RAM")


# ---------------------------------------------------------------------------
# GOAL 6b — Session labels persist across a monitor restart
# ---------------------------------------------------------------------------

class Goal6b_AliasPersistence(unittest.TestCase):
    """Labels are written to the config file so they survive a monitor
    restart; load_config sanitises whatever it finds on disk."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig = monitor.CONFIG_FILE
        monitor.CONFIG_FILE = Path(self._tmp.name) / "cfg.json"

    def tearDown(self) -> None:
        monitor.CONFIG_FILE = self._orig
        self._tmp.cleanup()

    def test_aliases_round_trip_through_config(self):
        cfg = monitor.load_config()
        cfg["aliases"]["sid-1"] = "RAM"
        cfg["aliases"]["sid-2"] = "GSD"
        monitor.save_config(cfg)
        self.assertEqual(monitor.load_config()["aliases"],
                         {"sid-1": "RAM", "sid-2": "GSD"})

    def test_missing_aliases_key_yields_empty_dict(self):
        monitor.CONFIG_FILE.write_text('{"mode": "compact"}', encoding="utf-8")
        self.assertEqual(monitor.load_config()["aliases"], {})

    def test_garbage_entries_are_dropped_and_values_stripped(self):
        monitor.CONFIG_FILE.write_text(
            '{"aliases": {"ok": "  RAM ", "blank": "  ", "num": 5}}',
            encoding="utf-8",
        )
        self.assertEqual(monitor.load_config()["aliases"], {"ok": "RAM"})

    def test_default_aliases_dict_not_shared_between_loads(self):
        """Mutable-default trap: each load_config must hand back its own dict,
        or one session's labels would leak into the next load."""
        first = monitor.load_config()
        first["aliases"]["leak"] = "nope"
        self.assertEqual(monitor.load_config()["aliases"], {})


class Goal6d_AliasKeyedByContainer(MonitorTestBase):
    """A label sticks to the container (its hostname), not to the jsonl's
    sessionId — so a /clear, /resume or CLI restart, which all rotate the
    sessionId (and therefore the row key), doesn't make the label vanish."""

    def setUp(self) -> None:
        super().setUp()
        self._tmp_cfg = TemporaryDirectory()
        self._orig_config_file = monitor.CONFIG_FILE
        monitor.CONFIG_FILE = Path(self._tmp_cfg.name) / "cfg.json"

    def tearDown(self) -> None:
        monitor.CONFIG_FILE = self._orig_config_file
        self._tmp_cfg.cleanup()
        super().tearDown()

    def _fake_app(self):
        class Fake:
            def __init__(self):
                self.config = monitor.load_config()
                self._session_aliases = self.config["aliases"]
                self._alias_keys: dict[str, str] = {}
                self._aliases_pruned = False
                self._dialog_open = False
                self._session_rows: dict[str, dict] = {}
                self._compact_chips: dict[str, dict] = {}

            def _alias_key(self, key):
                return self._alias_keys.get(key, key)

            def _ask_label(self, prompt, initial):
                return getattr(self, "_next_answer", None)

        return Fake()

    # -- derive_alias_key: the pure function every alias site is built on --

    def test_derive_alias_key_namespaces_a_known_hostname(self):
        self.assertEqual(monitor.derive_alias_key("container-1", "sid-abc"),
                          "host:container-1")

    def test_derive_alias_key_falls_back_when_hostname_unresolvable(self):
        for bad_hostname in (None, "", 5):
            self.assertEqual(
                monitor.derive_alias_key(bad_hostname, "sid-abc"), "sid-abc")

    # -- scan(): rows carry alias_key derived from container_info --

    def test_scan_row_gets_container_alias_key(self):
        _write_session(self.root, "-workspace-a", [
            _assistant([_text_block()], session_id="s1"),
        ])
        [s] = scan(sessionid_to_label={"s1": "L"},
                   container_info={"sessionid_to_hostname": {"s1": "c1"}})
        self.assertEqual(s["key"], "s1")
        self.assertEqual(s["alias_key"], "host:c1")

    def test_scan_row_without_container_info_keeps_todays_behaviour(self):
        _write_session(self.root, "-workspace-a", [
            _assistant([_text_block()], session_id="s1"),
        ])
        [s] = scan(sessionid_to_label={"s1": "L"})
        self.assertEqual(s["alias_key"], s["key"])

    def test_sessionid_rotation_keeps_same_alias_key(self):
        """THE REGRESSION: /clear rotates the sessionId (and therefore the
        row key), but the container hostname doesn't change — the alias key
        must stay identical, or a label set before /clear disappears after it."""
        _write_session(self.root, "-workspace-a", [
            _assistant([_text_block()], session_id="s1"),
        ])
        _write_session(self.root, "-workspace-b", [
            _assistant([_text_block()], session_id="s2"),
        ], filename="sess2.jsonl")
        container_info = {"sessionid_to_hostname": {"s1": "c1", "s2": "c1"}}
        sessions = scan(sessionid_to_label={"s1": "L", "s2": "L"},
                         container_info=container_info)
        self.assertEqual({s["key"] for s in sessions}, {"s1", "s2"})
        self.assertEqual({s["alias_key"] for s in sessions}, {"host:c1"})

    # -- scan_containers(): container_info's shape carries sessionid_to_hostname --

    def test_scan_containers_docker_absent_container_info_has_all_three_maps(self):
        orig_which = shutil.which
        shutil.which = lambda name: None
        try:
            result = monitor.scan_containers()
        finally:
            shutil.which = orig_which
        self.assertEqual(len(result), 4)
        container_info = result[3]
        self.assertIn("hostname_to_label", container_info)
        self.assertIn("hostname_to_status", container_info)
        self.assertIn("sessionid_to_hostname", container_info)
        self.assertEqual(container_info["sessionid_to_hostname"], {})

    # -- MonitorApp._alias_key: row-key -> alias-key lookup --

    def test_alias_key_maps_known_row_key_and_falls_back_for_unknown(self):
        fake = self._fake_app()
        fake._alias_keys = {"s1": "host:c1"}
        self.assertEqual(fake._alias_key("s1"), "host:c1")
        self.assertEqual(fake._alias_key("unknown-key"), "unknown-key")

    # -- MonitorApp._edit_alias: stores/reads under the resolved alias key --

    def test_edit_alias_stores_under_alias_key_readable_via_different_row_key(self):
        fake = self._fake_app()
        fake._alias_keys = {"s1": "host:c1"}
        fake._next_answer = "RAM"
        monitor.MonitorApp._edit_alias(fake, "s1")
        self.assertEqual(fake._session_aliases, {"host:c1": "RAM"})
        # /clear: a new row key ("s2") maps to the SAME container alias key —
        # the label set under "s1" must still be readable.
        fake._alias_keys = {"s2": "host:c1"}
        self.assertEqual(fake._session_aliases.get(fake._alias_key("s2")), "RAM")

    def test_edit_alias_clear_pops_under_alias_key(self):
        fake = self._fake_app()
        fake._alias_keys = {"s1": "host:c1"}
        fake._session_aliases["host:c1"] = "RAM"
        fake._next_answer = ""
        monitor.MonitorApp._edit_alias(fake, "s1")
        self.assertNotIn("host:c1", fake._session_aliases)

    # -- MonitorApp._prune_aliases: live/dead gate keyed by alias_key --

    def test_prune_aliases_keeps_live_drops_dead_and_runs_once(self):
        fake = self._fake_app()
        fake._session_aliases.update({"host:c1": "RAM", "host:c2": "GONE"})
        monitor.MonitorApp._prune_aliases(fake, [{"key": "s1", "alias_key": "host:c1"}])
        self.assertEqual(fake._session_aliases, {"host:c1": "RAM"})
        self.assertTrue(fake._aliases_pruned)
        # Runs at most once: a later call, even with different live data,
        # must not touch the dict again.
        fake._session_aliases["host:c3"] = "NEW"
        monitor.MonitorApp._prune_aliases(fake, [])
        self.assertIn("host:c3", fake._session_aliases)

    def test_prune_aliases_is_noop_on_empty_session_list(self):
        fake = self._fake_app()
        fake._session_aliases["host:c1"] = "RAM"
        monitor.MonitorApp._prune_aliases(fake, [])
        self.assertEqual(fake._session_aliases, {"host:c1": "RAM"})
        self.assertFalse(fake._aliases_pruned)


class Goal6c_NotificationToggles(unittest.TestCase):
    """Two independent notification switches persist through the config file:
    "local" (toast+audio+flash on this machine) and "telegram" (phone push).
    A pre-split config carrying only the old "sound" key migrates into "local".
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig = monitor.CONFIG_FILE
        monitor.CONFIG_FILE = Path(self._tmp.name) / "cfg.json"

    def tearDown(self) -> None:
        monitor.CONFIG_FILE = self._orig
        self._tmp.cleanup()

    def test_defaults_both_on(self):
        cfg = monitor.load_config()
        self.assertTrue(cfg["local"])
        self.assertTrue(cfg["telegram"])

    def test_toggles_round_trip(self):
        cfg = monitor.load_config()
        cfg["local"] = False
        cfg["telegram"] = False
        monitor.save_config(cfg)
        reloaded = monitor.load_config()
        self.assertFalse(reloaded["local"])
        self.assertFalse(reloaded["telegram"])

    def test_toggles_are_independent(self):
        monitor.CONFIG_FILE.write_text(
            '{"local": false, "telegram": true}', encoding="utf-8")
        cfg = monitor.load_config()
        self.assertFalse(cfg["local"])
        self.assertTrue(cfg["telegram"])

    def test_legacy_sound_key_migrates_into_local(self):
        # Pre-split config: only the old audio-only "sound" key, set to muted.
        monitor.CONFIG_FILE.write_text('{"sound": false}', encoding="utf-8")
        cfg = monitor.load_config()
        self.assertFalse(cfg["local"])
        # Telegram had no equivalent before, so it defaults on.
        self.assertTrue(cfg["telegram"])

    def test_explicit_local_wins_over_legacy_sound(self):
        # If both keys exist, the new "local" is authoritative.
        monitor.CONFIG_FILE.write_text(
            '{"sound": false, "local": true}', encoding="utf-8")
        self.assertTrue(monitor.load_config()["local"])

    def test_non_bool_values_coerced_to_on(self):
        monitor.CONFIG_FILE.write_text(
            '{"local": "yes", "telegram": 0}', encoding="utf-8")
        cfg = monitor.load_config()
        self.assertTrue(cfg["local"])
        self.assertTrue(cfg["telegram"])


class Goal7_ParseGeometry(unittest.TestCase):
    """parse_geometry must survive every geometry string Tk can emit — including
    the "+-609" off-screen-left form that used to crash the monitor on startup.
    """

    def test_normal_geometry(self):
        self.assertEqual(parse_geometry("300x200+40+60"), (300, 200, 40, 60))

    def test_off_screen_left_does_not_crash(self):
        # Regression: window dragged off the left edge → Tk reports "+-609".
        self.assertEqual(parse_geometry("300x200+-609+12"), (300, 200, -609, 12))

    def test_off_screen_top(self):
        self.assertEqual(parse_geometry("250x60+10+-40"), (250, 60, 10, -40))

    def test_minus_separator_keeps_sign(self):
        # "-50" separator (offset from the right edge) stays negative, as before.
        self.assertEqual(parse_geometry("300x200-50+34"), (300, 200, -50, 34))

    def test_malformed_returns_none(self):
        for bad in ("", "garbage", "300x200", "300x200+40", "axb+1+2"):
            self.assertIsNone(parse_geometry(bad), bad)


class Goal8_NotificationDebounce(unittest.TestCase):
    """A WORKING→WAITING flip must be confirmed by a second WAITING tick before
    notifying — Claude Code blips green for one tick between two tasks of the
    same turn, and that blip must not produce a toast.
    """

    def _fake_app(self):
        class Fake:
            def __init__(self):
                self._prev_status = {}
                self._working_since = {}
                self._pending_notify = {}
                self.notifications = []

            def _notify(self, label, elapsed, key=None):
                self.notifications.append((label, elapsed, key))

            def _dismiss_session_toast(self, key):
                pass

        return Fake()

    def _tick(self, app, status):
        monitor.MonitorApp._check_transitions(
            app, [{"key": "k1", "name": "nursy", "status": status}])

    def _backdate_work(self, app):
        # Pretend the WORKING stretch started long enough ago to qualify.
        app._working_since["k1"] -= monitor.NOTIFY_MIN_WORK_SEC + 5

    def test_green_blip_between_tasks_does_not_notify(self):
        app = self._fake_app()
        self._tick(app, "WORKING")
        self._backdate_work(app)
        self._tick(app, "WAITING")   # blip: armed, not fired yet
        self.assertEqual(app.notifications, [])
        self._tick(app, "WORKING")   # back to grey → pending discarded
        self.assertEqual(app._pending_notify, {})
        self._tick(app, "WAITING")   # second stretch too short to qualify
        self._tick(app, "WAITING")
        self.assertEqual(app.notifications, [])

    def test_sustained_waiting_notifies_on_second_tick(self):
        app = self._fake_app()
        self._tick(app, "WORKING")
        self._backdate_work(app)
        self._tick(app, "WAITING")
        self.assertEqual(app.notifications, [])
        self._tick(app, "WAITING")
        self.assertEqual(len(app.notifications), 1)
        label, elapsed, key = app.notifications[0]
        self.assertEqual(label, "nursy")
        self.assertEqual(key, "k1")
        self.assertGreaterEqual(elapsed, monitor.NOTIFY_MIN_WORK_SEC)
        self._tick(app, "WAITING")   # stays WAITING → no duplicate
        self.assertEqual(len(app.notifications), 1)

    def test_session_vanishing_discards_pending(self):
        app = self._fake_app()
        self._tick(app, "WORKING")
        self._backdate_work(app)
        self._tick(app, "WAITING")
        monitor.MonitorApp._check_transitions(app, [])  # session gone
        self.assertEqual(app._pending_notify, {})
        self.assertEqual(app.notifications, [])


# ---------------------------------------------------------------------------
# GOAL 9+ — Phase 2 state-file engine (shadow mode): scan_state_files()
# ---------------------------------------------------------------------------

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


class Goal9_StateFileVerdicts(StateFileTestBase):

    def test_working_state_maps_to_working(self):
        self._write_state("a", state="working")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual((s["status"], s["dot_color"], s["rank"]), ("WORKING", "#666", 2))

    def test_waiting_state_maps_to_waiting(self):
        self._write_state("a", state="waiting")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual((s["status"], s["dot_color"], s["rank"]), ("WAITING", "#4ade80", 1))

    def test_needs_input_state_maps_to_waiting_green_no_new_color(self):
        self._write_state("a", state="needs_input")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual((s["status"], s["dot_color"]), ("WAITING", "#4ade80"))

    def test_idle_state_maps_to_waiting(self):
        self._write_state("a", state="idle")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WAITING")

    def test_unknown_state_value_defaults_to_waiting(self):
        self._write_state("a", state="some-future-state")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WAITING")

    def test_shadow_dict_carries_every_key_scan_emits(self):
        self._write_state("a", state="working")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        scan_keys = {
            "key", "name", "session_id", "encoded_dir", "dot", "dot_color",
            "bg", "monitors", "agents", "status", "rank", "age", "mtime", "action",
        }
        self.assertTrue(scan_keys.issubset(s.keys()), s.keys())


class Goal10_StateFileRobustness(StateFileTestBase):
    """Nine broken-shape state files, each costing exactly one session —
    the tick (and every other valid session) must survive all of them
    (TEST-MATRIX case 20)."""

    def _labels(self) -> dict[str, str]:
        return {"keep": "L", "broken": "L"}

    def test_invalid_json_drops_only_that_session(self):
        self._write_state("keep", state="waiting")
        (self.root / "broken.json").write_text("{not valid json", encoding="utf-8")
        sessions = monitor.scan_state_files(sessionid_to_label=self._labels())
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_truncated_fragment_drops_only_that_session(self):
        self._write_state("keep", state="waiting")
        (self.root / "broken.json").write_text(
            '{"state": "working", "ts_ms":', encoding="utf-8")
        sessions = monitor.scan_state_files(sessionid_to_label=self._labels())
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_zero_byte_file_drops_only_that_session(self):
        self._write_state("keep", state="waiting")
        (self.root / "broken.json").write_text("", encoding="utf-8")
        sessions = monitor.scan_state_files(sessionid_to_label=self._labels())
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_json_array_instead_of_object_drops_only_that_session(self):
        self._write_state("keep", state="waiting")
        (self.root / "broken.json").write_text("[1, 2, 3]", encoding="utf-8")
        sessions = monitor.scan_state_files(sessionid_to_label=self._labels())
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_record_missing_state_key_resolves_to_waiting_default(self):
        self._write_state("a", omit=("state",))
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WAITING")

    def test_record_with_state_as_number_resolves_to_waiting_default(self):
        self._write_state("a", state=42)
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WAITING")

    def test_record_missing_ts_ms_falls_back_to_file_mtime(self):
        old_mtime = time.time() - 120
        self._write_state("a", omit=("ts_ms",), mtime=old_mtime)
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertAlmostEqual(s["age"], 120, delta=5)

    def test_non_json_file_in_directory_is_ignored(self):
        self._write_state("keep", state="waiting")
        (self.root / "notes.txt").write_text("hello", encoding="utf-8")
        sessions = monitor.scan_state_files(sessionid_to_label={"keep": "L"})
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_file_removed_between_glob_and_read_drops_only_that_session(self):
        self._write_state("keep", state="waiting")
        victim = self._write_state("victim", state="waiting")
        real_stat = Path.stat

        def flaky_stat(path_self, *a, **kw):
            if path_self == victim:
                if os.path.exists(victim):
                    os.unlink(victim)
                raise FileNotFoundError(victim)
            return real_stat(path_self, *a, **kw)

        with mock.patch.object(Path, "stat", flaky_stat):
            sessions = monitor.scan_state_files(
                sessionid_to_label={"keep": "L", "victim": "L"})
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_state_file_older_than_max_age_is_not_returned(self):
        old_mtime = time.time() - monitor.MAX_AGE_SEC - 10
        self._write_state("stale", state="waiting", mtime=old_mtime)
        sessions = monitor.scan_state_files(sessionid_to_label={"stale": "L"})
        self.assertEqual(sessions, [])

    def test_state_file_older_than_prune_age_is_unlinked_fresh_one_survives(self):
        old_mtime = time.time() - monitor.STATE_PRUNE_AGE_SEC - 10
        old_path = self._write_state("ancient", state="waiting", mtime=old_mtime)
        fresh_path = self._write_state("fresh", state="waiting")
        monitor.scan_state_files(sessionid_to_label={"ancient": "L", "fresh": "L"})
        self.assertFalse(old_path.exists())
        self.assertTrue(fresh_path.exists())


class Goal11_StateFileStaleness(StateFileTestBase):
    """A stale WORKING verdict recovers to WAITING via heartbeat silence +
    docker liveness cross-check — the named fallback for the Esc interrupt,
    the permission-denial dead end, the killed container and the abandoned
    pre-tool prompt (TEST-MATRIX cases 8, 5-deny, 9, 19)."""

    @staticmethod
    def _container_info(hostname_to_status: dict[str, str]) -> dict:
        return {"hostname_to_label": {}, "hostname_to_status": hostname_to_status}

    def test_fresh_working_record_stays_working(self):
        self._write_state("a", state="working", hostname="h1")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "running"}))
        self.assertEqual(s["status"], "WORKING")

    def test_stale_working_record_with_running_container_flips_waiting(self):
        old_ts = int((time.time() - monitor.STATE_HEARTBEAT_STALE_SEC - 5) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=old_ts,
                           last_event="PostToolUse")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "running"}))
        self.assertEqual(s["status"], "WAITING")

    def test_stale_working_record_with_paused_container_stays_working(self):
        old_ts = int((time.time() - monitor.STATE_HEARTBEAT_STALE_SEC - 5) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=old_ts,
                           last_event="PostToolUse")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "paused"}))
        self.assertEqual(s["status"], "WORKING")

    def test_stale_working_record_with_exited_container_flips_waiting(self):
        old_ts = int((time.time() - monitor.STATE_HEARTBEAT_STALE_SEC - 5) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=old_ts,
                           last_event="PostToolUse")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "exited"}))
        self.assertEqual(s["status"], "WAITING")

    def test_stale_working_record_with_unknown_container_status_flips_waiting(self):
        old_ts = int((time.time() - monitor.STATE_HEARTBEAT_STALE_SEC - 5) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=old_ts,
                           last_event="PostToolUse")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({}))
        self.assertEqual(s["status"], "WAITING")

    def test_stale_working_record_without_container_info_flips_waiting(self):
        old_ts = int((time.time() - monitor.STATE_HEARTBEAT_STALE_SEC - 5) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=old_ts,
                           last_event="PostToolUse")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WAITING")

    def test_working_record_with_user_prompt_submit_flips_after_shorter_window(self):
        ts = int((time.time() - 120) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=ts,
                           last_event="UserPromptSubmit")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "running"}))
        self.assertEqual(s["status"], "WAITING")

    def test_working_record_with_post_tool_use_at_same_age_stays_working(self):
        ts = int((time.time() - 120) * 1000)
        self._write_state("a", state="working", hostname="h1", ts_ms=ts,
                           last_event="PostToolUse")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "running"}))
        self.assertEqual(s["status"], "WORKING")

    def test_waiting_record_never_affected_by_silence(self):
        old_ts = int((time.time() - monitor.STATE_HEARTBEAT_STALE_SEC * 10) * 1000)
        self._write_state("a", state="waiting", hostname="h1", ts_ms=old_ts)
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({}))
        self.assertEqual(s["status"], "WAITING")


class Goal12_ContainerInfoShape(unittest.TestCase):
    """scan_containers()'s arity change (ENG-03): container_info carries
    both hostname maps even when the docker binary is absent, so the shape
    is provable without a docker install in this sandbox."""

    def test_scan_containers_returns_four_elements_with_container_info_maps(self):
        orig_which = shutil.which
        shutil.which = lambda name: None
        try:
            result = monitor.scan_containers()
        finally:
            shutil.which = orig_which
        self.assertEqual(len(result), 4)
        container_info = result[3]
        self.assertIn("hostname_to_label", container_info)
        self.assertIn("hostname_to_status", container_info)


class Goal13_HooklessFallback(unittest.TestCase):
    """The migration bridge (ENG-05, TEST-MATRIX case 21): a session legacy
    sees but that has no state file — a container running an image without
    the hooks installed — must not vanish from the shadow list."""

    def setUp(self) -> None:
        self._tmp_projects = TemporaryDirectory()
        self._tmp_state = TemporaryDirectory()
        self.projects_root = Path(self._tmp_projects.name)
        self.state_root = Path(self._tmp_state.name)
        self._orig_projects = monitor.PROJECTS_DIR
        self._orig_state = monitor.STATE_DIR
        monitor.PROJECTS_DIR = self.projects_root
        monitor.STATE_DIR = self.state_root

    def tearDown(self) -> None:
        monitor.PROJECTS_DIR = self._orig_projects
        monitor.STATE_DIR = self._orig_state
        self._tmp_projects.cleanup()
        self._tmp_state.cleanup()

    def _write_state(self, session_id: str, **fields) -> Path:
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
        f = self.state_root / f"{session_id}.json"
        f.write_text(json.dumps(record), encoding="utf-8")
        return f

    def test_state_file_and_disjoint_legacy_session_both_appear(self):
        self._write_state("a")
        _write_session(self.projects_root, "-workspace-b", [
            _assistant([_text_block()], session_id="b"),
        ])
        legacy = scan(sessionid_to_label={"b": "L"})
        sessions = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(sorted(s["key"] for s in sessions), ["a", "b"])

    def test_legacy_session_sharing_key_with_state_file_is_not_duplicated(self):
        self._write_state("a", state="working")
        _write_session(self.projects_root, "-workspace-a", [
            _assistant([_text_block()], session_id="a"),
        ])
        legacy = scan(sessionid_to_label={"a": "L"})
        sessions = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["status"], "WORKING")
        self.assertNotIn("legacy_origin", sessions[0])

    def test_no_state_files_merged_list_equals_legacy_entry_for_entry(self):
        _write_session(self.projects_root, "-workspace-b", [
            _assistant([_text_block()], session_id="b"),
        ])
        legacy = scan(sessionid_to_label={"b": "L"})
        sessions = monitor.scan_state_files(legacy_sessions=legacy)
        self.assertEqual([s["key"] for s in sessions], [s["key"] for s in legacy])

    def test_omitted_legacy_sessions_falls_back_to_internal_scan(self):
        _write_session(self.projects_root, "-workspace-b", [
            _assistant([_text_block()], session_id="b"),
        ])
        sessions = monitor.scan_state_files(sessionid_to_label={"b": "L"})
        self.assertEqual([s["key"] for s in sessions], ["b"])

    def test_carried_through_entries_marked_legacy_origin(self):
        _write_session(self.projects_root, "-workspace-b", [
            _assistant([_text_block()], session_id="b"),
        ])
        self._write_state("a")
        legacy = scan(sessionid_to_label={"b": "L"})
        sessions = monitor.scan_state_files(
            sessionid_to_label={"a": "L", "b": "L"}, legacy_sessions=legacy)
        by_key = {s["key"]: s for s in sessions}
        self.assertTrue(by_key["b"].get("legacy_origin"))
        self.assertNotIn("legacy_origin", by_key["a"])


class Goal6e_AliasKeyParityAcrossEngines(unittest.TestCase):
    """The legacy engine and the state-file engine must derive the SAME
    alias identity for the same container, so a label set in default mode
    (legacy-rendered) shows in --state-files diagnostic mode too."""

    def setUp(self) -> None:
        self._tmp_projects = TemporaryDirectory()
        self._tmp_state = TemporaryDirectory()
        self.projects_root = Path(self._tmp_projects.name)
        self.state_root = Path(self._tmp_state.name)
        self._orig_projects = monitor.PROJECTS_DIR
        self._orig_state = monitor.STATE_DIR
        monitor.PROJECTS_DIR = self.projects_root
        monitor.STATE_DIR = self.state_root

    def tearDown(self) -> None:
        monitor.PROJECTS_DIR = self._orig_projects
        monitor.STATE_DIR = self._orig_state
        self._tmp_projects.cleanup()
        self._tmp_state.cleanup()

    def _write_state(self, session_id: str, **fields) -> Path:
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
        f = self.state_root / f"{session_id}.json"
        f.write_text(json.dumps(record), encoding="utf-8")
        return f

    def test_state_file_row_alias_key_from_hostname(self):
        self._write_state("a", hostname="c1")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"}, legacy_sessions=[])
        self.assertEqual(s["alias_key"], "host:c1")

    def test_state_file_row_without_hostname_falls_back_to_session_id(self):
        self._write_state("a", hostname=None)
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"}, legacy_sessions=[])
        self.assertEqual(s["alias_key"], "a")

    def test_parity_legacy_and_state_file_rows_share_alias_key(self):
        _write_session(self.projects_root, "-workspace-a", [
            _assistant([_text_block()], session_id="a"),
        ])
        self._write_state("a", hostname="c1")
        container_info = {"sessionid_to_hostname": {"a": "c1"}}
        legacy = scan(sessionid_to_label={"a": "L"}, container_info=container_info)
        shadow = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, container_info=container_info,
            legacy_sessions=legacy)
        self.assertEqual(legacy[0]["alias_key"], shadow[0]["alias_key"])
        self.assertEqual(legacy[0]["alias_key"], "host:c1")

    def test_carried_through_legacy_row_keeps_its_alias_key(self):
        _write_session(self.projects_root, "-workspace-b", [
            _assistant([_text_block()], session_id="b"),
        ])
        container_info = {"sessionid_to_hostname": {"b": "c2"}}
        legacy = scan(sessionid_to_label={"b": "L"}, container_info=container_info)
        sessions = monitor.scan_state_files(
            sessionid_to_label={"b": "L"}, container_info=container_info,
            legacy_sessions=legacy)
        [s] = sessions
        self.assertTrue(s.get("legacy_origin"))
        self.assertEqual(s["alias_key"], "host:c2")

    def test_diagnostic_mode_internal_scan_forwards_container_info(self):
        """scan_state_files() with legacy_sessions=None (the --state-files
        diagnostic path) must forward container_info to its internal scan()
        call, or carried-through rows would key their aliases differently
        from the default-mode legacy list."""
        _write_session(self.projects_root, "-workspace-b", [
            _assistant([_text_block()], session_id="b"),
        ])
        container_info = {"sessionid_to_hostname": {"b": "c2"}}
        sessions = monitor.scan_state_files(
            sessionid_to_label={"b": "L"}, container_info=container_info)
        [s] = sessions
        self.assertEqual(s["alias_key"], "host:c2")


# ---------------------------------------------------------------------------
# GOAL 14-16 — Divergence records must be decisive, episodic, and bounded
# ---------------------------------------------------------------------------

def _legacy_rec(key: str = "s1", status: str = "WORKING", **overrides) -> dict:
    rec = {
        "key": key, "session_id": key, "name": "L", "status": status,
        "action": "🔧 Bash", "working_locked": True, "auq_locked": False,
        "bg": True, "monitors": 1, "agents": 0, "age": 12.3,
    }
    rec.update(overrides)
    return rec


def _shadow_rec(key: str = "s1", status: str = "WAITING", **overrides) -> dict:
    rec = {
        "key": key, "session_id": key, "name": "L", "status": status,
        "state": "waiting", "last_event": "Stop", "hostname": "container-1",
        "background_tasks_count": 0, "age": 5.0,
    }
    rec.update(overrides)
    return rec


class DivergenceLogTestBase(unittest.TestCase):
    """Wire a temp DIVERGENCE_LOG into the monitor module for each test."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig_log = monitor.DIVERGENCE_LOG
        monitor.DIVERGENCE_LOG = Path(self._tmp.name) / "monitor-divergence.log"

    def tearDown(self) -> None:
        monitor.DIVERGENCE_LOG = self._orig_log
        self._tmp.cleanup()


class Goal14_DivergenceRecords(DivergenceLogTestBase):
    """diff_verdicts() must carry enough context for a reviewer to judge
    which engine was right, without pre-judging it itself (D-04)."""

    def test_agreement_yields_zero_records(self):
        legacy = [_legacy_rec(status="WAITING")]
        shadow = [_shadow_rec(status="WAITING")]
        self.assertEqual(monitor.diff_verdicts(legacy, shadow, 1000.0), [])

    def test_disagreement_yields_one_decisive_record(self):
        legacy = [_legacy_rec(status="WORKING")]
        shadow = [_shadow_rec(status="WAITING")]
        [rec] = monitor.diff_verdicts(legacy, shadow, 1000.0)
        self.assertEqual(rec["legacy_verdict"], "WORKING")
        self.assertEqual(rec["state_file_verdict"], "WAITING")
        self.assertEqual(rec["last_event"], "Stop")
        self.assertEqual(rec["state"], "waiting")
        self.assertEqual(rec["hostname"], "container-1")
        self.assertEqual(rec["background_tasks_count"], 0)
        self.assertEqual(rec["age_sec"], 5.0)
        self.assertEqual(rec["tick"], 1000.0)
        self.assertEqual(rec["session_id"], "s1")
        self.assertTrue(rec["legacy_evidence"])
        self.assertIn("action=", rec["legacy_evidence"])
        for field in ("likely_cause", "winner", "severity"):
            self.assertNotIn(field, rec)

    def test_legacy_only_key_yields_absent_state_file_verdict(self):
        legacy = [_legacy_rec(status="WAITING")]
        [rec] = monitor.diff_verdicts(legacy, [], 1000.0)
        self.assertEqual(rec["legacy_verdict"], "WAITING")
        self.assertEqual(rec["state_file_verdict"], "ABSENT")

    def test_shadow_only_key_yields_absent_legacy_verdict(self):
        shadow = [_shadow_rec(status="WORKING")]
        [rec] = monitor.diff_verdicts([], shadow, 1000.0)
        self.assertEqual(rec["legacy_verdict"], "ABSENT")
        self.assertEqual(rec["legacy_evidence"], "ABSENT")

    def test_two_empty_lists_yield_zero_records(self):
        self.assertEqual(monitor.diff_verdicts([], [], 1000.0), [])

    def test_multi_session_records_sorted_by_key(self):
        legacy = [_legacy_rec(key="b", status="WORKING"),
                  _legacy_rec(key="a", status="WORKING")]
        shadow = [_shadow_rec(key="b", status="WAITING"),
                  _shadow_rec(key="a", status="WAITING")]
        records = monitor.diff_verdicts(legacy, shadow, 1000.0)
        self.assertEqual([r["key"] for r in records], ["a", "b"])


class Goal15_DivergenceEpisodes(DivergenceLogTestBase):
    """filter_divergence_events() collapses a persisting disagreement to one
    opening and one closing record instead of one line every tick (D-02)."""

    def test_same_disagreement_across_three_ticks_writes_one_diverged_event(self):
        legacy = [_legacy_rec(status="WORKING")]
        shadow = [_shadow_rec(status="WAITING")]

        records1 = monitor.diff_verdicts(legacy, shadow, 1000.0)
        events1, state1 = monitor.filter_divergence_events(records1, None, 1000.0)
        self.assertEqual(len(events1), 1)
        self.assertEqual(events1[0]["event"], "diverged")

        records2 = monitor.diff_verdicts(legacy, shadow, 1005.0)
        events2, state2 = monitor.filter_divergence_events(records2, state1, 1005.0)
        self.assertEqual(events2, [])

        records3 = monitor.diff_verdicts(legacy, shadow, 1010.0)
        events3, state3 = monitor.filter_divergence_events(records3, state2, 1010.0)
        self.assertEqual(events3, [])
        self.assertEqual(state3["s1"]["ticks"], 3)

    def test_change_of_verdict_pair_mid_episode_writes_second_diverged(self):
        legacy = [_legacy_rec(status="WORKING")]
        shadow = [_shadow_rec(status="WAITING")]
        records1 = monitor.diff_verdicts(legacy, shadow, 1000.0)
        events1, state1 = monitor.filter_divergence_events(records1, None, 1000.0)
        self.assertEqual(len(events1), 1)

        shadow_changed = [_shadow_rec(status="IDLE")]
        records2 = monitor.diff_verdicts(legacy, shadow_changed, 1005.0)
        events2, state2 = monitor.filter_divergence_events(records2, state1, 1005.0)
        self.assertEqual(len(events2), 1)
        self.assertEqual(events2[0]["event"], "diverged")
        self.assertEqual(state2["s1"]["ticks"], 1)

    def test_return_to_agreement_writes_one_resolved_with_ticks_greater_than_one(self):
        legacy = [_legacy_rec(status="WORKING")]
        shadow = [_shadow_rec(status="WAITING")]
        records1 = monitor.diff_verdicts(legacy, shadow, 1000.0)
        events1, state1 = monitor.filter_divergence_events(records1, None, 1000.0)
        records2 = monitor.diff_verdicts(legacy, shadow, 1005.0)
        events2, state2 = monitor.filter_divergence_events(records2, state1, 1005.0)
        records3 = monitor.diff_verdicts(legacy, shadow, 1010.0)
        events3, state3 = monitor.filter_divergence_events(records3, state2, 1010.0)
        self.assertEqual(state3["s1"]["ticks"], 3)

        shadow_agree = [_shadow_rec(status="WORKING")]
        records4 = monitor.diff_verdicts(legacy, shadow_agree, 1015.0)
        self.assertEqual(records4, [])
        events4, state4 = monitor.filter_divergence_events(records4, state3, 1015.0)
        self.assertEqual(len(events4), 1)
        self.assertEqual(events4[0]["event"], "resolved")
        self.assertGreater(events4[0]["ticks"], 1)
        self.assertEqual(events4[0]["ticks"], 3)
        self.assertEqual(state4, {})

    def test_session_disappearing_while_diverging_also_resolves(self):
        legacy = [_legacy_rec(status="WORKING")]
        shadow = [_shadow_rec(status="WAITING")]
        records1 = monitor.diff_verdicts(legacy, shadow, 1000.0)
        events1, state1 = monitor.filter_divergence_events(records1, None, 1000.0)

        records_end = monitor.diff_verdicts([], [], 1005.0)
        self.assertEqual(records_end, [])
        events_end, state_end = monitor.filter_divergence_events(records_end, state1, 1005.0)
        self.assertEqual(len(events_end), 1)
        self.assertEqual(events_end[0]["event"], "resolved")
        self.assertEqual(state_end, {})


class Goal16_DivergenceLogGuard(DivergenceLogTestBase):
    """The divergence log can't grow unbounded, a write can't break a tick,
    and evidence never carries raw prompt/tool-input content (T-02-17/18/19)."""

    def test_log_over_threshold_is_truncated_with_marker_first(self):
        monitor.DIVERGENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        monitor.DIVERGENCE_LOG.write_text(
            "x" * (monitor.DIVERGENCE_LOG_MAX_BYTES + 1), encoding="utf-8")
        monitor.write_divergences([{"event": "diverged", "key": "s1"}])
        lines = monitor.DIVERGENCE_LOG.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 2)
        marker = json.loads(lines[0])
        self.assertEqual(marker["event"], "_truncated")
        rec = json.loads(lines[1])
        self.assertEqual(rec["key"], "s1")

    def test_write_to_unwritable_path_raises_nothing(self):
        blocker = Path(self._tmp.name) / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monitor.DIVERGENCE_LOG = blocker / "sub" / "monitor-divergence.log"
        try:
            monitor.write_divergences([{"event": "diverged", "key": "s1"}])
        except OSError:
            self.fail("write_divergences raised OSError instead of swallowing it")

    def test_no_legacy_evidence_contains_raw_prompt_or_tool_input_text(self):
        secret = "SUPER-SECRET-PROMPT-TEXT-DO-NOT-LEAK"
        with TemporaryDirectory() as proj_root_str:
            proj_root = Path(proj_root_str)
            orig_projects = monitor.PROJECTS_DIR
            monitor.PROJECTS_DIR = proj_root
            try:
                _write_session(proj_root, "-workspace-app", [
                    _user_prompt(secret, session_id="s1"),
                ])
                legacy = scan(sessionid_to_label={"s1": "L"})
            finally:
                monitor.PROJECTS_DIR = orig_projects
        shadow = [_shadow_rec(key="s1", status="WAITING")]
        records = monitor.diff_verdicts(legacy, shadow, 1000.0)
        self.assertTrue(records)
        for rec in records:
            self.assertNotIn(secret, rec["legacy_evidence"])


# ---------------------------------------------------------------------------
# GOAL 17 — --state-files is a diagnostic mode, never the default path (D-01)
# ---------------------------------------------------------------------------

class Goal17_StateFilesMode(unittest.TestCase):

    def test_flag_absent_returns_false(self):
        self.assertFalse(monitor.state_files_mode(["monitor.py"]))

    def test_flag_present_returns_true(self):
        self.assertTrue(monitor.state_files_mode(["monitor.py", "--state-files"]))

    def test_empty_argv_returns_false(self):
        self.assertFalse(monitor.state_files_mode([]))

    def test_select_render_sessions_identity_reasserted(self):
        legacy = ["legacy"]
        shadow = ["shadow"]
        self.assertIs(monitor.select_render_sessions(legacy, shadow, False), legacy)
        self.assertIs(monitor.select_render_sessions(legacy, shadow, True), shadow)


# ---------------------------------------------------------------------------
# GOAL 18 — Docker rows show the container name when it disambiguates a
# duplicate project, else fall back to the project label (display-only)
# ---------------------------------------------------------------------------

class Goal18_ContainerDisplayName(unittest.TestCase):

    def test_suffixed_duplicate_name_is_displayed(self):
        row = {"project": "dev-tools", "name": "dev-tools-2", "status": "Up"}
        self.assertEqual(monitor.container_display_name(row), "dev-tools-2")

    def test_exact_match_name_looks_like_today(self):
        row = {"project": "dev-tools", "name": "dev-tools", "status": "Up"}
        self.assertEqual(monitor.container_display_name(row), "dev-tools")

    def test_docker_random_name_falls_back_to_project_label(self):
        row = {"project": "dev-tools", "name": "dreamy_bose", "status": "Up"}
        self.assertEqual(monitor.container_display_name(row), "dev-tools")


if __name__ == "__main__":
    unittest.main()
