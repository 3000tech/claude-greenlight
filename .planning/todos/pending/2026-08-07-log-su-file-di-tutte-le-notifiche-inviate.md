---
created: 2026-08-07T13:31:00.000Z
title: Log su file di tutte le notifiche inviate
area: general
severity: minor
files:
  - ~/.claude/monitor-state/
  - ~/.claude/hook-events.log
---

## Problem

Richiesta utente (2026-08-07, durante il debug delle notifiche nursy delle 15:14 e 15:28): oggi quando arriva una notifica "dubbia" bisogna ricostruire a mano da `hook-events.log` quale sessione l'ha generata, quando e perché. Un log persistente delle notifiche **inviate dal monitor** (non degli eventi hook grezzi) renderebbe la verifica immediata e darebbe una base per misurare il rumore (quante notifiche premature sopprimerebbe il gate di gruppo).

## Solution

Append-only, un record per notifica inviata, con almeno: timestamp, session_id, hostname/container, cwd/progetto, tipo (needs_input / stop / idle_prompt), testo mostrato, ed esito dell'eventuale gate (inviata vs soppressa e perché — utile insieme al todo "Notifica gated sul gruppo"). Posizione candidata: `~/.claude/monitor-state/notifications.log` o simile, formato jsonl coerente con `hook-events.log`. Loggare anche le notifiche soppresse permette di validare il gate sul campo prima di fidarsene.
