---
phase: quick-260730-kgw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - monitor.py
  - test_monitor.py
  - README.md
autonomous: true
requirements: [QUICK-260730-kgw]

must_haves:
  truths:
    - "A label set on a session survives /clear: the sessionId rotates and the row key changes, but the amber label stays on the row for that container"
    - "A label survives a monitor restart — the one-time startup prune keeps every alias whose container is still live and drops only aliases whose container is gone"
    - "Two containers that share a launcher label still get independent labels, because the alias identity is the container, not the project name"
    - "A session that cannot be resolved to a container (no docker, no state-file hostname) keeps today's behaviour exactly: its alias is keyed by the row key"
    - "The legacy engine and the state-file engine derive the SAME alias identity for the same container, so `--state-files` diagnostic mode shows the same labels the default mode shows"
    - "A ready-notification (toast/Telegram) shows the label for a session whose sessionId rotated after the label was set"
    - "Default operation is unchanged for state detection: the legacy list still drives rendering and notification, and the shadow comparison / divergence log behave exactly as before"
  prohibitions:
    - "MUST NOT alter select_render_sessions, diff_verdicts, filter_divergence_events or write_divergences behaviour, and MUST NOT let a state-file verdict reach rendering or notification in default operation (Phase 02 D-01)"
    - "MUST NOT write a migration for aliases persisted under old sessionId keys — the existing one-time startup prune drops them, which is the accepted outcome"
    - "MUST NOT change the `ls -t /tmp/claude-ctx-*.json | head -1` sessionId query or its head-1 semantics: the second-invocation label hole is a separate, out-of-scope issue"
    - "MUST NOT store non-string keys or values in the aliases config dict — load_config's sanitiser stays the only shape guard and must keep passing every existing Goal6b test"
    - "MUST NOT re-bind alias click handlers per tick: the row binding stays keyed by row key and the container identity is resolved at click time"
  artifacts:
    - path: "monitor.py"
      provides: "Container-keyed alias identity derived once and consumed by every alias read/write/prune site"
      contains: "derive_alias_key"
    - path: "test_monitor.py"
      provides: "Regression tests for alias survival across sessionId rotation and cross-engine alias-key parity"
      contains: "alias_key"
  key_links:
    - from: "monitor.py::scan_containers"
      to: "monitor.py::query_container_sessionids"
      via: "a cid→hostname map built from the existing docker inspect call is passed in, so the query returns sessionId→hostname alongside sessionId→label with no extra subprocess"
      pattern: "sessionid_to_hostname"
    - from: "monitor.py::scan"
      to: "session row dicts"
      via: "each row gains an alias_key derived from the container hostname, falling back to the row key"
      pattern: "alias_key"
    - from: "monitor.py::MonitorApp.refresh"
      to: "monitor.py::MonitorApp._alias_key"
      via: "the per-tick row-key→alias-key map is rebuilt from the rendered session list before transitions and rendering run"
      pattern: "_alias_keys"
    - from: "monitor.py::MonitorApp._edit_alias"
      to: "config aliases dict"
      via: "the label is written under the resolved container alias key, not the row key"
      pattern: "_alias_key"
---

<objective>
Make a user-set session label stick to the container it was set on, instead of to the
one conversation that happened to be open when it was set. Today aliases are stored as
{row_key: label} where row_key is the sessionId pulled off the jsonl tail — every /clear,
/resume or CLI restart rotates that sessionId, the lookup misses, the label vanishes from
the overlay, and the one-time startup prune then deletes it from the config for good.

Purpose: the label is the only way to tell two `yunoai-france` rows apart. A label that
evaporates on /clear is worse than no label — the user re-types it, it vanishes again, and
the feature reads as broken. The user is naming a terminal, not a conversation.

Output: an `alias_key` on every session row (container hostname when resolvable, today's
row key otherwise), threaded through every alias read, write and prune site, with tests
that lock the /clear survival guarantee down.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@monitor.py
@test_monitor.py

Repo state: mid-refactor, Phase 02 (state-writer shadow mode) executing. Two engines run
every tick — legacy `scan()` (jsonl parsing, drives rendering) and `scan_state_files()`
(hook-written state files, shadow only). Baseline before this task: `python3 -m unittest
test_monitor` = 105 tests, OK.

Relevant existing shape:
- `DEFAULT_CONFIG["aliases"]` — persisted {key: label}; `load_config()` sanitises it to
  string→non-blank-string pairs and always rebuilds a fresh dict.
- `scan(label_map, sessionid_to_label)` — row key is `session_id or f"{proj_dir.name}:{latest.name}"`.
- `scan_containers()` — returns a 4-tuple; the 4th element `container_info` already carries
  `hostname_to_label` / `hostname_to_status`, both built from one `docker inspect` call whose
  format string already includes `{{.Config.Hostname}}`.
- `query_container_sessionids(docker, container_labels, kwargs)` — `docker exec`s each
  container, returns {sessionId: label}. No test calls it directly.
- `scan_state_files(...)` — its records carry `hostname` (the container hostname captured by
  hooks/state-writer.sh at write time); it already normalises that field to a str-or-None local.
- `MonitorApp` — `_session_aliases` IS `config["aliases"]`; alias sites are `_edit_alias`,
  `_notify`, the standard-render loop, the compact-chip loop and the one-time prune in `refresh()`.
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: Alias identity = container, wired end-to-end through the default (legacy-rendered) path</name>
  <files>monitor.py, test_monitor.py</files>
  <read_first>monitor.py lines 166-213 (DEFAULT_CONFIG/load_config), 896-1033 (scan), 1036-1171 (scan_containers + query_container_sessionids), 1256-1301 (MonitorApp alias state), 1470-1490 (_bind_alias_click), 1563-1588 (_edit_alias), 1746-1766 (_notify), 1883-1940 (refresh: scan call, prune), 1988-2010 and 2041-2060 (render alias reads); test_monitor.py lines 140-167 (MonitorTestBase._scan), 729-795 (Goal6/Goal6b alias tests), 876-905 (Goal8 fake-app pattern), 1192-1208 (Goal12 container_info shape)</read_first>
  <behavior>
    - derive_alias_key("container-1", "sid-abc") returns "host:container-1"
    - derive_alias_key(None, "sid-abc") returns "sid-abc"; same for "" and for a non-string value (e.g. 5)
    - scan() with container_info mapping sessionId "s1" to hostname "c1" emits a row whose alias_key is "host:c1" while its key stays "s1"
    - scan() with no container_info emits a row whose alias_key equals its key (today's behaviour)
    - THE REGRESSION: two scans of the same container with different sessionIds ("s1" then "s2", both mapping to hostname "c1") emit different keys but the SAME alias_key
    - scan_containers() with docker absent still returns a 4-tuple whose container_info carries hostname_to_label, hostname_to_status AND sessionid_to_hostname
    - MonitorApp._alias_key(k) returns the mapped alias key for a known row key and the row key itself for an unknown one
    - MonitorApp._edit_alias stores the label under the resolved container alias key, and that label is then readable for a DIFFERENT row key that maps to the same alias key (the /clear case)
    - MonitorApp._prune_aliases keeps an alias whose alias_key is live, drops one whose alias_key is absent, runs at most once, and is a no-op on an empty session list
  </behavior>
  <action>
Add a module-level pure helper `derive_alias_key(hostname, fallback_key)` next to
`resolve_alias` in monitor.py: it returns the namespaced container identity when `hostname`
is a non-empty string, otherwise `fallback_key` unchanged. Namespace it with a module
constant `ALIAS_HOST_PREFIX = "host:"` so container-derived keys can never collide with a
raw sessionId or dir-fallback key in the same config dict, and so a hand-read config says
what each entry is bound to. Docstring it as: the user labels a container/terminal, not a
conversation, so the identity must outlive a sessionId rotation.

Pick the container HOSTNAME (docker inspect's Config.Hostname) as the identity, not the
container ID or name, because it is the one identity BOTH engines can observe: the legacy
path reaches it via docker inspect, and the hook-written state records carry it verbatim
(Phase 02 D-05/ENG-03 already treats it as the container-identity key). Anything else would
make the two engines disagree about which alias a row owns.

Producer side:
1. In `scan_containers()`, inside the existing inspect loop that already populates
   hostname_to_label/hostname_to_status from `parts[3]`, also record cid→hostname in a new
   local map. Do not add a second subprocess call.
2. Change `query_container_sessionids()` to take that cid→hostname map as a fourth argument
   and to return a pair of dicts — the existing {sessionId: label} plus {sessionId: hostname}
   — populated in the same regex loop. Containers with no hostname simply have no entry.
3. Return the new map as a third entry inside `container_info` (key `sessionid_to_hostname`),
   keeping `scan_containers()`'s 4-tuple arity intact. Add it to `empty_container_info` too so
   the docker-absent early returns keep the shape.
4. Give `scan()` a third keyword parameter `container_info=None` (default None keeps every
   existing 2-arg call site and test working) and emit `"alias_key": derive_alias_key(...)`
   on each row, resolving the hostname from `container_info["sessionid_to_hostname"]` by
   session_id and falling back to the row's own `key`. Use defensive `.get` chaining so a
   None or partial container_info can never raise.
5. Update `MonitorApp.refresh()`'s `scan(...)` call to pass `self._cached_container_info`.
6. Update the `DEFAULT_CONFIG["aliases"]` comment to describe the new key shape.

Consumer side (MonitorApp):
7. Add `self._alias_keys: dict[str, str] = {}` beside `_session_aliases` in `__init__`
   (it must exist before `self.refresh()` runs at the end of `__init__`).
8. In `refresh()`, immediately after `render_sessions` is computed by
   `select_render_sessions(...)` and BEFORE the prune, `_check_transitions` and the compact
   early-return, rebuild `self._alias_keys` as row-key→alias-key from `render_sessions`,
   reading each row with a `.get("alias_key") or s["key"]` fallback so a row from any
   producer (including a state-file row that does not carry the field until Task 2) degrades
   to today's behaviour instead of raising.
9. Add a one-line method `_alias_key(self, key)` returning the mapped alias key, defaulting
   to the row key itself. Route EVERY alias lookup through it: the standard render loop, the
   compact chip loop, `_notify`, and `_edit_alias`.
10. In `_edit_alias`, resolve the alias key once at the top and use it for the read, the
    store and the clear. Keep `_bind_alias_click` binding the ROW key — resolution must
    happen at click time, because a row's alias_key legitimately changes (row key stable,
    docker map lands a tick later). For the immediate visual feedback loop, update every row
    and chip whose resolved alias key matches the edited one, instead of only the clicked key.
11. Extract the one-time startup prune out of `refresh()` into `_prune_aliases(self, sessions)`
    and call it with `render_sessions`. Preserve its three existing guarantees exactly: runs
    at most once (`_aliases_pruned`), is skipped entirely on an empty list so a transient
    empty scan can never wipe every label, and calls `save_config` only when something was
    actually dropped. The only change is what "live" means — the set of alias keys of the
    rendered rows instead of the set of row keys. In default operation `render_sessions` is
    the legacy list object itself, so this is behaviour-identical to today's `sessions` gate.

Tests: add class `Goal6d_AliasKeyedByContainer` to test_monitor.py after `Goal6b_AliasPersistence`,
covering every bullet in `<behavior>`. Follow existing conventions: pure-function tests need
no fixture; scan() tests use `MonitorTestBase` with `_write_session`; MonitorApp tests use the
Goal8 fake-app pattern (a plain local class carrying only the attributes the method under test
touches, invoked as `monitor.MonitorApp._method(fake, ...)`) so nothing imports tkinter. For
`_edit_alias`, give the fake a stubbed `_ask_label`, a `_dialog_open` flag, `config`/
`_session_aliases` bound to the same dict, empty `_session_rows`/`_compact_chips` stores, and
redirect `monitor.CONFIG_FILE` into a TemporaryDirectory the way `Goal6b_AliasPersistence` does.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor.Goal6d_AliasKeyedByContainer -v 2>&amp;1 | tail -20</automated>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor 2>&amp;1 | tail -3</automated>
    <automated>cd /workspace &amp;&amp; test "$(grep -c 'alias_key' monitor.py)" -ge 8 &amp;&amp; test "$(grep -c 'def _alias_key' monitor.py)" = "1" &amp;&amp; test "$(grep -c 'def _prune_aliases' monitor.py)" = "1" &amp;&amp; echo GATE-OK</automated>
    <automated>cd /workspace &amp;&amp; test "$(grep -vE '^[[:space:]]*#' monitor.py | grep -c '_session_aliases\.get(key')" = "0" &amp;&amp; echo NO-RAW-KEY-READS</automated>
  </verify>
  <done>All four gates pass; the full test_monitor suite is green with no fewer than the 105 pre-existing tests still passing; a label set on a row keeps rendering after the row's sessionId (and therefore its key) changes, because both keys resolve to the same container alias key.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Same alias identity in the state-file engine, plus the README config note</name>
  <files>monitor.py, test_monitor.py, README.md</files>
  <read_first>monitor.py lines 550-688 (scan_state_files, especially the hostname local at 630-631, the row dict at 654-673 and the legacy_sessions bridge at 675-683); test_monitor.py lines 947-978 (StateFileTestBase._write_state) and 1210-1293 (Goal13_HooklessFallback); README.md line 73 (config table)</read_first>
  <behavior>
    - A state-file row whose record carries hostname "c1" has alias_key "host:c1"
    - A state-file row whose record omits hostname (or carries a non-string one) has alias_key equal to its session_id — the row key
    - PARITY: for one container, the legacy scan row and the state-file row for the same session carry the SAME alias_key, so a label set in default mode shows in --state-files mode
    - A legacy row carried through the hookless-fallback bridge keeps the alias_key scan() gave it, alongside its legacy_origin marker
    - scan_state_files() called without legacy_sessions forwards container_info to its internal scan(), so the carried-through rows still get container-derived alias keys
  </behavior>
  <action>
In `scan_state_files()`, emit `"alias_key": derive_alias_key(hostname, session_id)` on each
state-file-derived row, reusing the `hostname` local that is already normalised to a non-empty
string or None a few lines above the row dict. Rows carried through the `legacy_sessions`
bridge need no change — they are dict copies and already carry Task 1's alias_key — but the
internal fallback `scan(label_map, sessionid_to_label)` call (taken when `legacy_sessions` is
None, i.e. the `--state-files` diagnostic path) must now also forward `container_info`, or the
diagnostic mode's carried rows would key their aliases differently from the default mode's.

Touch nothing else in this function: the staleness gate, the paused-container branch, the
prune sweep, the sort and the legacy bridge all stay exactly as they are, and no divergence
or shadow-selection code is modified — this task only adds one field to a dict.

Tests: add class `Goal6e_AliasKeyParityAcrossEngines` to test_monitor.py next to
`Goal13_HooklessFallback`, reusing that class's dual-TemporaryDirectory setUp shape (both
PROJECTS_DIR and STATE_DIR redirected) to prove the parity bullet with one jsonl session and
one state file for the same sessionId and hostname.

README.md: the config table row for `aliases` currently reads "per-session display names
(managed from the UI)". Update it to say the labels are per-container and survive /clear and
CLI restarts, so the documented behaviour matches what ships.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor.Goal6e_AliasKeyParityAcrossEngines -v 2>&amp;1 | tail -20</automated>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor test_state_writer test_event_logger 2>&amp;1 | tail -3</automated>
    <automated>cd /workspace &amp;&amp; test "$(grep -c 'per-container' README.md)" -ge 1 &amp;&amp; echo README-OK</automated>
    <human-check>Start the monitor, click a session row and set a label (e.g. "RAM"). In that container run /clear, then send one prompt so the jsonl rotates to the new sessionId. The amber label must still be on the row. Then close and restart the monitor: the label must still be there after the startup prune.</human-check>
  </verify>
  <done>Both engines emit the same alias_key for the same container; all three test suites are green; the README config table describes per-container labels.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| docker daemon → monitor process | `docker ps` / `docker inspect` / `docker exec` stdout is parsed; hostname strings now become persisted config dict KEYS |
| container (hook-written state file) → monitor process | `~/.claude/monitor-state/<sid>.json` `hostname` field is written inside the container and now feeds the same key namespace |
| monitor process → config file on disk | user-typed label text plus derived alias keys are serialised to JSON and re-read on the next start |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-kgw-01 | Tampering | `derive_alias_key` key namespace | low | mitigate | Container-derived keys are namespaced with `ALIAS_HOST_PREFIX`, so a hostname string can never collide with (and silently steal) a sessionId- or dir-keyed alias entry |
| T-kgw-02 | Tampering | `load_config` aliases sanitiser | low | mitigate | Unchanged and still enforcing string-key/non-blank-string-value pairs on every load; `json.dumps` escapes any exotic character a hostname carries. Goal6b regression tests stay green as the gate |
| T-kgw-03 | Denial of Service | config file growth via alias-key churn | low | mitigate | The one-time startup prune (now `_prune_aliases`) keeps the dict bounded by live containers; its empty-list guard is preserved so a transient empty scan cannot instead wipe every label |
| T-kgw-04 | Information disclosure | notification body (`_notify`) | low | accept | The alias is user-authored text already sent to the toast and Telegram today; re-keying changes which label is looked up, not what is transmitted |
| T-kgw-05 | Spoofing | compromised container setting a colliding `hostname` in its state file | low | accept | A container able to forge that field already has write access to the shared `~/.claude` mount; worst case is two rows sharing one cosmetic label. No security decision is derived from an alias |
| T-kgw-SC | Tampering | supply chain | n/a | accept | No package-manager installs in this task — stdlib only, zero new dependencies, so the legitimacy gate does not apply |
</threat_model>

<verification>
1. `python3 -m unittest test_monitor test_state_writer test_event_logger` — all green, no fewer than the 105 pre-existing test_monitor tests.
2. `git diff --stat` — only monitor.py, test_monitor.py and README.md touched.
3. `git diff monitor.py | grep -E '^[-+].*(diff_verdicts|filter_divergence_events|write_divergences|select_render_sessions)'` returns nothing but the unchanged-context lines around the `scan(...)` call — no shadow-engine or divergence logic was modified (Phase 02 D-01).
4. Human check from Task 2: label survives /clear and a monitor restart.
</verification>

<success_criteria>
- A label follows the container across /clear, /resume and CLI restarts, in both the overlay row and the ready-notification.
- Aliases persisted under old sessionId keys are dropped once by the existing startup prune, with no migration code added.
- Sessions with no resolvable container identity behave exactly as before.
- The two engines agree on alias identity, so the `--state-files` diagnostic mode renders the same labels.
- Shadow-mode plumbing (diff/episode/divergence log, `select_render_sessions`) is untouched.
</success_criteria>

<output>
Create `.planning/quick/260730-kgw-fix-session-aliases-lost-on-clear-key-al/260730-kgw-SUMMARY.md` when done
</output>
