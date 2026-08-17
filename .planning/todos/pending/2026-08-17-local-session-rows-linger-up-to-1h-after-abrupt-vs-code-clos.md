---
created: 2026-08-17T14:02:17.237Z
title: Local session rows linger up to 1h after abrupt VS Code close - add local liveness check
area: general
severity: minor
files:
  - monitor.py:78
  - monitor.py:140
  - monitor.py:608
---

## Problem

Osservato live (2026-08-17): chiudendo la finestra di VS Code, il processo Claude Code locale viene ucciso senza che l'hook SessionEnd venga emesso — è una strada hook-silent analoga al container killato (RESEARCH Pitfall 10), ma per le sessioni LOCALI non esiste alcun check di liveness. Il file di stato resta orfano e la riga nel monitor:

1. resta WORKING fino a ~10 min di silenzio heartbeat (STATE_HEARTBEAT_STALE_SEC = 600, monitor.py:78), poi degrada a WAITING;
2. resta visibile come WAITING fino a 1h dall'ultima attività (MAX_AGE_SEC = 3600, monitor.py:140);
3. il file orfano viene ripulito solo dal prune a 24h (STATE_PRUNE_AGE_SEC).

Per i container Docker questo caso è già gestito: la staleness di scan_state_files() viene cross-checkata contro la liveness del container (container_info / paused). Le sessioni locali non hanno un equivalente, quindi "processo morto" e "Claude sta pensando a lungo" sono indistinguibili e la riga fantasma resta davanti all'utente fino a un'ora.

Caso concreto che ha originato il todo: sessione locale nel repo claude-greenlight aperta in VS Code accanto al container Docker omonimo — chiusa la finestra, la voce "claude-greenlight" locale è rimasta nel pannello.

## Solution

Due strade possibili, da valutare:

(a) Liveness check per sessioni locali, analogo al gate docker: lo state file potrebbe registrare il PID del processo Claude Code (state-writer.sh ha accesso all'env dell'hook) e scan_state_files() verificherebbe se il PID è ancora vivo — se morto, degradare/nascondere subito invece di aspettare MAX_AGE_SEC. Attenzione al riuso PID e al caso container (PID namespace diverso: il check deve applicarsi solo alle righe non-container).

(b) Più conservativo: abbassare la finestra di visibilità solo per righe già degradate a stale-WAITING (heartbeat silente da >STATE_HEARTBEAT_STALE_SEC), es. drop a 20-30 min invece di 1h. Nessun nuovo segnale richiesto, ma resta un'euristica.
