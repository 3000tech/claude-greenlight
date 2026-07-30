---
created: 2026-07-30T10:40:00.000Z
title: Ghost jsonl rows survive container kill via dir-fallback - consider SessionEnd tombstones
area: general
severity: minor
files:
  - monitor.py:995-1006
  - hooks/state-writer.sh:97-100
---

## Problem

Osservato live durante la UAT Phase 2 (2026-07-30, screenshot docs/Screenshot 2026-07-30 123049.png): due container yunoai, uno killato dopo che la sua sessione (f903ed8f) era terminata pulitamente. La riga della sessione morta resta nel pannello (verde, action "file-history-snapshot") fino a MAX_AGE (1h).

Causa: l'ultima riga del jsonl è un record `file-history-snapshot` SENZA sessionId → la guardia anti-fantasma di `scan()` (che scarta jsonl con sessionId non corrispondente a container vivi) non si applica → scatta il fallback dir-based, e con un solo container superstite sulla stessa workdir il dir diventa non-ambiguo → il jsonl morto eredita l'etichetta del fratello vivo.

Quirk legacy pre-esistente (identico prima di Phase 2, non è una regressione). L'ironia: lo state-writer SA che la sessione è finita (SessionEnd fa `rm -f` dello state file), ma il ponte legacy_origin di `scan_state_files()` ricopia la riga legacy tale e quale, quindi l'informazione va persa e nessuna divergenza viene loggata.

## Solution

Da valutare al flip di Phase 3: sostituire il `rm -f` di SessionEnd con un tombstone (es. file con `state: "ended"`, o marker separato) così il motore nuovo può distinguere "sessione terminata" da "sessione mai tracciata (hookless)" e sopprimere il fantasma jsonl invece di ricopiarlo dal ponte. Il tombstone avrebbe comunque bisogno del prune a 24h già esistente (STATE_PRUNE_AGE_SEC).
