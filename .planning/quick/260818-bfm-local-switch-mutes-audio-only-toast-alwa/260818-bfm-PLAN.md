---
phase: quick-260818-bfm
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - test_monitor.py
  - monitor.py
  - README.md
autonomous: true
requirements: [QUICK-260818-bfm]

estimate:
  tokens: 34000
  raw_tokens: 34000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "With `local` set to false, `_notify()` still calls `_notify_toast()` exactly once with the same title/body it would have used when the switch was on — the popup is no longer a casualty of muting the desk"
    - "With `local` set to false, `_notify()` still attempts the Windows taskbar flash — the flash helper is invoked unconditionally, and only `os.name` decides whether the OS call happens"
    - "With `local` set to false, no audio path runs at all: no winsound PlaySound, no MessageBeep, no Tk bell, and no NOTIFY_REPEAT replay chain scheduled through `root.after` — the audio helper is simply never called"
    - "With `local` set to true (and with the key absent from the config entirely, which defaults to true), all three channels fire exactly as they do today — toast, audio, flash"
    - "The Telegram gate stays completely independent of the audio gate in both directions: `local` false + `telegram` true still pushes to the phone, `local` true + `telegram` false still stays off the phone"
    - "The audio behaviour itself is byte-for-byte the behaviour that ran inline before: the same NOTIFY_WAV_FILES walk, the same MessageBeep and Tk-bell fallbacks, the same replay chain gated on a captured replay callable and NOTIFY_REPEAT > 1 — extraction into a helper changes where it lives, never what it does"
    - "The config key stays `local` and `load_config()` is untouched: the legacy `sound` migration, the non-bool coercion to true, and the round-trip through the config file all keep working exactly as their existing Goal6c tests assert"
    - "Every prose claim in monitor.py that described the switch as covering the popup or the flash is rewritten to describe an audio-only mute — the DEFAULT_CONFIG comment on the `local` key, the `load_config()` migration comment, the `_notify_toast` docstring, the `_send_telegram` docstring, and the `_notify` docstring — so the file is never self-contradictory about its own gating"
    - "README's configuration table row for `local` and its notification feature bullet describe an audio-only mute, so a user reading the docs is not told the switch hides the toast"
    - "The full test suite is green and strictly larger than the 198 tests that were green before this task; no pre-existing assertion is deleted or weakened"
  prohibitions:
    - "MUST NOT rename, split or deprecate the `local` config key, and MUST NOT touch `load_config()` / `save_config()`. Users have this key on disk today; the semantics narrow, the key does not move"
    - "MUST NOT add a new config key for audio (no `sound`, no `audio`, no `toast`). The requested behaviour is one switch with narrower reach, not a second switch — a new key would silently un-mute every machine that already has `local` false"
    - "MUST NOT let the audio helper's failure stop the flash, or the toast helper's failure stop either of the others. Each channel keeps its own broad try/except and `_notify()` must never branch on one channel's return value to decide whether another runs"
    - "MUST NOT build a tooltip framework, a hover-text widget or any new UI mechanism for the header button — monitor.py has no tooltip system today, and the 🔔/🔕 glyphs already read as sound. Only the explanatory comment near `_refresh_local_btn` changes"
    - "MUST NOT change `notification_text()`, `notification_record()`, `log_notification()`, `_check_transitions()` or the group-gate logic. The decision of WHETHER to notify is untouched; only the fan-out to channels changes"
    - "MUST NOT stage or commit any file outside the three in files_modified, and MUST NOT `git add -A` / `git add .`. The five hooks/* entries showing as modified in `git status` are a stale stat cache, not edits — staging them would fabricate a commit out of nothing"
    - "MUST NOT install any npm/pip/cargo package — this is a standard-library-only project by design"
  artifacts:
    - path: "test_monitor.py"
      provides: "Goal28_LocalSwitchMutesAudioOnly — the three-channel contract at both switch positions, the Telegram independence pair, the default-on case, plus real-code coverage of the two extracted helpers on a non-Windows host"
      contains: "Goal28_LocalSwitchMutesAudioOnly"
    - path: "monitor.py"
      provides: "`_notify()` re-gated so `local` governs audio only, with `_notify_audio()` and `_flash_taskbar()` extracted as the seams that make the gating assertable without tkinter or Windows"
      contains: "_flash_taskbar"
    - path: "README.md"
      provides: "Configuration table row and notification bullet describing the switch as an audio-only mute"
      contains: "mutes the sound only"
  key_links:
    - "The extraction is what makes the requirement testable at all. The flash lives behind `os.name == \"nt\"` and a `ctypes.windll` call that cannot run on the Linux test host — asserting 'the flash still fires when muted' is impossible against inline code, because the block would be skipped for the wrong reason. Behind `_flash_taskbar()` the test stubs the helper and asserts the call, so the assertion is about the gate and not about the platform"
    - "`_notify()` must read the switch exactly once, into a single local flag consumed only by the audio branch. If any second `self.config.get(\"local\")` read survives elsewhere in the notification path, the split silently half-applies and the toast stays muted on the branch nobody tested"
    - "The replay chain must move INTO the audio helper, not stay behind in `_notify()`. It is scheduled from the replay callable that the winsound path captures; left behind, it either loses its input or keeps a second audio side-effect running outside the mute gate — the exact bug this task exists to remove"
    - "The RED step is meaningful here precisely because two of the new assertions already pass against the old code (audio suppressed when muted, Telegram independence). Only the toast-fires and flash-fires assertions go red, which is the proof that the failing tests are measuring the requested change and not the harness"
    - "`git status` reports monitor.py and test_monitor.py as modified while `git diff HEAD --raw` returns nothing — the working tree content is identical to HEAD and the flags are stat noise from the 9p mount. This is why whole-file staging of the three edited files is safe here, and why the executor must re-confirm it with the precondition instead of taking it on faith"
---

<objective>
Make the monitor's local-notification switch mute the audio channel only. Today `local: false` silences the toast, the audio and the taskbar flash together; after this task it silences audio alone, and the toast plus the taskbar flash always fire.

Purpose: muting the desk should stop the noise, not blind the overlay. A user who mutes the sound during a call still needs to see which session came back to them.
Output: `_notify()` re-gated behind two extracted channel helpers, a new test class locking the contract at both switch positions, and monitor.py/README prose that no longer claims the switch covers the popup or the flash.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

Source files are read per-task with explicit line ranges — monitor.py and test_monitor.py are 2861 lines each and must not be read whole.
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: RED — lock the three-channel contract in test_monitor.py</name>
  <files>test_monitor.py</files>
  <precondition>`git diff HEAD --raw -- monitor.py test_monitor.py README.md` prints nothing before the first edit — the ` M` flags in `git status` for these files and for hooks/* are a stale 9p/WSL stat cache, not content. If it prints any hunk, stop and report: whole-file staging would then sweep up unrelated work.</precondition>
  <read_first>
    - test_monitor.py lines 2597-2660 — `Goal27_NotificationGateWiring` and its `_fake_app()` helper: the established pattern for driving an unbound `monitor.MonitorApp` method against a plain local class with no tkinter.
    - test_monitor.py lines 980-1036 — `Goal6c_NotificationToggles`, whose class docstring currently describes the switch as covering all three channels.
    - monitor.py lines 2390-2495 — the current `_notify()` body, so the Fake stubs match the real call sites.
    - monitor.py lines 1400-1415 — `notification_text()`, the single builder of the toast title/body.
  </read_first>
  <behavior>
    New class `Goal28_LocalSwitchMutesAudioOnly(unittest.TestCase)`, appended after `Goal27_NotificationGateWiring`, driving `monitor.MonitorApp._notify(fake, "proj", 600, key=None)`:
    - local false → `_notify_toast` called exactly once, with the title/body `notification_text("proj", 600, "")` returns
    - local false → `_notify_audio` never called
    - local false → `_flash_taskbar` called exactly once
    - local true → all three called exactly once
    - `local` key absent from config → treated as on: all three called
    - local false + telegram true → `_send_telegram` called once (phone push survives the mute)
    - local true + telegram false → `_send_telegram` never called (mute is not a telegram switch)
    - real `monitor.MonitorApp._flash_taskbar(fake)` on this non-Windows host returns False, raises nothing, and touches no OS call
    - real `monitor.MonitorApp._notify_audio(fake)` on this non-Windows host falls through winsound's absence to the Tk bell: returns ok True with a non-empty channel string, calls `root.bell` exactly once, and schedules no replay (`root.after` never called)
    Expected RED shape: the two toast/flash assertions fail as assertion failures, the two real-helper tests error on the not-yet-existing attributes, and the audio-suppressed / telegram / default-on assertions already pass against the old code.
  </behavior>
  <action>
    Add the class described in behavior, following `Goal27._fake_app()`'s shape: a plain `class Fake` defined inside a `_fake_app(self, **config)` helper, no tkinter, no MonitorApp instantiation. The Fake carries `config` (a dict built from the helper's kwargs), `_session_aliases = {}`, an `_alias_key` returning its argument, `_dismiss_session_toast` as a no-op, recording stubs for `_notify_toast` (returning True), `_notify_audio` (returning a two-tuple), `_flash_taskbar` (returning False) and `_send_telegram`, and a `root` stub object recording `bell`, `after` and `update_idletasks` calls. Pass `key=None` so the alias lookup is skipped.

    For the two real-helper tests, call the unbound `monitor.MonitorApp._notify_audio` / `monitor.MonitorApp._flash_taskbar` against a Fake that has only `root` — these are the tests that prove the extraction in Task 2 preserved behaviour rather than merely moved code.

    Also rewrite the `Goal6c_NotificationToggles` class docstring so it describes `local` as the audio mute and `telegram` as the phone push, and adjust the inline comment in `test_legacy_sound_key_migrates_into_local` to note that the migration is now semantically exact — the legacy key gated audio only, and so does the key it migrates into. Do not touch any assertion in that class; the persistence and coercion contract is unchanged.

    Do not modify monitor.py in this task.
  </action>
  <verify>
    <automated>python3 -m unittest test_monitor.Goal28_LocalSwitchMutesAudioOnly -q 2>&1 | grep -q 'FAILED (failures=' && test "$(python3 -m unittest test_monitor 2>&1 | grep -E '^(FAIL|ERROR):' | grep -v 'Goal28_LocalSwitchMutesAudioOnly' | wc -l)" -eq 0</automated>
  </verify>
  <done>Goal28 exists and fails with genuine assertion failures; every failure and error in the full run belongs to Goal28, proving the other 198 tests are untouched.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: GREEN — re-gate `_notify()` so the switch mutes audio only</name>
  <files>monitor.py</files>
  <read_first>
    - monitor.py lines 195-245 — DEFAULT_CONFIG (the `local` and `telegram` comments) and `load_config()`'s migration comment.
    - monitor.py lines 1917-1930 — `_refresh_local_btn` / `_toggle_local`.
    - monitor.py lines 2271-2282 — `_notify_toast`'s docstring.
    - monitor.py lines 2354-2360 — `_send_telegram`'s docstring.
    - monitor.py lines 2390-2495 — `_notify()` in full.
  </read_first>
  <behavior>
    Turns Goal28 green without editing test_monitor.py. Every other test class stays green unmodified, in particular Goal6c (config persistence) and Goal27 (notification gate wiring).
  </behavior>
  <action>
    Extract two channel helpers as methods on MonitorApp, placed immediately before `_notify()`:

    `_notify_audio(self) -> tuple[bool, str]` takes the current audio block verbatim — the winsound import, the NOTIFY_WAV_FILES walk with SND_FILENAME|SND_ASYNC, the captured replay callable, the MessageBeep fallback, the except-branch Tk bell — and returns the `(audio_ok, audio_channel)` pair it already computes. The NOTIFY_REPEAT replay chain moves inside this helper with it, unchanged in shape: scheduled through `self.root.after(NOTIFY_REPEAT_INTERVAL_MS, ...)` only when a replay callable was captured and NOTIFY_REPEAT > 1. The helper recomputes `verbose` from sys.argv itself, the way `_send_telegram` already does, and keeps its existing verbose stderr diagnostics.

    `_flash_taskbar(self) -> bool` takes the taskbar block verbatim, including the `self.root.update_idletasks()` warm-up that currently sits just above it and the `os.name == "nt"` guard, which moves INSIDE the helper so callers need no platform knowledge. It returns the existing `flash_ok` value and keeps its verbose diagnostics. On a non-Windows host it returns False without touching ctypes.

    Then rewrite `_notify()`'s body to fan out on three independent decisions: read the switch exactly once into a single flag whose only consumer is the audio branch; build the title/body through `notification_text()` as today; push to Telegram behind its own unchanged gate; call `_notify_toast(...)` unconditionally; call `_notify_audio()` only when the switch is on, substituting a `(False, ...)` pair with a distinguishable muted channel string otherwise; call `_flash_taskbar()` unconditionally. Preserve every verbose `[notify] ...` diagnostic line, with the muted case printing something that reads as deliberately silenced rather than as a failure. Keep the `--test-notify` entry point working — it drives this same method.

    Truth up the prose in the same pass, since these lines are the reason the old behaviour looked intentional:
    - the DEFAULT_CONFIG comment above the `local` key, which currently claims the switch covers all three channels — it now mutes audio and nothing else
    - the DEFAULT_CONFIG comment above `telegram`, whose "mute the desk" aside should now say the desk goes silent but stays visible
    - the `load_config()` comment above the legacy-key migration, which calls the destination a master switch — the migration is now semantically exact, since both keys gate audio alone
    - `_notify_toast`'s docstring, whose closing paragraph asserts the toast is only reached when local notifications are on — the toast is now unconditional
    - `_send_telegram`'s docstring, whose parenthetical lists what always fires first — toast and flash always do, audio only when unmuted
    - `_notify`'s own docstring, which must state the three gates plainly
    - a short comment above `_refresh_local_btn` recording that the 🔔/🔕 button mutes audio only

    Do NOT rename the `local` config key, do NOT touch `load_config()`/`save_config()` logic, do NOT add a tooltip mechanism (none exists in this file), and do NOT change `_toggle_local`'s persistence behaviour.
  </action>
  <verify>
    <automated>python3 -m unittest test_monitor -q && test "$(grep -c 'def _notify_audio' monitor.py)" -eq 1 && test "$(grep -c 'def _flash_taskbar' monitor.py)" -eq 1 && test "$(grep -c 'toast_ok = self._notify_toast(toast_title, toast_body, key=key)$' monitor.py)" -eq 1 && test "$(grep -c 'flash_ok = self._flash_taskbar()$' monitor.py)" -eq 1 && python3 -c "import ast,sys; sys.exit(0 if ast.parse(open('monitor.py').read()) else 1)"</automated>
  </verify>
  <done>Full suite green with more than 198 tests; the toast and flash call sites end at the call with no trailing conditional, proving both channels are unconditional; both helpers exist exactly once.</done>
</task>

<task type="auto">
  <name>Task 3: Truth up README's description of the switch</name>
  <files>README.md</files>
  <read_first>
    - README.md lines 22-31 — the "What it does" bullets (notification bullet and the Telegram bullet).
    - README.md lines 78-89 — the configuration table.
  </read_first>
  <action>
    Rewrite the configuration table row for `local` so it describes an audio-only mute and states explicitly that the toast and the taskbar flash always fire. Extend the notification bullet in "What it does" with the sentence `The bell button mutes the sound only; the toast and the taskbar flash always fire.` so a reader meets the semantics before the config table. Leave the Telegram bullet's independence claim intact — it is still true — and change nothing else in README.
  </action>
  <verify>
    <automated>test "$(grep -c '^| `local` |' README.md)" -eq 1 && grep '^| `local` |' README.md | grep -qi 'sound' && grep '^| `local` |' README.md | grep -qi 'toast' && test "$(grep -c 'mutes the sound only' README.md)" -eq 1</automated>
  </verify>
  <done>The `local` row names sound and toast with the narrowed semantics, and the feature bullet carries the one-sentence clarification.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `~/.claude-monitor-config.json` (hand-editable) → `_notify()` gating | User-controlled JSON decides whether a channel fires; `load_config()` is the only sanitiser |
| `_notify()` → the user's attention | This is the last hop of the whole product: a channel that silently stops firing is a session the user is never told about |
| `_notify()` → Windows OS calls (winsound, ctypes/FlashWindowEx) | Native calls that raise differently per host; they run inside the notification path and must never abort it |
| Toast Toplevel → whatever is on screen | The popup now renders on a machine where the user deliberately asked for silence |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-bfm-01 | Denial of service | `_notify()` channel fan-out | high | mitigate | A botched split could drop a channel for everyone, and a missed notification is this product's only real failure mode. Task 1 asserts all three channels at both switch positions plus the key-absent default before the code changes, and the toast/flash call sites are gated by `$`-anchored greps proving no conditional survived on either line |
| T-bfm-02 | Denial of service | Extracted `_notify_audio()` / `_flash_taskbar()` | high | mitigate | Each helper keeps its existing broad try/except so a winsound or ctypes failure returns a falsy result instead of propagating; `_notify()` never branches on a helper's return value to decide whether the next channel runs, so no channel can be starved by another's failure. Real-code tests exercise both helpers on the non-Windows host to prove they degrade rather than raise |
| T-bfm-03 | Information disclosure | Toast rendered while the user has muted the desk | medium | accept | The popup now appears in situations where the machine was previously silent AND blank — e.g. a screen-shared call. This is the explicitly requested behaviour, and the toast body is the unchanged `notification_text()` output (project label, optional alias, elapsed time): no new field, no new data source. Users who need the screen clear can close the overlay or use the compact mode |
| T-bfm-04 | Tampering | Hand-edited config with a hostile `local` value | low | mitigate | `load_config()` is untouched: a non-bool `local` still coerces to true, and the legacy `sound` key still migrates. Goal6c's existing coercion and round-trip assertions must stay green unmodified, which the full-suite gate enforces |
| T-bfm-05 | Tampering | Commit hygiene on a tree with stale stat flags | medium | mitigate | Five hooks/* files show as modified with zero content diff. The plan's precondition re-confirms `git diff HEAD --raw` is empty before editing, commits stage only the three named files by explicit path, and `git add -A`/`git add .` are prohibited |
| T-bfm-SC | Tampering | npm/pip/cargo installs | high | mitigate | No package installs in this plan — the project is standard-library-only and no package-manager task exists, so the legitimacy gate has nothing to clear |
</threat_model>

<verification>
- `python3 -m unittest test_monitor -q` green, test count strictly greater than the 198 green before this task
- `python3 -m unittest test_monitor.Goal28_LocalSwitchMutesAudioOnly -v` green, covering both switch positions, the default-on case, the Telegram independence pair, and both extracted helpers against real code
- `git diff HEAD --stat` at the end lists exactly monitor.py, test_monitor.py and README.md (plus the .planning artefacts) — no hooks/* entry
- Manual smoke (optional, Windows host only, not a gate): set `local` false in the config, run `python monitor.py --test-notify`, confirm the popup appears and the taskbar icon flashes while nothing is heard
</verification>

<success_criteria>
- `local: false` produces toast + taskbar flash and no sound of any kind, including no replay chain
- `local: true` and a config with no `local` key both produce all three channels, unchanged from today
- The Telegram gate is unaffected in both directions
- No prose in monitor.py or README still claims the switch hides the toast or the flash
- The `local` config key, its legacy `sound` migration and its persistence behaviour are byte-for-byte unchanged
- Three commits, one per task, each staging only its own file
</success_criteria>

<output>
Create `.planning/quick/260818-bfm-local-switch-mutes-audio-only-toast-alwa/260818-bfm-SUMMARY.md` when done
</output>
