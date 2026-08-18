#!/usr/bin/env bash
# Install the claude-monitor hooks into ~/.claude/ and merge the matching
# entries into ~/.claude/settings.json. Idempotent: re-running won't duplicate
# anything — the working-lock entries are deduped on their command string
# referencing working-lock.sh.
#
# Shipped hook set (Phase 3 flip — the AskUserQuestion lock below is retired,
# not shipped by default; see its own paragraph):
#   working-lock.sh  UserPromptSubmit/PreToolUse/Stop → WORKING during the
#                    prompt→flush gap AND while any tool is in flight.
#                    Session ids are validated against the same filename-safe
#                    allowlist state-writer.sh uses before either branch runs.
#   event-logger.sh  Phase 1 diagnostic instrument (see hooks/hook-events.json)
#                    → appends one JSONL line per hook event to
#                    ~/.claude/hook-events.log. Registered on every event name
#                    listed in hooks/hook-events.json — 22 names, the
#                    RESEARCH.md baseline (2026-07-28) minus WorktreeCreate/
#                    WorktreeRemove (removed 2026-08-18, quick-260818-ejg).
#                    Re-check that list against the live docs before treating
#                    "no line for event X" as a confirmed negative finding
#                    rather than a catalog gap. Registering on an event name a
#                    given Claude Code build does not know is expected to be
#                    inert — not a defect.
#
#                    WorktreeCreate/WorktreeRemove are DELEGATION hooks, not
#                    notification hooks: when any hook is configured on them,
#                    Claude Code stops running `git worktree add`/`remove`
#                    itself and expects the configured hook to create/remove
#                    the worktree and print its path on stdout. A passive
#                    logger prints nothing, so every worktree operation failed
#                    with `WorktreeCreate hook failed` — and because the
#                    delegation contract breaks before dispatch, no
#                    `WorktreeCreate` line ever reached hook-events.log either,
#                    so the logger was pure cost with zero diagnostic value on
#                    these two events. This file is the place that ban is
#                    documented because hook-events.json is strict JSON with
#                    no comment syntax. The installer now refuses to register
#                    on either event (see DELEGATION_EVENTS guard below) and
#                    prunes stale registrations left by an earlier install
#                    that ran before this fix. `--remove-logger`'s sweep below
#                    is generic and already removes these too on demand; the
#                    new default-path prune pass exists because the DEFAULT
#                    install path previously had no removal step at all.
#                    Diagnostic-only, disposable: run this script with
#                    `--remove-logger` to strip every logger entry from
#                    settings.json (and then delete
#                    ~/.claude/hooks/event-logger.sh / hook-events.log
#                    yourself) once the Phase 1 UAT concludes.
#   state-writer.sh  Phase 2/3 authoritative per-session state writer (see
#                    hooks/state-writer-events.json) → atomically (re)writes
#                    ~/.claude/monitor-state/<session_id>.json on every event
#                    name listed in hooks/state-writer-events.json (the D-08
#                    verdict event set, badge-only turn-end per D-03).
#                    Registered on install; `--remove-state-writer` strips its
#                    entries from settings.json.
#
# Retired (D-04): auq-lock.sh — this default install path no longer installs
# or registers it, and no longer creates its lock directory. An existing
# install that already has it registered can strip it with
# `--remove-auq-lock` (see below); the script itself is deleted from this
# repository (nothing installs it any more). The live parity confirmation
# that gates removing monitor.py's own auq-lock READ (scan()'s auq_locked
# block and the AUQ_LOCK_DIR constant) lives in the 03-UAT.md runbook, not
# here — that removal is a separately-gated follow-up, not part of this
# teardown.
#
# Usage: install.sh [--remove-logger|--remove-state-writer|--remove-auq-lock]
#
# Requires: jq, python3 (the two remove modes validate the rewritten
# settings.json through python3 before replacing the original).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
SNIPPET="$HERE/settings-snippet.json"
EVENTS_FILE="$HERE/hook-events.json"
LOGGER_CMD='bash "$HOME/.claude/hooks/event-logger.sh"'
# Delegation hooks: Claude Code expects a hook configured on either of these
# events to create/remove the worktree itself and print its path on stdout.
# A passive logger there breaks `git worktree add`/`remove` outright (see the
# event-logger.sh header paragraph above for the full story). One constant
# feeds both the pre-write guard and the prune pass below, so the banned list
# and the cleaned list can never drift apart.
DELEGATION_EVENTS='["WorktreeCreate","WorktreeRemove"]'
STATE_WRITER_EVENTS_FILE="$HERE/state-writer-events.json"
STATE_WRITER_CMD='bash "$HOME/.claude/hooks/state-writer.sh"'

mode="${1:-install}"

case "${1:-}" in
  ""|--remove-logger|--remove-state-writer|--remove-auq-lock) ;;
  *)
    echo "unknown argument: $1 (expected: --remove-logger, --remove-state-writer or --remove-auq-lock)" >&2
    exit 1
    ;;
esac

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

if [ "$mode" = "--remove-auq-lock" ]; then
  if [ ! -f "$SETTINGS" ]; then
    echo "nothing to do: $SETTINGS does not exist"
    exit 0
  fi
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  # The pre-flip Stop entry co-located auq-lock.sh's clear command alongside
  # working-lock.sh's clear command in the SAME entry object (one shared
  # "hooks" array), so filtering must strip the matching COMMAND, not the
  # whole entry — an entry-level filter would also delete the still-live
  # working-lock.sh clear sitting next to it. An entry is dropped only once
  # its own command list is left empty (e.g. the PostToolUse/Notification
  # entries, which existed solely for auq-lock.sh).
  jq '
    def is_auq_lock: (.command // "" | test("auq-lock\\.sh"));
    .hooks = ((.hooks // {}) | with_entries(
      .value |= (
        map(.hooks |= (map(select(is_auq_lock | not))))
        | map(select((.hooks // []) | length > 0))
      )
    ))
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "removed: auq-lock.sh entries from $SETTINGS (backup at $SETTINGS.bak.*)"
  exit 0
fi

# Guard: refuse to proceed if hook-events.json has re-acquired a delegation
# event. Runs before any file is copied or created, so a tripped guard leaves
# the machine untouched — no settings.json, no ~/.claude/hooks/ directory.
if ! jq -e --argjson bad "$DELEGATION_EVENTS" 'any(.[]; . as $e | $bad | index($e) != null) | not' "$EVENTS_FILE" >/dev/null; then
  echo "error: $EVENTS_FILE lists a delegation event (WorktreeCreate/WorktreeRemove)." >&2
  echo "Claude Code expects a hook configured on either of these events to create or" >&2
  echo "remove the worktree itself and print its path on stdout. A passive logger" >&2
  echo "there breaks every 'git worktree add'/'remove' with a 'hook failed' error." >&2
  echo "Remove both names from hook-events.json before re-running this installer." >&2
  exit 1
fi

mkdir -p "$CLAUDE_DIR/hooks" "$CLAUDE_DIR/working-locks" "$CLAUDE_DIR/monitor-state"
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
  # canonical set from the snippet. The matcher-less lock entries (PreToolUse/
  # Stop/UserPromptSubmit) are matched on a hook command referencing the lock
  # script, so re-running never duplicates them. The default path does NOT
  # sweep auq-lock.sh entries anywhere (WR-02 correction, 03-UAT.md Section
  # H): D-04's retirement is gated — a pre-flip install's auq-lock.sh
  # registrations (PreToolUse/PostToolUse/Notification/Stop, wherever they
  # live) must survive a plain `bash hooks/install.sh` untouched until the
  # user has confirmed needs_input parity live and runs the explicit
  # `--remove-auq-lock` teardown. Only `--remove-auq-lock` (below) removes
  # them.
  #
  # drop_working strips at the COMMAND level, not the entry level, for
  # exactly the same co-location reason --remove-auq-lock's is_auq_lock
  # filter does: a pre-flip Stop entry can carry auq-lock.sh's clear
  # command alongside working-lock.sh's clear command in the SAME entry
  # object. An entry-level filter on "has a working-lock.sh command" would
  # drop that whole entry — silently destroying the co-located auq-lock.sh
  # command as a side effect, exactly the untouched-preservation guarantee
  # this merge must not violate. Stripping only the matching command (and
  # dropping an entry only once it has zero commands left) leaves any
  # co-located auq-lock.sh command as its own surviving entry.
  jq --slurpfile snip "$SNIPPET" '
    def is_working_lock_cmd: (.command // "" | test("working-lock\\.sh"));
    def drop_working_cmd:
      map(.hooks |= (map(select(is_working_lock_cmd | not))))
      | map(select((.hooks // []) | length > 0));
    .hooks.PreToolUse       = ((.hooks.PreToolUse       // []) | drop_working_cmd) + ($snip[0].hooks.PreToolUse       // []) |
    .hooks.UserPromptSubmit = ((.hooks.UserPromptSubmit // []) | drop_working_cmd) + ($snip[0].hooks.UserPromptSubmit // []) |
    .hooks.Stop             = ((.hooks.Stop             // []) | drop_working_cmd) + ($snip[0].hooks.Stop             // [])
  ' "$SETTINGS" > "$SETTINGS.tmp"
  python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
  mv "$SETTINGS.tmp" "$SETTINGS"
  echo "merged into: $SETTINGS (backup at $SETTINGS.bak.*)"

  # Informational only (WR-02 correction): if a pre-flip auq-lock.sh
  # registration is still present anywhere in settings.json, point at the
  # gated teardown — never remove it here. Never fails the install.
  auq_count=$(jq '[.hooks | to_entries[] | .value[]? | select(.hooks[]?.command? // "" | test("auq-lock\\.sh"))] | length' "$SETTINGS" 2>/dev/null || echo 0)
  case "$auq_count" in
    ''|*[!0-9]*) auq_count=0 ;;
  esac
  if [ "$auq_count" -gt 0 ]; then
    echo "note: legacy auq-lock entries present ($auq_count) — remove with \`bash hooks/install.sh --remove-auq-lock\` after the 03-UAT Section H parity gate passes"
  fi
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

# Prune stale event-logger.sh registrations from the two delegation events.
# The registration pass above only touches events present in hook-events.json
# today, so dropping a name from that file is invisible to a settings.json
# that already carries the stale attachment from an earlier install — this
# pass is the missing other half. Filters at the individual hooks[].command
# level (not the whole entry object), the same reason --remove-auq-lock and
# drop_working_cmd do: an entry-level filter would delete a co-located
# foreign command (e.g. GSD's gsd-worktree-path-guard.js) sitting in the same
# entry as collateral damage. An entry is dropped only once its own command
# list empties, and the event KEY itself is deleted once its whole array
# empties, so no "WorktreeCreate": [] husk survives that Claude Code could
# still read as "a hook is configured here". A no-op on an already-clean
# settings.json creates and immediately deletes the key, so re-running
# install stays safe.
delegation_prune_count=$(jq --argjson bad "$DELEGATION_EVENTS" '
  [ $bad[] as $event | (.hooks[$event] // [])[]?.hooks[]? | select(.command // "" | test("event-logger\\.sh")) ] | length
' "$SETTINGS" 2>/dev/null || echo 0)
case "$delegation_prune_count" in
  ''|*[!0-9]*) delegation_prune_count=0 ;;
esac
jq --argjson bad "$DELEGATION_EVENTS" '
  def is_logger_cmd: (.command // "" | test("event-logger\\.sh"));
  reduce $bad[] as $event (.;
    .hooks[$event] = ((.hooks[$event] // [])
      | map(.hooks |= (map(select(is_logger_cmd | not))))
      | map(select((.hooks // []) | length > 0)))
    | (if ((.hooks[$event] // []) | length) == 0 then del(.hooks[$event]) else . end)
  )
' "$SETTINGS" > "$SETTINGS.tmp"
python3 -c "import json; json.load(open('$SETTINGS.tmp'))"
mv "$SETTINGS.tmp" "$SETTINGS"
if [ "$delegation_prune_count" -gt 0 ]; then
  echo "pruned: $delegation_prune_count stale event-logger.sh registration(s) from WorktreeCreate/WorktreeRemove in $SETTINGS"
fi

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
