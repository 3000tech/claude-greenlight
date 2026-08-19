---
created: 2026-07-30T10:55:00.000Z
title: Remove dead project_name() helper in monitor.py
area: general
severity: cosmetic
files:
  - monitor.py:279-293
---

## Problem

Analisi dead-code del 2026-07-30 (durante la UAT Phase 2): `project_name()` (monitor.py:279) non è chiamato da nessuna parte — né in monitor.py, né nei test, né in script/hook. Era l'euristico che indovinava l'etichetta dal nome della cartella codificata (encoded dir → ultimo segmento / suffisso launcher label), superseded dalla catena di risoluzione attuale (sessionid_to_label → label_map → hostname_to_label). Unico codice morto del file: metodi di classe e import sono tutti usati.

## Solution

Rimuovere la funzione (~15 righe) in Phase 3, nel giro di refactor del flip. Verifica banale: `grep -rn project_name` deve restituire zero hit fuori dalla definizione; suite test verde.
