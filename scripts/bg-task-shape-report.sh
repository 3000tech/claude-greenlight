#!/usr/bin/env bash
# Privacy-safe aggregator over hook-events.log's background_tasks_shape
# samples (added by hooks/event-logger.sh, quick task 260817-i5n, case #17
# rev.3: is a background AGENT distinguishable from a background SHELL at
# turn end?).
#
# Reads only what event-logger.sh already allowed onto the shared mount —
# descriptor field NAMES, a closed allowlist of enum/id-shaped VALUES, and
# the agent_id/agent_type already captured by value on SubagentStart/
# SubagentStop. Prints:
#   - a header count of Stop/SubagentStop lines seen and how many carried a
#     non-empty background_tasks_shape sample
#   - the distinct descriptor field-name shapes observed, with counts
#   - per allowlisted field, the distinct values observed, with counts
#   - the correlation join: descriptor ids that also appear as a known
#     agent_id, printed with that line's agent_type — the second evidence
#     path for agent-vs-shell when the descriptor itself carries no
#     discriminator
#
# This script never opens, reads or parses a session jsonl transcript, and
# never re-reads raw hook payloads — only the already-sampled log line
# fields. It never writes to the log it reads and never modifies anything
# under ~/.claude.
#
# Usage: scripts/bg-task-shape-report.sh [--self-test] [log-path]
#   --self-test   build a small synthetic log in a temp dir, run the report
#                 over it, assert the expected sections appear, print
#                 "self-test OK", exit 0. Touches nothing under ~/.claude.
#   log-path      hook-events.log to read (default:
#                 $HOME/.claude/hook-events.log). An absent log, or one
#                 with zero sampled descriptors, is a legitimate state —
#                 the script prints an explicit line saying so and exits 0.
#
# Requires: jq.
set -euo pipefail

DEFAULT_LOG="$HOME/.claude/hook-events.log"

# ---------------------------------------------------------------------------
# Core report, callable both from normal mode and from --self-test.
# Reads $1 (a log path); prints the report to stdout; never writes anywhere.
# ---------------------------------------------------------------------------
run_report() {
  local log="$1"

  if [ ! -f "$log" ]; then
    echo "== background_tasks descriptor shape report =="
    echo "No log found at $log — nothing to report yet."
    echo "Samples only appear on a Stop/SubagentStop occurring after the sampler was deployed."
    echo "Re-run: bash scripts/bg-task-shape-report.sh"
    return 0
  fi

  # Tolerate malformed/partial lines (matches the reader convention
  # elsewhere in this repo) — fromjson? drops any line that fails to parse
  # instead of aborting the whole read.
  local valid
  valid=$(jq -Rc 'fromjson? // empty' "$log")

  if [ -z "$valid" ]; then
    echo "== background_tasks descriptor shape report =="
    echo "Log at $log has no well-formed lines yet — nothing to report."
    echo "Re-run: bash scripts/bg-task-shape-report.sh"
    return 0
  fi

  local agg
  agg=$(jq -cs '
    def shape_entries: .[] | select(.event=="Stop" or .event=="SubagentStop") | (.background_tasks_shape // [])[];
    {
      stop_lines: (map(select(.event=="Stop")) | length),
      subagent_stop_lines: (map(select(.event=="SubagentStop")) | length),
      stop_with_shape: (map(select(.event=="Stop" and ((.background_tasks_shape // []) | length) > 0)) | length),
      subagent_stop_with_shape: (map(select(.event=="SubagentStop" and ((.background_tasks_shape // []) | length) > 0)) | length),
      total_shape_entries: ([shape_entries] | length),
      keyshape_counts: (
        [shape_entries | (.keys // []) | sort | join(",")]
        | group_by(.) | map({shape: .[0], count: length}) | sort_by(-.count, .shape)
      ),
      field_values: (
        reduce (shape_entries | to_entries[] | select(.key != "keys")) as $kv
          ({}; .[$kv.key] += [$kv.value])
        | to_entries
        | map({field: .key, values: (.value | group_by(.) | map({value: .[0], count: length}) | sort_by(-.count, (.value | tostring)))})
        | sort_by(.field)
      ),
      joins: (
        ( [.[] | select(.event=="SubagentStart" or .event=="SubagentStop") | select(.agent_id != null) | {agent_id, agent_type: (.agent_type // "")}] | unique_by(.agent_id) ) as $agents
        | ([shape_entries | ((.id // .task_id // .agent_id // .shell_id) // empty)] | unique) as $descriptor_ids
        | [$descriptor_ids[] as $did | $agents[] | select(.agent_id == $did) | {descriptor_id: $did, agent_type}]
        | sort_by(.descriptor_id)
      )
    }
  ' <<<"$valid")

  local total_shape_entries
  total_shape_entries=$(jq -r '.total_shape_entries' <<<"$agg")

  echo "== background_tasks descriptor shape report =="
  echo "Log: $log"
  local stop_lines subagent_stop_lines stop_with_shape subagent_stop_with_shape
  stop_lines=$(jq -r '.stop_lines' <<<"$agg")
  subagent_stop_lines=$(jq -r '.subagent_stop_lines' <<<"$agg")
  stop_with_shape=$(jq -r '.stop_with_shape' <<<"$agg")
  subagent_stop_with_shape=$(jq -r '.subagent_stop_with_shape' <<<"$agg")
  echo "Stop lines: $stop_lines ($stop_with_shape carried a non-empty background_tasks_shape sample)"
  echo "SubagentStop lines: $subagent_stop_lines ($subagent_stop_with_shape carried a non-empty background_tasks_shape sample)"
  echo

  if [ "$total_shape_entries" -eq 0 ]; then
    echo "No background_tasks descriptor has been sampled yet (0 entries across all Stop/SubagentStop lines)."
    echo "Samples only appear on a Stop/SubagentStop occurring after the sampler was deployed — trigger one (e.g. a turn ending with a background shell or agent in flight) and re-run:"
    echo "  bash scripts/bg-task-shape-report.sh"
    return 0
  fi

  echo "-- Distinct descriptor field-name shapes ($total_shape_entries sampled entries total) --"
  jq -r '.keyshape_counts[] | "  [\(.shape)] x\(.count)"' <<<"$agg"
  echo

  echo "-- Observed values by allowlisted field --"
  jq -r '.field_values[] | "  \(.field): " + ([.values[] | "\(.value) x\(.count)"] | join(", "))' <<<"$agg"
  echo

  echo "-- Descriptor id -> known agent_id join (SubagentStart/SubagentStop) --"
  local join_count
  join_count=$(jq -r '.joins | length' <<<"$agg")
  if [ "$join_count" -eq 0 ]; then
    echo "  No descriptor id matched a known agent_id yet."
  else
    jq -r '.joins[] | "  \(.descriptor_id) -> agent_type=\(.agent_type)"' <<<"$agg"
  fi
}

# ---------------------------------------------------------------------------
# --self-test: synthetic log covering a shell-shaped entry, an agent-shaped
# entry, a descriptor id that joins to a SubagentStart agent_id, and one
# that does not. Never touches ~/.claude.
# ---------------------------------------------------------------------------
run_self_test() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' RETURN

  local log="$tmpdir/hook-events.log"
  cat >"$log" <<'EOF'
{"event":"Stop","background_tasks_shape":[{"keys":["id","status","type"],"id":"shell-1","type":"shell","status":"running"}]}
{"event":"Stop","background_tasks_shape":[{"keys":["agent_type","id","status","type"],"id":"agent-2","type":"agent","agent_type":"gsd-planner","status":"running"}]}
{"event":"SubagentStop","background_tasks_shape":[]}
{"event":"SubagentStart","agent_type":"gsd-planner","agent_id":"agent-2"}
{"event":"SubagentStop","agent_type":"gsd-planner","agent_id":"agent-2"}
{"event":"PreToolUse"}
this is not valid json and must be tolerated, not fatal
EOF

  local output
  output=$(run_report "$log")

  local failed=0
  for needle in \
    "Stop lines: 2" \
    "SubagentStop lines: 2" \
    "id,status,type" \
    "agent_type,id,status,type" \
    "shell x1" \
    "agent x1" \
    "gsd-planner x1" \
    "agent-2 -> agent_type=gsd-planner"
  do
    if ! grep -qF -- "$needle" <<<"$output"; then
      echo "SELF-TEST FAILED: expected to find '$needle' in report output" >&2
      echo "--- full output ---" >&2
      echo "$output" >&2
      failed=1
    fi
  done
  # shell-1 must NOT appear in the join section (it has no matching agent_id).
  if grep -qF -- "shell-1 ->" <<<"$output"; then
    echo "SELF-TEST FAILED: shell-1 must not join to any agent_id" >&2
    failed=1
  fi

  if [ "$failed" -ne 0 ]; then
    return 1
  fi

  # Also exercise the no-samples-yet path on an empty log.
  local empty_log="$tmpdir/empty.log"
  : >"$empty_log"
  local empty_output
  empty_output=$(run_report "$empty_log")
  if ! grep -qF -- "nothing to report" <<<"$empty_output"; then
    echo "SELF-TEST FAILED: empty log did not produce the no-samples-yet message" >&2
    echo "$empty_output" >&2
    return 1
  fi

  # And the absent-file path.
  local missing_output
  missing_output=$(run_report "$tmpdir/does-not-exist.log")
  if ! grep -qF -- "nothing to report" <<<"$missing_output"; then
    echo "SELF-TEST FAILED: missing log did not produce the nothing-to-report message" >&2
    echo "$missing_output" >&2
    return 1
  fi

  echo "self-test OK"
  return 0
}

# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  run_self_test
  exit $?
fi

LOG_PATH="${1:-$DEFAULT_LOG}"
run_report "$LOG_PATH"
exit 0
