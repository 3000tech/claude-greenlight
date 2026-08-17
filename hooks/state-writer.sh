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
# background_tasks_count (a count, not the task descriptors themselves). A
# background task descriptor's `type` and `status` fields are read inside
# the Stop-branch jq expression (case 17 rev.3) to resolve the in-flight
# all-subagent check, but neither value — nor any other descriptor field —
# is ever captured into the record; only the boolean outcome of the check
# feeds the `state` value already covered above.
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
#
# Event-to-state mapping (D-08 verdict, TEST-MATRIX.md "Verdict to extract"):
#   UserPromptSubmit                         -> working
#   PostToolUse / PostToolUseFailure /
#     PostToolBatch (heartbeats)             -> working
#   PermissionRequest / Notification         -> needs_input
#   SessionStart (source != compact)         -> idle
#   SessionStart (source == compact)         -> no write (case 11 — a
#     mid-session /compact re-fires SessionStart on the SAME session_id;
#     writing idle here would blank a live working state and read
#     downstream as a turn that ended)
#   Stop                                     -> working, when every
#     in-flight background task's `type` is "subagent"; waiting otherwise
#     (case 17 rev.3, TEST-MATRIX.md section 4 — D-03 narrowed: an agent
#     still running is guaranteed to re-invoke this session at its own
#     completion, so the turn owes the user nothing yet and must not page
#     them. A background shell, an unrecognised or missing `type`, or no
#     in-flight task at all keeps the rev.2 behaviour — waiting,
#     notifying immediately. background_tasks_count still rides along in
#     the record either way, purely as badge data, never the sole verdict
#     input; the in-flight filter always runs before the type check)
#   SubagentStop                             -> no write, deliberate no-op
#     (case 12 — can arrive AFTER the parent's Stop; writing here would move
#     the verdict after the turn already ended)
#   SessionEnd                               -> removes the state file,
#     unconditionally, for every `reason` value (prunes /resume picker and
#     /clear orphans, cases 10/11/14), AND drops a zero-byte
#     "<session_id>.ended" tombstone marker (D-06) — monitor.py's
#     scan_state_files() reads it to suppress the legacy_origin bridge for
#     this session, so a cleanly-ended session's still-fresh jsonl can
#     never resurrect it as a ghost row, even across a monitor restart
#   any other/unregistered event name        -> no write
#
# `idle` is an internal writer state with no separate rendering: the engine
# maps it to the same WAITING verdict as `waiting` and `needs_input`, per
# D-07 and D-01 (zero UX change during Phase 2's shadow mode).
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

# SessionEnd removes the state file unconditionally for every `reason`
# value — this is the ONE branch that never reaches the record builder
# below. Handled first, ahead of the state-resolution case, since it has no
# `state` to resolve at all. The tombstone write sits AFTER this point
# deliberately: $sid has already passed the session_id allowlist guard
# above, so the tombstone path is built from the exact same validated
# value as the state-file path — never a second, weaker path build.
if [ "$event" = "SessionEnd" ]; then
  rm -f "$state_dir/$sid.json"
  : > "$state_dir/$sid.ended"
  exit 0
fi

# Resolve background_tasks_count once, from the deny-list rule (RESEARCH
# assumption A2): any entry whose status is NOT "completed" and NOT
# "failed" still counts as in-flight, including an entry with no `status`
# key at all. This single value feeds both the Stop gate below and the
# record's background_tasks_count field, so the number that gates the
# verdict and the number the future unified badge reads (D-09) can never
# disagree. An absent/non-array background_tasks yields 0.
background_tasks_count=$(jq '
  [.background_tasks[]?
    | select((.status // "running") != "completed" and (.status // "running") != "failed")]
  | length
' <<<"$payload" 2>/dev/null)
case "$background_tasks_count" in
  ''|*[!0-9]*) background_tasks_count=0 ;;
esac

# Resolve bg_agents_only (case 17 rev.3): true only when at least one
# background task is in flight AND every in-flight entry's `type` is
# exactly "subagent". Reuses the SAME deny-list clause as
# background_tasks_count above, verbatim, so the in-flight filter always
# runs BEFORE the type check — a long-finished shell from earlier in the
# turn can never permanently suppress this rule. Each entry is normalized
# with `if type == "object" then . else {} end` before the select, so a
# hostile array holding a bare string or number can never abort jq; each
# survivor's `type` is projected through `((.type // "") | tostring)` so a
# missing or non-string type can never accidentally equal "subagent". The
# empty-array vacuous-`all()` trap is closed by the explicit
# `($inflight | length) > 0` guard. Fail-safe direction: unknown evidence
# always resolves to false (never suppresses a notification), never true.
bg_agents_only=$(jq -r '
  [.background_tasks[]?
    | (if type == "object" then . else {} end)
    | select((.status // "running") != "completed" and (.status // "running") != "failed")
    | ((.type // "") | tostring)]
  as $inflight
  | if ($inflight | length) > 0 and ($inflight | all(. == "subagent")) then "true" else "false" end
' <<<"$payload" 2>/dev/null)
case "$bg_agents_only" in
  true) : ;;
  *) bg_agents_only=false ;;
esac

# Event-to-state mapping — the full D-08 verdict set (see header comment).
# Every branch either resolves a `state` value for the record builder below,
# or exits 0 without writing. No branch ever reads background_tasks
# descriptors past the count already resolved above.
case "$event" in
  UserPromptSubmit)
    state="working"
    ;;
  PostToolUse|PostToolUseFailure|PostToolBatch)
    state="working"
    ;;
  PermissionRequest|Notification)
    state="needs_input"
    ;;
  SessionStart)
    source_val=$(jq -r '.source // empty' <<<"$payload" 2>/dev/null)
    if [ "$source_val" = "compact" ]; then
      # A mid-session /compact re-fires SessionStart on the SAME
      # session_id (TEST-MATRIX case 11) — writing here would blank a
      # live `working` state and read downstream as a turn that ended.
      exit 0
    fi
    state="idle"
    ;;
  Stop)
    # D-03 (TEST-MATRIX case 17 rev.3): waiting is the default, promoted to
    # working only when bg_agents_only is true — every in-flight background
    # task at this Stop is confirmed type "subagent", which re-invokes this
    # session on its own completion, so the session owes the user nothing
    # yet. The in-flight filter (resolved above) always runs before the
    # type check, so a finished shell from earlier in the turn can never
    # pin this to waiting forever, nor can it ever count toward "all
    # subagent". Any other in-flight evidence — a shell, a missing type, an
    # unrecognised type, a non-string type, or no in-flight task at all —
    # keeps waiting unchanged, exactly rev.2's behaviour.
    # background_tasks_count still rides into the record either way, purely
    # as badge data (D-09) — it never gates this verdict on its own.
    state="waiting"
    if [ "$bg_agents_only" = "true" ]; then
      state="working"
    fi
    ;;
  SubagentStop)
    # Deliberate no-op: SubagentStop can arrive AFTER the parent's Stop
    # (TEST-MATRIX case 12) — writing here would move the verdict after
    # the turn already ended, the historical premature-transition bug.
    exit 0
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
  --argjson background_tasks_count "$background_tasks_count" \
  '{
    state: $state,
    ts: $ts,
    ts_ms: $ts_ms,
    cwd: ($payload.cwd // ""),
    hostname: $hostname,
    last_event: $last_event,
    background_tasks_count: $background_tasks_count
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
