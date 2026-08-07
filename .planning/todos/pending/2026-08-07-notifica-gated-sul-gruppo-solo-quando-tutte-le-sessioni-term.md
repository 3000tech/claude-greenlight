---
created: 2026-08-07T13:22:49.040Z
title: Notifica gated sul gruppo - solo quando tutte le sessioni terminano
area: general
severity: major
files:
  - ~/.claude/monitor-state/
  - ~/.claude/working-locks/
  - ~/.claude/hook-events.log
---

## Problem

Caso reale (2026-08-07, notifica "nursy" delle 15:14 locali / 13:14:20Z): il monitor notifica sullo `Stop` di una **singola** sessione anche quando altre sessioni dello stesso gruppo di lavoro stanno ancora lavorando. La sessione `6fff7d17` (gsd-executor fase 18 su nursy_app, host `8d5f9694f1de`) si è fermata a un checkpoint intermedio ("plan 18-02 complete, 1/8 plans done") ed è ripartita da sola ~90s dopo; nel frattempo la sessione gemella `8ced4fe8` (worktree `prd-gsd`, host `4353e1441213`) non si era mai fermata. Risultato: notifica fuorviante — l'utente la legge come "lavoro finito" quando è finito solo un turno di una sessione su n.

Regola voluta dall'utente: con n agenti/sessioni attivi sullo stesso lavoro, lo Stop di uno solo NON genera notifica; la notifica parte solo quando **tutti** i processi del gruppo sono terminati (ultimo Stop con nessun altro membro attivo).

## Solution

I dati per implementare il gate esistono già:
- l'evento `Stop` porta `background_tasks_count` nel payload hook (a 13:14:20 valeva 1 — già da solo avrebbe potuto sopprimere la notifica);
- `working-locks/` + `monitor-state/*.json` (che include `hostname` e `cwd`) danno la vista degli altri membri del gruppo, anche cross-container dato che `~/.claude` è condiviso.

Gate alla notifica: su Stop, notificare solo se (a) `background_tasks_count == 0` e (b) nessun'altra sessione del gruppo è in stato `working` / detiene un working-lock.

Punto aperto: definizione di "gruppo" — probabilmente sessioni che condividono lo stesso project root, tenendo conto che i worktrees `.claude/worktrees/*` mappano al repo principale (nel caso reale: cwd `/workspace` e cwd `/workspace/.claude/worktrees/prd-gsd` erano lo stesso lavoro su host diversi).
