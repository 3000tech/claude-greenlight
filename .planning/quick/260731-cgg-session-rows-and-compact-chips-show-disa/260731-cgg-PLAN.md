---
phase: quick-260731-cgg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - monitor.py
  - test_monitor.py
autonomous: true
requirements: [QUICK-260731-cgg]

estimate:
  tokens: 32000
  raw_tokens: 32000
  tasks: 2
  confidence: low

must_haves:
  truths:
    - "A session running in the SECOND container of a duplicated project renders as `dev-tools-2` — in the standard-mode session row AND in the compact-mode chip — while the first container's session still renders `dev-tools`; today both read `dev-tools`"
    - "A session in a container whose docker name does not start with the project label (pre-launcher random name like `dreamy_bose`), or a session with no resolvable container at all, renders exactly the text it renders today — the project label"
    - "The disambiguated text is used for the WORKING→WAITING notification label too, so the toast names the same session the overlay does"
    - "Session sort order is unchanged: a session displaying `dev-tools-2` keeps sorting at the `dev-tools` launcher position, not at the end of the list"
    - "`s[\"name\"]` remains the project label everywhere it acts as identity — sort key, divergence-log `name` field, and every consumer that is not drawing text"
    - "The display rule is the SAME rule as the docker rows': one prefix test, reused, not a second implementation"
  prohibitions:
    - "MUST NOT modify hooks/, shell_tracker.py, scan_state_files(), select_render_sessions(), diff_verdicts(), filter_divergence_events() or write_divergences() — the shadow-mode review window runs to ~2026-08-06 and both engines' verdicts must stay byte-identical"
    - "MUST NOT change the keys, the values, or the shape of container_info (hostname_to_label / hostname_to_status / sessionid_to_hostname) — the frozen shadow engine reads it; its values stay pure project labels"
    - "MUST NOT change alias behaviour: alias storage key (host:<hostname>), alias precedence, and the alias Label drawn beside the name stay exactly as they are"
    - "MUST NOT change the session row `key`, `alias_key`, dedup, or the sort expression itself"
  artifacts:
    - path: "monitor.py"
      provides: "Pure session display-name resolution reusing container_display_name's prefix rule, a hostname→container-name map produced by scan_containers, a display_name field on scan() rows, and the three display call sites (standard row, compact chip, notification)"
      contains: "session_display_name"
    - path: "test_monitor.py"
      provides: "Goal19 coverage: end-to-end duplicate-container resolution, every fallback branch, sort-unaffected guard, container_info-untouched guard"
      contains: "Goal19"
  key_links:
    - from: "monitor.py::scan_containers"
      to: "monitor.py::scan"
      via: "a NEW fifth return element hostname_to_name, cached on MonitorApp and passed to scan() as a keyword argument — container_info untouched"
      pattern: "hostname_to_name"
    - from: "monitor.py::scan row display_name"
      to: "monitor.py::MonitorApp.refresh session row / _refresh_compact chip / _check_transitions notify"
      via: "session_display_text(s), which falls back to s['name'] for any row lacking display_name (shadow-native rows)"
      pattern: "session_display_text"
    - from: "monitor.py::session_display_name"
      to: "monitor.py::container_display_name"
      via: "delegation — the prefix test lives in exactly one function"
      pattern: "container_display_name\\("
---

<objective>
In compact mode the user sees two chips both reading `dev-tools` and cannot tell which one
needs them. Quick 260731-c52 already fixed this for the DOCKER rows of standard mode
(`container_display_name()`), but the session rows and the compact chips draw `s["name"]`,
which is the project label — and two containers of the same project share that label by
construction.

This task carries the c52 rule up into the session layer: when a session's container is
resolvable and its docker name starts with the project label (launcher scheme `dev-tools`,
`dev-tools-2`), the session's DISPLAYED text becomes the container name. Everything else —
sessions in randomly-named containers, sessions with no container — draws exactly what it
draws today.

The label stays the identity. `s["name"]` is the sort key (`order.get(s["name"], big)`
against `launcher_order()`, which only knows base labels), the divergence log's `name`
field, and the shadow engine's carried value; a suffixed name in that slot would silently
drop the session to the bottom of the list and pollute the frozen comparison. So the
disambiguated text travels in a NEW `display_name` field read only where text is drawn.

Purpose: the overlay exists to point at one specific session. Two identical chips point at
nothing.

Output: `session_display_name()` + `session_display_text()` (pure, module-level, tkinter-free),
a `hostname_to_name` map from `scan_containers()` kept OUT of `container_info`, a
`display_name` field on `scan()` rows, three converted display call sites, and a Goal19 test
class locking the rule, its fallbacks, and the sort guarantee.
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

Repo state: Phase 02 (state-writer shadow mode) executing, SHADOW FREEZE in force until the
~2026-08-06 review. Two engines run every tick: legacy `scan()` (jsonl parsing — drives
rendering and notification) and `scan_state_files()` (hook-written state files, shadow only),
compared each tick by `diff_verdicts()` into the divergence log. This task must leave every
verdict path bit-identical; it only adds a field that no verdict path reads.

Baseline before starting: `python3 -m unittest test_monitor` → **134 tests, OK**.

Shape verified by reading the code (not assumed):

- `container_display_name(c)` monitor.py 1081-1111 (from c52): returns `c["name"]` when it
  `.startswith(c["project"])`, else `c["project"]`; degenerate/missing name falls back to the
  project label. This is THE rule — reuse it, do not restate it.
- `scan_containers()` monitor.py 1114-1231 returns a 4-tuple
  `(rows, label_map, sessionid_to_label, container_info)`.
  - First loop 1151-1157 parses `docker ps` output `ID\tproject-label\tNames\tStatus`:
    it already builds `cid_to_label[parts[0]] = parts[1]` and `rows.append({"project": parts[1],
    "name": parts[2], "status": parts[3]})`. The container NAME per cid is right there —
    nothing new needs fetching.
  - `container_labels`, `hostname_to_label`, `hostname_to_status`, `cid_to_hostname` are all
    declared at 1169-1172, BEFORE the `if ids:` block, deliberately (see the comment at
    1163-1168: a zero-container tick must still leave them defined or the worker thread's
    blanket `except Exception` silently freezes the cache). Any new map must follow that rule.
  - Inspect loop 1190-1206 parses `project\tWorkingDir\tState.Status\tHostname` and fills
    `hostname_to_label[parts[3]]`, `hostname_to_status[parts[3]]`, `cid_to_hostname[cid]` —
    the exact spot where a hostname→container-name map belongs.
  - `label_map` is encoded-dir→label and is deliberately NOT filled when two containers claim
    the same encoded dir (1207-1213, the `pending` ambiguity logic) — which is precisely the
    duplicate-project case this task is about. So per-session resolution runs through
    `sessionid_to_label` (docker exec, `query_container_sessionids` 1234-1269), and the
    hostname arrives through `container_info["sessionid_to_hostname"]`.
  - Three early returns (1133, 1145, 1147) and the final return (1227-1231) must all stay
    arity-consistent.
- `scan()` monitor.py 922-1078: `name` is resolved at 1036-1047 (sessionid_to_label first,
  dir fallback only for jsonls with no sessionId); `hostname` is already resolved at 1049-1051
  from `container_info["sessionid_to_hostname"]` — immediately before the `sessions.append`
  at 1052-1074, so the container hostname is in hand at row-construction time. Sort at 1077:
  `sessions.sort(key=lambda s: (order.get(s["name"], big), -s["mtime"]))` — do not touch.
- Display call sites, all three:
  - standard session row, `MonitorApp.refresh` 2156-2157: `row["name"].config(text=s["name"])`
  - compact chip, `_refresh_compact` 2206-2207: `chip["name"].config(text=s["name"])`
  - notification label, `_check_transitions` 1767: `self._notify(s["name"], ...)`
  The docker-row site at 2131-2133 already uses `container_display_name` (c52) — leave it.
- `_edit_alias` 1716 reads the drawn text (`row["name"].cget("text")`) for its prompt, so the
  dialog will read "Label for dev-tools-2:" after this change. That is the improvement, not a
  regression; the alias STORAGE key is `derive_alias_key`/`host:<hostname>` (474-487, quick
  260730-kgw) and is untouched.
- `scan_state_files()` (frozen) calls `scan(label_map, sessionid_to_label, container_info=...)`
  positionally/by keyword at 702. A new keyword argument with a `None` default keeps that call
  valid without editing the frozen function; shadow-native rows simply carry no `display_name`,
  which is why the read helper must tolerate its absence.
- `diff_verdicts()` 739-777 reads only named fields (`status`, `action`, the two locks, counts,
  `age`, `name`) — an extra `display_name` key changes no divergence record.
- test_monitor.py: tkinter stubbed at import (24-28), `mock` already imported (19),
  `MonitorTestBase` (248-274) swaps `monitor.PROJECTS_DIR` to a temp dir, `_write_session`
  (237-245) writes a jsonl fixture, `_assistant([...], session_id=...)` (45-50) builds records.
  `Goal18_ContainerDisplayName` (1990-2027) is the structural model: plain `unittest.TestCase`,
  one behaviour per test. `Goal12_ContainerInfoShape` (1568-1583) reads `result[3]` by INDEX,
  so appending a fifth return element leaves it green. File footer `unittest.main()` at 2029.
  `_workdir_to_encoded("/workspace")` → `"-workspace"` (298-303).
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: One duplicate-container session, resolved end-to-end and drawn in standard mode</name>
  <files>monitor.py, test_monitor.py</files>
  <read_first>
    monitor.py 1081-1231 (container_display_name + scan_containers), 1036-1078 (scan's name/hostname
    resolution and row construction), 2007-2031 (_kick_docker_query worker), 2049-2052 and 2141-2170
    (refresh's scan call and the standard session-row loop), 1386-1395 (MonitorApp cache fields);
    test_monitor.py 237-274 (fixtures) and 1990-2027 (Goal18 shape).
  </read_first>
  <behavior>
    Thin end-to-end slice through every layer the phase touches, for ONE path only: the second
    container of a duplicated project.
    - `session_display_name("dev-tools", "host2", {"host2": "dev-tools-2"})` → `"dev-tools-2"`
    - `scan_containers()`, fed a two-container `docker ps` + `docker inspect` for the same project,
      returns a fifth element `{"host1": "dev-tools", "host2": "dev-tools-2"}`, and its fourth
      element (container_info) still has exactly the three keys with pure-label values
    - a `scan()` row for a jsonl whose sessionId maps to label `dev-tools` and hostname `host2`,
      given that map, has `name == "dev-tools"` and `display_name == "dev-tools-2"`
    - `session_display_text(row)` on that row → `"dev-tools-2"`
    Write this as ONE test that threads scan_containers' real output into scan() (subprocess and
    query_container_sessionids mocked), so the wiring — not just the rule — is what is proven.
  </behavior>
  <action>
    Add two pure module-level functions immediately after `container_display_name` (monitor.py,
    after line 1111), with docstrings in the established style (WHY it lives outside the UI, what
    the fallback preserves) — the same shape as `derive_alias_key` and `container_display_name`:

    (a) `session_display_name(label, hostname, hostname_to_name)` — resolves the text a session
    row should draw. Returns `label` unchanged when `hostname` is falsy/non-str or
    `hostname_to_name` is empty/None or has no entry. Otherwise delegates to
    `container_display_name({"name": <mapped container name>, "project": label})` so the prefix
    test exists in exactly one place; document that delegation explicitly, since the whole point
    is that docker rows and session rows can never drift apart.

    (b) `session_display_text(s)` — the read side for the three drawing sites: returns
    `s.get("display_name")` when truthy, else `s.get("name")`, else the empty string. Document
    that the fallback is what lets rows produced by the frozen state-file engine (which has no
    display_name) render exactly as they do today, with no edit to that engine.

    In `scan_containers()`: declare `cid_to_name: dict[str, str] = {}` beside `cid_to_label`
    (~1150) and `hostname_to_name: dict[str, str] = {}` beside `hostname_to_label` (~1170) —
    the latter MUST be bound before the `if ids:` block for the reason documented at 1163-1168.
    Fill `cid_to_name[parts[0]] = parts[2]` in the ps loop next to the existing cid_to_label
    assignment, and `hostname_to_name[parts[3]] = cid_to_name.get(cid, "")` in the inspect loop
    next to the existing hostname_to_label assignment. Return it as a NEW FIFTH element from all
    four return statements (the three early returns get `{}`); the fourth element keeps exactly
    its three current keys and values. Update the docstring to describe the new element and state
    that it is kept out of container_info because the state-file engine's cross-check reads that
    dict and its values must stay pure project labels.

    In `scan()`: add a fourth keyword parameter `hostname_to_name: dict[str, str] | None = None`
    (default None keeps the frozen `scan_state_files` call at line 702 valid untouched), and add
    `"display_name": session_display_name(name, hostname, hostname_to_name),` to the appended row
    dict right after the `"name"` entry — `hostname` is already resolved just above at 1049-1051.
    Leave the sort expression at 1077 exactly as it is.

    In `MonitorApp`: add `self._cached_hostname_to_name: dict[str, str] = {}` beside
    `self._sessionid_to_label` (~1388) with a one-line comment saying it is display-only; unpack
    five values in the `_kick_docker_query` worker (~2014) and assign the new cache; pass
    `hostname_to_name=self._cached_hostname_to_name` to the `scan(...)` call at ~2051. Do not add
    it to the `scan_state_files(...)` call below it.

    Convert ONE display site now — the standard-mode session row at 2156-2157: compute the text
    once via `session_display_text(s)` into a local, compare against `row["name"].cget("text")`,
    and configure only on change (keep the existing no-op-avoidance pattern).

    Tests: add `class Goal19_SessionDisplayName(MonitorTestBase)` after Goal18 (before the
    `unittest.main()` footer) with a class docstring naming the user-facing behaviour. Its first
    test is the end-to-end one described in behaviour: patch `monitor.shutil.which` to a fake
    docker path, patch `monitor.subprocess.run` with a two-call side_effect returning objects with
    `returncode=0` and `stdout` set to a ps payload (`cid1\tdev-tools\tdev-tools\tUp 2 minutes`
    and `cid2\tdev-tools\tdev-tools-2\tUp 1 minute`, tab-separated, newline-terminated) then an
    inspect payload (`dev-tools\t/workspace\trunning\thost1` and `dev-tools\t/workspace\trunning\thost2`),
    and patch `monitor.query_container_sessionids` to return `({"s1": "dev-tools"}, {"s1": "host2"})`.
    Assert the fifth element maps both hostnames to their container names and that the fourth
    element's key set is unchanged; then write a jsonl fixture under `-workspace` with
    `_assistant([_text_block()], session_id="s1")`, call `scan(sessionid_to_label={"s1": "dev-tools"},
    container_info={"sessionid_to_hostname": {"s1": "host2"}}, hostname_to_name=<fifth element>)`
    and assert `name`/`display_name`/`session_display_text` as described. Note in the test docstring
    that label_map is legitimately empty here because two containers share the encoded dir — that
    ambiguity IS the bug's habitat.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor 2>&amp;1 | tail -3 &amp;&amp; grep -vE '^\s*#' monitor.py | grep -c 'def session_display_name' &amp;&amp; grep -vE '^\s*#' monitor.py | grep -c 'def session_display_text' &amp;&amp; grep -vE '^\s*#' monitor.py | grep -c 'hostname_to_name=self._cached_hostname_to_name'</automated>
  </verify>
  <done>
    Test suite is green with at least 135 tests (134 baseline + the end-to-end one). The three grep
    counts are 1, 1, 1. A session in the second container of a duplicated project resolves to
    `dev-tools-2` through the real scan_containers→scan→session_display_text chain, while its
    `name` stays `dev-tools`.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Compact chips and the notification label, plus every fallback and the sort guard</name>
  <files>monitor.py, test_monitor.py</files>
  <read_first>
    monitor.py 1760-1770 (_check_transitions notify call), 2194-2216 (_refresh_compact chip loop);
    test_monitor.py 1023-1101 (Goal6d — how scan() is exercised with container_info) and the Goal19
    class created in Task 1.
  </read_first>
  <behavior>
    - compact chip and notification draw the same resolved text as the standard row
    - first container of the pair (docker name equals the label) → `dev-tools`, i.e. today's text
    - randomly-named container (`dreamy_bose`) → `dev-tools`
    - hostname present but absent from the map, empty map, map omitted entirely, hostname None →
      `display_name` equals `name` in every case
    - a row with no `display_name` key at all (what the frozen state-file engine produces) →
      `session_display_text` returns `name`
    - SORT GUARD: with `launcher_order()` patched to `{"dev-tools": 0, "zeta": 1}`, a `dev-tools`
      session displaying `dev-tools-2` still sorts ahead of a `zeta` session — it does not fall to
      the end of the list
    - container_info keeps exactly its three keys and its values stay project labels
  </behavior>
  <action>
    Convert the two remaining display sites to `session_display_text(s)`, using the same
    compute-once-then-compare-then-configure shape as Task 1's standard row:
    - `_refresh_compact` chip name at 2206-2207
    - `_check_transitions` notification label at 1767 (`self._notify(...)`'s first argument)
    Decision to record in the SUMMARY: the notification label is included because the user
    identifies a session by the text the overlay shows, and a toast naming `dev-tools` while the
    chip reads `dev-tools-2` would point at the wrong container; the churn is one argument.
    Nothing else changes in `_check_transitions` — keys, debounce and toast dismissal all keep
    using `s["key"]`.

    Extend `Goal19_SessionDisplayName` with the remaining behaviours. Prefer direct calls to the
    pure functions for the rule branches (fast, no fixtures) and `scan()` fixtures for the row-level
    fallbacks, following Goal6d's pattern of passing `container_info` explicitly:
    - rule branches: label-equal name, `dreamy_bose`, unknown hostname, empty map, `None` map,
      `None`/empty hostname
    - `scan()` rows: a session with no container_info at all, and one whose hostname has no entry —
      both must have `display_name` equal to `name`
    - `session_display_text` on a dict carrying only `name` (the shadow-engine shape) returns that
      name; on a dict carrying both, the display value wins
    - sort guard: write two fixtures (`-workspace-a` sessionId `s1` label `dev-tools` hostname
      `host2`, `-workspace-z` sessionId `s2` label `zeta`), patch `monitor.launcher_order` with
      `mock.patch.object` to return `{"dev-tools": 0, "zeta": 1}`, scan with
      `hostname_to_name={"host2": "dev-tools-2"}`, and assert the resulting `[s["name"] for s in
      sessions]` is `["dev-tools", "zeta"]` while the first row's display text is `dev-tools-2`
    - container_info guard: reuse the Task 1 mocked scan_containers call (or the docker-absent path)
      to assert the fourth element's keys are exactly the three existing ones and that
      `hostname_to_label`'s values are project labels, not container names

    Do not touch hooks/, shell_tracker.py, or any of the frozen shadow functions.
  </action>
  <verify>
    <automated>cd /workspace &amp;&amp; python3 -m unittest test_monitor 2>&amp;1 | tail -3 &amp;&amp; grep -vE '^\s*#' monitor.py | grep -c 'session_display_text' &amp;&amp; python3 -c "
import subprocess, re
old = subprocess.run(['git','show','HEAD:monitor.py'],capture_output=True,text=True).stdout
new = open('monitor.py').read()
def body(src, name):
    m = re.search(r'\ndef ' + name + r'\(.*?(?=\ndef |\nclass )', src, re.S)
    assert m, 'not found: ' + name
    return m.group(0)
for fn in ('scan_state_files','diff_verdicts','filter_divergence_events','select_render_sessions','write_divergences'):
    assert body(old,fn) == body(new,fn), 'FROZEN FUNCTION CHANGED: ' + fn
print('frozen OK')
" &amp;&amp; git status --porcelain -- hooks shell_tracker.py | wc -l</automated>
  </verify>
  <done>
    Suite green with at least 143 tests. `session_display_text` appears 4+ times in non-comment
    lines of monitor.py (definition plus the three drawing sites). The frozen-function comparison
    prints `frozen OK`. `git status --porcelain` over hooks/ and shell_tracker.py yields 0 lines.
    Two chips for one duplicated project now read `dev-tools` and `dev-tools-2`, and the toast
    names the same thing the chip does.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| docker daemon → monitor process | Container names and project labels are attacker-influenceable strings if an untrusted container runs on the same host; they cross into the overlay's rendered text and into notification payloads |
| monitor → notification sinks (toast / taskbar flash / Telegram push) | The session label already crosses this boundary today; this change widens it from "project label" to "container name" for prefix-matching containers |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-cgg-01 | Spoofing | `session_display_name` | low | mitigate | The prefix test is the containment: a container can only display a string that STARTS WITH its own project label, so it cannot render itself as a different project. A hostile suffix (`dev-toolsXYZ`) can only impersonate a sibling of the same project the user launched |
| T-cgg-02 | Information disclosure | notification label at `_check_transitions` | low | accept | Container names are the same class of local, user-chosen data as the project labels already sent; no new secret category enters the notification path. Accepted for a local single-user overlay |
| T-cgg-03 | Tampering | frozen shadow engine (`scan_state_files`, `diff_verdicts`, `container_info`) | high | mitigate | Structural: the new map is a separate return element, `container_info`'s keys/values are asserted unchanged by a test, and Task 2's verify diffs the frozen function bodies against HEAD and fails on any byte change |
| T-cgg-04 | Denial of service | `scan_containers` inspect loop | low | mitigate | No new subprocess call: the map is built from the two `docker ps`/`docker inspect` invocations that already run, inside their existing 2s timeouts |
| T-cgg-05 | Tampering | dependency installs | low | accept | No npm/pip/cargo install occurs in this task — stdlib only, no new imports. Package Legitimacy Gate not applicable |
</threat_model>

<verification>
1. `python3 -m unittest test_monitor` — green, count strictly greater than the 134 baseline.
2. Frozen-engine gate (Task 2's inline script): `scan_state_files`, `diff_verdicts`,
   `filter_divergence_events`, `select_render_sessions`, `write_divergences` byte-identical to HEAD.
3. `git status --porcelain` shows only `monitor.py` and `test_monitor.py` modified — nothing under
   `hooks/`, no `shell_tracker.py`.
4. `python3 -c "import monitor"` succeeds headless (tkinter stub path already exercised by the suite).
5. Manual smoke (optional, user-side): with two `dev-tools` containers running, the compact bar shows
   two chips reading `dev-tools` and `dev-tools-2`, and the standard-mode session rows agree with the
   docker rows underneath.
</verification>

<success_criteria>
- Compact chips and standard session rows show `dev-tools` / `dev-tools-2` for two containers of the
  same project; the notification label matches the chip.
- Sessions in randomly-named or unresolvable containers render exactly today's text.
- `s["name"]` is still the project label; session sort order is unchanged.
- `container_info` and every frozen shadow function are byte-identical to HEAD.
- Alias storage keys and alias precedence unchanged.
- Test suite green, ≥143 tests.
</success_criteria>

<output>
Create `.planning/quick/260731-cgg-session-rows-and-compact-chips-show-disa/260731-cgg-SUMMARY.md` when done.
</output>
