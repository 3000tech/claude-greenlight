# Hook recertification runbook

Per-version companion to [TEST-MATRIX.md](TEST-MATRIX.md). The hook contract this
project depends on lives entirely inside Claude Code — a major or minor version
bump can silently change which events fire, rename a payload field, or add an
event this repo doesn't register on yet. Re-run this loop whenever that happens,
or any time state detection starts misbehaving in a way that looks version-related.

## When to run it

- After every Claude Code major or minor version bump.
- Any time the monitor's state detection starts misbehaving and a Claude Code
  update is a plausible cause.

## The loop

1. **Install the event logger.**
   ```
   bash hooks/install.sh
   ```
   This installs `event-logger.sh` alongside the shipped hooks and registers it
   on every event name in `hooks/hook-events.json`.

2. **Exercise the matrix cases.** Follow
   [01-UAT.md](../.planning/phases/01-hook-coverage-verification/01-UAT.md) —
   it has the exact trigger and observation command for each of the 21 cases
   in [TEST-MATRIX.md](TEST-MATRIX.md). Re-run the ⚠-marked cases first; they
   are the ones a version bump has historically broken.

3. **Compare against the two registration lists.** A case that looks silent
   because its event was never registered (rather than the hook genuinely not
   firing) is the failure mode both `01-UAT.md`'s Setup and this step exist to
   rule out:
   ```
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("event-logger\\.sh"))] | length' ~/.claude/settings.json
   jq 'length' hooks/hook-events.json
   jq '[.hooks | to_entries[] | .value[] | select(.hooks[]?.command? // "" | test("state-writer\\.sh"))] | length' ~/.claude/settings.json
   jq 'length' hooks/state-writer-events.json
   ```
   Each pair must match.

4. **Remove the logger when done.**
   ```
   bash hooks/install.sh --remove-logger
   ```

## What a failure looks like

- An event that used to fire for a case stops firing.
- A payload field the monitor or a hook script reads changes name or shape.
- A new event exists that should be added to `hooks/hook-events.json` and/or
  `hooks/state-writer-events.json` but isn't yet.

Any of these is a real finding — update the affected row(s) in
[TEST-MATRIX.md](TEST-MATRIX.md) with the new outcome, and open a fix if the
shipped hook mapping needs to change.

## Recording the result

Same convention as `01-UAT.md` and `02-UAT.md`: **date, Claude Code version,
outcome**, written directly into the affected `TEST-MATRIX.md` row(s). "No
change observed" is a valid, valuable outcome and must be written explicitly,
not left blank.

---

Out of scope for this runbook: per-version fixture generation and an
automated smoke-checklist harness. Both stay deferred (see the folded
recertification todo) — this document is the reduced, doc-only promotion
D-10 authorizes, not the full campaign.
