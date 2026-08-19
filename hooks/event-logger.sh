#!/usr/bin/env bash
# Diagnostic-only Phase 1 instrument (claude-greenlight hook-driven refactor).
# Appends one JSONL line per Claude Code hook event to
# ~/.claude/hook-events.log — the ground truth for which events actually
# fire and what fields they actually carry, since doc-fetch summaries have
# been observed reporting different field names on different fetches.
#
# Never emits decision-control stdout and never fails a session: every code
# path below ends in `exit 0`, even a missing/empty/partial payload,
# non-JSON stdin, or a jq parse failure. This script only records; it never
# gates or blocks.
#
# Captured by value: identity/scalar metadata only (ts, ts_ms, event,
# session_id, cwd, source, reason, trigger, matcher, permission_mode,
# tool_name, tool_use_id, notification_type, agent_type, agent_id,
# subagent_type, task_id, stop_hook_active, is_interrupt, duration_ms —
# the latter two carried by PostToolUseFailure and needed to tell an Esc
# interrupt apart from an ordinary tool error — and background_tasks_count,
# the LENGTH of Stop's background_tasks array: whether async work is in
# flight at turn end, without logging the tasks themselves, whose
# descriptors can carry command text) plus `keys`, the payload's own
# top-level field names — which answers "what fields does this event carry
# and what are they called" without logging any of their values.
#
# Since quick task 260817-i5n (case 17 rev.3: is a background AGENT
# distinguishable from a background SHELL at turn end), the first five
# entries of Stop/SubagentStop's background_tasks array are also sampled by
# SHAPE under background_tasks_shape — never by full value. Two independent
# guards gate what survives: a closed field-NAME allowlist of exactly
# fourteen names (id, task_id, agent_id, shell_id, type, kind, task_type,
# agent_type, subagent_type, status, state, source, mode, tool_name), and a
# value-SHAPE regex (`^[A-Za-z0-9_.:-]{1,64}$` for strings; booleans and
# numbers pass as-is) that drops any value carrying whitespace, a quote, a
# slash or more than 64 characters even when its name is allowlisted. A
# dropped value's NAME still appears in that entry's own `keys` list, so an
# undocumented content-bearing field is discoverable by name without its
# content ever landing on the shared mount. command/cmd/args/argv/prompt/
# description/env/output/result/stdout/stderr/message/last_assistant_message
# are deliberately excluded from the name allowlist — the two guards
# together mean a field named innocuously still can't leak a command-shaped
# value, and a field literally named `command` can't leak even one token.
#
# `message` (Notification's payload field) is captured by default but
# truncated to 200 characters, since its exact content shape was never
# confirmed against live docs before this instrument was written and it may
# echo back contentful text depending on notification type. The full,
# untruncated value is only ever written under GREENLIGHT_LOG_RAW=1 (see
# escape hatch below).
#
# Deliberately NOT captured by value: tool_input, tool_response/tool_output,
# prompt, last_assistant_message, or any other content-bearing field. These
# can carry secrets (Bash commands, file contents) from real sessions onto
# the shared ~/.claude bind mount. Their presence/spelling is still visible
# via `keys`.
#
# Escape hatch: set GREENLIGHT_LOG_RAW=1 in the environment to add the
# entire payload under a `raw` key for a deliberately scoped window. Off by
# default.
#
# Size guard: if hook-events.log exceeds 5 MB it is truncated before the
# next append, with a marker line recording that a truncation happened, so
# a reader never mistakes truncation for missing events.
#
# Teardown: `hooks/install.sh --remove-logger` strips every logger entry
# from settings.json and this file can then be deleted from
# ~/.claude/hooks/ — the whole instrument is disposable by design.
set -u

LOG_DIR="$HOME/.claude"
LOG="$LOG_DIR/hook-events.log"
MAX_BYTES=$((5 * 1024 * 1024))
RAW_FLAG="${GREENLIGHT_LOG_RAW:-}"

payload=$(cat)
if [ -z "$payload" ]; then
  exit 0
fi

# Parse stdin only through jq — no payload-derived text is ever interpolated
# into a shell command string or handed to the shell for interpretation.
line=$(jq -c --arg raw_flag "$RAW_FLAG" '
  . as $payload |
  if (.hook_event_name == null) then empty else
  (
    {
      ts: (now | todate),
      ts_ms: (now * 1000 | floor),
      event: .hook_event_name,
      session_id,
      cwd,
      keys: (keys),
      source,
      reason,
      trigger,
      matcher,
      permission_mode,
      tool_name,
      tool_use_id,
      notification_type,
      agent_type,
      agent_id,
      subagent_type,
      task_id,
      stop_hook_active,
      is_interrupt,
      duration_ms,
      background_tasks_count: (if (.background_tasks | type) == "array" then (.background_tasks | length) else null end),
      background_tasks_shape: (
        if (.background_tasks | type) == "array" then
          [ .background_tasks[0:5][]
            | (if type == "object" then . else {} end)
            | {keys: keys}
              + with_entries(select(
                  (.key | IN("id","task_id","agent_id","shell_id","type","kind","task_type","agent_type","subagent_type","status","state","source","mode","tool_name"))
                  and (
                    ((.value | type) == "boolean")
                    or ((.value | type) == "number")
                    or (((.value | type) == "string") and (.value | test("^[A-Za-z0-9_.:-]{1,64}$")))
                  )
                ))
          ]
        else null end
      )
    }
    + (
        if .message == null then {}
        elif ($raw_flag == "1") then {message: .message}
        elif (.message | type) == "string" and (.message | length) > 200 then
          {message: (.message[0:200] + "…[truncated]")}
        else {message: .message}
        end
      )
    + (if $raw_flag == "1" then {raw: $payload} else {} end)
    | with_entries(select(.value != null))
  )
  end
' <<<"$payload" 2>/dev/null)
jq_status=$?

if [ "$jq_status" -ne 0 ]; then
  exit 0
fi

if [ -z "$line" ]; then
  exit 0
fi

mkdir -p "$LOG_DIR"

# Size guard: truncate before the next append if the log has grown past the
# threshold, leaving a marker line so truncation is never read as missing
# events. The check-truncate-append sequence is serialized with a short-wait
# flock on a lock file derived from $LOG so two invocations racing past the
# threshold can't both truncate and wipe each other's lines. If the lock
# can't be acquired quickly, we deliberately skip the truncation this round
# (rather than block) and still append — never hang a Claude Code session
# over a diagnostic log.
(
  if flock -w 0.5 9 2>/dev/null; then
    if [ -f "$LOG" ]; then
      log_size=$(stat -c%s "$LOG" 2>/dev/null)
      if [ -z "$log_size" ]; then
        log_size=0
      fi
      if [ "$log_size" -gt "$MAX_BYTES" ]; then
        : > "$LOG"
        marker=$(jq -cn --arg ts "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" '
          {ts: $ts, event: "_truncated", note: "hook-events.log exceeded 5MB and was truncated before this line"}
        ' 2>/dev/null)
        if [ -n "$marker" ]; then
          printf '%s\n' "$marker" >> "$LOG"
        fi
      fi
    fi
  fi
  # $line is guaranteed non-empty here (see the exit-if-empty check above).
  printf '%s\n' "$line" >> "$LOG"
) 9>"$LOG.lock" 2>/dev/null || printf '%s\n' "$line" >> "$LOG"

exit 0
