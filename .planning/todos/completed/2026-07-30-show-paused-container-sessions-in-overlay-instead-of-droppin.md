---
created: 2026-07-30T09:49:21.706Z
title: Show paused-container sessions in overlay instead of dropping them
area: general
severity: minor
files:
  - monitor.py:995-1006
  - monitor.py:630-650
---

## Problem

Emerso durante la UAT live di Phase 2 (C4, 2026-07-30): quando un container viene messo in `docker pause`, la sua sessione sparisce dalla riga sessioni dell'overlay. Il legacy non può fare `docker exec` in un container paused, quindi `sessionid_to_label` perde il mapping e `scan()` scarta la sessione (nome irrisolvibile, monitor.py ~1000). La sezione Docker del pannello invece continua a mostrare il container con stato "(Paused)" — l'utente vede il container ma non la sessione.

Il motore state-file la tiene già: risolve il nome via `hostname_to_label` (docker inspect funziona anche da paused) e la guardia D-06 (`hostname_to_status == "paused"`) la marca alive-but-frozen. Divergenza `legacy=ABSENT vs shadow=WORKING` osservata dal vivo e loggata alle 09:37:37 — è il caso citato testualmente nel docstring di `diff_verdicts()`.

Priorità dell'utente: "nice to have, edge case minimo".

## Solution

Da valutare al flip di Phase 3: il motore nuovo ha già tutte le informazioni per mostrare la sessione con uno stato "paused" visibile (es. badge o colore dedicato) invece di farla sparire. Nessun dato aggiuntivo da raccogliere — solo una scelta di rendering.
