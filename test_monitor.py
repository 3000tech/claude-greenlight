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


def _monitor_started_result(tool_use_id: str, task_id: str,
                            session_id: str = "s1") -> str:
    """The synchronous tool_result Claude Code emits when a Monitor tool
    task starts watching — wires tool_use_id -> task_id the same way
    shell_tracker.count_active_monitors's MONITOR_RESULT_RE anchor did,
    now ported into monitor.py's _peek_agent_activity()."""
    return _line({
        "type": "user",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_result", "tool_use_id": tool_use_id,
            "content": f"Monitor started (task {task_id}) watching for a match",
        }]},
    })


def _task_stop(task_id: str, tool_id: str = "tu_stop",
              session_id: str = "s1") -> str:
    """A TaskStop tool_use terminating a Monitor (or bg shell) task_id."""
    return _line({
        "type": "assistant",
        "sessionId": session_id,
        "message": {"content": [{
            "type": "tool_use", "id": tool_id, "name": "TaskStop",
            "input": {"task_id": task_id},
        }]},
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
# GOAL 2h/2i (shell_tracker.py, D-03) retired at the flip: the bg-shell/
# Ctrl+B badge parser is deleted along with its two test classes. The
# user-facing guarantee they protected ("a live background shell never pins
# WORKING by itself") is re-asserted on state-file fixtures instead — see
# Goal21_UnifiedBadge below, which proves the badge is driven solely by the
# hook-captured background_tasks_count and never by status.
# ---------------------------------------------------------------------------


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
        self.assertEqual(len(result), 5)
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
    "local" mutes audio only on this machine (quick-260818-bfm narrowed its
    scope — the toast and the taskbar flash always fire regardless of it)
    and "telegram" governs the phone push. A pre-split config carrying only
    the old "sound" key migrates into "local".
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
        # The migration is now semantically exact: the legacy key gated audio
        # only, and so does "local" after quick-260818-bfm narrowed its scope.
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

    def setUp(self) -> None:
        # _check_transitions now logs every notification decision
        # (quick-260807-iz2 Task 3) — repoint NOTIFICATIONS_LOG so this
        # suite never writes to the developer's real ~/.claude.
        self._tmp = TemporaryDirectory()
        self._orig_log = monitor.NOTIFICATIONS_LOG
        monitor.NOTIFICATIONS_LOG = Path(self._tmp.name) / "notifications.log"

    def tearDown(self) -> None:
        monitor.NOTIFICATIONS_LOG = self._orig_log
        self._tmp.cleanup()

    def _fake_app(self):
        class Fake:
            def __init__(self):
                self._prev_status = {}
                self._working_since = {}
                self._pending_notify = {}
                # Attributes the group-gate wiring in _check_transitions
                # touches (quick-260807-iz2 Task 3): an empty hold register,
                # an empty alias map, an identity alias-key resolver, and a
                # config dict (group_gate defaults True but this fixture has
                # no cwd on its sessions, so the gate is always inert here).
                self._notify_hold = {}
                self._session_aliases = {}
                self.config = {}
                self.notifications = []

            def _alias_key(self, key):
                return key

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

    def test_minimum_work_threshold_is_60_seconds(self):
        """Plan 03-03 Task 3 Test 3 (D-07 preserved fix): the deliberate
        60-second minimum-work notification threshold is unchanged by the
        flip — this class (which exercises it end to end above) stays
        present and green as the primary coverage; this pins the constant
        itself so a future edit can't drift it silently."""
        self.assertEqual(monitor.NOTIFY_MIN_WORK_SEC, 60)


# ---------------------------------------------------------------------------
# GOAL 9+ — Phase 2 state-file engine (shadow mode): scan_state_files()
# ---------------------------------------------------------------------------

class StateFileTestBase(unittest.TestCase):
    """Wire a temp STATE_DIR into the monitor module for each test.

    WR-03: also repoints PROJECTS_DIR to an empty temp directory. Any test
    derived from this base that calls monitor.scan_state_files(...) without
    an explicit legacy_sessions= argument (the large majority) triggers the
    internal fallback that walks PROJECTS_DIR — without this, that fallback
    would silently read the REAL (unmocked) ~/.claude/projects on whatever
    machine runs the suite, the same isolation Goal13_HooklessFallback and
    Goal6e_AliasKeyParityAcrossEngines already apply locally. Pointing it at
    a real-but-empty temp dir (rather than passing legacy_sessions=[]
    everywhere) keeps every existing call site — explicit or not —
    hermetic with zero call-site changes.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._tmp_projects = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.projects_root = Path(self._tmp_projects.name)
        self._orig_state_dir = monitor.STATE_DIR
        self._orig_projects_dir = monitor.PROJECTS_DIR
        monitor.STATE_DIR = self.root
        monitor.PROJECTS_DIR = self.projects_root

    def tearDown(self) -> None:
        monitor.STATE_DIR = self._orig_state_dir
        monitor.PROJECTS_DIR = self._orig_projects_dir
        self._tmp.cleanup()
        self._tmp_projects.cleanup()

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
            "status", "rank", "age", "mtime", "action",
        }
        self.assertTrue(scan_keys.issubset(s.keys()), s.keys())
        # D-03: shell_tracker's counters are gone from both engines' rows —
        # the badge's only source is background_tasks_count.
        self.assertEqual(set(s) & {"bg", "monitors", "agents"}, set())


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
    docker liveness cross-check — the named fallback for the permission-
    denial dead end, the killed container and the abandoned pre-tool
    prompt (TEST-MATRIX cases 5-deny, 9, 19). D-02a (Esc interrupt, case 8)
    and D-02b (hook-silence pin, divergence class 6) extend the same
    staleness block — see the tests below."""

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

    def test_working_record_with_clock_ahead_ts_ms_still_flips_stale(self):
        """WR-04: a container clock skewed far AHEAD of the host would make
        a raw ts_ms-derived age under-report indefinitely — a session dead
        for well past the heartbeat window must still recover to WAITING,
        not stay pinned WORKING forever because ts_ms claims it's fresh.
        The file's own (host-clock) mtime is genuinely old here, same as
        every other staleness test in this class — only ts_ms lies."""
        old_mtime = time.time() - monitor.STATE_HEARTBEAT_STALE_SEC - 5
        future_ts = int((time.time() + 3600) * 1000)  # container clock 1h ahead
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=future_ts, last_event="PostToolUse",
                           mtime=old_mtime)
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"},
            container_info=self._container_info({"h1": "running"}))
        self.assertEqual(s["status"], "WAITING")

    # -----------------------------------------------------------------
    # D-02a/D-02b fallbacks (plan 03-02 task 2): both read a hand-built
    # `legacy_sessions` list rather than exercising scan() — these are
    # unit tests of the fallback wiring; the peek and lock computation
    # have their own coverage in Goal22_AgentActivityPeek.
    # -----------------------------------------------------------------

    def test_esc_interrupt_early_recovery_with_newer_legacy_mtime(self):
        """D-02a Test 1: aged between the prompt-stale and heartbeat
        windows, a legacy counterpart with working_locked False and a
        jsonl mtime newer than the record's own recovers early."""
        record_mtime = time.time() - 150  # inside (90s, 600s]
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolBatch", mtime=record_mtime)
        legacy = [{"key": "a", "session_id": "a", "working_locked": False,
                   "mtime": record_mtime + 30, "agent_activity": False}]
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(s["status"], "WAITING")

    def test_esc_interrupt_guard_working_locked_true_stays_working(self):
        """D-02a Test 2: same shape, but the legacy counterpart's
        working_locked is True — no early recovery, stays WORKING until
        the normal window elapses."""
        record_mtime = time.time() - 150
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolBatch", mtime=record_mtime)
        legacy = [{"key": "a", "session_id": "a", "working_locked": True,
                   "mtime": record_mtime + 30, "agent_activity": False}]
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(s["status"], "WORKING")

    def test_esc_interrupt_guard_no_legacy_match_stays_working(self):
        """D-02a Test 3: no matching legacy entry at all (hookless or
        jsonl-invisible session) — absence of evidence never triggers
        early recovery."""
        record_mtime = time.time() - 150
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolBatch", mtime=record_mtime)
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=[])
        self.assertEqual(s["status"], "WORKING")

    def test_hook_silence_pin_with_agent_activity_stays_working(self):
        """D-02b Test 4: past the heartbeat window, a legacy counterpart
        reporting agent_activity True suppresses the WAITING transition."""
        record_mtime = time.time() - (monitor.STATE_HEARTBEAT_STALE_SEC + 60)
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolUse", mtime=record_mtime)
        legacy = [{"key": "a", "session_id": "a", "working_locked": False,
                   "mtime": record_mtime, "agent_activity": True}]
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(s["status"], "WORKING")

    def test_hook_silence_pin_with_working_locked_stays_working(self):
        """D-02b Test 5: same, but working_locked True is the pinning
        signal instead of agent_activity."""
        record_mtime = time.time() - (monitor.STATE_HEARTBEAT_STALE_SEC + 60)
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolUse", mtime=record_mtime)
        legacy = [{"key": "a", "session_id": "a", "working_locked": True,
                   "mtime": record_mtime, "agent_activity": False}]
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(s["status"], "WORKING")

    def test_hook_silence_pin_with_neither_signal_flips_waiting(self):
        """D-02b Test 6: neither pin signal present — flips to WAITING
        exactly as today."""
        record_mtime = time.time() - (monitor.STATE_HEARTBEAT_STALE_SEC + 60)
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolUse", mtime=record_mtime)
        legacy = [{"key": "a", "session_id": "a", "working_locked": False,
                   "mtime": record_mtime, "agent_activity": False}]
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        self.assertEqual(s["status"], "WAITING")

    def test_paused_container_wins_over_fallback_evidence(self):
        """Test 7: the existing paused-container exception still
        suppresses the WAITING transition regardless of any fallback
        evidence (neither pin signal present, yet paused wins)."""
        record_mtime = time.time() - (monitor.STATE_HEARTBEAT_STALE_SEC + 60)
        self._write_state("a", state="working", hostname="h1",
                           ts_ms=int(record_mtime * 1000),
                           last_event="PostToolUse", mtime=record_mtime)
        legacy = [{"key": "a", "session_id": "a", "working_locked": False,
                   "mtime": record_mtime, "agent_activity": False}]
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "L"}, legacy_sessions=legacy,
            container_info=self._container_info({"h1": "paused"}))
        self.assertEqual(s["status"], "WORKING")

    def test_paused_container_session_visible_via_hostname_label_ordinary_row(self):
        """Plan 03-03 Task 3 Test 2 (D-05): a session whose label resolves
        ONLY through container_info['hostname_to_label'] — sessionid_to_label
        doesn't know it, because docker exec can't reach a paused container
        — still appears in the returned list as an ordinary row: status,
        dot_color and rank are drawn from the same set a non-paused waiting
        record produces (the Goal9_StateFileVerdicts baseline), no value or
        color unique to paused rows. Discretionary choice per CONTEXT.md:
        normal row, not dimmed — the least-surprising reading of "no new
        colors, no new notification types."""
        self._write_state("a", state="waiting", hostname="h1")
        container_info = {
            "hostname_to_label": {"h1": "myproj"},
            "hostname_to_status": {"h1": "paused"},
        }
        [s] = monitor.scan_state_files(sessionid_to_label={}, container_info=container_info)
        self.assertEqual(s["name"], "myproj")
        self.assertEqual((s["status"], s["dot_color"], s["rank"]), ("WAITING", "#4ade80", 1))

    def test_fallback_evidence_comes_from_passed_legacy_list_not_fresh_io(self):
        """No second jsonl read or lock-file stat: repoint PROJECTS_DIR
        and WORKING_LOCK_DIR at paths that don't exist, pass an explicit
        legacy_sessions list, and the pinned verdict still comes through —
        proving the evidence came from the list, not fresh I/O."""
        orig_projects = monitor.PROJECTS_DIR
        orig_wlock = monitor.WORKING_LOCK_DIR
        monitor.PROJECTS_DIR = self.root / "does-not-exist-projects"
        monitor.WORKING_LOCK_DIR = self.root / "does-not-exist-locks"
        try:
            record_mtime = time.time() - (monitor.STATE_HEARTBEAT_STALE_SEC + 60)
            self._write_state("a", state="working", hostname="h1",
                               ts_ms=int(record_mtime * 1000),
                               last_event="PostToolUse", mtime=record_mtime)
            legacy = [{"key": "a", "session_id": "a", "working_locked": True,
                       "mtime": record_mtime, "agent_activity": False}]
            [s] = monitor.scan_state_files(
                sessionid_to_label={"a": "L"}, legacy_sessions=legacy)
        finally:
            monitor.PROJECTS_DIR = orig_projects
            monitor.WORKING_LOCK_DIR = orig_wlock
        self.assertEqual(s["status"], "WORKING")


class Goal12_ContainerInfoShape(unittest.TestCase):
    """scan_containers()'s arity change (ENG-03): container_info carries
    both hostname maps even when the docker binary is absent, so the shape
    is provable without a docker install in this sandbox."""

    def test_scan_containers_returns_five_elements_with_container_info_maps(self):
        orig_which = shutil.which
        shutil.which = lambda name: None
        try:
            result = monitor.scan_containers()
        finally:
            shutil.which = orig_which
        self.assertEqual(len(result), 5)
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


# ---------------------------------------------------------------------------
# GOAL 24 — SessionEnd tombstones suppress ghost rows (D-06) and orphaned
# atomic-write temp files sweep themselves (D-08/T-03-03).
# ---------------------------------------------------------------------------

class Goal24_SessionEndTombstones(StateFileTestBase):

    def _write_tombstone(self, session_id: str, mtime: float | None = None) -> Path:
        f = self.root / f"{session_id}{monitor.STATE_TOMBSTONE_SUFFIX}"
        f.write_text("", encoding="utf-8")
        if mtime is not None:
            os.utime(f, (mtime, mtime))
        return f

    def test_tombstoned_legacy_session_is_not_carried_through_bridge(self):
        """Test 3: a legacy session whose key matches a live tombstone is
        excluded from the legacy_origin bridge."""
        self._write_tombstone("s1")
        legacy = [{"key": "s1", "session_id": "s1", "name": "L",
                   "status": "WAITING", "mtime": time.time(),
                   "working_locked": False, "agent_activity": False}]
        sessions = monitor.scan_state_files(legacy_sessions=legacy)
        self.assertEqual([s["key"] for s in sessions if s["key"] == "s1"], [])

    def test_legacy_session_without_tombstone_still_bridges(self):
        """Test 4: the D-02c hookless bridge is unaffected when no
        tombstone exists for that session."""
        legacy = [{"key": "s1", "session_id": "s1", "name": "L",
                   "status": "WAITING", "mtime": time.time(),
                   "working_locked": False, "agent_activity": False}]
        sessions = monitor.scan_state_files(legacy_sessions=legacy)
        [s] = sessions
        self.assertEqual(s["key"], "s1")
        self.assertTrue(s.get("legacy_origin"))

    def test_stale_tombstone_unlinked_fresh_one_kept(self):
        """Test 5: a tombstone older than STATE_PRUNE_AGE_SEC is unlinked
        by the sweep; one younger than that survives."""
        old = self._write_tombstone(
            "ancient", mtime=time.time() - monitor.STATE_PRUNE_AGE_SEC - 10)
        fresh = self._write_tombstone("fresh")
        monitor.scan_state_files(legacy_sessions=[])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_stale_temp_file_unlinked_fresh_one_kept(self):
        """Test 6: a leftover atomic-write temp file older than
        STATE_PRUNE_AGE_SEC is swept; a freshly-created one is untouched."""
        old_tmp = self.root / "s1.json.tmp.12345"
        old_tmp.write_text('{"state": "waiting"}', encoding="utf-8")
        os.utime(old_tmp, (time.time() - monitor.STATE_PRUNE_AGE_SEC - 10,) * 2)
        fresh_tmp = self.root / "s2.json.tmp.67890"
        fresh_tmp.write_text('{"state": "waiting"}', encoding="utf-8")
        monitor.scan_state_files(legacy_sessions=[])
        self.assertFalse(old_tmp.exists())
        self.assertTrue(fresh_tmp.exists())

    def test_tombstone_never_appears_as_a_session_row(self):
        """Test 7: a tombstone is not picked up by the state-record glob —
        it can never render as a session, with or without a matching
        legacy entry."""
        self._write_tombstone("ghost")
        self._write_state("keep", state="waiting")
        legacy = [{"key": "ghost", "session_id": "ghost", "name": "L",
                   "status": "WAITING", "mtime": time.time(),
                   "working_locked": False, "agent_activity": False}]
        sessions = monitor.scan_state_files(
            sessionid_to_label={"keep": "L"}, legacy_sessions=legacy)
        self.assertEqual([s["key"] for s in sessions], ["keep"])

    def test_resumed_session_deletes_its_own_stale_tombstone(self):
        """A live state record for a session id proves it's a resumed
        session, not a stale end-of-session marker — the tombstone must
        not survive to suppress a future bridge entry for the same id."""
        tombstone = self._write_tombstone("s1")
        self._write_state("s1", state="waiting")
        monitor.scan_state_files(sessionid_to_label={"s1": "L"})
        self.assertFalse(tombstone.exists())


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

    def test_sessionid_rotation_keeps_same_alias_key_on_state_files(self):
        """Plan 03-03 Task 3 Test 1 (D-07, the one confirmed Goal6d gap):
        the state-file equivalent of test_sessionid_rotation_keeps_same_alias_key
        — two state records with DIFFERENT session ids (a /clear rotation)
        but the SAME container hostname resolve to the same alias key, so a
        label set before the rotation survives it."""
        self._write_state("s1", hostname="c1")
        self._write_state("s2", hostname="c1")
        sessions = monitor.scan_state_files(
            sessionid_to_label={"s1": "L", "s2": "L"}, legacy_sessions=[])
        self.assertEqual({s["key"] for s in sessions}, {"s1", "s2"})
        alias_keys = {s["alias_key"] for s in sessions}
        self.assertEqual(alias_keys, {"host:c1"})

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
# GOAL 17 — select_render_sessions() is the one-argument identity seam the
# engine's output reaches rendering through; --state-files is inert (D-01/D-08)
# ---------------------------------------------------------------------------

class Goal17_RenderSeam(unittest.TestCase):

    def test_select_render_sessions_identity_reasserted(self):
        rows = ["a", "b"]
        self.assertIs(monitor.select_render_sessions(rows), rows)

    def test_no_flag_resolver_remains(self):
        self.assertFalse(hasattr(monitor, "state_files_mode"))


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

    def test_empty_or_missing_name_falls_back_to_project_label(self):
        row_empty = {"project": "dev-tools", "name": "", "status": "Up"}
        row_missing = {"project": "dev-tools", "status": "Up"}
        self.assertEqual(monitor.container_display_name(row_empty), "dev-tools")
        self.assertEqual(monitor.container_display_name(row_missing), "dev-tools")

    def test_shared_head_shorter_than_project_label_is_not_a_prefix_match(self):
        row = {"project": "dev-tools", "name": "dev", "status": "Up"}
        self.assertEqual(monitor.container_display_name(row), "dev-tools")

    def test_unrelated_container_sharing_a_character_prefix_is_not_a_suffix_match(self):
        """WR-05: a bare str.startswith has no word-boundary check —
        an unrelated docker-generated container name that merely begins
        with the same characters as the project label (e.g. "devops" vs
        project "dev") must NOT be treated as a disambiguating
        launcher-suffixed duplicate."""
        row = {"project": "dev", "name": "devops", "status": "Up"}
        self.assertEqual(monitor.container_display_name(row), "dev")

    def test_helper_does_not_mutate_the_row_dict(self):
        row = {"project": "dev-tools", "name": "dev-tools-2", "status": "Up"}
        before = dict(row)
        monitor.container_display_name(row)
        self.assertEqual(row, before)

    def test_same_project_pair_produces_distinct_text_and_shared_identity(self):
        row_a = {"project": "dev-tools", "name": "dev-tools", "status": "Up"}
        row_b = {"project": "dev-tools", "name": "dev-tools-2", "status": "Up"}
        display_a = monitor.container_display_name(row_a)
        display_b = monitor.container_display_name(row_b)
        self.assertNotEqual(display_a, display_b)
        self.assertEqual(row_a["project"], row_b["project"])


# ---------------------------------------------------------------------------
# GOAL 19 — Session rows and compact chips disambiguate a duplicate-project
# container the same way the docker row does (display-only)
# ---------------------------------------------------------------------------

class Goal19_SessionDisplayName(MonitorTestBase):
    """Two containers of the same project used to draw two identical session
    rows/chips reading the project label. session_display_name() reuses
    container_display_name()'s prefix rule so the second container's session
    renders `dev-tools-2` while `s["name"]` (identity: sort key, divergence
    log, alias) stays the pure project label `dev-tools`."""

    @staticmethod
    def _scan_containers_two_dev_tools():
        """Mock docker ps/inspect for two `dev-tools` containers and call the
        real scan_containers(), so tests exercise the actual wiring instead
        of restating the parsing logic. sessionId s1 is pinned (via a
        mocked query_container_sessionids) to the SECOND container's
        hostname (host2), which is exactly the duplicate-project ambiguity
        this task resolves."""
        ps_stdout = (
            "cid1\tdev-tools\tdev-tools\tUp 2 minutes\n"
            "cid2\tdev-tools\tdev-tools-2\tUp 1 minute\n"
        )
        inspect_stdout = (
            "dev-tools\t/workspace\trunning\thost1\n"
            "dev-tools\t/workspace\trunning\thost2\n"
        )
        orig_which = monitor.shutil.which
        monitor.shutil.which = lambda name: "/usr/bin/docker"
        run_results = [
            mock.Mock(returncode=0, stdout=ps_stdout),
            mock.Mock(returncode=0, stdout=inspect_stdout),
        ]
        try:
            with mock.patch.object(monitor.subprocess, "run", side_effect=run_results), \
                 mock.patch.object(monitor, "query_container_sessionids",
                                    return_value=({"s1": "dev-tools"}, {"s1": "host2"})):
                return monitor.scan_containers()
        finally:
            monitor.shutil.which = orig_which

    def test_duplicate_container_session_resolves_end_to_end(self):
        """Threads scan_containers()'s real output into scan(), proving the
        wiring (not just the rule): a docker ps/inspect pair for two
        `dev-tools` containers, a mocked sessionId lookup pinning s1 to the
        SECOND container's hostname, and a scan() row for that sessionId
        ending up with name=='dev-tools' but display_name=='dev-tools-2'.

        label_map is legitimately empty here — two containers sharing the
        same encoded dir is exactly the ambiguity this task resolves via
        sessionId, not via label_map.
        """
        self.assertEqual(
            monitor.session_display_name("dev-tools", "host2", {"host2": "dev-tools-2"}),
            "dev-tools-2")

        (rows, label_map, sid_map, container_info,
         hostname_to_name) = self._scan_containers_two_dev_tools()

        self.assertEqual(hostname_to_name, {"host1": "dev-tools", "host2": "dev-tools-2"})
        self.assertEqual(set(container_info.keys()),
                          {"hostname_to_label", "hostname_to_status", "sessionid_to_hostname"})
        self.assertEqual(set(container_info["hostname_to_label"].values()), {"dev-tools"})

        _write_session(self.root, "-workspace", [
            _assistant([_text_block()], session_id="s1"),
        ])
        [s] = scan(sessionid_to_label={"s1": "dev-tools"},
                   container_info={"sessionid_to_hostname": {"s1": "host2"}},
                   hostname_to_name=hostname_to_name)
        self.assertEqual(s["name"], "dev-tools")
        self.assertEqual(s["display_name"], "dev-tools-2")
        self.assertEqual(monitor.session_display_text(s), "dev-tools-2")

    # -- session_display_name(): the pure rule and every fallback branch --

    def test_first_container_of_the_pair_shows_todays_text(self):
        self.assertEqual(
            monitor.session_display_name("dev-tools", "host1", {"host1": "dev-tools"}),
            "dev-tools")

    def test_random_docker_name_falls_back_to_label(self):
        self.assertEqual(
            monitor.session_display_name("dev-tools", "host3", {"host3": "dreamy_bose"}),
            "dev-tools")

    def test_hostname_absent_from_map_falls_back_to_label(self):
        self.assertEqual(
            monitor.session_display_name("dev-tools", "host9", {"host1": "dev-tools-2"}),
            "dev-tools")

    def test_empty_map_falls_back_to_label(self):
        self.assertEqual(monitor.session_display_name("dev-tools", "host1", {}), "dev-tools")

    def test_none_map_falls_back_to_label(self):
        self.assertEqual(monitor.session_display_name("dev-tools", "host1", None), "dev-tools")

    def test_none_or_empty_hostname_falls_back_to_label(self):
        mapping = {"host1": "dev-tools-2"}
        self.assertEqual(monitor.session_display_name("dev-tools", None, mapping), "dev-tools")
        self.assertEqual(monitor.session_display_name("dev-tools", "", mapping), "dev-tools")

    # -- session_display_text(): the read side and its fallback --

    def test_display_text_falls_back_to_name_for_shadow_engine_rows(self):
        """A row from the frozen state-file engine carries no display_name
        key at all — the fallback is what lets it render unchanged."""
        self.assertEqual(monitor.session_display_text({"name": "dev-tools"}), "dev-tools")

    def test_display_text_prefers_display_name_when_present(self):
        row = {"name": "dev-tools", "display_name": "dev-tools-2"}
        self.assertEqual(monitor.session_display_text(row), "dev-tools-2")

    # -- scan() rows: name/display_name fallback when the container can't
    # -- be resolved at all --

    def test_scan_row_without_container_info_has_display_name_equal_to_name(self):
        _write_session(self.root, "-workspace", [
            _assistant([_text_block()], session_id="s1"),
        ])
        [s] = scan(sessionid_to_label={"s1": "dev-tools"})
        self.assertEqual(s["display_name"], s["name"])

    def test_scan_row_with_unmapped_hostname_has_display_name_equal_to_name(self):
        _write_session(self.root, "-workspace", [
            _assistant([_text_block()], session_id="s1"),
        ])
        [s] = scan(sessionid_to_label={"s1": "dev-tools"},
                   container_info={"sessionid_to_hostname": {"s1": "hostX"}},
                   hostname_to_name={})
        self.assertEqual(s["display_name"], s["name"])

    # -- sort guard: a suffixed display text must not move the session in
    # -- the sort order, which is keyed on s["name"] --

    def test_sort_order_unaffected_by_display_name(self):
        _write_session(self.root, "-workspace-a", [
            _assistant([_text_block()], session_id="s1"),
        ], filename="a.jsonl")
        _write_session(self.root, "-workspace-z", [
            _assistant([_text_block()], session_id="s2"),
        ], filename="z.jsonl")
        with mock.patch.object(monitor, "launcher_order",
                                return_value={"dev-tools": 0, "zeta": 1}):
            sessions = scan(
                sessionid_to_label={"s1": "dev-tools", "s2": "zeta"},
                container_info={"sessionid_to_hostname": {"s1": "host2"}},
                hostname_to_name={"host2": "dev-tools-2"})
        self.assertEqual([s["name"] for s in sessions], ["dev-tools", "zeta"])
        self.assertEqual(monitor.session_display_text(sessions[0]), "dev-tools-2")

    # -- container_info guard: the frozen engine's cross-check dict keeps
    # -- exactly its three keys, with values that stay pure project labels --

    def test_container_info_keeps_pure_project_labels(self):
        (rows, label_map, sid_map, container_info,
         hostname_to_name) = self._scan_containers_two_dev_tools()
        self.assertEqual(set(container_info.keys()),
                          {"hostname_to_label", "hostname_to_status", "sessionid_to_hostname"})
        for label in container_info["hostname_to_label"].values():
            self.assertEqual(label, "dev-tools")
            self.assertNotIn(label, ("dev-tools-2",))
        # hostname_to_name (the new, separate map) is where the container
        # NAME lives — proving the two maps didn't get merged/confused.
        self.assertIn("dev-tools-2", hostname_to_name.values())
        self.assertNotIn("dev-tools-2", container_info["hostname_to_label"].values())


# ---------------------------------------------------------------------------
# GOAL 20 — The render seam flip (phase 03-01): scan_state_files() is the
# one engine feeding rendering, its rows carry display_name, and the
# one-argument select_render_sessions() identity seam replaces the old
# two-engine selector (D-01, D-08).
# ---------------------------------------------------------------------------

class Goal20_RenderSeamFlip(StateFileTestBase):

    def test_state_file_row_carries_disambiguated_display_name(self):
        self._write_state("a", hostname="container-1")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "dev-tools"},
            container_info={"hostname_to_label": {}, "hostname_to_status": {},
                             "sessionid_to_hostname": {}},
            hostname_to_name={"container-1": "dev-tools-2"},
            legacy_sessions=[],
        )
        self.assertEqual(s["display_name"], "dev-tools-2")

    def test_state_file_row_display_name_falls_back_to_name_without_map(self):
        self._write_state("a", hostname="container-1")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "dev-tools"}, legacy_sessions=[],
            hostname_to_name=None,
        )
        self.assertEqual(s["display_name"], s["name"])

    def test_state_file_row_display_name_falls_back_for_unknown_hostname(self):
        self._write_state("a", hostname="container-1")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "dev-tools"}, legacy_sessions=[],
            hostname_to_name={"other-host": "dev-tools-9"},
        )
        self.assertEqual(s["display_name"], s["name"])

    def test_session_display_text_resolves_disambiguated_name(self):
        self._write_state("a", hostname="container-1")
        [s] = monitor.scan_state_files(
            sessionid_to_label={"a": "dev-tools"}, legacy_sessions=[],
            hostname_to_name={"container-1": "dev-tools-2"},
        )
        self.assertEqual(monitor.session_display_text(s), "dev-tools-2")
        self.assertNotEqual(monitor.session_display_text(s), "dev-tools")

    def test_select_render_sessions_is_a_one_argument_identity_seam(self):
        rows = [{"k": 1}]
        self.assertIs(monitor.select_render_sessions(rows), rows)

    def test_empty_state_dir_and_empty_legacy_returns_empty_list_no_raise(self):
        self.assertEqual(monitor.scan_state_files(legacy_sessions=[]), [])

    def test_absent_state_dir_and_empty_legacy_returns_empty_list_no_raise(self):
        monitor.STATE_DIR = self.root / "does-not-exist"
        self.assertEqual(monitor.scan_state_files(legacy_sessions=[]), [])

    def test_one_state_file_alone_yields_exactly_one_row(self):
        """Plan 03-03 Task 3 Test 5 (edge, empty/single): a single state
        file with no legacy sessions yields exactly one row."""
        self._write_state("a")
        sessions = monitor.scan_state_files(sessionid_to_label={"a": "L"}, legacy_sessions=[])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["key"], "a")

    def test_one_legacy_session_alone_yields_exactly_one_row(self):
        """Plan 03-03 Task 3 Test 5 (edge, empty/single): no state files,
        one legacy session, yields exactly one row (the bridge)."""
        sessions = monitor.scan_state_files(
            legacy_sessions=[{"key": "b", "session_id": "b", "name": "L", "mtime": time.time()}])
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["key"], "b")
        self.assertTrue(sessions[0].get("legacy_origin"))

    def test_equal_sort_keys_keep_input_order_stable(self):
        self._write_state("b")
        self._write_state("a")
        mtime = time.time()
        os.utime(self.root / "a.json", (mtime, mtime))
        os.utime(self.root / "b.json", (mtime, mtime))
        with mock.patch.object(Path, "glob",
                                return_value=[self.root / "b.json", self.root / "a.json"]):
            sessions = monitor.scan_state_files(
                sessionid_to_label={"a": "L", "b": "L"}, legacy_sessions=[])
        self.assertEqual([s["session_id"] for s in sessions], ["b", "a"])


# ---------------------------------------------------------------------------
# GOAL 21 — One unified badge, sourced only from the hook-captured
# background_tasks_count (D-03). Re-asserts the guarantee Goal2h/Goal2i used
# to protect ("a live background shell never pins WORKING by itself") on
# state-file fixtures, since the jsonl-based bg-shell parser that carried it
# is gone.
# ---------------------------------------------------------------------------

class Goal21_UnifiedBadge(StateFileTestBase):

    def test_badge_text_empty_for_zero_and_none(self):
        self.assertEqual(monitor.bg_badge_text(0), "")
        self.assertEqual(monitor.bg_badge_text(None), "")

    def test_badge_text_glyph_only_for_one_glyph_plus_count_above(self):
        one = monitor.bg_badge_text(1)
        self.assertEqual(len(one), 1)
        three = monitor.bg_badge_text(3)
        self.assertTrue(three.endswith("3"))
        self.assertNotEqual(three, one)

    def test_bg_count_drives_badge_text_status_stays_independent(self):
        """Test 3: background_tasks_count=2 produces a non-empty badge; the
        row's status is whatever the record's `state` maps to — the count
        never changes it."""
        self._write_state("a", state="working", background_tasks_count=2)
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WORKING")
        self.assertNotEqual(monitor.bg_badge_text(s["background_tasks_count"]), "")

    def test_bg_count_never_pins_working(self):
        """Test 4: state='waiting' + background_tasks_count=5 still yields
        WAITING — the bg count is badge-only, exactly like the deleted
        Goal2h/Goal2i guarantee, now proved on the hook-derived engine."""
        self._write_state("a", state="waiting", background_tasks_count=5)
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual(s["status"], "WAITING")
        self.assertNotEqual(monitor.bg_badge_text(s["background_tasks_count"]), "")


# ---------------------------------------------------------------------------
# GOAL 22 — The trimmed in-file agent-activity peek (D-02b evidence),
# absorbed from shell_tracker's count_active_monitors/count_active_agents/
# count_active_async_agents into one single-read helper.
# ---------------------------------------------------------------------------

class Goal22_AgentActivityPeek(MonitorTestBase):

    def test_unterminated_monitor_task_is_agent_activity_true(self):
        """Test 5 (first half): a started-but-not-terminated Monitor task
        yields agent_activity True. toolu_-prefixed id matches the
        MONITOR_USE_RE/MONITOR_RESULT_RE anchors ported from shell_tracker
        (real Anthropic tool_use ids carry this prefix)."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Monitor", "toolu_mon1")]),
            _monitor_started_result("toolu_mon1", "task_mon1"),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertTrue(s["agent_activity"])

    def test_task_stop_for_same_task_id_clears_agent_activity(self):
        """Test 5 (second half): a TaskStop for the same task_id flips it
        to False."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Monitor", "toolu_mon1")]),
            _monitor_started_result("toolu_mon1", "task_mon1"),
            _task_stop("task_mon1"),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertFalse(s["agent_activity"])

    def test_unmatched_foreground_agent_is_agent_activity_true(self):
        """Test 6 (first half): an in-flight foreground Agent tool_use with
        no matching tool_result yields agent_activity True."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Agent", "toolu_agentlive")]),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertTrue(s["agent_activity"])

    def test_matching_tool_result_clears_agent_activity(self):
        """Test 6 (second half): adding the matching tool_result flips it
        to False."""
        _write_session(self.root, "-workspace-app", [
            _assistant([_tool_use("Agent", "toolu_agentlive")]),
            _user_tool_result("toolu_agentlive"),
        ])
        [s] = self._scan({"-workspace-app": "app"})
        self.assertFalse(s["agent_activity"])


# ---------------------------------------------------------------------------
# GOAL 23 — shell_tracker.py is fully deleted (D-03); monitor.py carries no
# residue of its symbols and imports cleanly without it.
# ---------------------------------------------------------------------------

class Goal23_ShellTrackerRemoved(unittest.TestCase):

    def test_shell_tracker_module_is_gone(self):
        with self.assertRaises(ModuleNotFoundError):
            import shell_tracker  # noqa: F401

    def test_monitor_has_no_shell_tracker_symbols(self):
        for name in ("has_active_shells", "count_active_monitors",
                     "count_active_agents", "count_active_async_agents"):
            self.assertFalse(hasattr(monitor, name), name)


# ---------------------------------------------------------------------------
# GOAL 25 — group-gated notifications (quick-260807-iz2 Task 1): the two
# pure-function building blocks, notification_group_key() and
# gate_notification(), plus the real 2026-08-07 episode replayed end to end
# through scan_state_files().
# ---------------------------------------------------------------------------

class Goal25_GroupGatedNotifications(unittest.TestCase):
    """notification_group_key() and gate_notification() as pure functions —
    no tkinter, no state files. Key is now a three-part label :: worktree-
    folded root :: hostname (quick-260807-k0y): container identity is part
    of group identity, so two containers of the SAME project (nursy,
    nursy-2) get independent notification channels instead of one shared,
    mutually-silencing channel. The episode replay lives in
    Goal25b_GroupGateEpisodeReplay below (needs StateFileTestBase)."""

    def test_duplicate_project_containers_get_different_keys_and_dont_block(self):
        nursy = {"key": "a", "name": "nursy", "cwd": "/workspace",
                 "hostname": "a1b2c3d4e5f6", "background_tasks_count": 0}
        nursy_2 = {"key": "b", "name": "nursy", "cwd": "/workspace",
                   "hostname": "f6e5d4c3b2a1", "status": "WORKING"}
        self.assertNotEqual(monitor.notification_group_key(nursy),
                             monitor.notification_group_key(nursy_2))
        allowed, reason, _ = monitor.gate_notification(nursy, [nursy, nursy_2])
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_worktree_checkout_folds_onto_main_checkout(self):
        main = {"name": "nursy_app", "cwd": "/workspace", "hostname": "c0ffee00"}
        worktree = {"name": "nursy_app",
                     "cwd": "/workspace/.claude/worktrees/prd-gsd",
                     "hostname": "c0ffee00"}
        deeper = {"name": "nursy_app",
                   "cwd": "/workspace/.claude/worktrees/prd-gsd/src",
                   "hostname": "c0ffee00"}
        key_main = monitor.notification_group_key(main)
        self.assertEqual(key_main, monitor.notification_group_key(worktree))
        self.assertEqual(key_main, monitor.notification_group_key(deeper))

    def test_shared_cwd_and_hostname_different_project_labels_never_merge(self):
        a = {"name": "nursy_app", "cwd": "/workspace", "hostname": "h1"}
        b = {"name": "dev-tools", "cwd": "/workspace", "hostname": "h1"}
        self.assertNotEqual(monitor.notification_group_key(a),
                             monitor.notification_group_key(b))

    def test_unknown_hostname_is_ungrouped(self):
        base = {"name": "x", "cwd": "/workspace"}
        self.assertEqual(monitor.notification_group_key(dict(base)), "")
        self.assertEqual(
            monitor.notification_group_key(dict(base, hostname="")), "")
        self.assertEqual(
            monitor.notification_group_key(dict(base, hostname=123)), "")

        me = dict(base, hostname="", background_tasks_count=0)
        sibling = dict(base, hostname="", status="WORKING")
        allowed, _, _ = monitor.gate_notification(me, [me, sibling])
        self.assertTrue(allowed)

    def test_unknown_cwd_is_ungrouped(self):
        base = {"name": "x", "hostname": "h1"}
        self.assertEqual(monitor.notification_group_key(dict(base)), "")
        self.assertEqual(monitor.notification_group_key(dict(base, cwd="")), "")
        self.assertEqual(monitor.notification_group_key(dict(base, cwd=123)), "")

    def test_windows_separators_normalise_like_forward_slash(self):
        win = {"name": "nursy_app", "cwd": "C:\\workspace\\proj\\",
               "hostname": "h1"}
        posix = {"name": "nursy_app", "cwd": "C:/workspace/proj",
                  "hostname": "h1"}
        self.assertEqual(monitor.notification_group_key(win),
                          monitor.notification_group_key(posix))

    def test_own_background_tasks_refuse_with_reason(self):
        s = {"key": "a", "name": "solo", "background_tasks_count": 1}
        allowed, reason, detail = monitor.gate_notification(s, [s])
        self.assertFalse(allowed)
        self.assertEqual(reason, "background_tasks")
        self.assertEqual(detail["background_tasks_count"], 1)

    def test_zero_or_unknown_background_tasks_never_refuse_alone(self):
        s0 = {"key": "a", "name": "solo", "background_tasks_count": 0}
        allowed, reason, _ = monitor.gate_notification(s0, [s0])
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

        s_absent = {"key": "a", "name": "solo"}
        allowed, _, _ = monitor.gate_notification(s_absent, [s_absent])
        self.assertTrue(allowed)

        s_non_numeric = {"key": "a", "name": "solo", "background_tasks_count": "n/a"}
        allowed, _, _ = monitor.gate_notification(s_non_numeric, [s_non_numeric])
        self.assertTrue(allowed)

    def test_working_sibling_in_same_group_blocks_and_names_it(self):
        me = {"key": "a", "name": "nursy_app", "cwd": "/workspace",
              "hostname": "h1", "background_tasks_count": 0}
        sibling = {"key": "b", "name": "nursy_app",
                   "cwd": "/workspace/.claude/worktrees/prd-gsd",
                   "hostname": "h1", "status": "WORKING"}
        allowed, reason, detail = monitor.gate_notification(me, [me, sibling])
        self.assertFalse(allowed)
        self.assertEqual(reason, "group_working")
        self.assertIn("b", detail["blocked_by"])

        sibling_waiting = dict(sibling, status="WAITING")
        allowed, _, _ = monitor.gate_notification(me, [me, sibling_waiting])
        self.assertTrue(allowed)

    def test_sibling_in_different_group_never_blocks(self):
        me = {"key": "a", "name": "nursy_app", "cwd": "/workspace",
              "hostname": "h1", "background_tasks_count": 0}
        other_project = {"key": "b", "name": "dev-tools", "cwd": "/workspace",
                          "hostname": "h1", "status": "WORKING"}
        allowed, _, _ = monitor.gate_notification(me, [me, other_project])
        self.assertTrue(allowed)

    def test_legacy_working_locked_sibling_blocks_like_working(self):
        me = {"key": "a", "name": "nursy_app", "cwd": "/workspace",
              "hostname": "h1", "background_tasks_count": 0}
        legacy_sibling = {"key": "b", "name": "nursy_app", "cwd": "/workspace",
                           "hostname": "h1", "status": "WAITING",
                           "working_locked": True}
        allowed, reason, _ = monitor.gate_notification(me, [me, legacy_sibling])
        self.assertFalse(allowed)
        self.assertEqual(reason, "group_working")

    def test_session_never_blocked_by_its_own_presence(self):
        me = {"key": "a", "name": "nursy_app", "cwd": "/workspace",
              "hostname": "h1", "background_tasks_count": 0, "status": "WAITING"}
        allowed, _, _ = monitor.gate_notification(me, [me])
        self.assertTrue(allowed)


class Goal25b_GroupGateEpisodeReplay(StateFileTestBase):
    """The real 2026-08-07 13:14:20Z episode, replayed end to end: state
    files on disk -> scan_state_files() session dicts -> gate_notification()
    -> a refused notification. Also pins that adding `cwd` to the session
    dict did not disturb scan_state_files()'s pre-existing verdict fields
    (Goal9/Goal10/Goal11/Goal24 stay green untouched, run separately), and
    pins the accepted consequence of quick-260807-k0y: the real pair's two
    hostnames now resolve to DIFFERENT group keys, so the 13:14 replay is
    refused on the background_tasks condition alone, not on group_working."""

    def test_20260807_1314_episode_is_refused_by_the_gate(self):
        self._write_state("6fff7d17", state="waiting", last_event="Stop",
                           background_tasks_count=1, hostname="8d5f9694f1de",
                           cwd="/workspace")
        self._write_state("8ced4fe8", state="working", hostname="4353e1441213",
                           cwd="/workspace/.claude/worktrees/prd-gsd")
        sessions = monitor.scan_state_files(
            sessionid_to_label={"6fff7d17": "nursy_app", "8ced4fe8": "nursy_app"})
        by_id = {s["session_id"]: s for s in sessions}
        self.assertIn("cwd", by_id["6fff7d17"])
        self.assertEqual(by_id["6fff7d17"]["cwd"], "/workspace")
        allowed, reason, _ = monitor.gate_notification(by_id["6fff7d17"], sessions)
        self.assertFalse(allowed)
        self.assertEqual(reason, "background_tasks")

    def test_20260807_accepted_consequence_real_pair_now_different_groups(self):
        self._write_state("6fff7d17", state="waiting", last_event="Stop",
                           background_tasks_count=1, hostname="8d5f9694f1de",
                           cwd="/workspace")
        self._write_state("8ced4fe8", state="working", hostname="4353e1441213",
                           cwd="/workspace/.claude/worktrees/prd-gsd")
        sessions = monitor.scan_state_files(
            sessionid_to_label={"6fff7d17": "nursy_app", "8ced4fe8": "nursy_app"})
        by_id = {s["session_id"]: s for s in sessions}
        self.assertNotEqual(monitor.notification_group_key(by_id["6fff7d17"]),
                             monitor.notification_group_key(by_id["8ced4fe8"]))

    def test_scan_state_files_verdict_fields_unaffected_by_cwd_addition(self):
        self._write_state("a", state="working")
        [s] = monitor.scan_state_files(sessionid_to_label={"a": "L"})
        self.assertEqual((s["status"], s["dot_color"], s["rank"]),
                          ("WORKING", "#666", 2))
        self.assertIn("cwd", s)


# ---------------------------------------------------------------------------
# GOAL 26 — append-only notifications.log (quick-260807-iz2 Task 2): one
# jsonl record per notification decision, sent or suppressed.
# ---------------------------------------------------------------------------

class Goal26_NotificationsLog(unittest.TestCase):
    """log_notification()/notification_record()/notification_type()/
    notification_text() — the logging half of the group gate."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig_log = monitor.NOTIFICATIONS_LOG
        monitor.NOTIFICATIONS_LOG = Path(self._tmp.name) / "sub" / "notifications.log"

    def tearDown(self) -> None:
        monitor.NOTIFICATIONS_LOG = self._orig_log
        self._tmp.cleanup()

    def _read_lines(self) -> list[str]:
        if not monitor.NOTIFICATIONS_LOG.exists():
            return []
        return monitor.NOTIFICATIONS_LOG.read_text(encoding="utf-8").splitlines()

    def test_round_trip_appends_one_parseable_line_per_call(self):
        monitor.log_notification({"a": 1})
        lines = self._read_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"a": 1})

        monitor.log_notification({"a": 2})
        lines2 = self._read_lines()
        self.assertEqual(len(lines2), 2)
        self.assertEqual(lines2[0], lines[0])  # first line untouched, byte-identical
        self.assertEqual(json.loads(lines2[1]), {"a": 2})

    def test_record_shape_carries_the_documented_fields(self):
        s = {"session_id": "sid1", "key": "k1", "hostname": "h1",
             "cwd": "/workspace", "name": "proj", "state": "waiting",
             "background_tasks_count": 0}
        record = monitor.notification_record(s, 90, "", "sent", "")
        for field in ("ts", "ts_ms", "session_id", "key", "hostname", "cwd",
                      "project", "group", "type", "state", "title", "body",
                      "elapsed_sec", "background_tasks_count", "outcome", "reason"):
            self.assertIn(field, record, field)
        self.assertEqual(record["session_id"], "sid1")
        self.assertEqual(record["project"], "proj")
        self.assertEqual(record["outcome"], "sent")

    def test_type_mapping_never_crashes_on_unrecognised_or_missing(self):
        self.assertEqual(monitor.notification_type("waiting"), "stop")
        self.assertEqual(monitor.notification_type("needs_input"), "needs_input")
        self.assertEqual(monitor.notification_type("idle"), "idle_prompt")
        self.assertEqual(monitor.notification_type("something-else"), "unknown")
        self.assertEqual(monitor.notification_type(None), "unknown")
        self.assertEqual(monitor.notification_type(123), "unknown")

    def test_notification_text_matches_display_with_and_without_alias(self):
        title, body = monitor.notification_text("nursy_app", 65, "")
        self.assertEqual(title, "Claude ready — nursy_app")
        self.assertIn("1m 5s", body)

        title_alias, body_alias = monitor.notification_text("nursy_app", 65, "prod")
        self.assertEqual(title_alias, "Claude ready — nursy_app · prod")
        self.assertEqual(body_alias, body)

    def test_never_crashes_when_log_path_unwritable(self):
        # A FILE where the log's parent directory should be — mkdir(parents=True)
        # can never succeed here regardless of who runs the suite, unlike a
        # bare "does not exist" path that a root-run suite could still create.
        blocker = Path(self._tmp.name) / "not_a_dir"
        blocker.write_text("x", encoding="utf-8")
        monitor.NOTIFICATIONS_LOG = blocker / "notifications.log"
        monitor.log_notification({"a": 1})  # must not raise

    def test_size_guard_truncates_before_next_append_with_marker(self):
        monitor.NOTIFICATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        monitor.NOTIFICATIONS_LOG.write_bytes(
            b"x" * (monitor.NOTIFICATIONS_LOG_MAX_BYTES + 1))
        monitor.log_notification({"a": 1})
        lines = self._read_lines()
        self.assertEqual(len(lines), 2)
        marker = json.loads(lines[0])
        self.assertEqual(marker.get("event"), "_truncated")
        self.assertEqual(json.loads(lines[1]), {"a": 1})

    def test_log_under_threshold_is_never_touched(self):
        monitor.log_notification({"a": 1})
        monitor.log_notification({"a": 2})
        lines = self._read_lines()
        self.assertEqual(len(lines), 2)
        self.assertNotEqual(json.loads(lines[0]).get("event"), "_truncated")

    def test_no_content_leak_in_record(self):
        s = {"session_id": "sid1", "key": "k1", "hostname": "h1",
             "cwd": "/workspace", "name": "proj", "state": "waiting",
             "background_tasks_count": 0,
             "prompt": "SECRET PROMPT TEXT", "tool_input": "rm -rf /",
             "tool_output": "leaked output", "last_assistant_message": "hi there"}
        record = monitor.notification_record(s, 10, "", "sent", "")
        serialised = json.dumps(record)
        for leak in ("SECRET PROMPT TEXT", "rm -rf /", "leaked output", "hi there"):
            self.assertNotIn(leak, serialised)


# ---------------------------------------------------------------------------
# GOAL 27 — hold/release/discard wiring at the notification choke point
# (quick-260807-iz2 Task 3): both real 2026-08-07 episodes replayed end to
# end through _check_transitions, plus release/discard/expire/reason-change/
# solo/escape-hatch coverage.
# ---------------------------------------------------------------------------

class Goal27_NotificationGateWiring(unittest.TestCase):
    """Drives monitor.MonitorApp._check_transitions through a Fake app in
    Goal8's style, asserting on both captured _notify() calls and the
    parsed notifications.log jsonl lines.

    Container identity is now part of group identity (quick-260807-k0y):
    `_sibling()`'s hostname parameter controls whether it shares `_me()`'s
    container (hostname "8d5f9694f1de", the real 2026-08-07 primary
    session's host — same-container, still a real blocker) or defaults to
    a DIFFERENT container ("4353e1441213", the real 13:28 episode's host —
    no longer a blocker, per the user's k0y decision). The 13:28 episode
    now stays suppressed on its OWN background_tasks_count, not on the
    cross-container sibling. `_nursy`/`_nursy_2` are the new pair proving
    two containers of the SAME project notify independently."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._orig_log = monitor.NOTIFICATIONS_LOG
        monitor.NOTIFICATIONS_LOG = Path(self._tmp.name) / "notifications.log"
        self._now = [1_700_000_000.0]
        self._time_patch = mock.patch.object(
            monitor.time, "time", side_effect=lambda: self._now[0])
        self._time_patch.start()

    def tearDown(self) -> None:
        self._time_patch.stop()
        monitor.NOTIFICATIONS_LOG = self._orig_log
        self._tmp.cleanup()

    def _advance(self, seconds: float) -> None:
        self._now[0] += seconds

    def _fake_app(self, group_gate: bool = True):
        class Fake:
            def __init__(self):
                self._prev_status = {}
                self._working_since = {}
                self._pending_notify = {}
                self._notify_hold = {}
                self._session_aliases = {}
                self.config = {"group_gate": group_gate}
                self.notifications = []

            def _alias_key(self, key):
                return key

            def _notify(self, label, elapsed, key=None):
                self.notifications.append((label, elapsed, key))

            def _dismiss_session_toast(self, key):
                pass

        return Fake()

    def _tick(self, app, sessions):
        monitor.MonitorApp._check_transitions(app, sessions)

    def _read_records(self) -> list[dict]:
        if not monitor.NOTIFICATIONS_LOG.exists():
            return []
        return [json.loads(line) for line in
                monitor.NOTIFICATIONS_LOG.read_text(encoding="utf-8").splitlines()]

    def _me(self, status: str, bg: int = 0) -> dict:
        # The real 2026-08-07 primary session.
        return {"key": "6fff7d17", "session_id": "6fff7d17", "name": "nursy_app",
                "cwd": "/workspace", "hostname": "8d5f9694f1de",
                "status": status, "background_tasks_count": bg, "state": "waiting"}

    def _sibling(self, status: str, working_locked: bool = False,
                 hostname: str = "4353e1441213") -> dict:
        # The real 2026-08-07 sibling, checked out under a worktree.
        # Default hostname "4353e1441213" is a DIFFERENT container from
        # _me()'s "8d5f9694f1de" (quick-260807-k0y accepted consequence) —
        # no longer a group_working blocker. Pass _me()'s own hostname to
        # get the same-container main-tree/worktree sibling that still
        # blocks.
        return {"key": "8ced4fe8", "session_id": "8ced4fe8", "name": "nursy_app",
                "cwd": "/workspace/.claude/worktrees/prd-gsd",
                "hostname": hostname, "status": status,
                "working_locked": working_locked}

    def _nursy(self, status: str, bg: int = 0) -> dict:
        # Duplicate-project container "nursy" (quick-260807-k0y).
        return {"key": "nursy1", "session_id": "nursy1", "name": "nursy",
                "cwd": "/workspace", "hostname": "a1b2c3d4e5f6",
                "status": status, "background_tasks_count": bg, "state": "waiting"}

    def _nursy_2(self, status: str) -> dict:
        # Duplicate-project container "nursy-2" — same label, same cwd,
        # DIFFERENT hostname: an independent job, not this session's sibling.
        return {"key": "nursy2", "session_id": "nursy2", "name": "nursy",
                "cwd": "/workspace", "hostname": "f6e5d4c3b2a1", "status": status}

    def test_20260807_1314_episode_never_notifies_and_logs_once(self):
        app = self._fake_app()
        self._tick(app, [self._me("WORKING"), self._sibling("WORKING")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=1)
        sib = self._sibling("WORKING")
        self._tick(app, [me_wait, sib])   # arm
        self._tick(app, [me_wait, sib])   # gate check -> hold opens, logged
        self._tick(app, [me_wait, sib])   # hold persists -> no new log line
        self.assertEqual(app.notifications, [])
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outcome"], "suppressed")
        self.assertEqual(records[0]["reason"], "background_tasks")

    def test_20260807_1328_episode_own_background_tasks_only(self):
        # Was "...blocked_by_sibling_only". Per the user's k0y decision the
        # cross-container sibling (different hostname) no longer shares a
        # group with 6fff7d17, so it can no longer block it — but the real
        # 13:28 Stop still carried background_tasks_count 1, so this episode
        # stays suppressed anyway, now on the background_tasks condition.
        # The sibling stays in the tick's session list to prove it no
        # longer participates in the refusal. Zero-notify and one-record
        # assertions preserved verbatim.
        app = self._fake_app()
        self._tick(app, [self._me("WORKING"), self._sibling("WORKING")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=1)
        sib = self._sibling("WORKING")
        self._tick(app, [me_wait, sib])   # arm
        self._tick(app, [me_wait, sib])   # gate check -> background_tasks
        self.assertEqual(app.notifications, [])
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["reason"], "background_tasks")

    def test_duplicate_project_containers_notify_independently(self):
        # The new guarantee (quick-260807-k0y), end to end through
        # _check_transitions: "nursy" and "nursy-2" share a project label
        # and cwd but have different hostnames, so nursy-2 being WORKING
        # never blocks nursy from notifying.
        app = self._fake_app()
        self._tick(app, [self._nursy("WORKING"), self._nursy_2("WORKING")])
        app._working_since["nursy1"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        nursy_wait = self._nursy("WAITING", bg=0)
        nursy_2_working = self._nursy_2("WORKING")
        self._tick(app, [nursy_wait, nursy_2_working])   # arm
        self._tick(app, [nursy_wait, nursy_2_working])   # fires — different group
        self.assertEqual(len(app.notifications), 1)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outcome"], "sent")
        self.assertEqual(records[0]["group"],
                          monitor.notification_group_key(nursy_wait))

    def test_release_fires_exactly_once_with_held_sec(self):
        # Same-container sibling (shares _me()'s hostname) so it still
        # blocks per the k0y-narrowed group key.
        app = self._fake_app()
        self._tick(app, [self._me("WORKING"),
                          self._sibling("WORKING", hostname="8d5f9694f1de")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=0)
        sib_working = self._sibling("WORKING", hostname="8d5f9694f1de")
        self._tick(app, [me_wait, sib_working])   # arm
        self._tick(app, [me_wait, sib_working])   # held: group_working
        self._advance(30)
        sib_waiting = self._sibling("WAITING", hostname="8d5f9694f1de")
        self._tick(app, [me_wait, sib_waiting])   # release: last member done
        self.assertEqual(len(app.notifications), 1)
        self._tick(app, [me_wait, sib_waiting])   # further tick: nothing more
        self.assertEqual(len(app.notifications), 1)
        records = self._read_records()
        self.assertEqual(records[-1]["outcome"], "sent")
        self.assertIn("held_sec", records[-1])
        self.assertGreaterEqual(records[-1]["held_sec"], 30)

    def test_discard_on_self_resume_logs_session_resumed(self):
        app = self._fake_app()
        self._tick(app, [self._me("WORKING"), self._sibling("WORKING")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=1)
        sib = self._sibling("WORKING")
        self._tick(app, [me_wait, sib])   # arm
        self._tick(app, [me_wait, sib])   # held
        self._tick(app, [self._me("WORKING"), sib])   # the real 13:14 outcome
        self.assertEqual(app.notifications, [])
        self.assertEqual(app._pending_notify, {})
        self.assertEqual(app._notify_hold, {})
        records = self._read_records()
        self.assertEqual(records[-1]["reason"], "session_resumed")
        self.assertEqual(records[-1]["outcome"], "suppressed")

    def test_discard_on_vanish_logs_from_snapshot(self):
        app = self._fake_app()
        self._tick(app, [self._me("WORKING"), self._sibling("WORKING")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=1)
        sib = self._sibling("WORKING")
        self._tick(app, [me_wait, sib])   # arm
        self._tick(app, [me_wait, sib])   # held
        self._tick(app, [sib])            # 6fff7d17 vanishes from the list
        self.assertEqual(app.notifications, [])
        records = self._read_records()
        self.assertEqual(records[-1]["reason"], "session_gone")
        self.assertEqual(records[-1]["session_id"], "6fff7d17")

    def test_hold_expires_past_cap_and_is_dropped(self):
        app = self._fake_app()
        self._tick(app, [self._me("WORKING"), self._sibling("WORKING")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=1)
        sib = self._sibling("WORKING")
        self._tick(app, [me_wait, sib])   # arm
        self._tick(app, [me_wait, sib])   # held
        self._advance(monitor.NOTIFY_GATE_MAX_HOLD_SEC + 5)
        self._tick(app, [me_wait, sib])   # expire
        self.assertEqual(app.notifications, [])
        self.assertEqual(app._pending_notify, {})
        self.assertEqual(app._notify_hold, {})
        records = self._read_records()
        self.assertEqual(records[-1]["reason"], "hold_expired")
        self.assertEqual(records[-1]["outcome"], "suppressed")

    def test_reason_change_reopens_and_logs_once(self):
        # Same-container sibling (shares _me()'s hostname) so it still
        # blocks per the k0y-narrowed group key.
        app = self._fake_app()
        sib = self._sibling("WORKING", hostname="8d5f9694f1de")
        self._tick(app, [self._me("WORKING"), sib])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait_bg = self._me("WAITING", bg=1)
        self._tick(app, [me_wait_bg, sib])   # arm
        self._tick(app, [me_wait_bg, sib])   # held: background_tasks
        me_wait_nobg = self._me("WAITING", bg=0)
        self._tick(app, [me_wait_nobg, sib])   # still refused, now group_working
        self._tick(app, [me_wait_nobg, sib])   # persists, no new log line
        records = self._read_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["reason"], "background_tasks")
        self.assertEqual(records[1]["reason"], "group_working")

    def test_solo_session_notifies_on_second_tick_and_logs_sent(self):
        app = self._fake_app()
        self._tick(app, [{"key": "solo1", "name": "loner", "status": "WORKING"}])
        app._working_since["solo1"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        solo_wait = {"key": "solo1", "name": "loner", "status": "WAITING"}
        self._tick(app, [solo_wait])   # arm
        self.assertEqual(app.notifications, [])
        self._tick(app, [solo_wait])   # fires — no group, no bg tasks
        self.assertEqual(len(app.notifications), 1)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outcome"], "sent")

    def test_escape_hatch_disables_gate_but_log_still_written(self):
        app = self._fake_app(group_gate=False)
        self._tick(app, [self._me("WORKING"), self._sibling("WORKING")])
        app._working_since["6fff7d17"] -= monitor.NOTIFY_MIN_WORK_SEC + 5
        me_wait = self._me("WAITING", bg=1)
        sib = self._sibling("WORKING")
        self._tick(app, [me_wait, sib])   # arm
        self._tick(app, [me_wait, sib])   # gate disabled -> fires (today's behaviour)
        self.assertEqual(len(app.notifications), 1)
        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outcome"], "sent")


class Goal28_LocalSwitchMutesAudioOnly(unittest.TestCase):
    """`local` now gates the audio channel alone (quick-260818-bfm): the
    toast and the taskbar flash always fire regardless of the switch, only
    the audio helper is skipped when muted. Telegram stays on its own
    independent gate in both directions. Two further cases drive the real
    (unbound) `_notify_audio`/`_flash_taskbar` methods against a minimal
    Fake on this non-Windows host, proving Task 2's extraction preserves
    behaviour rather than merely relocating code: winsound is absent here,
    so `_notify_audio` must fall through to the Tk `bell` fallback, and
    `_flash_taskbar` must return False without touching ctypes (the
    `os.name == "nt"` guard moves inside the helper)."""

    def _fake_app(self, **config):
        calls = {
            "toast": [],
            "audio": [],
            "flash": [],
            "telegram": [],
            "bell": [],
            "after": [],
        }

        class Root:
            def bell(root_self):
                calls["bell"].append(True)

            def after(root_self, ms, fn, *args):
                calls["after"].append((ms, fn, args))

            def update_idletasks(root_self):
                pass

        class Fake:
            def __init__(self):
                self.config = dict(config)
                self._session_aliases = {}
                self.root = Root()
                self.calls = calls

            def _alias_key(self, key):
                return key

            def _dismiss_session_toast(self, key):
                pass

            def _notify_toast(self, title, body, key=None):
                calls["toast"].append((title, body, key))
                return True

            def _notify_audio(self):
                calls["audio"].append(True)
                return (True, "stub")

            def _flash_taskbar(self):
                calls["flash"].append(True)
                return False

            def _send_telegram(self, title, body):
                calls["telegram"].append((title, body))

        return Fake()

    def test_local_false_toast_still_fires(self):
        app = self._fake_app(local=False, telegram=True)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        expected_title, expected_body = monitor.notification_text("proj", 600, "")
        self.assertEqual(app.calls["toast"], [(expected_title, expected_body, None)])

    def test_local_false_audio_never_called(self):
        app = self._fake_app(local=False, telegram=True)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        self.assertEqual(app.calls["audio"], [])

    def test_local_false_flash_still_fires(self):
        app = self._fake_app(local=False, telegram=True)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        self.assertEqual(len(app.calls["flash"]), 1)

    def test_local_true_all_three_fire(self):
        app = self._fake_app(local=True, telegram=True)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        self.assertEqual(len(app.calls["toast"]), 1)
        self.assertEqual(len(app.calls["audio"]), 1)
        self.assertEqual(len(app.calls["flash"]), 1)

    def test_local_key_absent_defaults_to_all_three(self):
        app = self._fake_app(telegram=True)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        self.assertEqual(len(app.calls["toast"]), 1)
        self.assertEqual(len(app.calls["audio"]), 1)
        self.assertEqual(len(app.calls["flash"]), 1)

    def test_local_false_telegram_true_still_pushes(self):
        app = self._fake_app(local=False, telegram=True)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        self.assertEqual(len(app.calls["telegram"]), 1)

    def test_local_true_telegram_false_stays_off(self):
        app = self._fake_app(local=True, telegram=False)
        monitor.MonitorApp._notify(app, "proj", 600, key=None)
        self.assertEqual(app.calls["telegram"], [])

    def test_real_flash_taskbar_on_non_windows_host(self):
        app = self._fake_app()
        result = monitor.MonitorApp._flash_taskbar(app)
        self.assertFalse(result)

    def test_real_notify_audio_falls_back_to_tk_bell(self):
        app = self._fake_app()
        ok, channel = monitor.MonitorApp._notify_audio(app)
        self.assertTrue(ok)
        self.assertTrue(channel)
        self.assertEqual(len(app.calls["bell"]), 1)
        self.assertEqual(app.calls["after"], [])


if __name__ == "__main__":
    unittest.main()
