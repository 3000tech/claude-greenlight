---
phase: quick-260818-ejg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - hooks/hook-events.json
  - hooks/install.sh
  - test_event_logger.py
  - .planning/phases/03-flip-to-default-cleanup/03-UAT.md
autonomous: true
requirements: [QUICK-260818-ejg]

estimate:
  tokens: 60000
  raw_tokens: 40000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "REQ-1: `hooks/hook-events.json` is a 22-name array that contains neither `WorktreeCreate` nor `WorktreeRemove`, so a fresh `bash hooks/install.sh` never attaches `event-logger.sh` to either delegation hook and `git worktree add` keeps working on a newly-provisioned machine"
    - "REQ-1: The reason lives in `hooks/install.sh`'s header comment — the file that consumes the list — because `hook-events.json` is strict JSON with no comment syntax; the note states that these two events are DELEGATION hooks (Claude Code expects a hook configured there to create/remove the worktree itself and print its path) and that a passive logger there makes every worktree creation fail with `WorktreeCreate hook failed`"
    - "REQ-1: Re-adding either name to `hook-events.json` makes `bash hooks/install.sh` exit non-zero with an explanatory message BEFORE it writes anything (no `~/.claude/hooks/*` copies, no `settings.json` created) — the ban is machine-enforced, not just documented"
    - "REQ-2: A machine whose `settings.json` still carries a stale `event-logger.sh` attachment on `WorktreeCreate`/`WorktreeRemove` (the MacBook devbox case) has it removed by the next plain `bash hooks/install.sh` run — no flag, no manual edit"
    - "REQ-2: When pruning empties an event's array, the event KEY itself is deleted from `.hooks` rather than left as `[]`, so Claude Code cannot read a leftover empty key as `a hook is configured here` and re-enter delegation mode"
    - "REQ-2: The prune is scoped to greenlight's own logger command and filters at the individual `hooks[].command` level, not the entry level — a co-located foreign command on the same event (e.g. GSD's `gsd-worktree-path-guard.js`) survives byte-identical, and its event key survives with it"
    - "REQ-2: The prune is idempotent and silent in the common case: a machine that never had the stale attachment sees no new output and no `settings.json` content change beyond what install already did"
    - "REQ-3: `hooks/state-writer-events.json` and `hooks/settings-snippet.json` are asserted worktree-free by a mechanical gate, not by assumption — both are checked by a jq predicate that would fail if any worktree event name ever appeared in either"
    - "REQ-4: The registration count is derived, never hardcoded: `test_event_logger.py` keeps comparing the registered logger command count against `len(_hook_events())`, so the 24-to-22 change needs no test-fixture edit and a future widening of the list needs none either"
    - "REQ-4: A regression test proves the upgrade path (stale attachment pruned, foreign hook preserved, key deleted when empty) and a second proves the guard rejects a re-added delegation event — both run the real `hooks/install.sh` under a TemporaryDirectory HOME, never the live `~/.claude`"
    - "All three suites stay green: `test_event_logger.py`, `test_state_writer.py`, `test_monitor.py`, with a total strictly greater than the 307 tests green at planning time and no pre-existing assertion deleted or weakened"
    - "The 03-UAT.md Setup runbook step tells a future re-runner to expect the current count, so re-running Setup on the devbox cannot produce a false FAIL against a number the repo no longer produces"
  prohibitions:
    - "MUST NOT run `hooks/install.sh` against the real `$HOME`. This session runs inside the user's live container and `~/.claude` is the shared bind mount driving their running monitor. Every install invocation in this plan — verify gates included — pins HOME to a `mktemp -d`. The live file is already correct (22 logger attachments, zero Worktree keys, verified during planning); it needs no action from this task"
    - "MUST NOT delete or weaken `install.sh`'s existing behaviour: the working-lock merge, the auq-lock preservation (WR-02, gated by 03-UAT Section H), `--remove-logger`, `--remove-state-writer` and `--remove-auq-lock` all keep behaving exactly as they do today. The change is additive — one guard, one prune pass"
    - "MUST NOT convert the existing entry-level filter inside `--remove-logger` to command-level as a drive-by. That asymmetry is pre-existing and out of scope; the NEW prune pass is command-level, and the header comment may say why, but the teardown modes are not refactored here"
    - "MUST NOT prune anything other than the greenlight logger command on exactly the two delegation events. No sweeping of other tools' hooks, no removal of `state-writer.sh`, no touching of any event outside the denylist"
    - "MUST NOT hardcode a literal registration count (22, 24, or any other) in `test_event_logger.py` or `test_state_writer.py`. Counts are derived from the JSON file at runtime"
    - "MUST NOT rewrite the recorded UAT observations in `03-UAT.md` — the dated result rows near the bottom (`Setup (registration counts) | 2026-08-06 | ... event-logger 24 ...` and the `expected:` line under it) describe what was observed on 2026-08-06 and stay verbatim. Only the live runbook step's inline expectation is maintained"
    - "MUST NOT edit `.planning/phases/01-hook-coverage-verification/*` — those PLAN/SUMMARY/VERIFICATION/REVIEW files are the historical record of a completed phase and their 24-event references describe what was true then"
    - "MUST NOT stage or commit any file outside the four in files_modified, and MUST NOT `git add -A` / `git add .`. The `hooks/*` and `monitor.py` entries showing as modified in `git status` are a stale 9p/WSL stat cache — `git diff HEAD --raw` was verified during planning to contain only the already-deleted `.planning/HANDOFF.json`, so those paths have zero content diff and staging them would fabricate a commit out of nothing"
  artifacts:
    - "hooks/hook-events.json — 22 event names, both delegation events absent"
    - "hooks/install.sh — DELEGATION_EVENTS denylist constant, pre-write guard, post-registration prune pass, updated header comment"
    - "test_event_logger.py — regression tests for the prune upgrade path, the foreign-hook preservation, the empty-key deletion, the guard, and the sibling-JSON worktree-free assertion"
  key_links:
    - "hooks/hook-events.json -> install.sh's `--argjson events` reduce: the registration pass writes ONLY events present in the file, which is exactly why removing a name from the file does not remove it from an existing settings.json — this is the whole bug, and the prune pass is the missing half of that link"
    - "DELEGATION_EVENTS -> both the guard and the prune: one constant feeds both, so the banned list and the cleaned list can never drift apart"
    - "install.sh prune pass -> settings.json rewrite protocol: it must reuse the file's established `jq > .tmp` + `python3 -c json.load` + `mv` sequence, or a jq slip could leave the user's settings.json truncated"
---

<objective>
Stop `hooks/install.sh` from attaching the passive `event-logger.sh` to Claude Code's `WorktreeCreate` and `WorktreeRemove` hooks, and clean the attachment off machines that already have it.

Purpose: those two events are DELEGATION hooks — when any hook is configured on them, Claude Code stops running `git worktree add` itself and expects the hook to create (or remove) the worktree and print its path on stdout. `event-logger.sh` prints nothing, so every worktree creation on this machine failed with `WorktreeCreate hook failed` (and, because the delegation contract broke before dispatch, no `WorktreeCreate` line ever reached `hook-events.log` either — the logger was pure cost, zero diagnostic value). A different session already stripped the two entries from the live `~/.claude/settings.json`; re-running the installer would put them straight back.

Output: a 22-name `hook-events.json`, an installer that refuses to register on a delegation event and prunes stale registrations from prior installs, regression tests locking both, and a maintained UAT runbook expectation.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@hooks/hook-events.json
@hooks/install.sh
@test_event_logger.py

## Facts established during planning (do not re-derive)

- `git diff HEAD --raw` contains exactly one entry: `D .planning/HANDOFF.json`. The ` M` markers on `hooks/*` and `monitor.py` in `git status` are a WSL/9p stat-cache artifact with no content diff.
- Live `~/.claude/settings.json` on this machine: 22 `event-logger.sh` command attachments, zero `Worktree*` keys, zero empty hook arrays. Nothing to fix live; this task fixes the repo so the next install does not regress it.
- `jq` here is 1.6. Both jq programs prescribed below were executed against fixtures during planning and produced the asserted results.
- `hooks/state-writer-events.json` (10 names) and `hooks/settings-snippet.json` (3 working-lock entries) contain no worktree reference — confirmed by reading both files in full. Task 2 turns that reading into a standing gate.
- `test_event_logger.py` and `test_state_writer.py` already derive every expected count from the JSON files at runtime (`len(_hook_events())`, `_commands_matching(...)`), so no test fixture encodes 24. The only in-repo 24s are prose in completed-phase `.planning/` records plus one live runbook line in `03-UAT.md:53`.
- `install.sh` structure: arg parse (l.62-70) -> three `--remove-*` early-exit modes (l.72-130) -> `mkdir`/`install` of the three scripts (l.132-138) -> snippet merge or create (l.140-190) -> logger registration jq pass (l.196-204) -> state-writer registration jq pass (l.211-219). Each jq pass follows `jq > "$SETTINGS.tmp"` then `python3 -c "import json; json.load(...)"` then `mv`.
</context>

<tasks>

<task type="tracer">
  <name>Task 1: End-to-end — installer never attaches the logger to a delegation hook, and cleans up the ones it already attached</name>
  <files>hooks/hook-events.json, hooks/install.sh</files>
  <action>
Wire the whole path in one slice: the event list, the guard that protects it, the prune that repairs existing machines, and the documentation of why.

**hooks/hook-events.json (REQ-1):** remove the last two array elements, `WorktreeCreate` and `WorktreeRemove`. The array goes from 24 names to 22; every other name keeps its current order and spelling. The file stays strict JSON — no comment is added here because the format has none, and because `install.sh` reads it with `--argjson "$(cat ...)"`, where any non-JSON byte would abort the installer.

**hooks/install.sh — denylist constant:** beside the existing `EVENTS_FILE` / `LOGGER_CMD` constants (around l.57-60), add `DELEGATION_EVENTS='["WorktreeCreate","WorktreeRemove"]'` as a JSON-array string, so the same value can be passed to jq with `--argjson` in both places below. One constant feeds both the ban and the cleanup; they can never drift.

**hooks/install.sh — pre-write guard (REQ-1):** immediately before the `mkdir -p "$CLAUDE_DIR/hooks" ...` line, so it runs on the default install path only (the three `--remove-*` modes exit above it) and before any file is copied or created, validate the event list against the denylist. Verified jq 1.6 expression:

  `jq -e --argjson bad "$DELEGATION_EVENTS" 'any(.[]; . as $e | $bad | index($e) != null) | not' "$EVENTS_FILE" >/dev/null`

On failure, write to stderr an explanation naming the delegation contract (Claude Code expects a hook configured on these events to create/remove the worktree and print its path; a passive logger there fails every worktree creation) and `exit 1`. Placing it before the first write is load-bearing, not stylistic: Task 1's verify asserts that a tripped guard leaves no `settings.json` behind at all.

**hooks/install.sh — prune pass (REQ-2):** the existing registration reduce only touches events present in `hook-events.json`, so dropping a name there is invisible to a `settings.json` that already carries it — an existing install keeps the stale attachment forever. Add the missing half as its own jq pass placed immediately after the logger-registration pass and before the state-writer pass, reusing that file's established rewrite protocol verbatim (`jq > "$SETTINGS.tmp"`, then `python3 -c "import json; json.load(open('$SETTINGS.tmp'))"`, then `mv`). Verified jq 1.6 program:

    jq --argjson bad "$DELEGATION_EVENTS" '
      def is_logger_cmd: (.command // "" | test("event-logger\\.sh"));
      reduce $bad[] as $event (.;
        .hooks[$event] = ((.hooks[$event] // [])
          | map(.hooks |= (map(select(is_logger_cmd | not))))
          | map(select((.hooks // []) | length > 0)))
        | (if ((.hooks[$event] // []) | length) == 0 then del(.hooks[$event]) else . end)
      )
    ' "$SETTINGS" > "$SETTINGS.tmp"

Three properties of that program are deliberate and must survive any reformatting: it filters at the individual `hooks[].command` level (the same reason `--remove-auq-lock` and `drop_working_cmd` do — an entry-level filter would delete a co-located foreign command such as GSD's `gsd-worktree-path-guard.js` as collateral); it drops an entry only once that entry has zero commands left; and it deletes the event KEY when the whole array empties, so no `"WorktreeCreate": []` husk is left that Claude Code could still read as a configured hook. Running it on an already-clean settings.json is a no-op that creates and immediately deletes the key, so re-running install is safe. Placing it after the registration pass also guarantees `.hooks` already exists.

Report only when something was actually removed, following the `auq_count` precedent at l.183-189: count the matching commands with jq before the pass, and echo a one-line note naming the count and the events only when it is greater than zero. A machine that never had the stale attachment stays silent.

**hooks/install.sh — header comment (REQ-1):** the `event-logger.sh` paragraph currently says the logger is registered on "24 names, the RESEARCH.md baseline". Correct the count to match the file and append the why: which two names were removed, that they are delegation hooks rather than notification hooks, the concrete failure they caused (`WorktreeCreate hook failed`, with no event ever reaching the log), that the installer now refuses to register on them and prunes stale registrations from earlier installs, and that this is the place the ban is documented because `hook-events.json` is comment-less JSON. Keep the existing provenance and "re-check before trusting a negative" caveat intact — it still applies to the remaining 22. Also note in the `--remove-logger` sentence that its sweep is generic and already removes these too; the new pass exists because the DEFAULT path had no removal at all.
  </action>
  <verify>
    <automated>T=$(mktemp -d) && HOME="$T" bash hooks/install.sh >/dev/null && HOME="$T" bash hooks/install.sh >/dev/null && jq -e 'length == 22 and (index("WorktreeCreate") == null) and (index("WorktreeRemove") == null)' hooks/hook-events.json >/dev/null && jq -e '((.hooks | has("WorktreeCreate")) | not) and ((.hooks | has("WorktreeRemove")) | not)' "$T/.claude/settings.json" >/dev/null && N=$(jq 'length' hooks/hook-events.json) && L=$(jq '[..|objects|select(has("command"))|.command|select(test("event-logger"))]|length' "$T/.claude/settings.json") && [ "$L" = "$N" ] && S=$(jq '[..|objects|select(has("command"))|.command|select(test("working-lock"))]|length' hooks/settings-snippet.json) && M=$(jq '[..|objects|select(has("command"))|.command|select(test("working-lock"))]|length' "$T/.claude/settings.json") && [ "$S" = "$M" ] && W=$(jq 'length' hooks/state-writer-events.json) && X=$(jq '[..|objects|select(has("command"))|.command|select(test("state-writer"))]|length' "$T/.claude/settings.json") && [ "$W" = "$X" ] && U=$(mktemp -d) && mkdir -p "$U/.claude" && printf '%s' '{"hooks":{"WorktreeCreate":[{"hooks":[{"type":"command","command":"bash \"$HOME/.claude/hooks/event-logger.sh\"","timeout":2}]}],"WorktreeRemove":[{"hooks":[{"type":"command","command":"node /gsd/gsd-worktree-path-guard.js","timeout":5},{"type":"command","command":"bash \"$HOME/.claude/hooks/event-logger.sh\"","timeout":2}]}]}}' > "$U/.claude/settings.json" && HOME="$U" bash hooks/install.sh >/dev/null && jq -e '((.hooks | has("WorktreeCreate")) | not)' "$U/.claude/settings.json" >/dev/null && jq -e '(.hooks.WorktreeRemove | length) == 1 and ((.hooks.WorktreeRemove[0].hooks | length) == 1) and (.hooks.WorktreeRemove[0].hooks[0].command | test("gsd-worktree-path-guard"))' "$U/.claude/settings.json" >/dev/null && jq -e '[.hooks.WorktreeRemove[]?.hooks[]? | select(.command | test("event-logger"))] | length == 0' "$U/.claude/settings.json" >/dev/null && C=$(mktemp -d) && cp -r hooks "$C/" && jq '. + ["WorktreeCreate"]' hooks/hook-events.json > "$C/hooks/hook-events.json" && G=$(mktemp -d) && ! HOME="$G" bash "$C/hooks/install.sh" >/dev/null 2>&1 && [ ! -f "$G/.claude/settings.json" ] && [ ! -d "$G/.claude/hooks" ] && rm -rf "$T" "$U" "$C" "$G" && echo WORKTREE_PRUNE_OK</automated>
  </verify>
  <done>`WORKTREE_PRUNE_OK`. The list is 22 names with neither delegation event; a fresh double install registers one logger per listed event, creates no `Worktree*` key, and leaves the working-lock and state-writer registration counts at exactly their source-file counts; a seeded stale install has its `WorktreeCreate` key deleted outright and its `WorktreeRemove` key kept carrying only the foreign `gsd-worktree-path-guard.js` command; and an installer whose event list re-adds a delegation event exits non-zero having written neither `settings.json` nor the hooks directory.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Lock the ban, the prune and the sibling-file cleanliness down in the test suite</name>
  <files>test_event_logger.py</files>
  <behavior>
    - Upgrade path: a settings.json seeded with a logger command on `WorktreeCreate` loses it on a plain `_run_install(home)`, and the `WorktreeCreate` key is absent from `.hooks` afterwards (not present-and-empty).
    - Collateral safety: a `WorktreeRemove` entry holding a foreign command alongside the logger command keeps the foreign command verbatim, keeps its event key, and ends with zero logger commands.
    - Fresh install: no `Worktree*` key is created at all, and the registered logger command count still equals `len(_hook_events())`.
    - Idempotency: a second `_run_install` after the prune changes nothing (key still absent, foreign command still present exactly once).
    - Guard: an installer run from a copied hooks/ dir whose `hook-events.json` re-adds a delegation event exits non-zero, writes an explanatory message to stderr, and leaves the temp HOME without a settings.json.
    - Source-list hygiene: `hook-events.json`, `state-writer-events.json` and `settings-snippet.json` contain no worktree event name anywhere (REQ-3) — asserted over the parsed JSON, so a comment could never satisfy it.
    - Non-regression: the existing Goal5/Goal6/Goal7 expectations still hold unchanged, and every count still derives from `len(_hook_events())`.
  </behavior>
  <action>
Add a new goal-numbered test class to `test_event_logger.py` following the file's existing conventions exactly: subclass `_HomeTestCase`, drive the real script through `_run_install`, read state through `_load_settings` / `_commands_matching` / `_hook_events`, and never touch the real `$HOME` (the module docstring's rule — this suite runs inside the user's live container against a shared `~/.claude` bind mount). Place it after the existing Goal7 classes with the same `# ---` banner style, and name it for the user-facing guarantee (the delegation hooks stay logger-free) rather than for the function under test.

Seed the stale fixture by writing a settings.json before install, the way `Goal6` already seeds an unrelated entry: one `WorktreeCreate` entry whose only command is the logger command string, and one `WorktreeRemove` entry holding a foreign command (use a `gsd-worktree-path-guard.js` command, the real co-tenant on those events) plus the logger command in the SAME entry object. That co-location is the point of the test: it is precisely what an entry-level filter would destroy. Assert key absence with `not in settings["hooks"]`, not by comparing to `[]`, so a leftover empty husk fails.

For the guard test, copy the whole `hooks/` directory into a `TemporaryDirectory` (`shutil.copytree`), rewrite the copy's `hook-events.json` to include a delegation event, and run the copy's `install.sh` — `install.sh` resolves its inputs from its own directory, so the copy is self-contained and the repo file is never mutated by a test run. Assert non-zero exit, a non-empty stderr, and that no settings.json exists in that temp HOME.

For the source-list hygiene test, load all three JSON files and assert that no worktree event name appears in the parsed structures (event names for the two list files, serialized command/keys for the snippet). Derive the forbidden names from a module-level constant so the assertion reads as one rule rather than four scattered string literals.

Do not modify any existing test, helper or constant; this task is additive. Then run all three suites and confirm the total is strictly greater than before with zero failures.
  </action>
  <verify>
    <automated>set -o pipefail && python3 -m unittest test_event_logger.py test_state_writer.py test_monitor.py 2>&1 | tee /tmp/ejg-tests.txt | tail -4 && RAN=$(sed -n 's/^Ran \([0-9]*\) tests.*/\1/p' /tmp/ejg-tests.txt) && [ "$RAN" -gt 307 ] && python3 - <<'PY'
import json,re,pathlib
h=pathlib.Path("hooks")
names=set(json.loads((h/"hook-events.json").read_text()))|set(json.loads((h/"state-writer-events.json").read_text()))
assert not {n for n in names if "orktree" in n}, names
assert "orktree" not in (h/"settings-snippet.json").read_text()
src=(pathlib.Path("test_event_logger.py")).read_text()
assert "gsd-worktree-path-guard" in src, "co-located foreign-hook fixture missing"
assert re.search(r"copytree", src), "guard test must run install.sh from a copied hooks dir"
print("TESTS_LOCKED_OK")
PY</automated>
  </verify>
  <done>All three suites pass with a total strictly greater than the 307 green before this task and no pre-existing test edited; `TESTS_LOCKED_OK` prints, confirming both event lists and the snippet are worktree-free in their parsed form, the co-located foreign-hook fixture is present, and the guard test runs the installer from a copied hooks directory rather than mutating the repo's own event list.</done>
</task>

<task type="auto">
  <name>Task 3: Keep the 03-UAT Setup runbook step truthful without touching its recorded observations</name>
  <files>.planning/phases/03-flip-to-default-cleanup/03-UAT.md</files>
  <action>
`03-UAT.md:53` is a LIVE runbook instruction — the Setup step's jq one-liner carries an inline expected registration count for `event-logger.sh`. Phase 3's UAT is still open (Sections D-I pending, and Setup is re-run on any new machine, including the devbox), so leaving the pre-change number there would produce a false FAIL against a count the repo no longer produces.

Update that one inline expectation to the current count, keeping the parenthetical that names `hooks/hook-events.json` as the source of truth, and append a short dated note (2026-08-18, quick-260818-ejg) recording that the count dropped because the two worktree delegation events were removed from the registration list — so a future reader understands the change rather than suspecting a lost registration.

Strictly bounded: the recorded result rows further down (the dated `Setup (registration counts) | 2026-08-06 | ... event-logger 24 ...` row and the `expected:` line beneath it) describe what was observed on that date and stay byte-identical. Change nothing else in the file, and change nothing anywhere under `.planning/phases/01-hook-coverage-verification/` — those are a closed phase's historical record.
  </action>
  <verify>
    <automated>F=.planning/phases/03-flip-to-default-cleanup/03-UAT.md && N=$(jq 'length' hooks/hook-events.json) && grep -q "expect $N" "$F" && grep -q "260818-ejg" "$F" && grep -q "event-logger 24" "$F" && grep -q "working-lock 3, state-writer 10, event-logger 24" "$F" && D=$(git diff --numstat -- "$F" | awk '{print $2}') && [ "${D:-0}" -le 2 ] && [ -z "$(git diff --name-only -- .planning/phases/01-hook-coverage-verification/)" ] && echo UAT_NOTE_OK</automated>
  </verify>
  <done>`UAT_NOTE_OK`. The Setup step expects the count the repo now produces, the change is attributed to this quick task by id, the 2026-08-06 observation rows survive verbatim (both the standalone `event-logger 24` string and the full recorded counts line still match), at most two lines were removed from the file, and the completed Phase 1 directory is untouched.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| repo `hooks/*` -> `~/.claude/settings.json` | The installer rewrites a file that Claude Code executes commands from, on every session of every project on the machine, and which other tools (GSD) also register hooks in |
| repo `hook-events.json` -> Claude Code hook dispatch | An event name in this list becomes a hook registration; on delegation events a registration silently changes Claude Code's control flow rather than just observing it |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-ejg-01 | Tampering | prune pass in `install.sh` | high | mitigate | Filter at the `hooks[].command` level and drop an entry only when its command list empties — the verified precedent from `--remove-auq-lock`. Task 1's verify seeds GSD's `gsd-worktree-path-guard.js` co-located in the SAME entry object as the stale logger and asserts it survives byte-identical with its event key intact; Task 2 makes that a standing regression test |
| T-ejg-02 | Denial of service | delegation-event guard | medium | mitigate | The guard trips only on repo-file content (someone re-adding a banned name), runs before the first filesystem write, and its message names the fix. Task 1's verify asserts a tripped guard leaves neither `settings.json` nor `~/.claude/hooks/` behind, so a rejected install cannot leave a half-configured machine |
| T-ejg-03 | Tampering | settings.json rewrite | high | mitigate | The new jq pass reuses the file's established protocol unchanged: existing timestamped `.bak` from the merge step, write to `.tmp`, validate with `python3 json.load`, only then `mv`. A malformed jq result aborts under `set -euo pipefail` before the original is replaced |
| T-ejg-04 | Elevation of privilege | test suite touching live `~/.claude` | high | mitigate | Every install invocation in plan and tests pins `HOME` to a `mktemp -d` / `TemporaryDirectory`; the guard test copies `hooks/` rather than mutating the repo's event list. Explicit prohibition in `must_haves`, and the suite's module docstring already states the rule |
| T-ejg-05 | Information disclosure | logger on delegation events | low | accept | Removing registrations only reduces what is written to `hook-events.log`; no new data is collected or exposed by this change |
| T-ejg-SC | Tampering | package installs | n/a | accept | No npm/pip/cargo install task exists in this plan — no new dependency is added, so the package-legitimacy gate does not apply |
</threat_model>

<verification>
1. `jq 'length' hooks/hook-events.json` is 22 and neither delegation event name is in the array.
2. Fresh install on a temp HOME: logger command count equals the event-list length, no `Worktree*` key exists, working-lock and state-writer counts equal their source files' counts.
3. Stale-install simulation on a temp HOME: `WorktreeCreate` key deleted, `WorktreeRemove` key preserved with only the foreign command, zero logger commands on either.
4. Guard: an installer whose event list re-adds a delegation event exits non-zero and writes nothing.
5. `python3 -m unittest test_event_logger.py test_state_writer.py test_monitor.py` — all green, total strictly greater than before.
6. `git status --short` shows only the four files in `files_modified` staged; `git diff HEAD --raw` confirms no other path acquired content changes.
</verification>

<success_criteria>
- A newly provisioned machine can run `git worktree add` after `bash hooks/install.sh`, because the installer never registers a passive hook on a delegation event.
- The MacBook devbox — and any other machine carrying the stale attachment — is repaired by its next plain `bash hooks/install.sh`, with no flag and no manual settings.json edit.
- Another tool's hook on the same two events is provably untouched by the repair.
- The ban is enforced by the installer itself, so re-adding either name is a loud failure rather than a silent regression.
- `state-writer-events.json` and `settings-snippet.json` are proven worktree-free by a gate rather than assumed.
</success_criteria>

<output>
Create `.planning/quick/260818-ejg-installer-must-not-attach-event-logger-t/260818-ejg-SUMMARY.md` when done.

Record in the summary: that the live `~/.claude/settings.json` on this machine needed no action (already 22 attachments, zero Worktree keys, verified at planning time), and that the devbox at `matteo@192.168.1.139` gets fixed on its next `bash hooks/install.sh` run — worth mentioning to the user as the one remaining machine-level follow-up.
</output>
