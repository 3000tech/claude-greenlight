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
#
# Requires: jq.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
SNIPPET="$HERE/settings-snippet.json"

mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/auq-locks" "$CLAUDE_DIR/working-locks"
install -m 0755 "$HERE/auq-lock.sh" "$CLAUDE_DIR/hooks/auq-lock.sh"
echo "installed: $CLAUDE_DIR/hooks/auq-lock.sh"
install -m 0755 "$HERE/working-lock.sh" "$CLAUDE_DIR/hooks/working-lock.sh"
echo "installed: $CLAUDE_DIR/hooks/working-lock.sh"

if [ ! -f "$SETTINGS" ]; then
  cp "$SNIPPET" "$SETTINGS"
  echo "created: $SETTINGS"
  exit 0
fi

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
