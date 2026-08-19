---
created: 2026-07-30T10:12:00.000Z
title: Startup check - refuse to start with clear error when hooks are not installed
area: general
severity: minor
files:
  - monitor.py
  - hooks/install.sh
---

## Problem

Proposta dell'utente durante la UAT live di Phase 2 (2026-07-30): oggi il monitor parte anche se gli hook non sono installati in `~/.claude/settings.json`, degradando in silenzio (legacy senza lock-correction; dopo il flip di Phase 3 sarebbe peggio: il motore primario resterebbe quasi cieco, solo fallback jsonl). Nessun segnale all'utente che la detection è compromessa.

## Solution

All'avvio, validare `~/.claude/settings.json`: contare le registrazioni per hook come fa il Setup di 02-UAT.md (state-writer.sh = lunghezza di hooks/state-writer-events.json, working-lock.sh = 3, auq-lock.sh = 4). Se mancanti/incomplete: non partire e mostrare un errore chiaro con l'istruzione di fix (`bash hooks/install.sh` da un container col repo).

Da decidere in sede di planning Phase 3 (candidato naturale allo scope del flip): hard-block totale vs avvio degradato con warning esplicito; e se distinguere "mai installati" da "parzialmente installati / contatori sbagliati".
