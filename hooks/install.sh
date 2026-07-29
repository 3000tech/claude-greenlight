#!/usr/bin/env bash
# Install the claude-monitor hooks into ~/.claude/ and merge the matching
# entries into ~/.claude/settings.json. Idempotent: re-running won't duplicate
# anything — AskUserQuestion entries are deduped on matcher, the working-lock
# entries on their command string referencing working-lock.sh.
#
#   auq-lock.sh      PreToolUse/PostToolUse/Notification/Stop → WAITING during
#                    an AskUserQuestion modal OR a tool-permission prompt
#   working-lock.sh  UserPromptSubmit/PreToolUse/Stop → WORKING during the
#                    prompt→flush gap AND while any tool is in flight
#   event-logger.sh  Phase 1 diagnostic instrument (see hooks/hook-events.json)
#                    → appends one JSONL line per hook event to
#                    ~/.claude/hook-events.log. Registered on every event name
#                    listed in hooks/hook-events.json — 24 names, the
#                    RESEARCH.md baseline (2026-07-28), used because a live
#                    fetch of code.claude.com/docs/en/hooks was not available
#                    from this execution session. Re-check that list against
#                    the live docs before treating "no line for event X" as a
#                    confirmed negative finding rather than a catalog gap.
#                    Registering on an event name a given Claude Code build
#                    does not know is expected to be inert — not a defect.
#                    Diagnostic-only, disposable: run this script with
#                    `--remove-logger` to strip every logger entry from
#                    settings.json (and then delete
#                    ~/.claude/hooks/event-logger.sh / hook-events.log
#                    yourself) once the Phase 1 UAT concludes.
#   state-writer.sh  Phase 2 authoritative per-session state writer (see
#                    hooks/state-writer-events.json) → atomically (re)writes
#                    ~/.claude/monitor-state/<session_id>.json on every event
#                    name listed in hooks/state-writer-events.json (the D-08
#                    verdict event set). Registered on
#                    `--remove-state-writer` to strip its entries from
#                    settings.json.
#
# Usage: install.sh [--remove-logger|--remove-state-writer]
#
# Requires: jq.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
SNIPPET="$HERE/settings-snippet.json"
EVENTS_FILE="$HERE/hook-events.json"
LOGGER_CMD='bash "$HOME/.claude/hooks/event-logger.sh"'
STATE_WRITER_EVENTS_FILE="$HERE/state-writer-events.json"
STATE_WRITER_CMD='bash "$HOME/.claude/hooks/state-writer.sh"'

mode="${1:-install}"

if [ $# -gt 0 ] && [ "$1" != "--remove-logger" ] && [ "$1" != "--remove-state-writer" ]; then
  echo "unknown argument: $1 (expected: --remove-logger or --remove-state-writer)" >&2
  exit 1
fi

if [ "$mode" = "--remove-logger" ]; then
  if [ ! -f "$SETTINGS" ]; then
    echo "nothing to do: $SETTINGS does not exist"
    exit 0
  fi
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  jq '
    def has_logger: [.hooks[]?.command] | any(. // "" | test("event-logger\\.sh"));
    .hooks = ((.hooks // {}) | with_entries(.value |= map(select(has_logger | not))))
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "removed: event-logger.sh entries from $SETTINGS (backup at $SETTINGS.bak.*)"
  exit 0
fi

if [ "$mode" = "--remove-state-writer" ]; then
  if [ ! -f "$SETTINGS" ]; then
    echo "nothing to do: $SETTINGS does not exist"
    exit 0
  fi
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  jq '
    def has_state_writer: [.hooks[]?.command] | any(. // "" | test("state-writer\\.sh"));
    .hooks = ((.hooks // {}) | with_entries(.value |= map(select(has_state_writer | not))))
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "removed: state-writer.sh entries from $SETTINGS (backup at $SETTINGS.bak.*)"
  exit 0
fi

mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/auq-locks" "$CLAUDE_DIR/working-locks" "$CLAUDE_DIR/monitor-state"
install -m 0755 "$HERE/auq-lock.sh" "$CLAUDE_DIR/hooks/auq-lock.sh"
echo "installed: $CLAUDE_DIR/hooks/auq-lock.sh"
install -m 0755 "$HERE/working-lock.sh" "$CLAUDE_DIR/hooks/working-lock.sh"
echo "installed: $CLAUDE_DIR/hooks/working-lock.sh"
install -m 0755 "$HERE/event-logger.sh" "$CLAUDE_DIR/hooks/event-logger.sh"
echo "installed: $CLAUDE_DIR/hooks/event-logger.sh"
install -m 0755 "$HERE/state-writer.sh" "$CLAUDE_DIR/hooks/state-writer.sh"
echo "installed: $CLAUDE_DIR/hooks/state-writer.sh"

if [ ! -f "$SETTINGS" ]; then
  cp "$SNIPPET" "$SETTINGS"
  echo "created: $SETTINGS"
else
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  # Drop any entries we may have added on a previous install, then append the
  # canonical set from the snippet. AskUserQuestion PreToolUse/PostToolUse entries
  # are matched on `.matcher`; the matcher-less lock entries (Notification/Stop/
  # UserPromptSubmit) are matched on a hook command referencing the lock script,
  # so re-running never duplicates them.
  jq --slurpfile snip "$SNIPPET" '
    def has_cmd($re): [.hooks[]?.command] | any(. // "" | test($re));
    def drop_working: map(select(has_cmd("working-lock\\.sh") | not));
    def drop_auq:     map(select(has_cmd("auq-lock\\.sh")     | not));
    .hooks.PreToolUse       = ((.hooks.PreToolUse       // []) | map(select(.matcher != "AskUserQuestion")) | drop_working) + ($snip[0].hooks.PreToolUse       // []) |
    .hooks.PostToolUse      = ((.hooks.PostToolUse      // []) | map(select(.matcher != "AskUserQuestion"))) + ($snip[0].hooks.PostToolUse      // []) |
    .hooks.Notification     = ((.hooks.Notification     // []) | drop_auq)                                  + ($snip[0].hooks.Notification     // []) |
    .hooks.UserPromptSubmit = ((.hooks.UserPromptSubmit // []) | drop_working)                              + ($snip[0].hooks.UserPromptSubmit // []) |
    .hooks.Stop             = ((.hooks.Stop             // []) | drop_working | drop_auq)                   + ($snip[0].hooks.Stop             // [])
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "merged into: $SETTINGS (backup at $SETTINGS.bak.*)"
fi

# Register event-logger.sh on every event name in hook-events.json — the
# canonical registration list (see header comment above). Kept as a separate
# jq pass from the lock merge above so the lock merge's behavior stays
# byte-for-byte what it was before this instrument existed.
jq --argjson events "$(cat "$EVENTS_FILE")" --arg cmd "$LOGGER_CMD" '
  def has_logger: [.hooks[]?.command] | any(. // "" | test("event-logger\\.sh"));
  reduce $events[] as $event (.;
    .hooks[$event] = ((.hooks[$event] // []) | map(select(has_logger | not))) + [{"hooks": [{"type": "command", "command": $cmd, "timeout": 2}]}]
  )
' "$SETTINGS" > "$SETTINGS.tmp"
python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
mv "$SETTINGS.tmp" "$SETTINGS"
echo "registered: event-logger.sh on $(jq 'length' "$EVENTS_FILE") event(s) in $SETTINGS"

# Register state-writer.sh on every event name in state-writer-events.json —
# the D-08 verdict event set (see header comment above). Kept as its own jq
# pass, separate from both the lock merge and the logger registration pass
# above, so neither of those keeps behaving exactly as it did before the
# state writer existed.
jq --argjson events "$(cat "$STATE_WRITER_EVENTS_FILE")" --arg cmd "$STATE_WRITER_CMD" '
  def has_state_writer: [.hooks[]?.command] | any(. // "" | test("state-writer\\.sh"));
  reduce $events[] as $event (.;
    .hooks[$event] = ((.hooks[$event] // []) | map(select(has_state_writer | not))) + [{"hooks": [{"type": "command", "command": $cmd, "timeout": 2}]}]
  )
' "$SETTINGS" > "$SETTINGS.tmp"
python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
mv "$SETTINGS.tmp" "$SETTINGS"
echo "registered: state-writer.sh on $(jq 'length' "$STATE_WRITER_EVENTS_FILE") event(s) in $SETTINGS"
