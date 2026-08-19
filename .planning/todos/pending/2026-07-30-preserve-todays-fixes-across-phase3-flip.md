---
created: 2026-07-30T17:30:00.000Z
title: Preserve today's fixes (2026-07-30) across the Phase 3 flip
area: general
severity: major
files:
  - monitor.py
  - test_monitor.py
---

## Problem

Il 2026-07-30, durante la finestra di review dello shadow mode, sono entrate modifiche funzionali
sul default path che Phase 3 (flip + rimozione legacy) deve esplicitamente preservare — il rischio
è che la riscrittura dei test e la cancellazione dei percorsi legacy le perda per strada:

1. **Alias keyed by container** (`db8fc86` + `e558946`, quick 260730-kgw): `derive_alias_key()` /
   `ALIAS_HOST_PREFIX = "host:"` è l'identità alias condivisa da ENTRAMBI i motori. Il codice è già
   parity-safe (`scan_state_files()` emette `alias_key`, 5 test `Goal6e` lo provano), MA gli 11 test
   `Goal6d_AliasKeyedByContainer` esercitano `scan()` legacy: al flip vanno **riscritti su fixture
   state-file, non droppati** — coprono la garanzia /clear-survival (sessionId ruota, alias resta).
   Attenzione anche al prune: `_prune_aliases` legge `render_sessions` (oggi = lista legacy);
   post-flip deve leggere la lista del motore state-file.
2. **Multi-monitor fix** (`161bc7f`): toast e dialog alias restano sullo schermo del
   monitor. È UI-level, engine-agnostic — deve sopravvivere invariato, nessun porting necessario,
   ma verificare che il refactor del render loop non lo tocchi.
3. **Soglia notifica = 60s** (`edda3ce` revert di `c17e724`): il valore corrente 60s è quello
   DELIBERATO (il 5s è stato provato e revertito lo stesso giorno). Non "ripristinare" 5s
   leggendo la history.

## Solution

In `/gsd-plan-phase 3`, includere nei must_haves del piano test-rewrite:
- `Goal6d` riscritto contro fixture state-file (stessa garanzia: alias sopravvive a /clear e
  restart monitor); `Goal6e` (parità) può ridursi ai soli percorsi che restano vivi post-flip.
- Grep di controllo: `derive_alias_key`, `ALIAS_HOST_PREFIX`, `_prune_aliases` devono esistere
  e essere raggiunti dal path di default post-flip.
- Nessun cambio a soglia notifiche (60s) e al positioning multi-monitor.
