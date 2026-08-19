# Roadmap: Claude Greenlight — Hook-Driven State Refactor

## Overview

The monitor moves from *inferring* session state by parsing Claude Code's internal jsonl files to *reading* state that hooks write on official lifecycle events. This can't be done in one leap: hook coverage has unknowns (does AskUserQuestion fire anything? does `Stop` really fire after rendering?) that only the real Windows + Docker environment can answer. So the work runs in three phases that mirror the migration plan in NOTES.md — verify hook coverage live, build the state-writer and run it in shadow mode next to the current parser, then flip the default and delete the old path. Phase 1's live matrix run is the input Phase 2's fallback design depends on: the hybrid verdict decides which hook-silent cases (AUQ, interrupt, async work, badges) need a fallback and what that fallback is.

## Milestones

- ✅ **v1.0 Hook-Driven State Refactor** — SHIPPED 2026-08-19 (3 phases, 11 plans, UAT 11/11, 313 tests) — [archive](milestones/v1.0-ROADMAP.md)

## Next Milestone

Not yet planned — run `/gsd-new-milestone`. Candidates from the backlog and deferred items:
- Remote devbox + mobile notifications (state files already carry `hostname`; transport `~/.claude/monitor-state/*.json`)
- Monitor startup check when hooks are absent (deferred at v1.0 close)
- Local host (non-container) sessions visibility (deferred at v1.0 close)
- V2-02: explicit "no data" UI treatment for hookless sessions
