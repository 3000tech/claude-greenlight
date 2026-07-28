# claude-greenlight — backlog

- [x] **README screenshot** — capture the overlay with 2-3 live sessions (standard + compact mode) and embed it at the top of the README. Highest-impact single improvement for a visual tool. *(done 2026-07-28 — docs/standard-mode.png, docs/compact-mode.png)*
- [ ] **Packaging + `src/` layout** — restructure to `src/claude_greenlight/` with a `pyproject.toml` and console entry point (pipx/winget installable). Do these together: the `src/` move only pays off with packaging, and both should wait for a signal of external interest (stars/issues). Touches: `monitor.bat`/`monitor-debug.bat` paths, README, test invocation.
- [ ] **Hook-driven refactor** — see NOTES.md in this directory (state files from hooks, drop jsonl parsing). Before starting: verify whether AskUserQuestion emits any hook event on current Claude Code versions.
