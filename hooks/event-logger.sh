#!/usr/bin/env bash
# Diagnostic-only Phase 1 instrument (claude-greenlight hook-driven refactor).
# Appends one JSONL line per Claude Code hook event to
# ~/.claude/hook-events.log — the ground truth for which events actually
# fire and what fields they actually carry, since doc-fetch summaries have
# been observed reporting different field names on different fetches.
#
# Never emits decision-control stdout and never fails a session: every code
# path below ends in `exit 0`, even a missing/empty payload, non-JSON stdin,
# or a jq parse failure. This script only records; it never gates or blocks.
#
# Teardown: `hooks/install.sh --remove-logger` strips every logger entry
# from settings.json and this file can then be deleted from
# ~/.claude/hooks/ — the whole instrument is disposable by design.
set -u

LOG_DIR="$HOME/.claude"
LOG="$LOG_DIR/hook-events.log"

payload=$(cat)
if [ -z "$payload" ]; then
  exit 0
fi

line=$(jq -c '
  {
    ts: (now | todate),
    ts_ms: (now * 1000 | floor),
    event: .hook_event_name,
    session_id,
    cwd,
    keys: (keys),
    tool_name,
    stop_hook_active
  }
  | with_entries(select(.value != null))
' <<<"$payload" 2>/dev/null)
jq_status=$?

if [ "$jq_status" -ne 0 ]; then
  exit 0
fi

if [ -z "$line" ]; then
  exit 0
fi

mkdir -p "$LOG_DIR"

if [ -n "$line" ]; then
  printf '%s\n' "$line" >> "$LOG"
fi

exit 0
