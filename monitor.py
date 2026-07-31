"""Claude Code session monitor — always-on-top overlay for Windows.

Phase 2 (state-writer-shadow-mode): a second, hook-derived verdict engine
(scan_state_files()) runs alongside the legacy jsonl-parsing engine (scan())
on every tick, and disagreements between them are logged to DIVERGENCE_LOG
for later review — but during normal operation the overlay, notifications
and Telegram push are still driven exclusively by the legacy engine (D-01).
Launch with `--state-files` (see state_files_mode()) to render and notify
from the state-file engine instead, for hands-on verification of the new
engine including its notification behaviour; without the flag, this file
behaves exactly as it did before Phase 2.
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

from shell_tracker import (
    count_active_agents,
    count_active_async_agents,
    count_active_monitors,
    has_active_shells,
)

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
# Phase 2 state-writer engine (shadow mode): one small JSON verdict file per
# session_id, written atomically by hooks/state-writer.sh on lifecycle
# events. Module-level so tests can repoint them the way they already
# repoint PROJECTS_DIR/AUQ_LOCK_DIR. See scan_state_files() below and
# .planning/phases/02-state-writer-shadow-mode/ for the design — this engine
# is shadow-only during Phase 2 (D-01): its output never reaches rendering
# or notification directly, see select_render_sessions().
STATE_DIR = Path.home() / ".claude" / "monitor-state"
DIVERGENCE_LOG = Path.home() / ".claude" / "monitor-divergence.log"
# Size guard for DIVERGENCE_LOG, mirroring the 5MB threshold
# hooks/event-logger.sh already established for hook-events.log on the same
# shared 9p mount (T-02-18). See write_divergences() below.
DIVERGENCE_LOG_MAX_BYTES = 5 * 1024 * 1024
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
    # Master switch for local notifications (toast + audio + taskbar flash).
    "local": True,
    # Telegram push to the phone. Independent of "local" — silence one without
    # the other (e.g. mute the desk but keep the phone, or vice versa).
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
    # "local" master switch when an older config is loaded.
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


def project_name(encoded: str, label_map: dict[str, str] | None = None) -> str:
    # dir names like "c--Users-you-Documents-projects-my-app"
    # If a running container's workdir matches, use its launcher label instead.
    if label_map and encoded in label_map:
        return label_map[encoded]
    # If the encoded dir ends with a known launcher label (e.g. a Windows path
    # "C--Users-...-dev-tools"), prefer that over the raw last segment.
    order = launcher_order()
    if order:
        for label in sorted(order, key=len, reverse=True):
            if encoded.endswith("-" + label) or encoded == label:
                return label
    parts = [p for p in encoded.split("-") if p]
    return parts[-1] if parts else encoded


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
# Phase 2 state-writer engine (shadow mode) — reads ~/.claude/monitor-state/
# (hooks/state-writer.sh's output) as a second, independent verdict source.
# NEVER reaches rendering/notification directly during Phase 2 (D-01); see
# select_render_sessions(), the single seam that enforces this structurally.
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


# Compact per-event labels for the shadow list's `action` column — the
# diagnostic-mode equivalent of legacy's parse_last_action() jsonl-tail
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
    """
    ts_ms = obj.get("ts_ms")
    if isinstance(ts_ms, (int, float)) and ts_ms > 0:
        return now - (ts_ms / 1000.0)
    return now - mtime


def scan_state_files(label_map: dict[str, str] | None = None,
                      sessionid_to_label: dict[str, str] | None = None,
                      container_info: dict | None = None,
                      legacy_sessions: list[dict] | None = None) -> list[dict]:
    """Shadow-mode sibling of scan(): derives one verdict per session from
    ~/.claude/monitor-state/*.json (written atomically by
    hooks/state-writer.sh) instead of parsing any jsonl.

    Mirrors scan()'s session-dict shape (same keys legacy emits, so the
    divergence comparator can pair the two lists by `key`) plus shadow-only
    extras (`state`, `last_event`, `hostname`, `background_tasks_count`).
    `label_map` is accepted for signature parity with scan() (D-05 requires
    reproducing today's labels); state files always carry a real
    session_id (the filename stem), so `sessionid_to_label` and, as a
    fallback, `container_info["hostname_to_label"]` are what's actually
    consulted here — the hostname fallback matters because
    `sessionid_to_label` is built via `docker exec` (query_container_sessionids),
    which cannot reach a paused container; without it a paused session's
    label would be unresolved and it would vanish from the shadow list,
    making the paused-stays-WORKING staleness branch below unreachable.

    `container_info` (scan_containers()'s fourth return element) also gates
    a stale WORKING verdict: past STATE_HEARTBEAT_STALE_SEC (or the shorter
    STATE_PROMPT_STALE_SEC when the last event was UserPromptSubmit)
    without a fresher heartbeat, the verdict recovers to WAITING — unless
    the record's hostname maps to a `paused` container, which D-06 treats
    as alive-but-frozen, never dead. This is the named fallback for the
    Esc interrupt, the permission-denial dead end, the killed container and
    the abandoned pre-tool prompt (TEST-MATRIX cases 8, 5-deny, 9, 19) —
    none of which emit any hook event to hang a transition on.

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
    (STATE_PRUNE_AGE_SEC, 24h, is 24x the one-hour visibility window).

    `legacy_sessions` (ENG-05's migration bridge, TEST-MATRIX case 21): once
    the state-file-derived list above is built, every session `refresh()`'s
    already-computed legacy `scan()` saw but that has no state file — a
    container running an image without the hooks installed, by definition —
    is carried through unchanged, tagged with a shadow-only `legacy_origin`
    marker so divergence review can tell a genuine state-file verdict apart
    from a session simply copied across. When `legacy_sessions` is None,
    `scan(label_map, sessionid_to_label)` runs internally instead, so a
    standalone caller (the `--state-files` diagnostic mode) still sees the
    complete picture without a second full jsonl scan every tick.
    """
    sessions: list[dict] = []
    if STATE_DIR.is_dir():
        now = time.time()
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
                if age > window:
                    container_status = None
                    if container_info and hostname:
                        container_status = container_info.get(
                            "hostname_to_status", {}).get(hostname)
                    if container_status != "paused":
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
                "bg": bool(bg_count and bg_count > 0),
                "monitors": 0,
                "agents": 0,
                "status": status,
                "rank": rank,
                "age": age,
                "mtime": mtime,
                "action": _state_action_label(last_event),
                "state": state_val,
                "last_event": last_event,
                "hostname": obj.get("hostname"),
                "background_tasks_count": bg_count,
                "alias_key": derive_alias_key(hostname, session_id),
            })

    if legacy_sessions is None:
        legacy_sessions = scan(label_map, sessionid_to_label, container_info=container_info)
    seen_keys = {s["key"] for s in sessions}
    for legacy in legacy_sessions:
        if legacy["key"] in seen_keys:
            continue
        carried = dict(legacy)
        carried["legacy_origin"] = True
        sessions.append(carried)

    order = launcher_order()
    big = len(order) + 1
    sessions.sort(key=lambda s: (order.get(s["name"], big), -s["mtime"]))
    return sessions


def diff_verdicts(legacy: list[dict], shadow: list[dict], tick: float) -> list[dict]:
    """Pure comparison, no I/O. Emits one record per session `key` whose
    legacy and shadow `status` disagree, compared over the UNION of both
    engines' keys — not the intersection — because a session one engine
    sees and the other does not is itself one of the most informative
    divergences there is (a paused container the shadow engine keeps and
    legacy drops, or a session one engine picks up a tick earlier). The
    missing side's verdict is represented as the string "ABSENT". Two lists
    that agree completely, and two empty lists, both yield an empty list.
    Records are sorted by `key` so the divergence log reads stable and
    diffable across ticks.

    Field shape carries everything D-04 requires to judge which side was
    right during review: both verdicts, the state-file engine's context
    (`state`, `last_event`, `hostname`, `background_tasks_count`, `age_sec`)
    and a compact `legacy_evidence` string assembled only from safe,
    non-content legacy signals — the tool-name-only `action` label, the two
    lock booleans, the `bg`/`monitors`/`agents` counts and the age — never
    prompt text, tool input or tool output (T-02-17). No field here
    classifies which side was correct: D-04 keeps that judgment in the
    review conversation, not in code that could quietly steer it.
    """
    legacy_by_key = {s["key"]: s for s in legacy}
    shadow_by_key = {s["key"]: s for s in shadow}
    records: list[dict] = []
    for key in set(legacy_by_key) | set(shadow_by_key):
        l = legacy_by_key.get(key)
        s = shadow_by_key.get(key)
        legacy_status = l["status"] if l else None
        shadow_status = s["status"] if s else None
        if legacy_status == shadow_status:
            continue
        ref = l or s
        if l is None:
            legacy_evidence = "ABSENT"
        else:
            legacy_evidence = (
                f"action={l.get('action', '')} "
                f"working_locked={l.get('working_locked', False)} "
                f"auq_locked={l.get('auq_locked', False)} "
                f"bg={l.get('bg', False)} "
                f"monitors={l.get('monitors', 0)} "
                f"agents={l.get('agents', 0)} "
                f"age={l.get('age', 0):.0f}s"
            )
        records.append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tick)),
            "ts_ms": int(tick * 1000),
            "tick": tick,
            "key": key,
            "session_id": ref.get("session_id"),
            "name": ref.get("name"),
            "legacy_verdict": legacy_status if l is not None else "ABSENT",
            "state_file_verdict": shadow_status if s is not None else "ABSENT",
            "state": s.get("state") if s else None,
            "last_event": s.get("last_event") if s else None,
            "hostname": s.get("hostname") if s else None,
            "background_tasks_count": s.get("background_tasks_count") if s else None,
            "age_sec": s.get("age") if s else None,
            "legacy_evidence": legacy_evidence,
        })
    records.sort(key=lambda r: r["key"])
    return records


def filter_divergence_events(records: list[dict], prev: dict[str, dict] | None,
                              tick: float) -> tuple[list[dict], dict[str, dict]]:
    """Collapse a persisting disagreement to one `diverged` event when it
    opens and one `resolved` event when it closes, instead of one identical
    line every tick (D-02). Pure function — no I/O, no tkinter — so it is
    testable on its own; the caller (MonitorApp.refresh()) holds `prev` on
    `self._divergence_state` and threads it through each tick.

    `records` is this tick's diff_verdicts() output. `prev` is the state
    dict this same function returned last tick, keyed by `key`: each entry
    is `{"pair": (legacy_verdict, state_file_verdict), "since_ts_ms": ...,
    "ticks": N}`. A key whose verdict pair is new, or whose pair changed
    since `prev`, yields a `diverged` event and (re)starts its episode at
    `ticks=1`. A key present in `prev` but absent from this tick's
    `records` — because the two engines now agree, or the session vanished
    while diverging — yields a `resolved` event carrying `since_ts_ms` and
    the `ticks` the episode lasted. A key whose pair is unchanged
    contributes no event, only an incremented tick count in the returned
    state.
    """
    prev = dict(prev) if prev else {}
    next_state: dict[str, dict] = {}
    events: list[dict] = []
    current_keys: set[str] = set()
    for r in records:
        key = r["key"]
        current_keys.add(key)
        pair = (r["legacy_verdict"], r["state_file_verdict"])
        prev_entry = prev.get(key)
        if prev_entry is None or prev_entry["pair"] != pair:
            since_ts_ms = r["ts_ms"]
            ticks = 1
            event = dict(r)
            event["event"] = "diverged"
            event["since_ts_ms"] = since_ts_ms
            event["ticks"] = ticks
            events.append(event)
            next_state[key] = {"pair": pair, "since_ts_ms": since_ts_ms, "ticks": ticks}
        else:
            next_state[key] = {
                "pair": pair,
                "since_ts_ms": prev_entry["since_ts_ms"],
                "ticks": prev_entry["ticks"] + 1,
            }
    for key, entry in prev.items():
        if key in current_keys:
            continue
        events.append({
            "event": "resolved",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(tick)),
            "ts_ms": int(tick * 1000),
            "tick": tick,
            "key": key,
            "since_ts_ms": entry["since_ts_ms"],
            "ticks": entry["ticks"],
        })
    events.sort(key=lambda e: e["key"])
    return events, next_state


def write_divergences(records: list[dict]) -> None:
    """Append one JSON line per divergence event to DIVERGENCE_LOG.

    Size-guarded at DIVERGENCE_LOG_MAX_BYTES (mirrors the 5MB threshold
    hooks/event-logger.sh already uses for hook-events.log on the same
    shared 9p mount, T-02-18): a file already over the threshold is
    truncated and an explicit marker record is written first, so a reader
    can never mistake a truncation for a gap in observation (T-02-21). No
    flock is needed or added here, unlike hook-events.log — the monitor
    holds its own process-wide singleton lock (SINGLETON_PORT), so this log
    has exactly one writer.

    Wrapped so an OSError on the shared mount can never interrupt a tick —
    same "a log write must never break the loop" discipline
    hooks/event-logger.sh already established for hook-events.log (T-02-19).
    """
    if not records:
        return
    try:
        DIVERGENCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = DIVERGENCE_LOG.stat().st_size
        except OSError:
            size = 0
        truncated = size > DIVERGENCE_LOG_MAX_BYTES
        with DIVERGENCE_LOG.open("w" if truncated else "a", encoding="utf-8") as f:
            if truncated:
                marker = {
                    "event": "_truncated",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time())),
                    "note": (
                        f"monitor-divergence.log exceeded {DIVERGENCE_LOG_MAX_BYTES} "
                        "bytes and was truncated before this line"
                    ),
                }
                f.write(json.dumps(marker) + "\n")
            for r in records:
                f.write(json.dumps(r) + "\n")
    except OSError:
        pass


def select_render_sessions(legacy: list[dict], shadow: list[dict],
                            state_files_mode: bool) -> list[dict]:
    """The single seam through which either engine's output can reach
    rendering or notification. Returns the legacy list *object* itself
    (identity, not a copy) when state_files_mode is False — this is what
    makes D-01 ("zero UX change during Phase 2") structurally enforceable
    rather than just a promise never to wire the shadow engine into the UI.
    """
    return shadow if state_files_mode else legacy


def state_files_mode(argv: list[str] | None = None) -> bool:
    """Whether monitor.py was launched with the `--state-files` diagnostic
    flag (ENG-01), read directly from argv the same way `--test-notify`
    already is — this codebase deliberately has no argparse. Kept behind a
    function, not inlined at the call site, so it is unit-testable without
    constructing the tkinter-backed MonitorApp; defaults to `sys.argv` so
    normal callers don't have to pass anything.

    Without the flag, every path the overlay drives — the overlay itself,
    toasts, audio, the taskbar flash and the Telegram push — is driven by
    the legacy list exactly as it is today (D-01). With the flag, those
    same paths are driven by the state-file engine instead, so the new
    engine (including its notification behaviour) can be verified by eye.
    The shadow comparison (diff_verdicts/write_divergences) always runs
    every tick regardless of this flag — it's a pure rendering choice made
    once through select_render_sessions(), not a scan-time one.

    Operational note: the monitor is a process-wide singleton (see
    SINGLETON_PORT above), so a normal monitor instance has to be closed
    before starting a `--state-files` diagnostic run — a second instance
    started with the flag while the first is running exits silently.
    """
    if argv is None:
        argv = sys.argv
    return "--state-files" in argv


def scan(label_map: dict[str, str] | None = None,
         sessionid_to_label: dict[str, str] | None = None,
         container_info: dict | None = None) -> list[dict]:
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
        has_bg = has_active_shells(latest)
        monitors = count_active_monitors(latest)
        agents = count_active_agents(latest)
        async_agents = count_active_async_agents(latest)
        # Default GREEN (waiting). Flip to GREY only when evidence is
        # unambiguous: a foreground Agent/Monitor is in flight, the assistant
        # tail proves Claude is mid-turn (thinking block or tool_use still
        # waiting on its tool_result), or a fresh `user` tail means Claude
        # owes a response and the file is still being written. Stale user
        # tails (without new events) go GREEN so interrupted/abandoned
        # sessions don't get stuck grey forever — but tool_result tails get a
        # much longer grace window because the follow-up turn can legitimately
        # take many minutes (slow bash, deep thinking, long web research). A
        # live background shell (has_bg) does NOT pin grey — it is badge-only
        # (the row's `bg` field below). A bg shell is not evidence Claude owes
        # anyone a reply; when its finite task finishes and re-invokes Claude,
        # that re-invocation emits a fresh UserPromptSubmit (TEST-MATRIX case
        # 13) and grey comes from the working-lock, not from the shell itself.
        # Accepted trade-off: a turn that ends while a build/test/install bg
        # task is still running shows green immediately (notification fires),
        # with the badge reporting the still-running process.
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
        # has_bg is deliberately absent from this chain — a live background
        # shell is badge-only (see the row's `bg` field below) and must never
        # pin WORKING by itself. A foreground Agent genuinely blocks the turn,
        # Monitor tasks terminate via TaskStop or their own timeout, and async
        # agents end with a task-notification — those three keep their pins
        # unchanged; only the unbounded-lifetime bg-shell signal was dropped.
        if auq_locked:
            status, dot, color, rank = "WAITING", "●", "#4ade80", 1
        elif (agents > 0 or async_agents > 0 or monitors > 0
                or is_certainly_working(last_line) or fresh_user_tail
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
            "session_id": session_id,
            "alias_key": derive_alias_key(hostname, key),
            "encoded_dir": proj_dir.name,
            "dot": dot,
            "dot_color": color,
            "bg": has_bg,
            "monitors": monitors,
            "agents": agents,
            "status": status,
            "rank": rank,
            "age": age,
            "mtime": latest_mtime,
            "action": parse_last_action(last_line),
            # Phase 2 shadow engine (ENG-02): both locks were already computed
            # above for the legacy status decision — reported here too so
            # diff_verdicts() can assemble legacy_evidence without a second
            # lock-file stat.
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
    if name.startswith(project):
        return name
    return project


def scan_containers() -> tuple[list[dict], dict[str, str], dict[str, str], dict]:
    """List running Docker containers that carry a 'project' label.

    Returns (rows, label_map, sessionid_to_label, container_info):
    `label_map` maps encoded session-dir names (as they appear under
    ~/.claude/projects/) to the container's launcher label; `container_info`
    is the Phase 2 state-file engine's container-identity/liveness
    cross-check (D-05, ENG-03) — {"hostname_to_label": ..., "hostname_to_status": ...,
    "sessionid_to_hostname": ...}, keyed by the container hostname the state
    writer captures at write time, built from the one container-inspection
    call below (no second subprocess call added). `sessionid_to_hostname`
    also feeds derive_alias_key() so a session's alias survives a sessionId
    rotation.
    """
    empty_container_info = {
        "hostname_to_label": {}, "hostname_to_status": {}, "sessionid_to_hostname": {},
    }
    docker = shutil.which("docker")
    if not docker:
        return [], {}, {}, dict(empty_container_info)
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
        return [], {}, {}, dict(empty_container_info)
    if out.returncode != 0:
        return [], {}, {}, dict(empty_container_info)
    rows = []
    ids = []
    cid_to_label: dict[str, str] = {}
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[1]:
            continue
        ids.append(parts[0])
        cid_to_label[parts[0]] = parts[1]
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
    }


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
        # Phase 2 shadow engine (ENG-03): hostname_to_label/hostname_to_status
        # from scan_containers()'s fourth return element, feeding
        # scan_state_files()'s staleness gate and paused-container label
        # fallback. Empty maps until the first docker tick completes.
        self._cached_container_info: dict = {
            "hostname_to_label": {}, "hostname_to_status": {}, "sessionid_to_hostname": {},
        }
        self._docker_query_inflight = False
        # Phase 2 shadow engine (D-01/ENG-01): read once at startup from the
        # `--state-files` CLI flag via state_files_mode() below. False keeps
        # select_render_sessions() returning the legacy list unconditionally
        # — the default run's behaviour is unchanged from before this phase.
        self.state_files_mode = state_files_mode()
        # Phase 2 shadow engine (ENG-02): per-key episode state carried
        # across ticks for filter_divergence_events(), so a persisting
        # disagreement collapses to one `diverged` line and one `resolved`
        # line instead of one identical line every REFRESH_MS.
        self._divergence_state: dict[str, dict] = {}

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
                     "bg", "monitor", "age", "action"):
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
                # the armed notification is discarded, no toast fires.
                self._pending_notify.pop(key, None)
            else:  # WAITING
                if prev == "WORKING":
                    started = self._working_since.pop(key, None)
                    if started is not None and (now - started) >= NOTIFY_MIN_WORK_SEC:
                        # Debounce: arm now, fire only if still WAITING next tick.
                        self._pending_notify[key] = int(now - started)
                elif key in self._pending_notify:
                    self._notify(s["name"], self._pending_notify.pop(key), key=key)
            self._prev_status[key] = curr
        # Drop tracking for sessions no longer present
        for key in list(self._prev_status):
            if key not in seen:
                del self._prev_status[key]
                self._working_since.pop(key, None)
                self._pending_notify.pop(key, None)
                self._dismiss_session_toast(key)

    def _notify_toast(self, title: str, message: str, key: str | None = None) -> bool:
        """In-app toast: borderless Toplevel in the bottom-right corner.

        Why not the native Windows toast API? It silently drops notifications whose
        AppUserModelID isn't registered (shortcut in Start Menu, or via registry).
        Our own Toplevel is always visible, doesn't care about system notification
        policies, and stays consistent across Windows/WSL.

        Only reached when local notifications are on (the audio cue fires alongside),
        so the toast auto-dismisses after a few seconds or on click.
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
        notification stack (toast+audio+flash always fire first).
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

    def _notify(self, label: str, elapsed_sec: int, key: str | None = None) -> None:
        """Toast + audio beep + taskbar flash when a long-running session is ready for user input.

        Two independent gates: "local" governs toast/audio/flash on this machine,
        "telegram" governs the phone push. Either can be silenced without the other.
        """
        verbose = "--test-notify" in sys.argv
        local_on = bool(self.config.get("local", True))
        mins, secs = divmod(elapsed_sec, 60)
        elapsed_human = f"{mins}m {secs}s" if mins else f"{secs}s"
        # Append the user's per-session alias when set, so two sessions sharing
        # a project name (e.g. two `yunoai-france`) are still tellable apart.
        alias = self._session_aliases.get(self._alias_key(key), "") if key else ""
        shown = f"{label} · {alias}" if alias else label
        toast_title = f"Claude ready — {shown}"
        toast_body = f"Waiting for your input after {elapsed_human} of work."
        # Telegram fires regardless of the local switch — the whole point of the
        # phone push is to reach you when you're away from the desk (local muted).
        if self.config.get("telegram", True):
            self._send_telegram(toast_title, toast_body)
        toast_ok = self._notify_toast(toast_title, toast_body, key=key) if local_on else False
        if verbose:
            print(f"[notify] local={'on' if local_on else 'off'} "
                  f"toast={'ok' if toast_ok else 'skip/FAIL'}", file=sys.stderr)
        # Audio: walk NOTIFY_WAV_FILES, play the first one that exists.
        # MessageBeep / Tk bell are silent-OK fallbacks for odd systems.
        audio_ok = False
        audio_channel = "none"
        replay_fn = None
        if local_on:
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
        # Taskbar flash (Windows only, continues until window gains focus).
        # Ensure the window is fully realized before asking the OS to flash it.
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        flash_ok = False
        if local_on and os.name == "nt":
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
        if verbose:
            print(f"[notify] flash={'ok' if flash_ok else 'FAIL'} label={label} elapsed={elapsed_sec}s",
                  file=sys.stderr)

    def _kick_docker_query(self) -> None:
        if self._docker_query_inflight:
            return
        self._docker_query_inflight = True

        def worker() -> None:
            try:
                rows, label_map, sid_map, container_info = scan_containers()
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
                             container_info=self._cached_container_info)
        except Exception:
            sessions = []

        # Phase 2 shadow engine (D-01: shadow-only, never rendered directly
        # during default operation). One bad shadow tick must never break
        # the loop — same defensive wrapping as the legacy scan() call
        # above.
        try:
            shadow_sessions = scan_state_files(
                self._cached_label_map, self._sessionid_to_label,
                container_info=self._cached_container_info,
                legacy_sessions=sessions,
            )
        except Exception:
            shadow_sessions = []
        divergence_tick = time.time()
        diverge_records = diff_verdicts(sessions, shadow_sessions, divergence_tick)
        diverge_events, self._divergence_state = filter_divergence_events(
            diverge_records, self._divergence_state, divergence_tick)
        write_divergences(diverge_events)
        # The single seam through which either engine's output can reach
        # rendering/notification — select_render_sessions(..., False) always
        # returns the legacy `sessions` list object itself (identity), which
        # is what makes D-01 structurally enforceable rather than a promise.
        render_sessions = select_render_sessions(sessions, shadow_sessions, self.state_files_mode)

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

        count_txt = f"{len(containers)}d · {len(sessions)}s"
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
            if row["name"].cget("text") != s["name"]:
                row["name"].config(text=s["name"])
            alias_txt = self._session_aliases.get(self._alias_key(key), "")
            if row["alias"].cget("text") != alias_txt:
                row["alias"].config(text=alias_txt)
            bg_txt = "⚙" if s["bg"] else ""
            if row["bg"].cget("text") != bg_txt:
                row["bg"].config(text=bg_txt)
            mon_txt = "" if not s["monitors"] else ("◉" if s["monitors"] == 1 else f"◉{s['monitors']}")
            if row["monitor"].cget("text") != mon_txt:
                row["monitor"].config(text=mon_txt)
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
            if chip["name"].cget("text") != s["name"]:
                chip["name"].config(text=s["name"])
            alias_txt = self._session_aliases.get(self._alias_key(key), "")
            if chip["alias"].cget("text") != alias_txt:
                chip["alias"].config(text=alias_txt)
            bg_txt = "⚙" if s["bg"] else ""
            if chip["bg"].cget("text") != bg_txt:
                chip["bg"].config(text=bg_txt)
            mon_txt = "" if not s["monitors"] else ("◉" if s["monitors"] == 1 else f"◉{s['monitors']}")
            if chip["monitor"].cget("text") != mon_txt:
                chip["monitor"].config(text=mon_txt)
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
        bg_badge = tk.Label(inner, text="", bg="#242424", fg="#c8a24a",
                            font=("Segoe UI", 10))
        bg_badge.pack(side="left", padx=(3, 0))
        mon_badge = tk.Label(inner, text="", bg="#242424", fg="#5fbfb0",
                             font=("Segoe UI", 10))
        mon_badge.pack(side="left", padx=(3, 0))
        return {"frame": frame, "inner": inner, "dot": dot, "name": name,
                "alias": alias, "bg": bg_badge, "monitor": mon_badge}

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
        bg_badge = tk.Label(top, text="", bg="#242424", fg="#c8a24a",
                            font=("Segoe UI", 11))
        bg_badge.pack(side="left", padx=(4, 0))
        mon_badge = tk.Label(top, text="", bg="#242424", fg="#5fbfb0",
                             font=("Segoe UI", 11))
        mon_badge.pack(side="left", padx=(4, 0))
        age = tk.Label(top, text="", bg="#242424", fg="#888",
                       font=("Segoe UI", 10))
        age.pack(side="right")
        action = tk.Label(frame, text="", bg="#242424", fg="#9cb4d6",
                          font=("Segoe UI", 10), anchor="w")
        action.pack(fill="x", padx=30, pady=(0, 5))
        return {"frame": frame, "top": top, "dot": dot, "name": name,
                "alias": alias, "bg": bg_badge, "monitor": mon_badge,
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
