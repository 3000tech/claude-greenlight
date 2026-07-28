#!/usr/bin/env bash
# Set/clear a user-input wait lock so claude-monitor can show WAITING while
# Claude is blocked on the user. Two triggers feed it:
#   AskUserQuestion  PreToolUse → set / PostToolUse → clear  (the modal)
#   Notification                → set                        (a tool-permission
#                    prompt, e.g. the "dangerous rm" confirmation, or an idle
#                    "waiting for your input" nudge)
# Both work around Claude Code's batched jsonl flush, which only writes the
# assistant tool_use record together with its tool_result — so during the actual
# wait the file tail still looks like the previous record and the monitor would
# otherwise paint the session GREY (WORKING). A Stop clear + the monitor's
# stale-lock guard (jsonl mtime advancing past the lock) heal it once the user
# answers, so no explicit clear is needed on the Notification path.
#
# Mode: $1 = "set" (PreToolUse | Notification) or "clear" (PostToolUse | Stop).
set -eu
mode="${1:-}"
sid=$(cat | jq -r '.session_id // empty' 2>/dev/null || true)
[ -z "$sid" ] && exit 0
lock_dir="$HOME/.claude/auq-locks"
mkdir -p "$lock_dir"
case "$mode" in
  set)   touch "$lock_dir/$sid" ;;
  clear) rm -f "$lock_dir/$sid" ;;
esac
exit 0
