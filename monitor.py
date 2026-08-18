"""Claude Code session monitor — always-on-top overlay for Windows.

One hook-driven state engine (scan_state_files(), reading
~/.claude/monitor-state/*.json written by hooks/state-writer.sh) drives the
overlay, toasts, sound, taskbar flash and Telegram push, via
select_render_sessions() — the single seam through which its output
reaches rendering. The legacy jsonl scan (scan()) is retained only as a
data source for three named hybrid fallbacks (the hookless-container
bridge now, interrupt-recovery + hook-silence pins in plan 03-02), never
as a second rendered verdict. `--state-files` is accepted but ignored —
retained-but-inert so existing launch shortcuts keep working.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

SINGLETON_PORT = 52731  # loopback bind used as a single-instance lock (POSIX)
_SINGLETON_HANDLE = None  # Windows mutex HANDLE or POSIX socket


def _release_singleton() -> None:
    global _SINGLETON_HANDLE
    handle = _SINGLETON_HANDLE
    _SINGLETON_HANDLE = None
    if handle is None:
        return
    try:
        if os.name == "nt" and isinstance(handle, int):
            import ctypes
            ctypes.windll.kernel32.CloseHandle(handle)
        elif hasattr(handle, "close"):
            handle.close()
    except Exception:
        pass

PROJECTS_DIR = Path.home() / ".claude" / "projects"
AUQ_LOCK_DIR = Path.home() / ".claude" / "auq-locks"
# Ignore lock files older than this — defends against ghost locks when the
# PostToolUse cleanup hook never fires (Claude crash, hook timeout). 1h
# matches MAX_AGE_SEC: any session past it is dropped from the UI anyway.
AUQ_LOCK_MAX_AGE_SEC = 3600
# Working lock: UserPromptSubmit drops ~/.claude/working-locks/<sid> at the
# start of a turn and PreToolUse re-touches it at the start of every tool; a
# Stop hook removes it at the end. Claude Code batches jsonl writes — an
# assistant tool_use record only lands together with its tool_result, i.e. when
# the tool FINISHES. So both at the prompt→first-flush gap AND while any tool is
# in flight, the file tail still looks like the previous record (a bare prompt
# or an assistant `text` reply) and the tail logic would expire mid-work (false
# WAITING + notification). Re-arming on PreToolUse keeps the lock mtime ahead of
# the still-stale jsonl for the whole in-flight window. Same ghost-lock defence
# as AUQ: ignore anything older than an hour. See hooks/ for the hook script
# + installer.
WORKING_LOCK_DIR = Path.home() / ".claude" / "working-locks"
WORKING_LOCK_MAX_AGE_SEC = 3600
# The state-writer engine: one small JSON verdict file per session_id,
# written atomically by hooks/state-writer.sh on lifecycle events.
# Module-level so tests can repoint them the way they already repoint
# PROJECTS_DIR/AUQ_LOCK_DIR. See scan_state_files() below — this engine is
# the primary source rendering and notification are driven from (D-01),
# reached through select_render_sessions().
STATE_DIR = Path.home() / ".claude" / "monitor-state"
# A WORKING verdict whose heartbeat (record ts_ms) has gone silent this long
# is treated as stale — the same "~10 min heartbeat silence" staleness
# design D-06 keeps at today's behaviour, now driven by the state file
# instead of jsonl mtimes. Covers the hook-silent Esc interrupt, the
# permission-denial dead end and the killed container (TEST-MATRIX cases
# 8, 5-deny, 9) once cross-checked against docker liveness.
STATE_HEARTBEAT_STALE_SEC = 600
# Shorter staleness window used only when the record's last_event is
# UserPromptSubmit: a turn that dies before its first tool call has no
# PostToolUse/PostToolBatch heartbeat to wait on, so it must not sit WORKING
# for the full heartbeat window (TEST-MATRIX case 19, the abandoned
# pre-tool prompt). Deliberately identical to legacy's
# USER_PROMPT_WORKING_SEC so the abandoned-prompt window matches exactly.
STATE_PROMPT_STALE_SEC = 90
# Best-effort orphan cleanup for a state file SessionEnd never got the
# chance to remove — the one hook-silent path is a killed container
# (RESEARCH Pitfall 10). 24h is far past MAX_AGE_SEC's one-hour visibility
# window, so pruning can never remove a file the engine would still show.
STATE_PRUNE_AGE_SEC = 86400
# WR-04 clock-skew guard: how far `ts_ms`-derived age is allowed to
# under-report the filesystem-mtime-derived age before `_state_record_age`
# stops trusting `ts_ms` and falls back to `mtime`. Generous (a few
# minutes) so ordinary write-then-stat scheduling jitter never trips it —
# this only guards against a container clock running noticeably AHEAD of
# the host, the dangerous direction (see `_state_record_age`).
STATE_CLOCK_SKEW_GUARD_SEC = 300
# SessionEnd tombstone marker suffix (D-06): hooks/state-writer.sh drops a
# zero-byte "<session_id>.ended" file alongside removing the state file, so
# a cleanly-ended session's ghost jsonl row can never resurrect through the
# legacy_origin bridge (scan_state_files() below), even across a monitor
# restart that would otherwise forget an in-process suppression set. Chosen
# so it can never collide with the "*.json" glob the state-record loop uses.
STATE_TOMBSTONE_SUFFIX = ".ended"
# Notification group-gate (quick-260807-iz2): a worktree checkout of the
# same repo (e.g. .claude/worktrees/prd-gsd) sits on its own cwd but is the
# SAME work group as its main-checkout sibling — the real 2026-08-07 case
# (session 6fff7d17 at /workspace, sibling 8ced4fe8 at
# /workspace/.claude/worktrees/prd-gsd, same job, two containers). Truncate
# from this marker onward so both fold onto the same group key.
WORKTREE_MARKER = "/.claude/worktrees/"
# Append-only jsonl log of every notification decision, sent AND suppressed
# (quick-260807-iz2), so the group gate above can be audited against the
# field before it's trusted. The todo that requested this proposed
# monitor-state/, but that directory is the hook writer's per-session state
# store that scan_state_files() sweeps and prunes on its own schedule — a
# monitor-written append-only log belongs beside hook-events.log, at the
# same ~/.claude root and in the same jsonl-with-size-guard shape
# (hooks/event-logger.sh), not inside a directory something else owns and
# cleans. Module-level so tests repoint it exactly as they repoint
# STATE_DIR/PROJECTS_DIR.
NOTIFICATIONS_LOG = Path.home() / ".claude" / "notifications.log"
NOTIFICATIONS_LOG_MAX_BYTES = 5 * 1024 * 1024
# How long a gated notification may sit held before it's dropped outright
# rather than fired late. A toast released 40 minutes after the fact would
# misinform the user about when the session actually became ready, and
# dropping it costs nothing — the overlay keeps rendering the session green
# for the whole hold, so the information is never actually lost, just not
# pushed. Precedent: the legacy bg-shell WORKING pin (quick-260731-an2) used
# the same "don't let a stale signal run forever" reasoning with a
# 900-second cap before badge-only replaced it entirely.
NOTIFY_GATE_MAX_HOLD_SEC = 1800
# Optional launcher-registry integration: a shell script with a PROJECTS=( ... )
# array (label|... entries) that controls project naming and display order.
# Point CLAUDE_LAUNCHER_SH at it; without it, labels fall back to path segments.
LAUNCHER_SH = Path(os.environ.get("CLAUDE_LAUNCHER_SH", "")) if os.environ.get("CLAUDE_LAUNCHER_SH") \
    else Path(__file__).resolve().parent / "launcher.sh"
CONFIG_FILE = Path.home() / ".claude-monitor-config.json"
REFRESH_MS = 5000
MAX_AGE_SEC = 3600
NOTIFY_MIN_WORK_SEC = 60  # only beep+flash if Claude was working for at least this long
# Window after a plain-user-prompt tail during which Claude is presumed to be
# generating the first response. Short because if no assistant record appears
# within this time the session is almost certainly abandoned.
USER_PROMPT_WORKING_SEC = 90
# Window after a tool_result tail during which Claude is presumed still mid-turn.
# A tool_result means Claude owes a follow-up — the next assistant event can be
# delayed by slow bash output, deep thinking, or long web research, so the
# window has to cover realistic model+tool latencies. Bounded by MAX_AGE_SEC
# overall so truly abandoned sessions still drop out of the list after an hour.
TOOL_RESULT_WORKING_SEC = 900  # 15 min
# Notification WAV played on every long-work-ready transition. Order matters:
# the first file that exists wins. `tada.wav` is the classic Windows "ta-da!"
# three-note flourish — short, musical, identical across devices. Fallback
# chain covers Windows installs where tada is missing.
NOTIFY_WAV_FILES = (
    r"C:\Windows\Media\chimes.wav",
    r"C:\Windows\Media\Windows Notify.wav",
    r"C:\Windows\Media\Alarm01.wav",
    r"C:\Windows\Media\chord.wav",
    r"C:\Windows\Media\tada.wav",
    r"C:\Windows\Media\Ring01.wav",
)
# Play the sample N times in a row so it stays audible even if the user is
# briefly away from the keyboard. Interval must exceed the sample length
# (tada.wav ≈ 1.3s) or successive SND_ASYNC plays cut each other off.
NOTIFY_REPEAT = 3
NOTIFY_REPEAT_INTERVAL_MS = 1500

# .env at repo root is read at startup so Telegram credentials live outside
# the code (file is gitignored). Both keys are optional — if either is missing
# the Telegram channel is skipped silently; toast/audio/flash still fire.
ENV_FILE = Path(__file__).resolve().parent / ".env"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_TIMEOUT_SEC = 5


def load_env() -> dict[str, str]:
    """Minimal .env parser: KEY=VALUE lines, ignores blanks and #-comments.

    Full-blown python-dotenv isn't worth the dependency for two keys.
    """
    env: dict[str, str] = {}
    try:
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env

DEFAULT_SIZE = {"standard": (300, 200), "compact": (250, 60)}
DEFAULT_MARGIN = (20, 60)  # right, bottom — bottom margin clears the Windows taskbar
DEFAULT_CONFIG = {
    "mode": "standard",
    # Geometry is computed at runtime (bottom-right of the active screen).
    "standard": "",
    "compact": "",
    # Audio-only mute for local notifications (quick-260818-bfm narrowed its
    # scope): the toast popup and the taskbar flash always fire — this
    # switch silences the beep/chime alone.
    "local": True,
    # Telegram push to the phone. Independent of "local" — silencing the
    # desk's audio leaves the toast/flash visible AND still pages the phone;
    # silence one without the other (mute the desk but keep the phone, or
    # vice versa).
    "telegram": True,
    # {alias_key: label} — runtime session labels, persisted so they survive
    # a monitor restart AND a sessionId rotation (/clear, /resume, CLI
    # restart): alias_key is the container hostname (namespaced with
    # ALIAS_HOST_PREFIX) when resolvable, or today's row key otherwise. See
    # derive_alias_key(). Pruned at startup once the container is gone.
    "aliases": {},
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    data: dict = {}
    try:
        loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    if cfg["mode"] not in ("standard", "compact"):
        cfg["mode"] = "standard"
    # Migrate the pre-split "sound" key (it gated audio only) into the new
    # "local" switch when an older config is loaded — semantically exact
    # now that "local" itself gates audio only (quick-260818-bfm).
    if "local" not in data and isinstance(data.get("sound"), bool):
        cfg["local"] = data["sound"]
    if not isinstance(cfg["local"], bool):
        cfg["local"] = True
    if not isinstance(cfg["telegram"], bool):
        cfg["telegram"] = True
    # Always rebuild aliases into a fresh, sanitised dict — never share the
    # DEFAULT_CONFIG instance (mutable-default trap), and drop any non-string
    # or blank entries a hand-edited config might carry.
    raw = cfg.get("aliases")
    cfg["aliases"] = (
        {k: v.strip() for k, v in raw.items()
         if isinstance(k, str) and isinstance(v, str) and v.strip()}
        if isinstance(raw, dict) else {}
    )
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg), encoding="utf-8")
    except OSError:
        pass


def launcher_order() -> dict[str, int]:
    """Parse launcher.sh PROJECTS array, return {label: index}. Empty on failure."""
    try:
        text = LAUNCHER_SH.read_text(encoding="utf-8")
    except OSError:
        return {}
    order: dict[str, int] = {}
    in_array = False
    idx = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not in_array:
            if line.startswith("PROJECTS=("):
                in_array = True
            continue
        if line.startswith(")"):
            break
        # entries look like: "label|script|optional_dir"  or  ""  (separator)
        if not (line.startswith('"') and line.endswith('"')):
            continue
        inner = line[1:-1]
        if not inner:
            continue
        label = inner.split("|", 1)[0]
        if label and label not in order:
            order[label] = idx
            idx += 1
    return order


def tail_last_line(path: Path) -> str | None:
    """Most recent user/assistant line, skipping `system` meta records."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            read_size = min(32768, size)
            f.seek(size - read_size)
            data = f.read(read_size)
            lines = [ln for ln in data.splitlines() if ln.strip()]
            if not lines:
                return None
            for raw in reversed(lines):
                try:
                    obj = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(obj, dict) and obj.get("type") in ("user", "assistant"):
                    return raw.decode("utf-8", errors="replace")
            return lines[-1].decode("utf-8", errors="replace")
    except OSError:
        return None


def _workdir_to_encoded(workdir: str) -> str:
    # Claude Code encodes the project path by replacing non-alphanumerics with '-'.
    # Linux workdirs like "/workspace/foo" → "-workspace-foo".
    if not workdir:
        return ""
    return workdir.replace("/", "-").replace("\\", "-").replace(":", "-")


def parse_last_action(line: str | None) -> str:
    if not line:
        return ""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return ""

    # Claude Code session events: wrapper has 'type' (user/assistant/...) and 'message'
    msg = obj.get("message") if isinstance(obj, dict) else None
    content = None
    if isinstance(msg, dict):
        content = msg.get("content")
    if content is None and isinstance(obj, dict):
        content = obj.get("content")

    label = ""
    if isinstance(content, list):
        for item in reversed(content):
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            if t == "tool_use":
                label = f"🔧 {item.get('name', 'tool')}"
                break
            if t == "text":
                label = "💬 reply"
                break
            if t == "tool_result":
                label = "✓ result"
                break
    elif isinstance(content, str) and content.strip():
        label = "💬 reply"

    if not label:
        label = obj.get("type", "") if isinstance(obj, dict) else ""

    return label[:30]


def user_tail_kind(line: str | None) -> str:
    """Classify a `user` tail: "tool_result", "prompt", or "" (not a user tail).

    tool_result ⇒ Claude just finished a tool and owes a follow-up — can legitimately
    take many minutes (slow bash, deep thinking, long web research).
    prompt      ⇒ a fresh user message; Claude's first token should arrive within seconds,
    so a long silence means the session was abandoned mid-turn.
    """
    if not line:
        return ""
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(obj, dict) or obj.get("type") != "user":
        return ""
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else obj.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                return "tool_result"
        return "prompt"
    return "prompt"


def is_certainly_working(line: str | None) -> bool:
    """True ⇔ the tail proves Claude is actively mid-turn.

    Default posture: assume idle (GREEN). Flip to GREY only when evidence is
    unambiguous — a stale/interrupted session must not stay grey forever.

    Working signals (from the last user/assistant record):
      - assistant record with a `thinking` block (model is still generating)
      - assistant record whose last block is a `tool_use` other than
        `AskUserQuestion` — Claude is mid-loop, waiting for a tool_result

    Anything else (assistant text reply, AskUserQuestion, user/tool_result,
    plain user prompt, malformed line, missing file) counts as idle.
    """
    if not line:
        return False
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return False
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    for item in reversed(content):
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "thinking":
            return True
        if kind == "tool_use":
            return item.get("name") != "AskUserQuestion"
        if kind == "text":
            return False
    return False


def fmt_age(sec: float) -> str:
    s = int(sec)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def parse_geometry(geom: str) -> tuple[int, int, int, int] | None:
    """Parse a Tk geometry string "WxH+X+Y" into (w, h, x, y), or None if malformed.

    Tkinter reports a window dragged off the left/top edge as "+-609": the "+" is
    the field separator and "-609" the (negative) coordinate. Stripping the leading
    separator keeps int() from choking on the "+-" pair.
    """
    m = re.match(r"(\d+)x(\d+)([+-]-?\d+)([+-]-?\d+)$", geom)
    if not m:
        return None
    try:
        return (
            int(m.group(1)), int(m.group(2)),
            int(m.group(3).lstrip("+")), int(m.group(4).lstrip("+")),
        )
    except ValueError:
        return None


def _extract_session_id(last_line: str | None) -> str | None:
    if not last_line:
        return None
    try:
        obj = json.loads(last_line)
    except (json.JSONDecodeError, ValueError):
        return None
    sid = obj.get("sessionId") if isinstance(obj, dict) else None
    return sid if isinstance(sid, str) else None


def resolve_alias(answer: str | None, previous: str = "") -> str:
    """Normalize a raw label-dialog answer to the value the monitor stores.

    The dialog has three outcomes: `None` means the user cancelled (keep the
    previous value), an empty/whitespace string means "clear it", anything
    else is stored stripped. Aliases are runtime-only — they let the user tell
    apart two sessions that share a launcher label (two `yunoai-france`) and are
    dropped on monitor restart or when the session ends.
    """
    if answer is None:
        return previous
    return answer.strip()


# Namespaces container-derived alias keys so a hostname string can never
# collide with (and silently steal) a raw sessionId- or dir-fallback-keyed
# alias entry already sitting in the same config dict.
ALIAS_HOST_PREFIX = "host:"


def derive_alias_key(hostname: str | None, fallback_key: str) -> str:
    """Resolve the identity a session label is stored under.

    The user is labelling the container/terminal, not the conversation: a
    label must outlive a sessionId rotation (/clear, /resume, CLI restart).
    When the container's hostname is known, it becomes the alias identity
    (namespaced with ALIAS_HOST_PREFIX, both engines can observe it, and it
    is stable across those rotations). When it isn't resolvable (no docker,
    no state-file hostname), `fallback_key` — today's row key — is returned
    unchanged, preserving existing behaviour exactly for those sessions.
    """
    if isinstance(hostname, str) and hostname:
        return f"{ALIAS_HOST_PREFIX}{hostname}"
    return fallback_key


# ---------------------------------------------------------------------------
# The state-writer engine — reads ~/.claude/monitor-state/ (hooks/state-
# writer.sh's output) as the primary verdict source rendering and
# notification are driven from (D-01); see select_render_sessions(), the
# single seam that carries its output to rendering.
# ---------------------------------------------------------------------------

def _read_state_file(path: Path) -> dict | None:
    """Defensive read of one monitor-state/<session_id>.json file.

    Mirrors tail_last_line()'s idiom exactly: any read/parse failure
    degrades to None rather than raising, so a missing (hookless container),
    corrupt, or partially-written file (caught mid tmp-rename, TEST-MATRIX
    case 20) can never crash a scan_state_files() tick — it just drops that
    one session.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _state_to_status(state: str | None) -> tuple[str, str, str, int]:
    """Map a state-file `state` value to the same (status, dot, color, rank)
    tuple legacy's scan() builds, so scan_state_files()'s output is a
    structural lookalike the divergence comparator can pair by key.

    `working` -> WORKING (grey, "#666", rank 2). `waiting`, `needs_input`
    (D-07: identical to turn-end green, no new color) and `idle` all ->
    WAITING (green, "#4ade80", rank 1) — legacy's exact WAITING colour. Any
    unknown, missing, or wrong-typed value (a record whose `state` is a
    number, say) also -> WAITING, matching legacy's default-green posture
    (scan() only flips to WORKING on unambiguous evidence) and giving
    Task 1's malformed-record robustness a free ride: a bad `state` value
    just never equals the string "working".
    """
    if state == "working":
        return "WORKING", "●", "#666", 2
    return "WAITING", "●", "#4ade80", 1


# Compact per-event labels for the state-file list's `action` column — the
# state-file-engine equivalent of legacy's parse_last_action() jsonl-tail
# label, derived from the state file's own last_event instead.
_STATE_ACTION_LABELS = {
    "SessionStart": "session start",
    "UserPromptSubmit": "prompt",
    "PreToolUse": "tool start",
    "PostToolUse": "tool done",
    "PostToolUseFailure": "tool failed",
    "PostToolBatch": "tool batch",
    "PermissionRequest": "permission",
    "Notification": "notify",
    "Stop": "turn end",
    "SubagentStop": "subagent",
    "SessionEnd": "session end",
}


def _state_action_label(last_event: object) -> str:
    """Best-effort, never-raise label for an arbitrary `last_event` value —
    a known event name maps to a short phrase, an unrecognised string is
    shown as-is, anything else (missing, wrong type) is blank."""
    if not isinstance(last_event, str) or not last_event:
        return ""
    return _STATE_ACTION_LABELS.get(last_event, last_event)


def _state_record_age(obj: dict, mtime: float, now: float) -> float:
    """Age of a state record, preferring its own `ts_ms` over the file's
    mtime when `ts_ms` is a usable number — the file mtime is always
    trustworthy (it can't be corrupted by a half-written record, since the
    writer's tmp+rename only ever commits a complete file) but `ts_ms` is
    the more precise signal when present and well-formed.

    WR-04 clock-skew guard: `ts_ms` is written inside the container (its
    own clock domain) while `mtime` and `now` are both read on the monitor
    host. If a container's clock runs noticeably AHEAD of the host, a raw
    `ts_ms`-derived age would under-report the true age indefinitely and a
    genuinely dead WORKING session could never recover via the
    heartbeat-silence fallback — exactly the "must keep telling the user
    this session needs you now" failure the Core Value calls out. Guarded
    one-directionally only: when `ts_ms` reports an age more than
    STATE_CLOCK_SKEW_GUARD_SEC FRESHER than `mtime` says, distrust it and
    fall back to `mtime`. The opposite direction (a container clock behind
    the host, `ts_ms` reporting an OLDER age than `mtime`) is left
    untouched — it only makes a session look stale a little early, the
    less dangerous direction, and is also exactly how this file's own
    staleness tests simulate an aged record without sleeping in real time
    (a freshly-written file carrying a deliberately backdated `ts_ms`).
    """
    ts_ms = obj.get("ts_ms")
    if isinstance(ts_ms, (int, float)) and ts_ms > 0:
        ts_age = now - (ts_ms / 1000.0)
        mtime_age = now - mtime
        if ts_age < mtime_age - STATE_CLOCK_SKEW_GUARD_SEC:
            return mtime_age
        return ts_age
    return now - mtime


def scan_state_files(label_map: dict[str, str] | None = None,
                      sessionid_to_label: dict[str, str] | None = None,
                      container_info: dict | None = None,
                      legacy_sessions: list[dict] | None = None,
                      hostname_to_name: dict[str, str] | None = None) -> list[dict]:
    """The primary verdict engine: derives one verdict per session from
    ~/.claude/monitor-state/*.json (written atomically by
    hooks/state-writer.sh) instead of parsing any jsonl.

    Mirrors scan()'s session-dict shape (same keys legacy emits) plus its
    own extras (`state`, `last_event`, `hostname`, `background_tasks_count`).
    `label_map` is accepted for signature parity with scan() (D-05 requires
    reproducing today's labels); state files always carry a real
    session_id (the filename stem), so `sessionid_to_label` and, as a
    fallback, `container_info["hostname_to_label"]` are what's actually
    consulted here — the hostname fallback matters because
    `sessionid_to_label` is built via `docker exec` (query_container_sessionids),
    which cannot reach a paused container; without it a paused session's
    label would be unresolved and it would vanish from the rendered list,
    making the paused-stays-WORKING staleness branch below unreachable.

    `hostname_to_name` (scan_containers()'s fifth return element) resolves
    each row's `display_name` via session_display_name(); rows carried
    through the legacy bridge already have it from scan().

    `container_info` (scan_containers()'s fourth return element) also gates
    a stale WORKING verdict: past STATE_HEARTBEAT_STALE_SEC (or the shorter
    STATE_PROMPT_STALE_SEC when the last event was UserPromptSubmit)
    without a fresher heartbeat, the verdict recovers to WAITING — unless
    the record's hostname maps to a `paused` container, which D-06 treats
    as alive-but-frozen, never dead. This is the named fallback for the
    permission-denial dead end, the killed container and the abandoned
    pre-tool prompt (TEST-MATRIX cases 5-deny, 9, 19) — none of which emit
    any hook event to hang a transition on.

    Two more fallbacks extend that same staleness block, both reading
    evidence `scan()` already computed once per tick via `legacy_sessions`
    — never a second jsonl read or WORKING_LOCK_DIR stat:

    - D-02a (Esc-interrupt early recovery, TEST-MATRIX case 8): when the
      matching legacy entry reports `working_locked` False AND its jsonl
      `mtime` is newer than the state record's own, recovers to WAITING
      before the heartbeat window elapses — `working_locked` False alone is
      ambiguous (also the pre-turn state), the jsonl-advance conjunct is
      what proves an interrupt already happened (UAT C1, cc 2.1.220).
    - D-02b (hook-silence pin, divergence class 6 — 9 events/week, longest
      ~50min): when the matching legacy entry reports `agent_activity` True
      or `working_locked` True, suppresses the post-window WAITING
      transition the same way the paused-container exception does — a
      long-running Monitor tool, foreground subagent or slow Bash call
      keeps the session pinned WORKING instead of firing a false
      notification.

    Both are inert whenever the matching legacy entry is missing (a
    hookless or jsonl-invisible session falls through to the plain window).

    Degrades one session at a time, never the whole tick (TEST-MATRIX case
    20): a directory-listing failure returns an empty list, a single file's
    stat/read failure — including the file vanishing between the listing
    and the read, an inherent race against the writer's own tmp+rename —
    drops only that session, and a record missing or misshaping any field
    still yields a usable (if defensively-defaulted) session.

    Also prunes state files this engine will never show again:
    SessionEnd already removes a file on every clean exit/resume/clear, so
    this best-effort sweep only ever catches the one hook-silent path — a
    killed container — well after MAX_AGE_SEC has already hidden it
    (STATE_PRUNE_AGE_SEC, 24h, is 24x the one-hour visibility window). Two
    more sweeps run alongside it, same age threshold, same best-effort
    single-file-failure isolation: orphaned SessionEnd tombstones
    (STATE_TOMBSTONE_SUFFIX markers — see below) and leftover atomic-write
    `*.json.tmp.*` files from an interrupted write (D-08/T-03-03) — the
    writer's tmp+rename completes in milliseconds, so anything this old is
    unambiguously orphaned, never a write genuinely in flight.

    `legacy_sessions` (ENG-05's migration bridge, D-02c, TEST-MATRIX case
    21): every session `refresh()`'s already-computed legacy `scan()` saw
    but that has no state file — a hookless container, by definition — is
    carried through unchanged, tagged `legacy_origin`. This is a permanent
    v1 behaviour, not a diagnostic tag: it is how a hookless container
    stays visible at all post-flip. When `legacy_sessions` is None,
    `scan(label_map, sessionid_to_label)` runs internally instead, so a
    standalone caller still sees the complete picture without a second
    full jsonl scan every tick.

    SessionEnd tombstones (D-06): hooks/state-writer.sh drops a
    STATE_TOMBSTONE_SUFFIX marker alongside removing a session's state
    file. A legacy entry whose key/session_id matches a live tombstone is
    excluded from the bridge above — the state engine SAW this session end,
    so its still-fresh jsonl must never resurrect it as a ghost row, even
    across a monitor restart (an in-process suppression set would forget on
    restart; the on-disk marker doesn't). A resumed session's own fresh
    state record deletes its stale tombstone as it's read, so a resume can
    never be suppressed by its own earlier SessionEnd.
    """
    if legacy_sessions is None:
        legacy_sessions = scan(label_map, sessionid_to_label, container_info=container_info)
    # D-02a/D-02b fallback lookup: keyed by `key`, and by `session_id` too
    # when it differs, so a state record finds its legacy counterpart in
    # O(1). Built once per tick from the already-computed legacy_sessions —
    # the per-record loop below never opens a jsonl or stats a lock file.
    legacy_by_id: dict[str, dict] = {}
    for legacy in legacy_sessions:
        legacy_by_id[legacy["key"]] = legacy
        sid = legacy.get("session_id")
        if sid and sid not in legacy_by_id:
            legacy_by_id[sid] = legacy

    sessions: list[dict] = []
    tombstone_ids: set[str] = set()
    if STATE_DIR.is_dir():
        now = time.time()
        # Sweep 1: SessionEnd tombstones (D-06). A tombstone marks a
        # session the state engine SAW end — the legacy bridge below must
        # never resurrect it as a ghost row via that session's still-fresh
        # jsonl. Pruned past STATE_PRUNE_AGE_SEC exactly like an orphaned
        # state file; a single bad stat/unlink drops only that one marker.
        try:
            tombstones = list(STATE_DIR.glob(f"*{STATE_TOMBSTONE_SUFFIX}"))
        except OSError:
            tombstones = []
        for t in tombstones:
            try:
                t_mtime = t.stat().st_mtime
            except OSError:
                continue
            if now - t_mtime > STATE_PRUNE_AGE_SEC:
                try:
                    t.unlink()
                except OSError:
                    pass
                continue
            tombstone_ids.add(t.name[:-len(STATE_TOMBSTONE_SUFFIX)])
        # Sweep 2: orphaned atomic-write temp files (D-08/T-03-03). The
        # writer's tmp+rename completes in milliseconds, so anything past
        # STATE_PRUNE_AGE_SEC is unambiguously interrupted, never a write
        # genuinely in flight.
        try:
            temp_files = list(STATE_DIR.glob("*.json.tmp.*"))
        except OSError:
            temp_files = []
        for tf in temp_files:
            try:
                tf_mtime = tf.stat().st_mtime
            except OSError:
                continue
            if now - tf_mtime > STATE_PRUNE_AGE_SEC:
                try:
                    tf.unlink()
                except OSError:
                    pass
        try:
            entries = list(STATE_DIR.glob("*.json"))
        except OSError:
            entries = []
        for f in entries:
            session_id = f.stem
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            age_by_mtime = now - mtime
            if age_by_mtime > STATE_PRUNE_AGE_SEC:
                try:
                    f.unlink()
                except OSError:
                    pass
                continue
            if age_by_mtime > MAX_AGE_SEC:
                continue
            obj = _read_state_file(f)
            if obj is None:
                continue
            hostname = obj.get("hostname")
            hostname = hostname if isinstance(hostname, str) and hostname else None
            # cwd (quick-260807-iz2): read the same defensive way as
            # hostname above — a missing or non-string value becomes None,
            # never a crash or a stray "" that would masquerade as a real
            # path. Consumed only by notification_group_key(); scan_state_files
            # itself never opens, joins, globs or stats this value.
            cwd = obj.get("cwd")
            cwd = cwd if isinstance(cwd, str) and cwd else None
            name = sessionid_to_label.get(session_id) if sessionid_to_label else None
            if name is None and container_info and hostname:
                name = container_info.get("hostname_to_label", {}).get(hostname)
            if name is None:
                continue
            age = _state_record_age(obj, mtime, now)
            state_val = obj.get("state")
            last_event = obj.get("last_event")
            status, dot, color, rank = _state_to_status(state_val)
            if status == "WORKING":
                window = (STATE_PROMPT_STALE_SEC if last_event == "UserPromptSubmit"
                          else STATE_HEARTBEAT_STALE_SEC)
                legacy_match = legacy_by_id.get(session_id)
                container_status = None
                if container_info and hostname:
                    container_status = container_info.get(
                        "hostname_to_status", {}).get(hostname)
                # D-02a — Esc-interrupt early recovery (TEST-MATRIX case 8):
                # working_locked False alone is ambiguous (also the
                # pre-turn state) — the jsonl mtime advancing past the state
                # record's own mtime is what proves the interrupt already
                # happened (UAT C1, cc 2.1.220), so recover now rather than
                # waiting out the rest of the window. Floored at
                # STATE_PROMPT_STALE_SEC so a state record that's still
                # genuinely fresh (write-order races between the hook and
                # the jsonl at turn start, both landing within the same
                # instant) can never misfire this as an interrupt.
                early_recovery = (
                    STATE_PROMPT_STALE_SEC < age <= window
                    and legacy_match is not None
                    and legacy_match.get("working_locked") is False
                    and legacy_match.get("status") != "WORKING"
                    and isinstance(legacy_match.get("mtime"), (int, float))
                    and legacy_match["mtime"] > mtime
                )
                if early_recovery:
                    if container_status != "paused":
                        status, dot, color, rank = "WAITING", "●", "#4ade80", 1
                elif age > window:
                    # D-02b — hook-silence pin (divergence class 6): a
                    # still-in-flight Monitor/foreground-Agent/async-agent
                    # (agent_activity) or an armed working-lock suppresses
                    # the transition exactly like the paused-container
                    # exception below it.
                    pinned = legacy_match is not None and (
                        legacy_match.get("agent_activity")
                        or legacy_match.get("working_locked")
                    )
                    if container_status != "paused" and not pinned:
                        status, dot, color, rank = "WAITING", "●", "#4ade80", 1
            bg_count = obj.get("background_tasks_count")
            if not isinstance(bg_count, (int, float)):
                bg_count = None
            sessions.append({
                "key": session_id,
                "name": name,
                "session_id": session_id,
                "encoded_dir": "",
                "dot": dot,
                "dot_color": color,
                "status": status,
                "rank": rank,
                "age": age,
                "mtime": mtime,
                "action": _state_action_label(last_event),
                "state": state_val,
                "last_event": last_event,
                "hostname": obj.get("hostname"),
                "cwd": cwd,
                "background_tasks_count": bg_count,
                "alias_key": derive_alias_key(hostname, session_id),
                "display_name": session_display_name(name, hostname, hostname_to_name),
            })
            if session_id in tombstone_ids:
                # A live state record for this session id proves it's a
                # resumed session, not a stale end-of-session marker —
                # delete the tombstone so the resume can never be
                # suppressed by its own earlier SessionEnd.
                try:
                    (STATE_DIR / f"{session_id}{STATE_TOMBSTONE_SUFFIX}").unlink()
                except OSError:
                    pass
                tombstone_ids.discard(session_id)

    seen_keys = {s["key"] for s in sessions}
    for legacy in legacy_sessions:
        if legacy["key"] in seen_keys:
            continue
        if legacy["key"] in tombstone_ids or legacy.get("session_id") in tombstone_ids:
            # The state engine SAW this session end (D-06) — its still-
            # fresh jsonl must never resurrect it as a ghost row.
            continue
        carried = dict(legacy)
        carried["legacy_origin"] = True
        sessions.append(carried)

    order = launcher_order()
    big = len(order) + 1
    sessions.sort(key=lambda s: (order.get(s["name"], big), -s["mtime"]))
    return sessions


def select_render_sessions(sessions: list[dict]) -> list[dict]:
    """The single seam through which the engine's output reaches rendering
    or notification — a one-argument identity seam (D-08): returns the same
    list *object* it was given, unchanged. Kept as a named function, not
    inlined, so a future producer has exactly one documented place to plug
    into rendering.

    `--state-files` is retained-but-inert (RESEARCH.md Open Question 2): it
    no longer selects between two engines — there is only one — so existing
    `monitor.bat` shortcuts keep working without a `--legacy` escape hatch.
    No argv handling exists for it anywhere: this codebase has no argparse,
    so an unrecognised argument is already inert by construction.
    """
    return sessions


# --- Trimmed in-file agent-activity peek (D-02b, D-03) -------------------
# shell_tracker.py is gone: its badge-driving detections (bg-shell start/
# kill, the older task-wrapper status format) went with it, since the badge
# is hook-native now (background_tasks_count). Only the Monitor/foreground-
# Agent/async-agent evidence 02-DIVERGENCE-REVIEW carry-forward #1 named as
# still-needed survives, absorbed here as ONE single-read peek instead of
# three independent whole-file reads per session per tick. Patterns are
# byte-anchored exactly as shell_tracker's were — that anchoring is what
# stops a grep/cat echo of a jsonl (inner quotes escaped as \") from
# spoofing a match; do not relax it.
_PEEK_TAIL_BYTES = 10 * 1024 * 1024
_PEEK_MONITOR_USE_RE = re.compile(
    rb'"type"\s*:\s*"tool_use"\s*,\s*"id"\s*:\s*"(toolu_[A-Za-z0-9]+)"\s*,\s*"name"\s*:\s*"Monitor"'
)
_PEEK_MONITOR_RESULT_RE = re.compile(
    rb'"tool_use_id"\s*:\s*"(toolu_[A-Za-z0-9]+)"[^{}]*?"content"\s*:\s*'
    rb'"Monitor started \(task ([A-Za-z0-9_]+)'
)
_PEEK_MONITOR_PERSISTENT_RE = re.compile(
    rb'"toolUseResult"\s*:\s*\{[^{}]*?"taskId"\s*:\s*"([A-Za-z0-9_]+)"[^{}]*?"persistent"\s*:\s*(true|false)'
)
_PEEK_TASK_STOP_RE = re.compile(
    rb'"name"\s*:\s*"TaskStop".{0,500}?"task_id"\s*:\s*"([A-Za-z0-9_]+)"', re.DOTALL,
)
_PEEK_MONITOR_TIMEOUT_RE = re.compile(
    rb'<task-id>([A-Za-z0-9_]+)</task-id>.{0,1500}?\[Monitor timed out', re.DOTALL,
)
_PEEK_TASK_NOTIF_TASKID_RE = re.compile(
    rb'<task-notification>.{0,2000}?<task-id>([A-Za-z0-9_]+)</task-id>', re.DOTALL,
)
_PEEK_AGENT_USE_RE = re.compile(
    rb'"type"\s*:\s*"tool_use"\s*,\s*"id"\s*:\s*"(toolu_[A-Za-z0-9]+)"\s*,\s*"name"\s*:\s*"Agent"'
)
_PEEK_TOOL_RESULT_ID_RE = re.compile(rb'"tool_use_id"\s*:\s*"(toolu_[A-Za-z0-9]+)"')
_PEEK_ASYNC_AGENT_LAUNCH_RE = re.compile(
    rb'Async agent launched successfully[^"]{0,200}?agentId:\s*([0-9a-f]+)'
)
_PEEK_TASK_NOTIF_RE = re.compile(
    rb"<task-notification>.{0,400}?<task-id>([A-Za-z0-9_]+)</task-id>.{0,800}?<status>([a-zA-Z_]+)</status>",
    re.DOTALL,
)
_PEEK_TERMINAL = {"completed", "failed", "cancelled", "killed", "timeout"}


def _peek_agent_activity(path: Path) -> bool:
    """True when a Monitor tool task, foreground Agent call or async agent
    launch is started-but-not-terminated in `path`'s trailing window.

    Reads the file exactly once and derives all three signals from that one
    buffer — the module this replaces performed three independent whole-file
    reads per session per tick (T-03-09). OSError (missing/vanished file)
    returns the safe default, False, matching shell_tracker's behaviour.
    """
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return False
            read_size = min(_PEEK_TAIL_BYTES, size)
            f.seek(size - read_size)
            data = f.read(read_size)
    except OSError:
        return False

    # Monitor tasks: started only once a tool_use is confirmed by its own
    # "Monitor started (task ...)" tool_result; terminated via TaskStop, a
    # "[Monitor timed out" event, or (persistent=false only) the match event
    # itself, which Claude Code writes no explicit terminator for.
    monitor_use_ids = {m.group(1) for m in _PEEK_MONITOR_USE_RE.finditer(data)}
    monitor_started: set[bytes] = set()
    for m in _PEEK_MONITOR_RESULT_RE.finditer(data):
        if m.group(1) in monitor_use_ids:
            monitor_started.add(m.group(2))
    if monitor_started:
        non_persistent = {
            m.group(1) for m in _PEEK_MONITOR_PERSISTENT_RE.finditer(data)
            if m.group(2) == b"false"
        }
        monitor_terminated: set[bytes] = set()
        for m in _PEEK_TASK_STOP_RE.finditer(data):
            monitor_terminated.add(m.group(1))
        for m in _PEEK_MONITOR_TIMEOUT_RE.finditer(data):
            monitor_terminated.add(m.group(1))
        for m in _PEEK_TASK_NOTIF_TASKID_RE.finditer(data):
            tid = m.group(1)
            if tid in non_persistent:
                monitor_terminated.add(tid)
        if monitor_started - monitor_terminated:
            return True

    # Foreground Agent: blocks the parent turn until its tool_result lands.
    agent_use_ids = {m.group(1) for m in _PEEK_AGENT_USE_RE.finditer(data)}
    if agent_use_ids:
        agent_completed = {
            m.group(1) for m in _PEEK_TOOL_RESULT_ID_RE.finditer(data)
            if m.group(1) in agent_use_ids
        }
        if agent_use_ids - agent_completed:
            return True

    # Async agent (Agent run_in_background=True): its dispatch tool_result
    # returns immediately, so completion is a later <task-notification>
    # carrying the launched agentId with a terminal <status>.
    launched = {m.group(1) for m in _PEEK_ASYNC_AGENT_LAUNCH_RE.finditer(data)}
    if launched:
        ended: set[bytes] = set()
        for m in _PEEK_TASK_NOTIF_RE.finditer(data):
            tid, status = m.group(1), m.group(2).lower()
            if tid in launched and status.decode("ascii", errors="replace") in _PEEK_TERMINAL:
                ended.add(tid)
        if launched - ended:
            return True

    return False


def scan(label_map: dict[str, str] | None = None,
         sessionid_to_label: dict[str, str] | None = None,
         container_info: dict | None = None,
         hostname_to_name: dict[str, str] | None = None) -> list[dict]:
    if not PROJECTS_DIR.is_dir():
        return []
    now = time.time()
    sessions = []
    # Every jsonl within MAX_AGE_SEC is a candidate. No "newest-per-dir" dedup:
    # the sessionId match below already filters out older jsonls of the same
    # container (each CLI invocation gets a fresh sessionId) and jsonls from
    # containers that aren't running, so dedup here would just drop the live
    # session when a freshly-killed sibling container left a newer jsonl behind.
    candidates: list[tuple[Path, Path, float]] = []
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        try:
            for f in proj_dir.glob("*.jsonl"):
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if now - m <= MAX_AGE_SEC:
                    candidates.append((proj_dir, f, m))
        except OSError:
            continue
    for proj_dir, latest, latest_mtime in candidates:
        age = now - latest_mtime
        last_line = tail_last_line(latest)
        agent_activity = _peek_agent_activity(latest)
        # Default GREEN (waiting). Flip to GREY only when evidence is
        # unambiguous: a foreground Agent/Monitor/async agent is in flight
        # (agent_activity), the assistant tail proves Claude is mid-turn
        # (thinking block or tool_use still waiting on its tool_result), or a
        # fresh `user` tail means Claude owes a response and the file is
        # still being written. Stale user tails (without new events) go
        # GREEN so interrupted/abandoned sessions don't get stuck grey
        # forever — but tool_result tails get a much longer grace window
        # because the follow-up turn can legitimately take many minutes
        # (slow bash, deep thinking, long web research). A live background
        # shell is NOT evidence here at all post-flip (D-03): the badge is
        # hook-native (background_tasks_count, read by scan_state_files()),
        # and bg-shell detection was shell_tracker-only — it never belonged
        # in this WORKING chain to begin with, so its removal from `scan()`
        # changes nothing here. When a bg task finishes and re-invokes
        # Claude, that re-invocation emits a fresh UserPromptSubmit
        # (TEST-MATRIX case 13) and grey comes from the working-lock.
        tail_kind = user_tail_kind(last_line)
        if tail_kind == "tool_result":
            fresh_user_tail = age < TOOL_RESULT_WORKING_SEC
        elif tail_kind == "prompt":
            fresh_user_tail = age < USER_PROMPT_WORKING_SEC
        else:
            fresh_user_tail = False
        session_id = _extract_session_id(last_line)
        # User-input wait lock: a hook writes ~/.claude/auq-locks/<sid> whenever
        # Claude is blocked on the user — a PreToolUse hook for an AskUserQuestion
        # modal (cleared by PostToolUse), OR a Notification hook for a tool-
        # permission prompt (e.g. the "dangerous rm" confirmation) or an idle
        # "waiting for your input" nudge. This bypasses the batched-jsonl-flush
        # blind spot — Claude Code 2.1.x only writes the assistant tool_use record
        # together with its tool_result, so during the actual wait the jsonl tail
        # still looks like the previous record and would otherwise stay GREY
        # (worse: the PreToolUse-armed working-lock, set before the permission
        # prompt appears, actively pins WORKING). This lock is checked first and
        # forces WAITING, beating both fresh_user_tail and the working lock.
        # See claude-monitor/hooks/ for the hook scripts + installer.
        auq_locked = False
        if session_id:
            try:
                lock_mtime = (AUQ_LOCK_DIR / session_id).stat().st_mtime
                auq_locked = (now - lock_mtime) < AUQ_LOCK_MAX_AGE_SEC
                # Stale-lock guard: during a real AUQ wait the jsonl is batched
                # and latest_mtime ≈ lock_mtime. Once the user answers, the flush
                # bumps latest_mtime past lock_mtime — if PostToolUse missed the
                # clear (2s timeout, no Stop because Claude keeps working), the
                # lock would otherwise pin WAITING for an hour.
                if auq_locked and latest_mtime > lock_mtime + 5:
                    auq_locked = False
            except OSError:
                pass
        # Working lock: a UserPromptSubmit hook marks the session mid-turn so
        # the monitor stays GREY until the jsonl catches up. The stale-lock
        # guard is the handoff — the lock only has to cover the prompt→first-
        # flush gap, so once latest_mtime advances past the lock the normal tail
        # logic (tool_result's long window, is_certainly_working) takes over. A
        # Stop hook clears the lock at end-of-turn; the guard + max-age cover the
        # case where Stop never fires (interrupt, crash, hook timeout).
        working_locked = False
        if session_id:
            try:
                wlock_mtime = (WORKING_LOCK_DIR / session_id).stat().st_mtime
                working_locked = (now - wlock_mtime) < WORKING_LOCK_MAX_AGE_SEC
                if working_locked and latest_mtime > wlock_mtime + 5:
                    working_locked = False
            except OSError:
                pass
        if auq_locked:
            status, dot, color, rank = "WAITING", "●", "#4ade80", 1
        elif (agent_activity or is_certainly_working(last_line) or fresh_user_tail
                or working_locked):
            status, dot, color, rank = "WORKING", "●", "#666", 2
        else:
            status, dot, color, rank = "WAITING", "●", "#4ade80", 1
        name = None
        if session_id and sessionid_to_label:
            name = sessionid_to_label.get(session_id)
        if name is None and not session_id and label_map and proj_dir.name in label_map:
            # Only fall back to dir-based labelling when the jsonl carries no
            # sessionId at all. A jsonl WITH a sessionId that doesn't match any
            # running container is stale (e.g. a container that shared the dir
            # and was just killed) — labelling it from label_map would paint it
            # with a sibling container's name.
            name = label_map[proj_dir.name]
        if name is None:
            continue
        key = session_id or f"{proj_dir.name}:{latest.name}"
        hostname = None
        if session_id and container_info:
            hostname = container_info.get("sessionid_to_hostname", {}).get(session_id)
        sessions.append({
            "key": key,
            "name": name,
            "display_name": session_display_name(name, hostname, hostname_to_name),
            "session_id": session_id,
            "alias_key": derive_alias_key(hostname, key),
            "encoded_dir": proj_dir.name,
            "dot": dot,
            "dot_color": color,
            "agent_activity": agent_activity,
            "status": status,
            "rank": rank,
            "age": age,
            "mtime": latest_mtime,
            "action": parse_last_action(last_line),
            # Both locks were already computed above for the legacy status
            # decision — reported here too since a hookless-container row
            # carried through scan_state_files()'s legacy bridge (D-02c)
            # needs them, same as any consumer reading a legacy row.
            "auq_locked": auq_locked,
            "working_locked": working_locked,
        })
    order = launcher_order()
    big = len(order) + 1
    sessions.sort(key=lambda s: (order.get(s["name"], big), -s["mtime"]))
    return sessions


def container_display_name(c: dict) -> str:
    """Resolve the text drawn in a docker row.

    The launcher now names a container after its project label and suffixes
    duplicates (`dev-tools`, `dev-tools-2`, ...), so the docker name is a
    strictly-more-specific identifier than the project label WHEN it carries
    that prefix. The prefix test is what makes the fallback safe: a
    docker-generated name (the two-random-words kind, e.g. `dreamy_bose`)
    never carries the project label as a prefix and would be noise where the
    label is the meaningful text, so those containers keep displaying their
    project label exactly as before the launcher change.

    This is a DISPLAY rule only. The project label remains the identifier
    used for sorting, for the container->session label maps
    (label_map / sessionid_to_label / container_info) and for filtering; the
    docker row stays keyed by the container name. Nothing downstream should
    start treating this return value as an identity.

    Lives at module level, outside MonitorApp, so it is unit-testable
    without tkinter — the same reason state_files_mode() is not inlined at
    its call site.
    """
    name = c.get("name")
    project = c.get("project")
    if not isinstance(name, str) or not name:
        return project if isinstance(project, str) else ""
    if not isinstance(project, str) or not project:
        return project if isinstance(project, str) else ""
    if name.startswith(project) and (
        len(name) == len(project) or name[len(project)] in "-_"
    ):
        return name
    return project


def session_display_name(label: str, hostname: str | None,
                          hostname_to_name: dict[str, str] | None) -> str:
    """Resolve the text a SESSION row/chip should draw.

    Lives at module level (display-only, tkinter-free) for the same reason
    `container_display_name` does, and delegates to it deliberately: the
    prefix rule that disambiguates a duplicate-container project must exist
    in exactly one place, or a docker row and a session row for the same
    container could one day drift apart and point the user at the wrong
    chip. `label` (the project label, i.e. today's `s["name"]`) is returned
    unchanged whenever the container can't be resolved — no hostname, no
    map, or an unknown hostname — which is what keeps every session in a
    randomly-named or unresolvable container rendering exactly as it does
    today.
    """
    if not isinstance(hostname, str) or not hostname:
        return label
    if not hostname_to_name:
        return label
    name = hostname_to_name.get(hostname)
    if not name:
        return label
    return container_display_name({"name": name, "project": label})


def session_display_text(s: dict) -> str:
    """Read side for the three places that draw a session's name.

    Prefers `display_name` (set by both `scan()` and `scan_state_files()`
    via `session_display_name()`) and falls back to `name` — and then to
    "" — for any row a future producer forgets to stamp.
    """
    return s.get("display_name") or s.get("name") or ""


def bg_badge_text(count: int | float | None) -> str:
    """Display text for the single unified background-task badge (D-03):
    supersedes the two-badge pair (gold bg-shell gear + teal Monitor count)
    with one, sourced only from the hook-captured `background_tasks_count`
    — never from jsonl parsing.

    Empty string for a falsy/absent/zero count (no badge shown at all); the
    bare glyph for exactly 1; the glyph followed by the number for anything
    greater. Lives at module level (display-only, tkinter-free) for the
    same reason `container_display_name`/`session_display_name` do — unit-
    testable without constructing MonitorApp.
    """
    if not count:
        return ""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n == 1:
        return "◉"
    return f"◉{n}"


def notification_group_key(s: dict) -> str:
    """Work-group identity of one session dict, for the notification gate
    (quick-260807-iz2, narrowed by quick-260807-k0y): a work group is one
    project label, at one worktree-folded root, INSIDE ONE CONTAINER.

    Container identity belongs here because the user runs duplicate-project
    containers (nursy, nursy-2 — same label, same mount path, different
    hosts) as INDEPENDENT jobs, and every other identity consumer in this
    file already disambiguates them per-container: derive_alias_key() keys
    aliases by hostname, session_display_name()/container_display_name()
    draw the disambiguated name. This group key was the one consumer still
    treating duplicate containers as interchangeable — nursy-2 finishing a
    turn was silenced while nursy was still working, which is exactly the
    notification the user needs. hostname is the right field to add: it's
    the same identity family those other consumers already key on, it's
    already stamped into every state-file session dict (no producer
    change), and it survives a sessionId rotation.

    Still retained, and why: the worktree fold (a worktree checkout and its
    main checkout inside ONE container are still one job — a WAITING
    checkpoint there isn't "the job is done" while a sibling worktree in
    the SAME container is still WORKING) and the project label (two
    unrelated devcontainers both mounted at /workspace must never merge).

    Returns "" ("ungrouped") when `s["cwd"]` OR `s["hostname"]` is missing,
    empty or not a string — a solo group of one, which gate_notification()
    treats as never blocking and never being blocked. That's the same
    fallback direction as the existing cwd guard: it keeps a legacy/
    hookless row (scan()'s dicts carry neither field) notifying exactly as
    it does today, and it keeps any future producer that forgets to stamp
    a field failing toward notifying rather than toward silence.
    Under-grouping can at worst duplicate a notification; over-grouping
    could silence a genuine "this session needs you now" — the wrong
    direction to fail in.

    Deliberately reads the raw `s.get("hostname")` field, never
    derive_alias_key()'s return value: that function's documented fallback
    returns the ROW KEY when hostname is unknown, which would hand every
    hostname-less session a non-empty singleton group key and destroy the
    ungrouped-"" fallback this function relies on.

    Accepted consequence, recorded as a decision rather than a regret: two
    containers genuinely running one job across a main tree and a worktree
    (the real 2026-08-07 case, hosts 8d5f9694f1de and 4353e1441213) no
    longer share a group — that pair now resolves to two independent
    groups. That's the user's call, made knowing it, and it's what makes
    the far more common duplicate-container case (nursy vs nursy-2) fire
    correctly instead of silencing each other.
    """
    cwd = s.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return ""
    hostname = s.get("hostname")
    if not isinstance(hostname, str) or not hostname:
        return ""
    normalized = cwd.replace("\\", "/")
    while len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized[:-1]
    marker_idx = normalized.find(WORKTREE_MARKER)
    if marker_idx != -1:
        normalized = normalized[:marker_idx]
    name = s.get("name")
    label = name if isinstance(name, str) else ""
    return f"{label}::{normalized}::{hostname}"


def gate_notification(session: dict, sessions: list[dict]) -> tuple[bool, str, dict]:
    """Whether `session`'s armed WORKING→WAITING notification should be
    allowed to fire right now (quick-260807-iz2).

    Two independent conditions, checked in order, either of which refuses:

      (a) "background_tasks" — this session's OWN background_tasks_count is
          a known, positive number: async work this session itself started
          is still in flight. An absent, None or non-numeric count is
          UNKNOWN and must never refuse — that's what keeps a hookless/
          legacy row (no background_tasks_count field at all) notifying
          exactly as it does today. Note this is a NOTIFICATION-gate read,
          not a STATE input: D-03's badge-only rule for the rendered
          STATE/colour stays untouched — scan_state_files()'s verdict logic
          never calls this function.

      (b) "group_working" — another session sharing this session's work
          group (see notification_group_key) is itself WORKING, or (a
          legacy row) carries working_locked True. A session is never
          blocked by its own presence in `sessions`. A session with an
          ungrouped ("") key is never blocked by this condition — solo
          sessions and legacy/hookless rows behave exactly as before this
          gate existed.

    Returns (allowed, reason, detail). `allowed` is False iff either
    condition above refused; `reason` is "background_tasks",
    "group_working" or "" (allowed). `detail` carries only identifiers —
    the group key, the background_tasks_count examined, and for a group
    refusal the list of blocking sessions' `key` values — never any text a
    session produced (T-iz2-01/T-iz2-03).
    """
    group = notification_group_key(session)
    bg_count = session.get("background_tasks_count")
    detail: dict = {"group": group, "background_tasks_count": bg_count}
    if (isinstance(bg_count, (int, float)) and not isinstance(bg_count, bool)
            and bg_count > 0):
        return False, "background_tasks", detail
    if not group:
        return True, "", detail
    own_key = session.get("key")
    blockers = [
        other.get("key") for other in sessions
        if other.get("key") != own_key
        and notification_group_key(other) == group
        and (other.get("status") == "WORKING" or other.get("working_locked"))
    ]
    if blockers:
        detail["blocked_by"] = blockers
        return False, "group_working", detail
    return True, "", detail


def _group_gate_enabled(app) -> bool:
    """Config-file-only escape hatch for the notification group gate
    (quick-260807-iz2): `group_gate: false` in the config file disables it
    in the field with no code change and no new UI surface. A module-level
    function (not a MonitorApp method) so it can be called on any object
    that merely LOOKS like an app — `_check_transitions` is exercised in
    tests via `MonitorApp._check_transitions(fake, ...)` where `fake` is a
    bare test double, and a bound-method call (`self._group_gate_enabled()`)
    would raise AttributeError on a double that doesn't define it. Reads
    `app.config` defensively: missing or non-dict `config` (any test double
    that hasn't grown one) defaults to the gate being ON.
    """
    config = getattr(app, "config", None)
    if not isinstance(config, dict):
        return True
    return bool(config.get("group_gate", True))


def notification_text(label: str, elapsed_sec: int, alias: str = "") -> tuple[str, str]:
    """Compose the toast title/body pair for a "Claude ready" notification
    (quick-260807-iz2): the SINGLE place this text is built, so `_notify()`
    (what the user sees) and `notification_record()` (what gets logged) are
    provably showing/recording the same string, never two independently
    maintained f-strings that could drift apart.

    Byte-identical to what `_notify()` built before this extraction,
    including the minutes/seconds humanisation (no "0m" prefix under a
    minute) and the alias suffix (appended only when `alias` is non-empty,
    so two sessions sharing a project label — e.g. two `yunoai-france` — are
    still tellable apart).
    """
    mins, secs = divmod(elapsed_sec, 60)
    elapsed_human = f"{mins}m {secs}s" if mins else f"{secs}s"
    shown = f"{label} · {alias}" if alias else label
    toast_title = f"Claude ready — {shown}"
    toast_body = f"Waiting for your input after {elapsed_human} of work."
    return toast_title, toast_body


def notification_type(state) -> str:
    """Map a state-file `state` value to the notifications-log vocabulary
    the originating todo specified (quick-260807-iz2): "stop" for a plain
    turn-end wait, "needs_input" and "idle_prompt" for their like-named
    state values, and "unknown" for anything else — including None,
    non-strings, and any value this engine doesn't currently emit — so a
    future state value or a malformed record can never crash the logger,
    only log as unknown.
    """
    mapping = {"waiting": "stop", "needs_input": "needs_input", "idle": "idle_prompt"}
    if not isinstance(state, str):
        return "unknown"
    return mapping.get(state, "unknown")


def notification_record(s: dict, elapsed_sec: int, alias: str, outcome: str,
                         reason: str, **extra) -> dict:
    """Build the flat dict logged for one notification decision — sent or
    suppressed (quick-260807-iz2).

    Fields are enumerated explicitly rather than dumping `s` — this
    explicit allow-list is what keeps prompt/tool/jsonl content out of
    notifications.log (T-iz2-01, T-02-17 precedent): the only free text in
    the record is the monitor-COMPOSED title/body from notification_text()
    (project label + alias + elapsed time), never anything a session itself
    produced. `**extra` lets callers attach hold/gate bookkeeping
    (held_sec, blocked_by, group detail) without this function needing to
    know about hold state.
    """
    now = time.time()
    label = session_display_text(s)
    title, body = notification_text(label, elapsed_sec, alias)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "ts_ms": int(now * 1000),
        "session_id": s.get("session_id") or s.get("key"),
        "key": s.get("key"),
        "hostname": s.get("hostname"),
        "cwd": s.get("cwd"),
        "project": s.get("name"),
        "group": notification_group_key(s),
        "type": notification_type(s.get("state")),
        "state": s.get("state"),
        "title": title,
        "body": body,
        "elapsed_sec": elapsed_sec,
        "background_tasks_count": s.get("background_tasks_count"),
        "outcome": outcome,
        "reason": reason,
    }
    record.update(extra)
    return record


def log_notification(record: dict) -> None:
    """Append one compact JSON line to NOTIFICATIONS_LOG (quick-260807-iz2)
    — mirrors hooks/event-logger.sh's jsonl shape and 5MB
    truncate-and-marker size guard, so a reader never mistakes truncation
    for missing decisions.

    Runs inside the 5-second refresh loop, so the whole body is
    best-effort: an unwritable path, a full disk, or a read-only home must
    never stall or crash that loop — any exception is swallowed and this
    returns None. Unlike the hook script, no flock is used: the monitor
    holds a process singleton (SINGLETON_PORT), so there is exactly one
    writer and no cross-process race to guard against.
    """
    try:
        line = json.dumps(record, separators=(",", ":"))
        NOTIFICATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        if (NOTIFICATIONS_LOG.exists()
                and NOTIFICATIONS_LOG.stat().st_size > NOTIFICATIONS_LOG_MAX_BYTES):
            marker = json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event": "_truncated",
                "note": "notifications.log exceeded 5MB and was truncated before this line",
            }, separators=(",", ":"))
            NOTIFICATIONS_LOG.write_text(marker + "\n", encoding="utf-8")
        with open(NOTIFICATIONS_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return None


def scan_containers() -> tuple[list[dict], dict[str, str], dict[str, str], dict, dict[str, str]]:
    """List running Docker containers that carry a 'project' label.

    Returns (rows, label_map, sessionid_to_label, container_info,
    hostname_to_name): `label_map` maps encoded session-dir names (as they
    appear under ~/.claude/projects/) to the container's launcher label;
    `container_info` is the state-file engine's container-identity/
    liveness cross-check (D-05, ENG-03) — {"hostname_to_label": ...,
    "hostname_to_status": ..., "sessionid_to_hostname": ...}, keyed by the
    container hostname the state writer captures at write time, built from
    the one container-inspection call below (no second subprocess call
    added). `sessionid_to_hostname` also feeds derive_alias_key() so a
    session's alias survives a sessionId rotation. `hostname_to_name` maps
    that same hostname to the container's DOCKER NAME (not its label) for
    session_display_name() to disambiguate duplicate-project sessions; it is
    kept OUT of container_info because the state-file engine's cross-check
    reads that dict and its values must stay pure project labels.
    """
    empty_container_info = {
        "hostname_to_label": {}, "hostname_to_status": {}, "sessionid_to_hostname": {},
    }
    docker = shutil.which("docker")
    if not docker:
        return [], {}, {}, dict(empty_container_info), {}
    kwargs: dict = {}
    if os.name == "nt":
        # Suppress console window flash on Windows (pythonw still shows one otherwise)
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        out = subprocess.run(
            [docker, "ps", "--filter", "label=project",
             "--format", "{{.ID}}\t{{.Label \"project\"}}\t{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=2, check=False, **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], {}, {}, dict(empty_container_info), {}
    if out.returncode != 0:
        return [], {}, {}, dict(empty_container_info), {}
    rows = []
    ids = []
    cid_to_label: dict[str, str] = {}
    cid_to_name: dict[str, str] = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[1]:
            continue
        ids.append(parts[0])
        cid_to_label[parts[0]] = parts[1]
        cid_to_name[parts[0]] = parts[2]
        rows.append({"project": parts[1], "name": parts[2], "status": parts[3]})
    order = launcher_order()
    big = len(order) + 1
    rows.sort(key=lambda r: (order.get(r["project"], big), r["project"].lower()))

    label_map: dict[str, str] = {}
    # Bound before the `if ids:` block below: a tick with zero labelled
    # containers must still leave this defined, or the `if container_labels:`
    # check further down raises NameError into the worker thread's blanket
    # `except Exception`, silently freezing the sessionId cache on its last
    # known value. Pre-existing latent bug in this function, fixed here
    # since this task rewrites the function anyway.
    container_labels: dict[str, str] = {}
    hostname_to_label: dict[str, str] = {}
    hostname_to_status: dict[str, str] = {}
    hostname_to_name: dict[str, str] = {}
    cid_to_hostname: dict[str, str] = {}
    if ids:
        try:
            insp = subprocess.run(
                [docker, "inspect",
                 "--format",
                 "{{.Config.Labels.project}}\t{{.Config.WorkingDir}}"
                 "\t{{.State.Status}}\t{{.Config.Hostname}}",
                 *ids],
                capture_output=True, text=True, timeout=2, check=False, **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired):
            insp = None
        # Track each container's encoded dir alongside its label, to detect ambiguity.
        per_container_encoded: dict[str, str] = {}
        if insp is not None and insp.returncode == 0:
            pending: dict[str, list[str]] = {}
            insp_lines = insp.stdout.splitlines()
            for cid, line in zip(ids, insp_lines):
                parts = line.split("\t")
                if len(parts) < 2 or not parts[0] or not parts[1]:
                    continue
                encoded = _workdir_to_encoded(parts[1])
                if encoded:
                    per_container_encoded[cid] = encoded
                    pending.setdefault(encoded, []).append(parts[0])
                # Container-identity cross-check (D-05/ENG-03): keyed by
                # hostname — the state writer captures $HOSTNAME at write
                # time, and docker exec (query_container_sessionids below)
                # cannot reach a paused container, so this is the only
                # label path a paused session has.
                if len(parts) >= 4 and parts[3]:
                    hostname_to_label[parts[3]] = cid_to_label.get(cid, "")
                    hostname_to_status[parts[3]] = parts[2] if len(parts) >= 3 else ""
                    hostname_to_name[parts[3]] = cid_to_name.get(cid, "")
                    cid_to_hostname[cid] = parts[3]
            for encoded, labels in pending.items():
                # Only safe to map encoded_dir → label without docker exec when
                # exactly one container claims this dir. Two containers with the
                # same label (e.g. launcher run twice) are still ambiguous —
                # they need sessionId disambiguation, not a single label_map entry.
                if len(labels) == 1:
                    label_map[encoded] = labels[0]
        # Query sessionIds for every running container (not just the ambiguous
        # ones). Non-ambiguous dirs were previously resolved via label_map
        # alone, but that mislabels stale jsonls from a sibling container that
        # just died: the surviving container becomes "non-ambiguous" and its
        # label is pasted onto the dead container's lingering session.
        container_labels = dict(cid_to_label)

    sessionid_to_label: dict[str, str] = {}
    sessionid_to_hostname: dict[str, str] = {}
    if container_labels:
        sessionid_to_label, sessionid_to_hostname = query_container_sessionids(
            docker, container_labels, kwargs, cid_to_hostname
        )
    return rows, label_map, sessionid_to_label, {
        "hostname_to_label": hostname_to_label,
        "hostname_to_status": hostname_to_status,
        "sessionid_to_hostname": sessionid_to_hostname,
    }, hostname_to_name


def query_container_sessionids(
    docker: str, container_labels: dict[str, str], kwargs: dict,
    cid_to_hostname: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """For each container, read its ~/.claude/sessions/*.json and map sessionId → project label.

    Also returns sessionId → hostname (from `cid_to_hostname`, when known), so
    the caller can feed derive_alias_key() the container identity a label
    should stick to.
    """
    result: dict[str, str] = {}
    sessionid_to_hostname: dict[str, str] = {}
    cid_to_hostname = cid_to_hostname or {}
    # Claude Code writes /tmp/claude-ctx-<sessionId>.json inside each container.
    # /tmp is container-local (unlike ~/.claude which is bind-mounted), so
    # listing the filenames gives us exactly THIS container's sessionId(s).
    # -t sorts by mtime desc; we take head -1 so a restarted CLI's stale ctx file
    # doesn't produce a second row for the same container.
    script = "ls -t /tmp/claude-ctx-*.json 2>/dev/null | head -1"
    for cid, label in container_labels.items():
        try:
            out = subprocess.run(
                [docker, "exec", cid, "sh", "-c", script],
                capture_output=True, text=True, timeout=2, check=False, **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode != 0 or not out.stdout:
            continue
        for match in re.finditer(r"claude-ctx-([0-9a-f-]+)\.json", out.stdout):
            sid = match.group(1)
            result[sid] = label
            hostname = cid_to_hostname.get(cid)
            if hostname:
                sessionid_to_hostname[sid] = hostname
    return result, sessionid_to_hostname


class MonitorApp:
    def __init__(self) -> None:
        self.config = load_config()
        self.mode = self.config["mode"]
        self.root = tk.Tk()
        self.root.title("Claude Monitor")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1a1a1a")
        self.root.overrideredirect(False)

        self.header = tk.Frame(self.root, bg="#0d0d0d", height=30)
        self.header.pack(fill="x")
        self.title_lbl = tk.Label(self.header, text="  Claude Sessions",
                                  bg="#0d0d0d", fg="#e0e0e0",
                                  font=("Segoe UI", 12, "bold"))
        self.title_lbl.pack(side="left")
        restart_btn = tk.Label(self.header, text="↻", bg="#0d0d0d", fg="#9cb4d6",
                               font=("Segoe UI", 13, "bold"), cursor="hand2")
        restart_btn.pack(side="right", padx=(4, 8))
        restart_btn.bind("<Button-1>", lambda e: self._restart())
        restart_btn.bind("<Enter>", lambda e: restart_btn.config(fg="#ffffff"))
        restart_btn.bind("<Leave>", lambda e: restart_btn.config(fg="#9cb4d6"))
        self.mode_btn = tk.Label(self.header, text="", bg="#0d0d0d", fg="#9cb4d6",
                                 font=("Segoe UI", 12, "bold"), cursor="hand2")
        self.mode_btn.pack(side="right", padx=(4, 4))
        self.mode_btn.bind("<Button-1>", lambda e: self._toggle_mode())
        self.mode_btn.bind("<Enter>", lambda e: self.mode_btn.config(fg="#ffffff"))
        self.mode_btn.bind("<Leave>", lambda e: self.mode_btn.config(fg="#9cb4d6"))
        self.reset_btn = tk.Label(self.header, text="⟲", bg="#0d0d0d", fg="#9cb4d6",
                                  font=("Segoe UI", 12, "bold"), cursor="hand2")
        self.reset_btn.pack(side="right", padx=(4, 4))
        self.reset_btn.bind("<Button-1>", lambda e: self._reset_geometry())
        self.reset_btn.bind("<Enter>", lambda e: self.reset_btn.config(fg="#ffffff"))
        self.reset_btn.bind("<Leave>", lambda e: self.reset_btn.config(fg="#9cb4d6"))
        self.telegram_btn = tk.Label(self.header, bg="#0d0d0d",
                                     font=("Segoe UI", 11), cursor="hand2")
        self.telegram_btn.pack(side="right", padx=(4, 4))
        self.telegram_btn.bind("<Button-1>", lambda e: self._toggle_telegram())
        self.telegram_btn.bind("<Enter>", lambda e: self.telegram_btn.config(fg="#ffffff"))
        self.telegram_btn.bind("<Leave>", lambda e: self._refresh_telegram_btn())
        self._refresh_telegram_btn()
        self.local_btn = tk.Label(self.header, bg="#0d0d0d",
                                  font=("Segoe UI", 11), cursor="hand2")
        self.local_btn.pack(side="right", padx=(4, 4))
        self.local_btn.bind("<Button-1>", lambda e: self._toggle_local())
        self.local_btn.bind("<Enter>", lambda e: self.local_btn.config(fg="#ffffff"))
        self.local_btn.bind("<Leave>", lambda e: self._refresh_local_btn())
        self._refresh_local_btn()
        self.count_lbl = tk.Label(self.header, text="", bg="#0d0d0d",
                                  fg="#888", font=("Segoe UI", 11))
        self.count_lbl.pack(side="right", padx=4)

        self.body = tk.Frame(self.root, bg="#1a1a1a")
        self.compact_body = tk.Frame(self.root, bg="#1a1a1a")
        self.compact_row = tk.Frame(self.compact_body, bg="#1a1a1a")
        self.compact_row.pack(fill="x", padx=4, pady=2)
        self.compact_empty = tk.Label(self.compact_row, text="—",
                                      bg="#1a1a1a", fg="#555",
                                      font=("Segoe UI", 10))
        self._compact_chips: dict[str, dict] = {}

        self.loading_lbl = tk.Label(self.body, text="loading…",
                                    bg="#1a1a1a", fg="#555",
                                    font=("Segoe UI", 11))
        self.loading_lbl.pack(pady=20)

        # Sessions first (primary content)
        self.session_header = tk.Label(self.body, text="SESSIONS", bg="#1a1a1a",
                                       fg="#666", font=("Segoe UI", 8, "bold"),
                                       anchor="w")
        self.session_section = tk.Frame(self.body, bg="#1a1a1a")
        self.empty_lbl = tk.Label(self.session_section, text="no active sessions",
                                  bg="#1a1a1a", fg="#555", font=("Segoe UI", 11))

        # Docker at the bottom, accordion-collapsed by default
        self.docker_divider = tk.Frame(self.body, bg="#333", height=1)
        self.docker_header = tk.Label(self.body, text="▶ DOCKER", bg="#1a1a1a",
                                      fg="#666", font=("Segoe UI", 8, "bold"),
                                      anchor="w", cursor="hand2")
        self.docker_header.bind("<Button-1>", lambda e: self._toggle_docker())
        self.docker_section = tk.Frame(self.body, bg="#1a1a1a")

        self._container_rows: dict[str, dict] = {}
        self._session_rows: dict[str, dict] = {}
        # Free-text labels keyed by session key — let the user disambiguate two
        # sessions sharing a launcher label. Same dict object as the config's
        # "aliases" so save_config() persists edits across monitor restarts.
        self._session_aliases: dict[str, str] = self.config["aliases"]
        # Row key -> alias key, rebuilt every tick in refresh() from the
        # rendered session list. Lets every alias site key off the container
        # identity (derive_alias_key) while still being addressed by today's
        # row key (row bindings and lookups happen at click/render time).
        self._alias_keys: dict[str, str] = {}
        # Dropped once, at the first non-empty scan: persisted aliases whose
        # session ended while the monitor was off.
        self._aliases_pruned = False
        # True while a modal dialog is up — pauses the topmost re-assertion in
        # refresh() so the dialog isn't shoved behind the monitor window.
        self._dialog_open = False
        self._session_order: list[str] = []
        self._compact_order: list[str] = []
        # Per-session transition tracking for "back to WAITING after long work" notifications.
        self._prev_status: dict[str, str] = {}
        self._working_since: dict[str, float] = {}
        # WORKING→WAITING debounce: elapsed work seconds keyed by session, armed on
        # the first WAITING tick and fired only if the next tick is still WAITING.
        self._pending_notify: dict[str, int] = {}
        # Group-gate open-hold register (quick-260807-iz2 Task 3): one entry
        # per session whose notification is armed (in _pending_notify) but
        # currently gate-refused. Keyed by session key; each value holds the
        # tick the hold opened at ("opened_at"), the reason currently
        # blocking it ("reason", so a reason CHANGE can be told apart from a
        # steady-state hold and re-logged once), and a snapshot of the
        # record fields captured when the hold opened ("record_kwargs" —
        # elapsed_sec/alias/session fields), so a session that later VANISHES
        # can still be logged as "session_gone" without its (now-missing)
        # session dict.
        self._notify_hold: dict[str, dict] = {}
        # Live toast Toplevels keyed by session key, so we can close a stale "ready" toast
        # when the session goes back to WORKING (grey) or disappears.
        self._open_toasts: dict[str, "tk.Toplevel"] = {}
        self._docker_header_visible = False
        self._docker_expanded = False
        self._session_visible = False
        self._first_docker_done = False
        self._cached_containers: list[dict] = []
        self._cached_label_map: dict[str, str] = {}
        self._sessionid_to_label: dict[str, str] = {}
        # ENG-03: hostname_to_label/hostname_to_status from
        # scan_containers()'s fourth return element, feeding
        # scan_state_files()'s staleness gate and paused-container label
        # fallback. Empty maps until the first docker tick completes.
        self._cached_container_info: dict = {
            "hostname_to_label": {}, "hostname_to_status": {}, "sessionid_to_hostname": {},
        }
        # Display-only: hostname -> container NAME (not label), from
        # scan_containers()'s fifth return element, feeding
        # session_display_name() so a session row/chip can disambiguate a
        # duplicate-project container the same way the docker row does.
        self._cached_hostname_to_name: dict[str, str] = {}
        self._docker_query_inflight = False

        # drag support via header
        self.header.bind("<Button-1>", self._start_drag)
        self.header.bind("<B1-Motion>", self._drag)

        self._apply_mode()
        # Persist geometry changes (drag, resize) with a small debounce
        self._save_after_id: str | None = None
        self.root.bind("<Configure>", self._on_configure)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.refresh()

    def _on_configure(self, _e) -> None:
        if self._save_after_id is not None:
            try:
                self.root.after_cancel(self._save_after_id)
            except Exception:
                pass
        self._save_after_id = self.root.after(500, self._remember_geometry)

    def _on_close(self) -> None:
        self._remember_geometry()
        try:
            self.root.destroy()
        except Exception:
            pass
        _release_singleton()
        os._exit(0)

    def _apply_mode(self) -> None:
        compact = self.mode == "compact"
        if compact:
            self.title_lbl.pack_forget()
            self.count_lbl.pack_forget()
            self.body.pack_forget()
            self.compact_body.pack(fill="both", expand=True)
            self.mode_btn.config(text="□")
        else:
            self.compact_body.pack_forget()
            if not self.title_lbl.winfo_ismapped():
                self.title_lbl.pack(side="left")
            if not self.count_lbl.winfo_ismapped():
                self.count_lbl.pack(side="right", padx=4)
            self.body.pack(fill="both", expand=True, padx=4, pady=4)
            self.mode_btn.config(text="_")
        geom = self.config.get(self.mode) or self._default_geometry(self.mode)
        geom = self._sanitize_geometry(geom)
        self.root.geometry(geom)
        # Reassert topmost — tkinter can drop the flag after geometry changes,
        # especially across monitor switches.
        self.root.attributes("-topmost", True)

    def _sanitize_geometry(self, geom: str) -> str:
        """Discard saved geometry that lands fully off-screen.

        Why: an unplugged second monitor leaves the window stuck at coordinates
        the current screen can't render. Taskbar icon shows, window doesn't.
        Require at least 60×30 px of overlap with the primary screen rect —
        less than that and the title bar / restore handle aren't reachable.
        """
        parsed = parse_geometry(geom)
        if parsed is None:
            return self._default_geometry(self.mode)
        w, h, x, y = parsed
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        visible_w = max(0, min(x + w, sw) - max(x, 0))
        visible_h = max(0, min(y + h, sh) - max(y, 0))
        if visible_w < 60 or visible_h < 30:
            return self._default_geometry(self.mode)
        return geom

    def _remember_geometry(self) -> None:
        try:
            self.config[self.mode] = self.root.geometry()
            save_config(self.config)
        except Exception:
            pass

    def _default_geometry(self, mode: str) -> str:
        w, h = DEFAULT_SIZE[mode]
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        mx, my = DEFAULT_MARGIN
        x = max(0, sw - w - mx)
        y = max(0, sh - h - my)
        return f"{w}x{h}+{x}+{y}"

    def _reset_geometry(self) -> None:
        geom = self._default_geometry(self.mode)
        self.config[self.mode] = geom
        save_config(self.config)
        self.root.geometry(geom)
        self.root.attributes("-topmost", True)

    def _toggle_mode(self) -> None:
        self._remember_geometry()
        self.mode = "compact" if self.mode == "standard" else "standard"
        self.config["mode"] = self.mode
        save_config(self.config)
        self._apply_mode()

    def _refresh_local_btn(self) -> None:
        # 🔔/🔕 mutes audio only (quick-260818-bfm) — the toast and the
        # taskbar flash keep firing either way.
        on = bool(self.config.get("local", True))
        self.local_btn.config(text="🔔" if on else "🔕",
                              fg="#9cb4d6" if on else "#666")

    def _toggle_local(self) -> None:
        self.config["local"] = not bool(self.config.get("local", True))
        save_config(self.config)
        self._refresh_local_btn()

    def _refresh_telegram_btn(self) -> None:
        on = bool(self.config.get("telegram", True))
        self.telegram_btn.config(text="📱" if on else "📵",
                                 fg="#9cb4d6" if on else "#666")

    def _toggle_telegram(self) -> None:
        self.config["telegram"] = not bool(self.config.get("telegram", True))
        save_config(self.config)
        self._refresh_telegram_btn()

    def _restart(self) -> None:
        self._remember_geometry()
        _release_singleton()
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(
                [sys.executable, os.path.abspath(__file__)],
                close_fds=True, creationflags=flags,
            )
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def _toggle_docker(self) -> None:
        self._docker_expanded = not self._docker_expanded
        arrow = "▼" if self._docker_expanded else "▶"
        self.docker_header.config(text=f"{arrow} DOCKER")
        if self._docker_expanded:
            self.docker_section.pack(fill="x")
        else:
            self.docker_section.pack_forget()

    def _start_drag(self, e) -> None:
        self._drag_x, self._drag_y = e.x, e.y

    def _drag(self, e) -> None:
        x = self.root.winfo_x() + e.x - self._drag_x
        y = self.root.winfo_y() + e.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _dismiss_session_toast(self, key: str) -> None:
        """Close a live toast for this session key, if any. Safe to call twice."""
        toast = self._open_toasts.pop(key, None)
        if toast is None:
            return
        try:
            toast.destroy()
        except Exception:
            pass

    def _alias_key(self, key: str) -> str:
        """Resolve a row key to the identity its label is stored under.

        Backed by self._alias_keys, rebuilt every tick in refresh() from the
        rendered session list's alias_key field. Defaults to the row key
        itself for a row with no resolved container identity (or, before
        the first refresh() tick, for any row) — today's behaviour.
        """
        return self._alias_keys.get(key, key)

    def _prune_aliases(self, sessions: list[dict]) -> None:
        """One-time startup prune of persisted aliases whose container is gone.

        Runs at most once (self._aliases_pruned) and is a no-op on an empty
        session list, so a transient empty scan can never wipe every label.
        "Live" means the alias_key of each session, not its row key, so a
        label survives a sessionId rotation while a container that's truly
        gone still drops its alias exactly once, as before.
        """
        if self._aliases_pruned or not sessions:
            return
        live = {s.get("alias_key") or s["key"] for s in sessions}
        dead = [k for k in self._session_aliases if k not in live]
        if dead:
            for k in dead:
                del self._session_aliases[k]
            save_config(self.config)
        self._aliases_pruned = True

    def _bind_alias_click(self, row: dict, key: str) -> None:
        """Make a whole session row/chip clickable to open its label editor.

        tkinter click events don't bubble from a child widget up to its parent
        frame, so every visible widget in the row gets the same binding.
        """
        def handler(_e, k=key):
            self._edit_alias(k)

        for slot in ("frame", "top", "inner", "dot", "name", "alias",
                     "badge", "age", "action"):
            w = row.get(slot)
            if w is None:
                continue
            w.bind("<Button-1>", handler)
            try:
                w.config(cursor="hand2")
            except tk.TclError:
                pass

    def _ask_label(self, prompt: str, initial: str) -> str | None:
        """Modal one-field input that stays *above* the always-on-top monitor.

        A plain simpledialog ends up behind the monitor — refresh() keeps
        re-asserting -topmost on the main window. This Toplevel is itself
        -topmost, and _dialog_open pauses that re-assertion while it's up.
        Returns the entered text, or None if cancelled / closed.
        """
        result: dict[str, str | None] = {"value": None}
        try:
            win = tk.Toplevel(self.root)
        except Exception:
            return None
        win.title("Session label")
        win.configure(bg="#1a1a1a")
        win.resizable(False, False)
        win.transient(self.root)
        win.attributes("-topmost", True)

        tk.Label(win, text=prompt, bg="#1a1a1a", fg="#e0e0e0",
                 font=("Segoe UI", 10), anchor="w").pack(
            fill="x", padx=14, pady=(12, 4))
        var = tk.StringVar(value=initial)
        entry = tk.Entry(win, textvariable=var, bg="#242424", fg="#f0f0f0",
                         insertbackground="#f0f0f0", relief="flat",
                         font=("Segoe UI", 11), width=22)
        entry.pack(padx=14, ipady=3)

        def done(commit: bool) -> None:
            result["value"] = var.get() if commit else None
            try:
                win.destroy()
            except Exception:
                pass

        btns = tk.Frame(win, bg="#1a1a1a")
        btns.pack(fill="x", padx=14, pady=12)
        tk.Button(btns, text="OK", width=7, relief="flat", cursor="hand2",
                  bg="#2f4f2f", fg="#e8e8e8", activebackground="#3f5f3f",
                  command=lambda: done(True)).pack(side="right")
        tk.Button(btns, text="Cancel", width=7, relief="flat", cursor="hand2",
                  bg="#333333", fg="#e8e8e8", activebackground="#444444",
                  command=lambda: done(False)).pack(side="right", padx=(0, 6))
        win.bind("<Return>", lambda _e: done(True))
        win.bind("<Escape>", lambda _e: done(False))
        win.protocol("WM_DELETE_WINDOW", lambda: done(False))

        # Park the dialog just *above* the monitor window — same spot as the
        # toast: where the user is already looking, and it clears the monitor
        # instead of covering it. Centered horizontally, clamped on-screen.
        win.update_idletasks()
        try:
            w, h = win.winfo_width(), win.winfo_height()
            sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
            mx, my = self.root.winfo_x(), self.root.winfo_y()
            x = mx + max(0, (self.root.winfo_width() - w) // 2)
            y = my - h - 8
            # Same primary-screen-only clamp as the toast: never drag the
            # dialog off a secondary screen the monitor window lives on.
            if 0 <= mx < sw and 0 <= my < sh:
                x = max(0, min(x, sw - w))
                y = max(0, min(y, sh - h))
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        entry.focus_set()
        entry.icursor("end")
        entry.selection_range(0, "end")

        self._dialog_open = True
        try:
            win.grab_set()
            self.root.wait_window(win)
        except Exception:
            pass
        finally:
            self._dialog_open = False
        return result["value"]

    def _edit_alias(self, key: str) -> None:
        """Prompt for a label to disambiguate same-named sessions.

        Two containers can share a launcher label (e.g. two `yunoai-france`); a
        free-text alias ("RAM", "GSD") tells the rows apart. Cancelling keeps
        the current value, submitting an empty field clears it. Persisted to
        the config file so it survives a monitor restart; pruned once the
        session itself is gone (see refresh()).
        """
        if self._dialog_open:
            return
        alias_key = self._alias_key(key)
        row = self._session_rows.get(key) or self._compact_chips.get(key)
        shown = row["name"].cget("text") if row else key
        current = self._session_aliases.get(alias_key, "")
        answer = self._ask_label(f"Label for {shown}:", current)
        alias = resolve_alias(answer, current)
        if alias:
            self._session_aliases[alias_key] = alias
        else:
            self._session_aliases.pop(alias_key, None)
        save_config(self.config)  # _session_aliases is self.config["aliases"]
        # Immediate visual feedback — the next refresh tick keeps it in sync.
        # A container can have more than one visible row key (row key stable,
        # alias_key resolves a tick later) — update every row/chip whose
        # resolved alias key matches the one just edited, not only `key`.
        for store in (self._session_rows, self._compact_chips):
            for k, r in store.items():
                if self._alias_key(k) == alias_key:
                    r["alias"].config(text=alias)

    def _check_transitions(self, sessions: list[dict]) -> None:
        """Fire a notification when a session flips WORKING → WAITING after a long work stretch.

        The flip is debounced by one tick (REFRESH_MS): Claude Code briefly goes
        WAITING between two tasks of the same turn, and notifying on that blip is
        a false positive — the notification fires only if the session is still
        WAITING on the following tick.

        Also dismiss any stale "ready" toast when the session goes back to WORKING
        (semaforo grigio = utente ha ripreso) or disappears entirely — the notice
        is no longer relevant and shouldn't sit around, especially in muted/sticky mode.

        Group gate (quick-260807-iz2): once armed (`_pending_notify`), a
        notification is re-checked against `gate_notification()` every tick
        it stays WAITING, not just once. A refusal opens/updates an entry in
        `self._notify_hold` rather than dropping the notification — the
        `_pending_notify` entry is deliberately NOT popped while held, so
        the next tick re-evaluates the same armed notification. From a held
        state exactly one of four things eventually happens: RELEASE (the
        gate clears -> fires, `_notify` called exactly once), DISCARD on
        self-resume (this loop's WORKING branch below), DISCARD on vanish
        (the sweep at the bottom), or EXPIRE past
        NOTIFY_GATE_MAX_HOLD_SEC. Every one of those four outcomes, plus a
        plain (never-held) send, logs exactly one notification_record() —
        and while a hold merely PERSISTS with the same reason tick after
        tick, nothing new is logged, so a 5-second refresh loop can't flood
        notifications.log over one stuck episode.
        """
        now = time.time()
        seen: set[str] = set()
        for s in sessions:
            key = s["key"]
            seen.add(key)
            curr = s["status"]
            prev = self._prev_status.get(key)
            if curr == "WORKING":
                if prev != "WORKING":
                    self._working_since[key] = now
                    self._dismiss_session_toast(key)
                # A green blip between two tasks lands here on the next tick:
                # the armed notification is discarded, no toast fires. If a
                # gate hold was open, the session resuming ITSELF is what
                # discards it — the real 2026-08-07 13:14 outcome.
                elapsed = self._pending_notify.pop(key, None)
                hold = self._notify_hold.pop(key, None)
                if hold is not None:
                    held_sec = int(now - hold["opened_at"])
                    alias = self._session_aliases.get(self._alias_key(key), "")
                    log_notification(notification_record(
                        s, elapsed if elapsed is not None else 0, alias,
                        "suppressed", "session_resumed", held_sec=held_sec))
            else:  # WAITING
                if prev == "WORKING":
                    started = self._working_since.pop(key, None)
                    if started is not None and (now - started) >= NOTIFY_MIN_WORK_SEC:
                        # Debounce: arm now, fire only if still WAITING next tick.
                        self._pending_notify[key] = int(now - started)
                elif key in self._pending_notify:
                    elapsed = self._pending_notify[key]
                    allowed, reason, detail = True, "", {}
                    if _group_gate_enabled(self):
                        allowed, reason, detail = gate_notification(s, sessions)
                    hold = self._notify_hold.get(key)
                    alias = self._session_aliases.get(self._alias_key(key), "")
                    if allowed:
                        # RELEASE (hold was open) or a plain, never-held send.
                        held_sec = None
                        if hold is not None:
                            held_sec = int(now - hold["opened_at"])
                            del self._notify_hold[key]
                        del self._pending_notify[key]
                        self._notify(session_display_text(s), elapsed, key=key)
                        extra = {"held_sec": held_sec} if held_sec is not None else {}
                        log_notification(notification_record(
                            s, elapsed, alias, "sent",
                            "gate_cleared" if held_sec is not None else "", **extra))
                    elif hold is not None and (now - hold["opened_at"]) >= NOTIFY_GATE_MAX_HOLD_SEC:
                        # EXPIRE: dropped, not fired — the overlay keeps showing
                        # the session green regardless, so nothing is lost, just
                        # not pushed this late.
                        held_sec = int(now - hold["opened_at"])
                        del self._pending_notify[key]
                        del self._notify_hold[key]
                        log_notification(notification_record(
                            s, elapsed, alias, "suppressed", "hold_expired",
                            held_sec=held_sec))
                    elif hold is None:
                        # Hold OPENS: log once now, snapshot for a possible
                        # future vanish (the session dict won't exist then).
                        self._notify_hold[key] = {
                            "opened_at": now, "reason": reason,
                            "snapshot": dict(s), "elapsed": elapsed, "alias": alias,
                        }
                        log_notification(notification_record(
                            s, elapsed, alias, "suppressed", reason, **detail))
                    elif hold.get("reason") != reason:
                        # Reason CHANGED mid-hold (e.g. background_tasks ->
                        # group_working): log once for the new reason, refresh
                        # the snapshot, then go quiet again while it persists.
                        hold["reason"] = reason
                        hold["snapshot"] = dict(s)
                        hold["elapsed"] = elapsed
                        hold["alias"] = alias
                        log_notification(notification_record(
                            s, elapsed, alias, "suppressed", reason, **detail))
                    # else: hold persists with the same reason this tick —
                    # already logged when it opened, nothing new to record.
            self._prev_status[key] = curr
        # Drop tracking for sessions no longer present
        for key in list(self._prev_status):
            if key not in seen:
                del self._prev_status[key]
                self._working_since.pop(key, None)
                elapsed = self._pending_notify.pop(key, None)
                hold = self._notify_hold.pop(key, None)
                if hold is not None:
                    # DISCARD on vanish, built from the hold's own snapshot —
                    # `sessions` no longer carries this session's dict.
                    held_sec = int(now - hold["opened_at"])
                    snapshot = hold.get("snapshot") or {"key": key}
                    snap_elapsed = hold.get("elapsed", elapsed if elapsed is not None else 0)
                    snap_alias = hold.get("alias", "")
                    log_notification(notification_record(
                        snapshot, snap_elapsed, snap_alias,
                        "suppressed", "session_gone", held_sec=held_sec))
                self._dismiss_session_toast(key)

    def _notify_toast(self, title: str, message: str, key: str | None = None) -> bool:
        """In-app toast: borderless Toplevel in the bottom-right corner.

        Why not the native Windows toast API? It silently drops notifications whose
        AppUserModelID isn't registered (shortcut in Start Menu, or via registry).
        Our own Toplevel is always visible, doesn't care about system notification
        policies, and stays consistent across Windows/WSL.

        Always reached, regardless of the "local" switch (quick-260818-bfm) —
        that switch mutes the audio cue only, so the toast fires even on a
        muted machine and auto-dismisses after a few seconds or on click.
        """
        try:
            # Replace any prior toast for this session — avoids stacking duplicates
            # when transitions fire rapidly.
            if key is not None:
                self._dismiss_session_toast(key)
            toast = tk.Toplevel(self.root)
            toast.overrideredirect(True)
            toast.attributes("-topmost", True)
            bg = "#1f3a1f"
            toast.configure(bg=bg, highlightbackground="#4ade80", highlightthickness=2)
            w, h = 340, 82
            sw = toast.winfo_screenwidth()
            sh = toast.winfo_screenheight()
            # Park the toast right above the main monitor window, right-aligned to
            # its right edge. The monitor window itself sits topmost in the
            # bottom-right corner, so this places the toast where the user is
            # already looking, and above the area where app windows live — so no
            # focus competition, no flicker.
            try:
                mx = self.root.winfo_x()
                my = self.root.winfo_y()
                mw = self.root.winfo_width()
                x = mx + mw - w
                y = my - h - 8
                anchored = True
            except Exception:
                x = sw - w - 30
                y = sh - h - 200
                anchored = False
            # Clamp inside the screen so the toast can't render off-screen —
            # but only when the monitor window itself is on the primary
            # display: winfo_screenwidth/height only describe the primary,
            # and clamping against them would drag the toast away from a
            # monitor window parked on a secondary screen.
            if not anchored or (0 <= mx < sw and 0 <= my < sh):
                x = max(0, min(x, sw - w))
                y = max(0, min(y, sh - h))
            toast.geometry(f"{w}x{h}+{x}+{y}")

            def dismiss(_e=None):
                try:
                    toast.destroy()
                except Exception:
                    pass

            title_row = tk.Frame(toast, bg=bg)
            title_row.pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(title_row, text=title, bg=bg, fg="#7fd17f",
                     font=("Segoe UI", 11, "bold"), anchor="w"
                     ).pack(side="left", fill="x", expand=True)
            tk.Label(toast, text=message, bg=bg, fg="#e8e8e8",
                     font=("Segoe UI", 10), anchor="w",
                     wraplength=w - 24, justify="left"
                     ).pack(fill="x", padx=12, pady=(2, 8))

            toast.bind("<Button-1>", dismiss)
            toast.after(6000, dismiss)

            if key is not None:
                self._open_toasts[key] = toast
                # Clear the bookkeeping entry when the toplevel actually goes away
                # (manual ×, auto-dismiss, _dismiss_session_toast). Only the Toplevel's
                # own <Destroy> fires with widget==toast — child widgets fire too but
                # we filter them out.
                def _on_destroy(_e, k=key, t=toast):
                    if _e.widget is t and self._open_toasts.get(k) is t:
                        del self._open_toasts[k]
                toast.bind("<Destroy>", _on_destroy)
            return True
        except Exception:
            return False

    def _send_telegram(self, title: str, body: str) -> None:
        """Fire-and-forget Telegram push; runs in a daemon thread so UI never blocks.

        Credentials come from .env at repo root. If either key is missing the
        call is a no-op — Telegram is an optional addition to the local
        notification stack (toast and flash always fire first; audio fires
        too unless the "local" switch has muted it).
        """
        env = load_env()
        token = env.get("TELEGRAM_BOT_TOKEN")
        chat_id = env.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return
        verbose = "--test-notify" in sys.argv

        def worker() -> None:
            import urllib.parse
            import urllib.request
            payload = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": f"{title}\n{body}",
            }).encode("utf-8")
            req = urllib.request.Request(
                TELEGRAM_API.format(token=token),
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            try:
                with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT_SEC) as r:
                    if verbose:
                        print(f"[notify] telegram={r.status}", file=sys.stderr)
            except Exception as e:
                if verbose:
                    print(f"[notify] telegram failed: {e}", file=sys.stderr)

        threading.Thread(target=worker, daemon=True).start()

    def _notify_audio(self) -> tuple[bool, str]:
        """Audio cue: walk NOTIFY_WAV_FILES, play the first one that exists.
        MessageBeep / Tk bell are silent-OK fallbacks for odd systems.

        Only reached from `_notify()` when the "local" switch is on — the
        toast and taskbar flash fire regardless of it (quick-260818-bfm),
        this helper is the one channel the switch actually gates.
        """
        verbose = "--test-notify" in sys.argv
        audio_ok = False
        audio_channel = "none"
        replay_fn = None
        try:
            import winsound
            SND_ASYNC = 0x0001
            SND_FILENAME = 0x00020000
            for wav in NOTIFY_WAV_FILES:
                if os.path.exists(wav) and winsound.PlaySound(wav, SND_FILENAME | SND_ASYNC):
                    audio_ok, audio_channel = True, f"PlaySound:{os.path.basename(wav)}"
                    replay_fn = lambda w=wav: winsound.PlaySound(w, SND_FILENAME | SND_ASYNC)
                    break
            if not audio_ok:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
                audio_ok, audio_channel = True, "MessageBeep"
        except Exception as e:
            if verbose:
                print(f"[notify] winsound failed: {e}", file=sys.stderr)
            try:
                self.root.bell()
                audio_ok, audio_channel = True, "Tk bell"
            except Exception:
                pass
        if verbose:
            print(f"[notify] audio={'ok' if audio_ok else 'FAIL'} via={audio_channel}",
                  file=sys.stderr)
        # Repeat the sample N-1 more times to raise perceived loudness without
        # touching the system mixer. Only chained for the async PlaySound paths
        # that captured a replay_fn; Beep/MessageBeep/bell are soft fallbacks
        # where repetition isn't worth the UI lag / hardware quirks.
        if replay_fn is not None and NOTIFY_REPEAT > 1:
            def _replay(n: int = NOTIFY_REPEAT - 1) -> None:
                try:
                    replay_fn()
                except Exception:
                    return
                if n > 1:
                    self.root.after(NOTIFY_REPEAT_INTERVAL_MS, _replay, n - 1)
            self.root.after(NOTIFY_REPEAT_INTERVAL_MS, _replay)
        return audio_ok, audio_channel

    def _flash_taskbar(self) -> bool:
        """Taskbar flash (Windows only, continues until window gains focus).
        Ensure the window is fully realized before asking the OS to flash it.

        Unconditional: called from `_notify()` regardless of the "local"
        switch (quick-260818-bfm) — the switch mutes audio only, so muting
        the desk no longer blinds the taskbar too. On a non-Windows host
        this returns False without touching ctypes.
        """
        verbose = "--test-notify" in sys.argv
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        flash_ok = False
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                FLASHW_ALL = 0x00000003

                class FLASHWINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.UINT),
                        ("hwnd", wintypes.HWND),
                        ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT),
                        ("dwTimeout", wintypes.DWORD),
                    ]

                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
                if verbose:
                    print(f"[notify] hwnd={hwnd}", file=sys.stderr)
                # Flash a fixed number of times, then stop — no FLASHW_TIMERNOFG,
                # otherwise the taskbar icon blinks forever until the window gets
                # foreground. 5 cycles is loud enough to notice without being
                # stuck on screen if the user doesn't click.
                info = FLASHWINFO(
                    ctypes.sizeof(FLASHWINFO), hwnd,
                    FLASHW_ALL, 5, 0,
                )
                result = ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
                flash_ok = bool(result) or bool(hwnd)
                if verbose:
                    print(f"[notify] FlashWindowEx returned {result}", file=sys.stderr)
            except Exception as e:
                if verbose:
                    print(f"[notify] FlashWindowEx failed: {e}", file=sys.stderr)
        return flash_ok

    def _notify(self, label: str, elapsed_sec: int, key: str | None = None) -> None:
        """Toast + audio beep + taskbar flash when a long-running session is ready for user input.

        Three independent gates: "local" mutes audio only on this machine —
        the toast and the taskbar flash always fire regardless of it
        (quick-260818-bfm narrowed the switch's reach) — and "telegram"
        governs the phone push. Any one of the three can be silenced
        without affecting the other two.
        """
        verbose = "--test-notify" in sys.argv
        local_on = bool(self.config.get("local", True))
        # Append the user's per-session alias when set, so two sessions sharing
        # a project name (e.g. two `yunoai-france`) are still tellable apart.
        alias = self._session_aliases.get(self._alias_key(key), "") if key else ""
        toast_title, toast_body = notification_text(label, elapsed_sec, alias)
        # Telegram fires regardless of the local switch — the whole point of the
        # phone push is to reach you when you're away from the desk (local muted).
        if self.config.get("telegram", True):
            self._send_telegram(toast_title, toast_body)
        # Toast always fires — "local" gates audio only, never the popup.
        toast_ok = self._notify_toast(toast_title, toast_body, key=key)
        if verbose:
            print(f"[notify] local={'on' if local_on else 'off'} "
                  f"toast={'ok' if toast_ok else 'skip/FAIL'}", file=sys.stderr)
        if local_on:
            audio_ok, audio_channel = self._notify_audio()
        else:
            audio_ok, audio_channel = False, "muted"
            if verbose:
                print("[notify] audio=skip (local muted)", file=sys.stderr)
        # Flash always fires — "local" gates audio only, never the taskbar flash.
        flash_ok = self._flash_taskbar()
        if verbose:
            print(f"[notify] flash={'ok' if flash_ok else 'FAIL'} label={label} elapsed={elapsed_sec}s",
                  file=sys.stderr)

    def _kick_docker_query(self) -> None:
        if self._docker_query_inflight:
            return
        self._docker_query_inflight = True

        def worker() -> None:
            try:
                rows, label_map, sid_map, container_info, hostname_to_name = scan_containers()
            except Exception:
                # Transient docker hiccup — keep prior cache, skip this tick.
                self._first_docker_done = True
                self._docker_query_inflight = False
                return
            self._cached_containers = rows
            self._cached_label_map = label_map
            # Replace (not merge) the sessionId→label map: a sessionId no
            # longer reported by a live container is stale and must drop from
            # the UI, otherwise jsonls from killed containers keep showing as
            # ghost rows (still within MAX_AGE_SEC mtime).
            self._sessionid_to_label = sid_map
            self._cached_container_info = container_info
            self._cached_hostname_to_name = hostname_to_name
            self._first_docker_done = True
            self._docker_query_inflight = False

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self) -> None:
        # Re-assert topmost every tick — Windows sometimes drops the flag after
        # monitor switches or taskbar interactions. Skipped while a modal
        # dialog is open, otherwise it would shove the dialog out of sight.
        if not self._dialog_open:
            try:
                self.root.attributes("-topmost", True)
            except tk.TclError:
                pass
        self._kick_docker_query()
        if not self._first_docker_done:
            # Avoid a flash of raw session names before docker label_map is loaded.
            self.root.after(100, self.refresh)
            return
        if self.loading_lbl.winfo_ismapped():
            self.loading_lbl.pack_forget()
        containers = self._cached_containers
        try:
            sessions = scan(self._cached_label_map, self._sessionid_to_label,
                             container_info=self._cached_container_info,
                             hostname_to_name=self._cached_hostname_to_name)
        except Exception:
            sessions = []

        # The primary engine (D-01: hook-derived state is what renders and
        # notifies). One bad tick must never break the loop — same
        # defensive wrapping as the legacy scan() call above. scan()'s
        # `sessions` result still feeds this call (legacy_sessions=, the
        # D-02c hookless bridge) and, in plan 03-02, the jsonl-advance
        # signal and working-lock pin evidence — it is not dead code.
        try:
            render_sessions = scan_state_files(
                self._cached_label_map, self._sessionid_to_label,
                container_info=self._cached_container_info,
                legacy_sessions=sessions,
                hostname_to_name=self._cached_hostname_to_name,
            )
        except Exception:
            render_sessions = []
        # The single seam through which the engine's output reaches
        # rendering/notification — returns render_sessions unchanged
        # (identity), the one documented point D-08 requires a future
        # producer to plug into.
        render_sessions = select_render_sessions(render_sessions)

        # Rebuild the row-key -> alias-key map from what's about to render,
        # before the prune / transitions / rendering below read it. A row
        # missing alias_key (e.g. a producer that hasn't been updated yet)
        # degrades to today's behaviour: alias key == row key.
        self._alias_keys = {
            s["key"]: (s.get("alias_key") or s["key"]) for s in render_sessions
        }

        # One-time prune of persisted aliases: anything whose container is
        # gone. Gated on a non-empty rendered list so a transient empty
        # result can't wipe every label the user set.
        self._prune_aliases(render_sessions)

        count_txt = f"{len(containers)}d · {len(render_sessions)}s"
        if self.count_lbl.cget("text") != count_txt:
            self.count_lbl.config(text=count_txt)

        self._check_transitions(render_sessions)

        if self.mode == "compact":
            self._refresh_compact(render_sessions)
            self.root.after(REFRESH_MS, self.refresh)
            return

        # Sessions stay on top; docker header appears underneath when containers exist.
        if not self._session_visible:
            self.session_header.pack(fill="x", padx=6, pady=(0, 2))
            self.session_section.pack(fill="x")
            self._session_visible = True

        want_docker_header = bool(containers)
        if want_docker_header != self._docker_header_visible:
            if want_docker_header:
                self.docker_divider.pack(fill="x", pady=(8, 4))
                self.docker_header.pack(fill="x", padx=6, pady=(0, 2))
                if self._docker_expanded:
                    self.docker_section.pack(fill="x")
            else:
                self.docker_divider.pack_forget()
                self.docker_header.pack_forget()
                self.docker_section.pack_forget()
            self._docker_header_visible = want_docker_header

        # Update container rows (keyed by docker container name)
        seen = set()
        for c in containers:
            key = c["name"]
            seen.add(key)
            row = self._container_rows.get(key)
            if row is None:
                row = self._make_container_row()
                self._container_rows[key] = row
            display = container_display_name(c)
            if row["project"].cget("text") != display:
                row["project"].config(text=display)
            if row["status"].cget("text") != c["status"]:
                row["status"].config(text=c["status"])
        for key in list(self._container_rows):
            if key not in seen:
                self._container_rows[key]["frame"].destroy()
                del self._container_rows[key]

        # Update session rows (keyed by project name)
        seen = set()
        for s in render_sessions:
            key = s["key"]
            seen.add(key)
            row = self._session_rows.get(key)
            if row is None:
                row = self._make_session_row()
                self._session_rows[key] = row
                self._bind_alias_click(row, key)
            age_txt = fmt_age(s["age"])
            if row["dot"].cget("text") != s["dot"]:
                row["dot"].config(text=s["dot"])
            if row["dot"].cget("fg") != s["dot_color"]:
                row["dot"].config(fg=s["dot_color"])
            display_txt = session_display_text(s)
            if row["name"].cget("text") != display_txt:
                row["name"].config(text=display_txt)
            alias_txt = self._session_aliases.get(self._alias_key(key), "")
            if row["alias"].cget("text") != alias_txt:
                row["alias"].config(text=alias_txt)
            badge_txt = bg_badge_text(s.get("background_tasks_count"))
            if row["badge"].cget("text") != badge_txt:
                row["badge"].config(text=badge_txt)
            if row["age"].cget("text") != age_txt:
                row["age"].config(text=age_txt)
            if row["action"].cget("text") != s["action"]:
                row["action"].config(text=s["action"])
        for key in list(self._session_rows):
            if key not in seen:
                self._session_rows[key]["frame"].destroy()
                del self._session_rows[key]
                # Alias is left in place — a session can blink out of one scan
                # and back. Persisted aliases are pruned once, at startup.

        new_order = [s["key"] for s in render_sessions]
        if new_order != self._session_order:
            for key in new_order:
                row = self._session_rows.get(key)
                if row is not None:
                    row["frame"].pack_forget()
                    row["frame"].pack(fill="x", pady=2)
            self._session_order = new_order

        if not render_sessions and not self._session_rows:
            self.empty_lbl.pack(pady=12)
        else:
            self.empty_lbl.pack_forget()

        self.root.after(REFRESH_MS, self.refresh)

    def _refresh_compact(self, sessions: list[dict]) -> None:
        seen: set[str] = set()
        for i, s in enumerate(sessions):
            key = s["key"]
            seen.add(key)
            chip = self._compact_chips.get(key)
            if chip is None:
                chip = self._make_compact_chip()
                self._compact_chips[key] = chip
                self._bind_alias_click(chip, key)
            if chip["dot"].cget("fg") != s["dot_color"]:
                chip["dot"].config(fg=s["dot_color"])
            display_txt = session_display_text(s)
            if chip["name"].cget("text") != display_txt:
                chip["name"].config(text=display_txt)
            alias_txt = self._session_aliases.get(self._alias_key(key), "")
            if chip["alias"].cget("text") != alias_txt:
                chip["alias"].config(text=alias_txt)
            badge_txt = bg_badge_text(s.get("background_tasks_count"))
            if chip["badge"].cget("text") != badge_txt:
                chip["badge"].config(text=badge_txt)
        for key in list(self._compact_chips):
            if key not in seen:
                self._compact_chips[key]["frame"].destroy()
                del self._compact_chips[key]
                # Alias kept — pruned once at startup, not on a per-tick blink.

        new_order = [s["key"] for s in sessions]
        if new_order != self._compact_order:
            for key in new_order:
                chip = self._compact_chips.get(key)
                if chip is not None:
                    chip["frame"].pack_forget()
                    chip["frame"].pack(side="left", padx=3, pady=2)
            self._compact_order = new_order

        if not self._compact_chips:
            if not self.compact_empty.winfo_ismapped():
                self.compact_empty.pack(side="left", padx=6)
        else:
            self.compact_empty.pack_forget()

    def _make_compact_chip(self) -> dict:
        frame = tk.Frame(self.compact_row, bg="#242424")
        frame.pack(side="left", padx=3, pady=2)
        inner = tk.Frame(frame, bg="#242424")
        inner.pack(padx=6, pady=3)
        dot = tk.Label(inner, text="●", bg="#242424",
                       font=("Segoe UI", 12, "bold"))
        dot.pack(side="left")
        name = tk.Label(inner, text="", bg="#242424", fg="#f0f0f0",
                        font=("Segoe UI", 10, "bold"))
        name.pack(side="left", padx=(4, 0))
        alias = tk.Label(inner, text="", bg="#242424", fg="#e0a458",
                         font=("Segoe UI", 10, "bold"))
        alias.pack(side="left", padx=(3, 0))
        badge = tk.Label(inner, text="", bg="#242424", fg="#5fbfb0",
                         font=("Segoe UI", 10))
        badge.pack(side="left", padx=(3, 0))
        return {"frame": frame, "inner": inner, "dot": dot, "name": name,
                "alias": alias, "badge": badge}

    def _make_container_row(self) -> dict:
        frame = tk.Frame(self.docker_section, bg="#1f2a1f")
        frame.pack(fill="x", pady=1)
        top = tk.Frame(frame, bg="#1f2a1f")
        top.pack(fill="x", padx=8, pady=(4, 4))
        tk.Label(top, text="🐳", bg="#1f2a1f",
                 font=("Segoe UI Emoji", 11)).pack(side="left")
        project = tk.Label(top, text="", bg="#1f2a1f", fg="#c8e6c8",
                           font=("Segoe UI", 12, "bold"))
        project.pack(side="left", padx=(6, 0))
        status = tk.Label(top, text="", bg="#1f2a1f", fg="#7a9a7a",
                          font=("Segoe UI", 9))
        status.pack(side="right")
        return {"frame": frame, "project": project, "status": status}

    def _make_session_row(self) -> dict:
        frame = tk.Frame(self.session_section, bg="#242424")
        frame.pack(fill="x", pady=2)
        top = tk.Frame(frame, bg="#242424")
        top.pack(fill="x", padx=8, pady=(5, 0))
        dot = tk.Label(top, text="", bg="#242424",
                       font=("Segoe UI", 14, "bold"))
        dot.pack(side="left")
        name = tk.Label(top, text="", bg="#242424", fg="#f0f0f0",
                        font=("Segoe UI", 12, "bold"))
        name.pack(side="left", padx=(6, 0))
        # User-set runtime label; stays empty (zero-width) until the row is
        # clicked. Amber so it reads as distinct from the project name.
        alias = tk.Label(top, text="", bg="#242424", fg="#e0a458",
                         font=("Segoe UI", 11, "bold"))
        alias.pack(side="left", padx=(5, 0))
        badge = tk.Label(top, text="", bg="#242424", fg="#5fbfb0",
                         font=("Segoe UI", 11))
        badge.pack(side="left", padx=(4, 0))
        age = tk.Label(top, text="", bg="#242424", fg="#888",
                       font=("Segoe UI", 10))
        age.pack(side="right")
        action = tk.Label(frame, text="", bg="#242424", fg="#9cb4d6",
                          font=("Segoe UI", 10), anchor="w")
        action.pack(fill="x", padx=30, pady=(0, 5))
        return {"frame": frame, "top": top, "dot": dot, "name": name,
                "alias": alias, "badge": badge,
                "age": age, "action": action}

    def run(self) -> None:
        self.root.mainloop()


def _acquire_singleton():
    """Reserve a single-instance lock. Returns a handle (or None if already running).

    Windows: named mutex (no TIME_WAIT issues). POSIX: loopback socket bind.
    """
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return object()  # can't check — let it run
        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, "Global\\ClaudeMonitorSingleton")
        if not handle:
            return object()
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return handle
    # POSIX: loopback socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", SINGLETON_PORT))
        s.listen(1)
        return s
    except OSError:
        s.close()
        return None


if __name__ == "__main__":
    if "--test-notify" in sys.argv:
        # Fire a single beep + taskbar flash and exit — lets the user confirm
        # the notification hardware responds without waiting for a real session
        # to cross the 5-minute threshold.
        app = MonitorApp()

        def fire():
            # FlashWindowEx does nothing if the target is already foreground.
            # Iconify first so the OS has an inactive taskbar icon to animate —
            # that's how the notification will actually look in production when
            # the user is focused on another window.
            try:
                app.root.update_idletasks()
                app.root.iconify()
                app.root.update()
            except Exception:
                pass
            app.root.after(400, lambda: app._notify("test", 600))
            # Deiconify after a moment so the user sees the flash settle, then exit.
            app.root.after(6000, app.root.deiconify)
            app.root.after(8000, app.root.destroy)

        # Give Tk 1.5s to map the window before firing.
        app.root.after(1500, fire)
        app.run()
        sys.exit(0)
    # Retry briefly — a restarting instance might still hold the lock for a moment.
    for _ in range(10):
        _SINGLETON_HANDLE = _acquire_singleton()
        if _SINGLETON_HANDLE is not None:
            break
        time.sleep(0.3)
    if _SINGLETON_HANDLE is None:
        sys.exit(0)
    MonitorApp().run()
