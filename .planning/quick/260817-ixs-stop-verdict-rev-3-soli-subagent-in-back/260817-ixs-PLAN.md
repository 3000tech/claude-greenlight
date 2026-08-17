---
phase: quick-260817-ixs
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - hooks/state-writer.sh
  - test_state_writer.py
  - docs/TEST-MATRIX.md
autonomous: true
requirements: [QUICK-260817-ixs]

estimate:
  tokens: 12000
  raw_tokens: 38000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A Stop payload whose in-flight background_tasks are ALL `type: \"subagent\"` writes `state: \"working\"` to the session's state file — the session that is guaranteed to be re-invoked when its agents finish no longer shows green and no longer pages the user"
    - "A Stop payload with ANY in-flight entry that is not `type: \"subagent\"` still writes `state: \"waiting\"`: a `shell` entry, an entry with no `type` key, an entry whose `type` carries an unrecognised string, and an entry whose `type` is a non-string value each keep today's verdict"
    - "The in-flight filter runs BEFORE any `type` inspection and uses the same deny-list rule as background_tasks_count: a completed or failed shell entry sitting alongside a running subagent entry does NOT force waiting, while a subagent entry that is itself completed/failed does not qualify the Stop for working"
    - "A Stop with zero in-flight background tasks — no `background_tasks` key, an empty array, or only completed/failed entries — still writes `waiting`, unchanged, because that is the ordinary end-of-turn notify path"
    - "The state-file record schema is byte-for-byte the same shape as before: exactly the seven keys state, ts, ts_ms, cwd, hostname, last_event, background_tasks_count — no new field, and no descriptor value (agent_type, command, id, description) ever reaches the file"
    - "hooks/state-writer.sh still writes nothing to stdout and still exits 0 on every path, including a background_tasks array holding a string or a number instead of an object, a non-array background_tasks, and a jq failure — every degradation lands on `waiting`, never on a suppressed notification"
    - "monitor.py is unmodified and needs no modification: a state file carrying state=working with last_event=Stop is rendered WORKING/grey/rank 2 by scan_state_files() and labelled `turn end`, proven end-to-end by a test that drives the real hook script and then the real monitor function"
    - "test_state_writer.py Goal6 covers the full rev.3 truth table, and every pre-existing Goal6 assertion is still present and still green — the D-03 tests keep their assertions verbatim, with only the names/docstrings whose claim narrowed reworded"
    - "hooks/state-writer.sh's header event-to-state mapping describes the rev.3 rule instead of the rev.2 one, so the file is never self-contradictory about its own Stop verdict"
    - "docs/TEST-MATRIX.md section 4 case #17 records branch (a) as confirmed and implemented, with the rev.3 evidence tables left intact"
    - "`~/.claude/hooks/state-writer.sh` is byte-identical to the repo copy after the run, and `~/.claude/settings.json` is untouched (no rewrite, no new .bak)"
  prohibitions:
    - "MUST NOT add any field to the state-file record — not `bg_agents_only`, not a descriptor list, not a type histogram. `state: working` together with `last_event: Stop` is already the unique, sufficient signature of this rule firing, so a new field would widen the schema on the shared ~/.claude mount for zero information gain"
    - "MUST NOT capture, log or persist any background_tasks descriptor value. Only `type` and `status` are ever inspected, and only inside the jq expression — neither value may reach the record, stdout, or any file"
    - "MUST NOT change the background_tasks_count expression or its deny-list semantics — the badge count is a separate, already-shipped contract (D-09) and this task must leave every existing count assertion green without editing it"
    - "MUST NOT let an in-flight entry with a missing, empty, unrecognised or non-string `type` qualify a Stop as working. Unknown evidence resolves to waiting, always: suppressing a notification on a guess is the one failure mode this rule must never have"
    - "MUST NOT introduce a jq expression that can abort on a hostile array (a string or number where an object is expected) and thereby leave the flag unset — normalize non-object entries before the select, and clamp any non-`true` output to false"
    - "MUST NOT add stdout output, a non-zero exit, `set -e`, a subshell that can trap, or any second file read to hooks/state-writer.sh — it runs on PermissionRequest, PostToolBatch and Stop, all of which can alter Claude Code's control flow"
    - "MUST NOT modify monitor.py. If the executor concludes a monitor change IS required, stop and report it rather than making it — that is a scope change the user has to see"
    - "MUST NOT weaken, reword away or delete any existing assertion in test_state_writer.py. Renaming a test or rewriting its docstring is allowed where the D-03 claim narrowed; removing an assertLine is not"
    - "MUST NOT rewrite ~/.claude/settings.json — state-writer.sh is already registered on this machine; deployment is a file copy of the script alone"
    - "MUST NOT deploy to ~/.claude/hooks/ before both test suites are green"
    - "MUST NOT install any npm/pip/cargo package"
  artifacts:
    - path: "hooks/state-writer.sh"
      provides: "The rev.3 Stop verdict: an in-flight-filtered all-subagent check that maps Stop to working, plus the rewritten header event-to-state mapping"
      contains: "subagent"
    - path: "test_state_writer.py"
      provides: "Goal6 coverage of the full rev.3 truth table — all-subagent, mixed, shell-only, missing type, unknown type, non-string type, completed-shell-plus-running-subagent, all-completed, hostile non-object — plus the end-to-end hook-to-monitor render assertion"
      contains: "subagent"
    - path: "docs/TEST-MATRIX.md"
      provides: "Case #17 rev.3 outcome paragraph: branch (a) confirmed on 42 live samples and implemented, superseding the no-verdict-change scope statement"
      contains: "260817-ixs"
  key_links:
    - "The in-flight filter is the hinge of the whole rule. It must run BEFORE `type` is read, using the same deny-list clause the count already uses — otherwise a long-finished background shell from earlier in the turn would permanently pin the session to waiting and the rule would silently never fire. Live evidence: every sampled in-flight descriptor carried `status: running`, and completed entries do appear in the same array"
    - "The fail-safe direction runs one way only: missing/unknown `type` means waiting. jq's `all()` is vacuously true over an empty generator, so an entry whose `.type?` yields nothing would sneak through as subagent unless every entry is first normalized to an object and projected to a concrete string. Normalizing with `if type == \"object\" then . else {} end` before the select is what makes a hostile array resolve to waiting instead of aborting jq"
    - "monitor.py already renders this exact record: `_state_to_status` maps the string `working` to (WORKING, #666, rank 2) and `_STATE_ACTION_LABELS[\"Stop\"]` is `turn end`. test_monitor.py's `StateFileTestBase._write_state` even defaults to `last_event: \"Stop\"`, so `Goal9_StateFileVerdicts.test_working_state_maps_to_working` is already, incidentally, a test of the new record shape — which is why zero monitor change is needed"
    - "The 10-minute heartbeat staleness window is the built-in escape hatch, not a gap: a working record whose last_event is not UserPromptSubmit ages out through STATE_HEARTBEAT_STALE_SEC (600s) and recovers to WAITING (monitor.py's scan_state_files staleness block, already covered by test_monitor.Goal11_StateFileStaleness). So an agent that never re-invokes the session produces a LATE notification, never a lost one — the rule cannot strand a session grey forever"
    - "None of the existing Goal6 tests passes a `type` key inside background_tasks (verified: their entries are `{\"status\": \"running\"}`-shaped), so the whole pre-existing D-03 suite stays green under the new rule by construction — the fail-safe covers them. That is the cheapest possible proof that the change is a narrowing, not a reversal"
    - "Deployment is live on this machine's shared ~/.claude mount: the copy takes effect on the very next Stop of every running session, including the executor's own. Tests are the only gate before that"
---

<objective>
Refine the Stop verdict so a turn that ends with only background AGENTS in flight resolves to `working` instead of `waiting` — the session is guaranteed to be re-invoked when those agents finish, so it owes the user nothing and must not page them.

Purpose: TEST-MATRIX case #17 rev.2 (D-03) made `background_tasks_count` badge-only — correct for a background shell, since a build or a dev server running is not evidence Claude owes a reply. But it cannot tell a shell from an agent, and that produced two recorded false positives on 2026-08-17, session 34518633 (yunoai): a notification at 11:15:20Z after a Stop at 11:14:15Z with two gsd-planner agents in flight (session self-resumed ~40s later), and a second at 13:06:49Z after a Stop at 13:05:44Z with one gsd-executor in flight (self-resumed ~2 min later). The user never needed to act, either time. Quick task 260817-i5n sampled the payloads and confirmed branch (a) of the rev.3 rule: the descriptor's `type` field discriminates cleanly — `subagent` x30, `shell` x12 across 42 live samples, zero other values, zero missing. This task implements branch (a) and closes the rev.3 entry with the real answer.

Output: a narrowed Stop rule in hooks/state-writer.sh (one new jq resolution, one conditional in the Stop branch, a rewritten header mapping), full truth-table coverage in test_state_writer.py Goal6, the rev.3 entry in TEST-MATRIX marked implemented, and the refreshed script deployed live.

Environment note (carried from 260817-i5n's execution): this sandbox's working tree can show spurious CRLF corruption and spurious `M` entries in `git status` on files whose content is byte-identical to HEAD. `set -u`/`set -euo pipefail` scripts fail outright on a shebang line with a trailing `\r`. If a suite fails with an error like `set: pipefail\r: invalid option name`, restore the affected file with `git show HEAD:<path> > <path>` (a content no-op, confirmed via `git hash-object`) and continue — do not treat it as a real defect and do not commit it.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@hooks/state-writer.sh
@test_state_writer.py
@docs/TEST-MATRIX.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: An all-subagent Stop reaches the monitor as grey, end to end</name>
  <files>hooks/state-writer.sh, test_state_writer.py</files>
  <read_first>
    hooks/state-writer.sh lines 41-70 (header event-to-state mapping), 112-126 (the background_tasks_count resolution and its case-guard fallback), 152-159 (the Stop branch), 175-191 (the record builder — note it emits exactly seven keys).
    test_state_writer.py lines 100-110 (`_payload` helper), 153-185 (`Goal1_TracerEndToEnd` — the existing hook-script-then-monitor pattern this task's test mirrors, including the STATE_DIR repoint/restore), 460-467 (`Goal6_TurnEndSemantics._stop` and `_read` helpers).
  </read_first>
  <behavior>
    - Stop carrying one in-flight entry `{"status": "running", "type": "subagent", "agent_type": "gsd-executor"}` writes `state: "working"` and `background_tasks_count: 1`
    - the same state file, read by the real monitor.scan_state_files(), renders (status, dot_color, rank) == ("WORKING", "#666", 2) with action "turn end"
    - the file text contains neither "gsd-executor" nor "subagent" — only type/status are inspected, never captured
    - the record still has exactly the seven documented keys
  </behavior>
  <action>
    Write the failing test first, then the script change.

    TEST (test_state_writer.py, a new method on `Goal6_TurnEndSemantics`, named for what it proves — that an agent-only turn end reaches the monitor grey): drive `self._stop(sid, background_tasks=[{"status": "running", "type": "subagent", "agent_type": "gsd-executor"}])`, assert returncode 0 and empty stdout, then assert the record's `state` is "working" and `background_tasks_count` is 1. Assert the raw file text does not contain "gsd-executor" and does not contain "subagent". Assert `sorted(obj.keys())` equals the seven-key set (state, ts, ts_ms, cwd, hostname, last_event, background_tasks_count) so the schema-freeze prohibition has a live guard. Then repoint `monitor.STATE_DIR` to the temp state dir inside a try/finally exactly the way `Goal1_TracerEndToEnd` does, call `monitor.scan_state_files(sessionid_to_label={sid: "my-label"})`, and assert the single rendered row's `status`/`dot_color`/`rank` are "WORKING"/"#666"/2 and its `action` is "turn end". Run it and confirm it fails on the state assertion (RED) before touching the script.

    SCRIPT (hooks/state-writer.sh): immediately after the existing `background_tasks_count` case-guard block, add a second jq resolution assigning to a new shell variable `bg_agents_only`. Its jq program: iterate `.background_tasks[]?`; normalize each entry with `if type == "object" then . else {} end` so a string or number in the array can never abort the program; apply the SAME in-flight select clause the count above uses, verbatim — an entry whose `(.status // "running")` is neither "completed" nor "failed" survives; project each survivor to `((.type // "") | tostring)`; collect into an array bound `as $inflight`; emit the literal string true only when `($inflight | length) > 0` and `($inflight | all(. == "subagent"))`, otherwise the literal string false. Invoke it with `jq -r`, `2>/dev/null`, and heredoc-string input from `$payload`, matching the count's invocation style. Follow it with a `case` statement that leaves the value alone when it is exactly `true` and rewrites anything else — empty output, a jq failure, an unexpected token — to `false`.

    Then change the Stop branch: keep `state="waiting"` as the resolved default and add a conditional that promotes it to `working` only when `bg_agents_only` is `true`. Replace the branch's comment so it states the rev.3 rule, names the in-flight filter as running before the type check, and records why unknown types stay at waiting.

    Finally rewrite the header's Stop line in the event-to-state mapping (currently the rev.2 wording that describes a single verdict for every payload) so it describes both outcomes: in-flight tasks all of type subagent map to working because the completing agent re-invokes the session; anything else — a shell entry, an unknown or missing type, or no in-flight task at all — maps to waiting. Cite case 17 rev.3 and note that background_tasks_count remains badge data. Also extend the "Captured by value" paragraph to say that `type` and `status` are read from descriptors but never captured, so the privacy discipline stays accurate.

    Do not add a record field. Do not touch the count expression. Do not touch monitor.py.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_state_writer.py -v 2>&amp;1 | tail -5</automated>
    <automated>cd /workspace &amp;&amp; printf '%s' '{"hook_event_name":"Stop","session_id":"probe","cwd":"/w","background_tasks":[{"status":"running","type":"subagent"}]}' | bash hooks/state-writer.sh; echo "exit=$?"</automated>
    <automated>cd /workspace &amp;&amp; git diff --stat -- monitor.py | wc -l</automated>
  </verify>
  <done>The new test passes; the whole test_state_writer.py suite is green with no pre-existing assertion edited; the probe invocation exits 0 with no stdout; `git diff --stat -- monitor.py` is empty.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The full rev.3 truth table, including every fail-safe direction</name>
  <files>test_state_writer.py</files>
  <read_first>
    test_state_writer.py lines 460-532 (the existing Goal6 background-task cases, whose entries are all `{"status": ...}`-shaped with no `type` key — they stay green unchanged) and 604-617 (the descriptor-leak test, the model for the privacy assertion style).
  </read_first>
  <behavior>
    - two in-flight subagent entries -> working, count 2
    - one in-flight subagent + one in-flight shell -> waiting, count 2
    - one in-flight shell only -> waiting, count 1
    - in-flight subagent + in-flight entry with no `type` key -> waiting
    - in-flight entry whose `type` is an unrecognised string ("future_kind") -> waiting
    - in-flight entry whose `type` is a non-string (the number 5) -> waiting
    - completed shell + failed shell + running subagent -> working, count 1 (in-flight filter precedes the type check)
    - only completed/failed subagent entries -> waiting, count 0
    - a bare string sitting in the array next to a running subagent -> waiting, exit 0, no stdout
    - no `background_tasks` key, an empty array, and a non-array `background_tasks` -> waiting, count 0
  </behavior>
  <action>
    Extend `Goal6_TurnEndSemantics` with the cases above, following the class's existing driving style — `self._stop(sid, background_tasks=[...])` then `self._read(sid)` — and using `subTest` for the parameterised families the way `test_stop_never_produces_working_regardless_of_background_task_count` already does. Each case asserts returncode 0, empty stdout, the expected `state`, and the expected `background_tasks_count` where the count is part of the claim.

    Group them so the intent is legible: one method for the qualifying cases (all-subagent, and completed-or-failed-shell-alongside-running-subagent), one for the disqualifying `type` values (shell, missing key, unrecognised string, non-string), one for the zero-in-flight cases (absent key, empty array, non-array value, only-completed subagents), and one for hostile input (a bare string entry beside a running subagent — assert waiting AND that the script neither wrote to stdout nor exited non-zero).

    Add one privacy case in the leak-test style: a Stop whose in-flight entry carries `type: "subagent"` plus a sentinel secret in both `command` and `description`, asserting the sentinel is absent from the file text, that the entry's `agent_type` value is absent too, and that the record still holds exactly the seven documented keys — the schema-freeze guard applied to the qualifying path as well as the tracer's.

    Reword, do not delete, the pre-existing methods whose stated claim narrowed: `test_stop_never_produces_working_regardless_of_background_task_count` still holds for the payloads it drives (none carries a `type` key) but its name and docstring now overclaim. Rename it so it names the class of payloads it actually covers — untyped background tasks — and rewrite its docstring to say that D-03 is preserved for every entry that is not a confirmed subagent, citing rev.3. Its assertions stay byte-identical. Do the same for `test_stop_with_one_running_entry_produces_waiting_and_count_one`'s docstring, whose rev.2 explanation is now only half the story.

    Add no new helper the class does not need, and change no other Goal class.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_state_writer.py -v 2>&amp;1 | tail -5</automated>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_state_writer.Goal6_TurnEndSemantics -v 2>&amp;1 | tail -3</automated>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor.py 2>&amp;1 | tail -3</automated>
  </verify>
  <done>Goal6 covers every row of the truth table above and the full suite is green; test_monitor.py is green with monitor.py unmodified; the reworded pre-existing tests still assert exactly what they asserted before.</done>
</task>

<task type="auto">
  <name>Task 3: Close the rev.3 entry with the real answer, then deploy live</name>
  <files>docs/TEST-MATRIX.md</files>
  <precondition>`~/.claude/hooks/state-writer.sh` already exists and is registered in `~/.claude/settings.json` on this machine — deployment is a file copy only, never a settings rewrite. Verify with `ls -l "$HOME/.claude/hooks/state-writer.sh"` before the copy; if it is absent, stop and report rather than running hooks/install.sh.</precondition>
  <reversibility rating="reversible">The live copy is one `install -m 0755` of a git-tracked file; rollback is the same copy from the previous commit.</reversibility>
  <read_first>docs/TEST-MATRIX.md lines 173-197 (the three-branch proposed rule and the no-verdict-change scope statement — the two paragraphs this task supersedes; the evidence tables above them at lines 136-171 stay untouched).</read_first>
  <action>
    DOC: in docs/TEST-MATRIX.md section 4, case #17, append an outcome paragraph after the three-branch rule, in Italian to match the surrounding prose, headed as the esito of quick task 260817-ixs (2026-08-17). It states: branch (a) confirmed on 42 live samples (subagent x30, shell x12, zero other values, zero missing `type`); the rule as shipped — a Stop whose in-flight tasks are all of type subagent resolves to working, any in-flight entry that is not a confirmed subagent (shell, missing type, unknown type) keeps waiting, and a Stop with no in-flight task keeps waiting unchanged; the fail-safe direction, that unknown evidence never suppresses a notification; and the escape hatch, that a working verdict aged past the 600-second heartbeat window recovers to WAITING, so an agent that never re-invokes the session yields a late notification rather than none.

    Then correct the scope statement that currently says no verdict change ships here — rewrite it to record that the verdict change shipped in 260817-ixs, that `background_tasks_count` stays badge-only, and that D-03/rev.2 remains intact for shells. Leave the evidence tables, the provenance note and the episode narratives exactly as they are — this is an append plus one paragraph correction, not a rewrite.

    DEPLOY (only after both suites are green): copy the reviewed script into the live hooks directory with `install -m 0755 hooks/state-writer.sh "$HOME/.claude/hooks/state-writer.sh"`, then gate with `cmp` proving the installed copy matches the repo copy byte for byte. Confirm `~/.claude/settings.json` was not rewritten: record its mtime before the copy and assert it is unchanged after, and assert no new `.bak` file appeared beside it. This copy takes effect on the very next Stop of every session sharing this mount, including the executor's own — which is why it comes last.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_state_writer.py test_monitor.py 2>&amp;1 | tail -3</automated>
    <automated>cd /workspace &amp;&amp; grep -c '260817-ixs' docs/TEST-MATRIX.md</automated>
    <automated>cmp "$HOME/.claude/hooks/state-writer.sh" /workspace/hooks/state-writer.sh &amp;&amp; echo "live copy identical"</automated>
    <automated>ls -1 "$HOME/.claude/" | grep -c 'settings.json.bak' || echo "0 bak files"</automated>
    <human-check>At the next turn end where a background agent is still running (a gsd-executor or gsd-planner launched in the background), the monitor row for this session should stay GREY and no notification should fire; when a background SHELL is in flight instead, the row should still go green and notify as it does today. Both behaviours are the point of the change.</human-check>
  </verify>
  <done>TEST-MATRIX case #17 records branch (a) as confirmed and implemented with its evidence tables intact; both suites green; the live `~/.claude/hooks/state-writer.sh` is byte-identical to the repo copy; `~/.claude/settings.json` mtime unchanged and no new .bak file.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Claude Code hook payload -> state-writer.sh | Untrusted JSON crosses here; `background_tasks` is an attacker-shaped-if-buggy array whose entries are now read, not just counted |
| state-writer.sh -> ~/.claude/monitor-state/ (shared bind mount) | Anything written here is visible to every container sharing the mount and to the monitor host |
| repo script -> live ~/.claude/hooks/ | A file copy into the path Claude Code executes on every registered event of every live session on this machine |
| state file -> monitor.py notification decision | The verdict this task changes is the input to whether the user is paged at all |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-ixs-01 | Denial of service | The new `type` inspection in state-writer.sh | high | mitigate | The rule suppresses a user-facing notification, so a wrong `true` means the user is never told a session needs them. Every unknown path resolves to `false`: non-object entries normalized before the select, `type` projected through `tostring` so a non-string can never equal "subagent", the empty-array vacuous-`all()` trap closed by an explicit `length > 0` guard, and a `case` clamp rewriting any non-`true` output to `false`. Task 2 asserts each direction individually |
| T-ixs-02 | Denial of service | Stop hook execution path | high | mitigate | state-writer.sh is registered on Stop, PermissionRequest and PostToolBatch, all of which can alter Claude Code's control flow. The new jq runs with `2>/dev/null`, writes nothing to stdout, and its failure degrades to the safe default; the script's every-path-`exit 0` contract is unchanged and re-asserted by Goal2 plus the Task 1 probe invocation |
| T-ixs-03 | Information disclosure | State file on the shared ~/.claude mount | high | mitigate | Descriptor values are read only inside the jq expression and never reach the record. The schema is frozen at exactly seven keys, asserted in Task 1 and again on the qualifying path in Task 2, and a sentinel-secret case proves `command`/`description`/`agent_type` values never appear in the file text |
| T-ixs-04 | Elevation of privilege | Deploying a modified hook into every live session's execution path | medium | mitigate | The copy is a single `install -m 0755` performed only after both suites are green, gated by a `cmp` against the reviewed repo copy. `settings.json` is not rewritten (registration already exists), so no new event surface is created; rollback is one copy of the previous commit's file |
| T-ixs-05 | Tampering | Regression of the already-shipped badge contract | medium | mitigate | The `background_tasks_count` expression is untouched and every pre-existing count assertion must stay green without being edited — a prohibition, verified by running the full suite rather than a filtered subset |
| T-ixs-06 | Repudiation | TEST-MATRIX evidence record | low | accept | The rev.3 evidence tables, provenance note and episode timestamps are preserved verbatim; the new paragraph is appended and attributed to this task, so the confirmed/implemented claim stays traceable to the samples that support it |
| T-ixs-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package installs in this plan — no package-manager task exists, so the legitimacy gate has nothing to clear |
</threat_model>

<verification>
- `python3 -m unittest test_state_writer.py` green; `python3 -m unittest test_monitor.py` green.
- `git diff --stat -- monitor.py` empty — the change is hook-side only.
- The state file produced for an all-subagent Stop has exactly seven keys and `state: "working"`; the same file rendered through `monitor.scan_state_files()` is WORKING/#666/rank 2 with action "turn end".
- Every disqualifying payload (shell, missing type, unknown type, non-string type, hostile non-object, zero in-flight) still yields `waiting`.
- `~/.claude/hooks/state-writer.sh` byte-identical to the repo copy; `~/.claude/settings.json` mtime unchanged, no new `.bak`.
</verification>

<success_criteria>
- A Stop with only in-flight subagents no longer pages the user; a Stop with any in-flight shell, unknown-type or untyped entry still does, exactly as today.
- The in-flight filter runs before the type check, so a finished background shell cannot permanently suppress the new rule.
- No new state-file field, no descriptor value on the shared mount, no monitor.py change.
- TEST-MATRIX case #17 rev.3 is closed with the real answer and its evidence intact.
- The refreshed hook is live and byte-identical to the reviewed copy.
</success_criteria>

<output>
Create `.planning/quick/260817-ixs-stop-verdict-rev-3-soli-subagent-in-back/260817-ixs-SUMMARY.md` when done
</output>
