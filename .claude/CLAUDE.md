<!-- GSD:project-start source:PROJECT.md -->

## Project

**Claude Greenlight — Hook-Driven State Refactor**

Refactor of the claude-greenlight monitor's state-detection engine: today session state (working / waiting / needs input) is **inferred** by parsing Claude Code's internal session jsonl files, with three lock-file hooks bolted on as corrective patches. The refactor inverts the hierarchy: **Claude Code hooks become the primary source of state** (one small state file per session written on official lifecycle events), and jsonl parsing shrinks to targeted fallbacks only where hooks are provably silent (hybrid model).

Design and migration plan already exist in [NOTES.md](NOTES.md); the 21-case verification matrix in [TEST-MATRIX.md](TEST-MATRIX.md) defines what "detected correctly" means.

**Core Value:** The monitor must keep telling the user *"this session needs you now"* reliably — but stop breaking every time Claude Code changes its internal jsonl format (already happened three times). Hooks are a documented, stable interface; state derived from them is correct by construction instead of guessed.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->

## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
