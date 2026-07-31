"""Track background-shell state from a Claude Code jsonl session log.

A Bash command can reach the background two ways, and Claude Code (≥2.1)
writes a different tool_result marker for each:
  - Claude starts it that way (run_in_background=True input):
        Command running in background with ID: <shell_id>. Output is being written to: ...
  - The user promotes a running foreground command with Ctrl+B:
        Command was manually backgrounded by user with ID: <shell_id>. Output is being written to: ...

Termination is identical for both paths, so only start detection is dual:
  - Explicit KillShell tool_use with input.shell_id = <shell_id>
  - Older variants: <task_id>...</task_id> + <status>completed|failed|cancelled</status>

A shell is considered "active" if its start marker (either form) appears in
the tail window and no subsequent terminal signal for that ID is present.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

TAIL_BYTES = 10 * 1024 * 1024  # 10MB — enough to cover the full jsonl in practice,
# so we don't lose sight of long-running bg shells started hours ago.

# Anchor to the tool_result `content` field so we don't match the phrase when
# it merely appears inside shell output (e.g. grep/tail results quoting the
# text) or an escaped grep/cat echo of a jsonl (inner quotes escaped as \"
# won't satisfy the unescaped `"type"`/`"content"` keys this pattern requires).
# In the user-initiated (Ctrl+B) record, tool_use_id precedes type — harmless,
# since the anchor only constrains the brace-free span from type to content.
BG_START_RE = re.compile(
    rb'"type"\s*:\s*"tool_result"[^{}]*?"content"\s*:\s*'
    rb'"Command (?:running in background|was manually backgrounded by user) with ID:\s*([A-Za-z0-9_]+)'
)
# A raw `tool_use` with name=Monitor; grep/cat output quoting a jsonl has
# quotes escaped as \" and won't match this unescaped form, avoiding false positives.
MONITOR_USE_RE = re.compile(
    rb'"type"\s*:\s*"tool_use"\s*,\s*"id"\s*:\s*"(toolu_[A-Za-z0-9]+)"\s*,\s*"name"\s*:\s*"Monitor"'
)
# The corresponding tool_result wires tool_use_id → task-id for termination lookups.
MONITOR_RESULT_RE = re.compile(
    rb'"tool_use_id"\s*:\s*"(toolu_[A-Za-z0-9]+)"[^{}]*?"content"\s*:\s*"Monitor started \(task ([A-Za-z0-9_]+)'
)
# Capture the `persistent` flag from toolUseResult so we can distinguish
# first-match monitors (persistent=false, terminate on any event) from
# persistent ones (terminate only via TaskStop or timeout).
MONITOR_PERSISTENT_RE = re.compile(
    rb'"toolUseResult"\s*:\s*\{[^{}]*?"taskId"\s*:\s*"([A-Za-z0-9_]+)"[^{}]*?"persistent"\s*:\s*(true|false)'
)
# Monitor termination markers — Claude Code does NOT emit a task-notification
# with <status> for monitors. Instead they end via:
#   1. TaskStop tool_use with input.task_id
#   2. A task-notification whose <event> contains "[Monitor timed out"
#   3. For persistent=false monitors: any task-notification for their task-id
#      (the match event itself ends them, and no explicit terminator is written)
TASK_STOP_RE = re.compile(
    rb'"name"\s*:\s*"TaskStop".{0,500}?"task_id"\s*:\s*"([A-Za-z0-9_]+)"', re.DOTALL,
)
MONITOR_TIMEOUT_RE = re.compile(
    rb'<task-id>([A-Za-z0-9_]+)</task-id>.{0,1500}?\[Monitor timed out', re.DOTALL,
)
TASK_NOTIF_TASKID_RE = re.compile(
    rb'<task-notification>.{0,2000}?<task-id>([A-Za-z0-9_]+)</task-id>', re.DOTALL,
)
KILL_SHELL_RE = re.compile(rb'"name"\s*:\s*"KillShell"[^{}]{0,500}?"shell_id"\s*:\s*"([^"]+)"')
# Sub-agent invocations (gsd-planner, gsd-executor, etc.). A foreground Agent
# blocks the parent until it returns its tool_result with the matching tool_use_id.
AGENT_USE_RE = re.compile(
    rb'"type"\s*:\s*"tool_use"\s*,\s*"id"\s*:\s*"(toolu_[A-Za-z0-9]+)"\s*,\s*"name"\s*:\s*"Agent"'
)
# Match any tool_result by its tool_use_id — used to confirm an Agent finished.
TOOL_RESULT_ID_RE = re.compile(rb'"tool_use_id"\s*:\s*"(toolu_[A-Za-z0-9]+)"')
# Background sub-agent (Agent run_in_background=True) launches. The synchronous
# tool_result for the dispatch contains "Async agent launched successfully" and
# the agent's hex id; the agent's actual completion arrives later as a
# <task-notification> whose <task-id> equals that agentId.
ASYNC_AGENT_LAUNCH_RE = re.compile(
    rb'Async agent launched successfully[^"]{0,200}?agentId:\s*([0-9a-f]+)'
)
# Task completion notifications emitted by Claude Code when a bg task ends.
TASK_NOTIF_RE = re.compile(
    rb"<task-notification>.{0,400}?<task-id>([A-Za-z0-9_]+)</task-id>.{0,800}?<status>([a-zA-Z_]+)</status>",
    re.DOTALL,
)
# Older task-wrapper status format — same anchoring logic.
STATUS_RE = re.compile(
    rb'"type"\s*:\s*"tool_result"[^{}]*?<task_id>([^<]+)</task_id>[^<]{0,100}?<status>([a-zA-Z_]+)</status>'
)
TERMINAL = {"completed", "failed", "cancelled", "killed", "timeout"}


def has_active_shells(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return False
            read_size = min(TAIL_BYTES, size)
            f.seek(size - read_size)
            data = f.read(read_size)
    except OSError:
        return False

    started_ids: set[bytes] = set()
    terminated_ids: set[bytes] = set()

    for m in BG_START_RE.finditer(data):
        started_ids.add(m.group(1))

    # Scan the whole tail (not line-by-line) for kills; KillShell blocks may span lines
    for m in KILL_SHELL_RE.finditer(data):
        terminated_ids.add(m.group(1))

    # TaskStop terminates any backgrounded task — including bg shells, not just Monitors.
    # The id passed to TaskStop matches the shell_id from the bg-start marker.
    for m in TASK_STOP_RE.finditer(data):
        terminated_ids.add(m.group(1))

    # Task-notification blocks (final completion signal from Claude Code)
    for m in TASK_NOTIF_RE.finditer(data):
        tid, status = m.group(1), m.group(2).lower()
        if status.decode("ascii", errors="replace") in TERMINAL:
            terminated_ids.add(tid)

    # Older task-wrapped status format
    latest_status: dict[bytes, bytes] = {}
    for m in STATUS_RE.finditer(data):
        latest_status[m.group(1)] = m.group(2).lower()
    for tid, status in latest_status.items():
        if status.decode("ascii", errors="replace") in TERMINAL:
            terminated_ids.add(tid)
        else:
            started_ids.add(tid)

    return bool(started_ids - terminated_ids)


def count_active_monitors(path: Path) -> int:
    """Number of Monitor tool tasks started but not yet terminated.

    Monitors are streamed-event watchers (e.g. tail -F | grep). Unlike bg shells
    they don't emit a `<status>` task-notification on end — termination signals are
    a TaskStop tool_use carrying their task_id, or a `[Monitor timed out` event.
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return 0
            read_size = min(TAIL_BYTES, size)
            f.seek(size - read_size)
            data = f.read(read_size)
    except OSError:
        return 0

    monitor_use_ids = {m.group(1) for m in MONITOR_USE_RE.finditer(data)}
    started: set[bytes] = set()
    for m in MONITOR_RESULT_RE.finditer(data):
        if m.group(1) in monitor_use_ids:
            started.add(m.group(2))
    non_persistent: set[bytes] = {
        m.group(1) for m in MONITOR_PERSISTENT_RE.finditer(data) if m.group(2) == b"false"
    }
    terminated: set[bytes] = set()
    for m in TASK_STOP_RE.finditer(data):
        terminated.add(m.group(1))
    for m in MONITOR_TIMEOUT_RE.finditer(data):
        terminated.add(m.group(1))
    # First-match monitors (persistent=false) end on the match event itself;
    # Claude Code writes no explicit terminator in that case.
    for m in TASK_NOTIF_TASKID_RE.finditer(data):
        tid = m.group(1)
        if tid in non_persistent:
            terminated.add(tid)
    return len(started - terminated)


def count_active_agents(path: Path) -> int:
    """Number of foreground sub-agent (Agent tool) calls still in flight.

    A foreground Agent blocks the parent: its tool_use line is written when
    the agent is spawned, and the matching tool_result lands when it returns.
    Unmatched tool_use IDs ⇒ Claude is currently waiting on a sub-agent
    (typical for gsd-* workflows that spawn planner/executor/researcher).

    Background agents (run_in_background=true) get an immediate tool_result
    with a "Started agent…" wrapper, so this function won't catch them — it
    only reflects foreground in-flight work, which is the case the user cares
    about ("gsd is currently running and I'm waiting").
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return 0
            read_size = min(TAIL_BYTES, size)
            f.seek(size - read_size)
            data = f.read(read_size)
    except OSError:
        return 0

    use_ids = {m.group(1) for m in AGENT_USE_RE.finditer(data)}
    if not use_ids:
        return 0
    completed = {m.group(1) for m in TOOL_RESULT_ID_RE.finditer(data) if m.group(1) in use_ids}
    return len(use_ids - completed)


def count_active_async_agents(path: Path) -> int:
    """Number of background sub-agents (Agent run_in_background=True) in flight.

    Async agents return their tool_result immediately ("Async agent launched
    successfully\\nagentId: <hex>"), so count_active_agents — which keys off
    the foreground tool_use→tool_result pairing — sees them as already done.
    Without this counter, an orchestrator that dispatches async work and waits
    silently (e.g. gsd-execute-phase between waves) looks idle to the monitor
    and fires a premature WAITING notification mid-run.

    Termination signal: a <task-notification> whose <task-id> matches the
    launched agentId, with <status> in TERMINAL. Same shape that
    has_active_shells already uses for bg shells.
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return 0
            read_size = min(TAIL_BYTES, size)
            f.seek(size - read_size)
            data = f.read(read_size)
    except OSError:
        return 0

    launched = {m.group(1) for m in ASYNC_AGENT_LAUNCH_RE.finditer(data)}
    if not launched:
        return 0
    ended: set[bytes] = set()
    for m in TASK_NOTIF_RE.finditer(data):
        tid, status = m.group(1), m.group(2).lower()
        if tid in launched and status.decode("ascii", errors="replace") in TERMINAL:
            ended.add(tid)
    return len(launched - ended)
