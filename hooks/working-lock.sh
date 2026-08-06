#!/usr/bin/env bash
# Set/clear a "Claude is mid-turn" working lock so claude-monitor stays GREY
# while Claude is actually working, bridging Claude Code's batched jsonl writes.
#
# Claude Code batches jsonl writes: an assistant tool_use record only lands
# together with its tool_result, i.e. when the tool FINISHES. While a tool is
# in flight (slow Read/Bash, deep thinking, long web research) nothing new hits
# the file, so the tail still looks like the previous record — typically an
# assistant `text` reply, which the monitor reads as idle → false WAITING (toast
# + beep + Telegram), even though a tool is running.
#
# Two triggers cover the whole turn:
#   UserPromptSubmit → bridges the prompt→first-flush gap.
#   PreToolUse       → re-arms the lock at the START of every tool, so the lock
#                      mtime stays ahead of the (still-stale) jsonl for the
#                      entire in-flight window.
# Once a tool finishes and the jsonl flushes past the lock, the monitor's
# stale-lock guard drops the lock and the normal tail logic (tool_result's long
# window) takes over until the next PreToolUse re-arms it. Stop clears it at
# end-of-turn; the guard + max-age cover a missed Stop (interrupt/crash).
#
# Mode: $1 = "set" (UserPromptSubmit | PreToolUse) or "clear" (Stop).
set -eu
mode="${1:-}"
sid=$(cat | jq -r '.session_id // empty' 2>/dev/null || true)
[ -z "$sid" ] && exit 0

# Path-traversal guard (T-03-01): sid becomes part of a filesystem path
# below. Reject anything that isn't a bare filename-safe token before it is
# used, mirroring hooks/state-writer.sh's identical guard byte-for-byte so
# the two scripts cannot drift. A rejected payload exits 0 silently — same
# as every other early-exit path here and in state-writer.sh; a hook must
# never fail loudly and disrupt the session.
case "$sid" in
  *[!A-Za-z0-9._-]*)
    exit 0
    ;;
esac

lock_dir="$HOME/.claude/working-locks"
mkdir -p "$lock_dir"
case "$mode" in
  set)   touch "$lock_dir/$sid" ;;
  clear) rm -f "$lock_dir/$sid" ;;
esac
exit 0
