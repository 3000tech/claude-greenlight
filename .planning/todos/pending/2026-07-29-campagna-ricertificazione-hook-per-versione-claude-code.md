---
created: 2026-07-29T13:19:47.524Z
title: Campagna ricertificazione hook per versione Claude Code
area: testing
severity: minor
files:
  - .planning/TEST-MATRIX.md
  - .planning/phases/01-hook-coverage-verification/01-UAT.md
  - hooks/event-logger.sh
  - hooks/install.sh
---

## Problem

Il contratto hook di Claude Code deriva tra versioni — dimostrato dal vivo il
2026-07-29 su cc 2.1.220: AskUserQuestion emette PreToolUse+PermissionRequest
(le issue 28273/12605/15872 lo davano hook-silente su versioni precedenti), ed
esistono eventi non documentati (PostToolBatch, PostToolUseFailure,
SubagentStart). Un major bump (es. cc 3.0) può ribaltare qualunque verdetto
della TEST-MATRIX su cui poggia il design di Phase 2 — stesso rischio dei tre
breakage jsonl storici del monitor. Oggi matrice e runbook vivono in
`.planning/`, che viene archiviato a fine milestone: la campagna sparirebbe
proprio quando servirà rieseguirla.

## Solution

A fine Phase 1 (o come parte di Phase 3 cleanup):
1. Promuovere TEST-MATRIX + runbook 01-UAT da `.planning/` a posizione stabile
   (es. `docs/hook-verification/`), con snapshot/colonna Verified per versione
   Claude Code (i verdetti sono già version-stamped `data / cc X.Y.Z / esito`).
2. Salvare payload reali sanificati da hook-events.log come fixture per
   versione — doppio uso: prova storica + fixture dei test automatici Phase 2.
3. Distillare il sottoinsieme auto-testabile in-sessione (casi 6, 7, 8, 10, 13
   — chiusi oggi dall'interno di una sessione in pochi minuti) in una checklist
   "smoke di ricertificazione" da girare a ogni major bump di Claude Code.
   Lo strumento (event-logger + install/teardown) è già permanente in `hooks/`.
