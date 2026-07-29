#!/usr/bin/env bash
# Phase 2 state writer (claude-greenlight hook-driven refactor).
# Authoritative per-session state source: on every registered Claude Code
# hook event, atomically (re)writes ~/.claude/monitor-state/<session_id>.json
# — one small JSON verdict record per session — which monitor.py's
# scan_state_files() reads as the new engine's primary input, alongside
# (never replacing, during Phase 2's shadow mode) the existing jsonl-based
# scan(). See hooks/state-writer-events.json for the registered event set
# and .planning/phases/02-state-writer-shadow-mode/ for the design.
#
# Never emits decision-control stdout and never fails a session: every code
# path below ends in `exit 0`, even a missing/empty/partial payload,
# non-JSON stdin, a payload missing session_id or hook_event_name, or a jq
# parse failure. This matters MORE here than for the Phase 1 diagnostic
# logger: this script is registered on PermissionRequest, PostToolBatch and
# Stop, all of which can alter Claude Code's control flow via a non-zero
# exit code or a decision JSON on stdout — this script writes ONLY to the
# state file, nothing to stdout, ever.
#
# Captured by value: scalar verdict fields only — state, ts, ts_ms, cwd,
# hostname (container identity for the cwd-collision problem, captured as
# data only, never displayed — see D-05), last_event, and
# background_tasks_count (a count, not the task descriptors themselves).
#
# Deliberately NOT captured: prompt, tool_input, tool_response, message
# bodies, background_tasks descriptors, command text, or any other
# content-bearing payload field. The state file lives on the shared
# ~/.claude bind mount and must stay a scalar-only verdict record, never a
# second transcript (same privacy discipline hooks/event-logger.sh already
# established for the Phase 1 diagnostic log).
#
# session_id is validated against ^[A-Za-z0-9._-]+$ before it is ever used
# to build a filesystem path (path-traversal guard) — a payload-derived
# string becomes part of a path here, unlike event-logger.sh's append-only
# log.
#
# Teardown: `hooks/install.sh --remove-state-writer` strips every
# state-writer entry from settings.json; ~/.claude/monitor-state/ can then
# be deleted once nothing reads it.
set -u

payload=$(cat)
if [ -z "$payload" ]; then
  exit 0
fi

sid=$(jq -r '.session_id // empty' <<<"$payload" 2>/dev/null)
if [ -z "$sid" ]; then
  exit 0
fi

event=$(jq -r '.hook_event_name // empty' <<<"$payload" 2>/dev/null)
if [ -z "$event" ]; then
  exit 0
fi

# Path-traversal guard: session_id becomes part of a filesystem path below.
# Reject anything that isn't a bare filename-safe token before it is used.
case "$sid" in
  *[!A-Za-z0-9._-]*)
    exit 0
    ;;
esac

state_dir="$HOME/.claude/monitor-state"
mkdir -p "$state_dir"

# Event-to-state mapping — this task maps exactly ONE event (Stop). Every
# other event name exits 0 without writing; the full D-08 mapping (plan
# 02-02) fills in the remaining branches. This is a functionality gap, not
# an architectural one — the write path proven here is the whole point.
case "$event" in
  Stop)
    state="waiting"
    ;;
  *)
    exit 0
    ;;
esac

# Build the full state-file record in a single jq -cn invocation. $payload
# is guaranteed to be a well-formed JSON object at this point — the jq -r
# extractions above would have produced empty output (and already exited)
# on any non-object/non-JSON stdin.
line=$(jq -cn \
  --arg state "$state" \
  --arg ts "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
  --argjson ts_ms "$(($(date +%s%N) / 1000000))" \
  --argjson payload "$payload" \
  --arg hostname "${HOSTNAME:-$(hostname 2>/dev/null || echo unknown)}" \
  --arg last_event "$event" \
  '{
    state: $state,
    ts: $ts,
    ts_ms: $ts_ms,
    cwd: ($payload.cwd // ""),
    hostname: $hostname,
    last_event: $last_event,
    background_tasks_count:
      ([$payload.background_tasks[]?
        | select((.status // "running") != "completed" and (.status // "running") != "failed")]
       | length)
  }' 2>/dev/null)
jq_status=$?

if [ "$jq_status" -ne 0 ] || [ -z "$line" ]; then
  exit 0
fi

# Atomic overwrite: stage in the SAME directory (so the rename stays
# same-filesystem and therefore atomic), then mv over the final path. Never
# redirect straight onto the final path — that truncates it the instant the
# shell opens it for writing, before any content exists (TEST-MATRIX case
# 20 — a hook killed mid-write must never leave a corrupt file behind).
tmp="$state_dir/$sid.json.tmp.$$"
printf '%s\n' "$line" > "$tmp" && mv -f "$tmp" "$state_dir/$sid.json"

exit 0
