# Phase 3 — API Coverage Declaration

**This phase integrates no external API, SDK, or service.**

## Reasoning

Phase 3 flips the monitor's state-detection engine from inferred (jsonl parsing) to hook-derived,
deletes the shadow-mode diff/divergence machinery, retires one lock hook, and updates the
documentation to match. None of that touches an external API, SDK, or third-party service surface:

- **`monitor.py`** is Python 3.10+ standard library only (tkinter for the overlay). This phase's
  changes are internal: the render seam flip, the two staleness fallbacks (D-02a/D-02b), the
  `legacy_origin` bridge (D-02c), SessionEnd tombstones, and the unified background-task badge.
  No new network call, no new dependency, no new SDK client is introduced anywhere in this diff.
- **The hooks** (`hooks/state-writer.sh`, `hooks/working-lock.sh`, `hooks/install.sh`) are bash
  and `jq` against the local filesystem — they read a JSON payload Claude Code passes on stdin and
  write a JSON file under `~/.claude/`. Claude Code's hook events are a **local file/process
  interface** (the hook script is invoked as a subprocess with a payload on stdin), not a remote
  API — there is no HTTP call, no auth token, no external endpoint anywhere in the hook contract.
- **Deleted in this phase:** `shell_tracker.py` (jsonl parsing) and the shadow-mode divergence
  logging machinery — removals, not new integration surface.
- **The one existing optional external integration** (Telegram push, `TELEGRAM_BOT_TOKEN`/
  `TELEGRAM_CHAT_ID` in `.env`) is pre-existing, untouched by this phase, and was already covered
  under the project's original v1 requirements — it is not part of Phase 3's diff.

No task in this phase's plans (03-01 through 03-04) adds an `npm`/`pip`/package-manager
dependency, a network client, or a credential of any kind.
