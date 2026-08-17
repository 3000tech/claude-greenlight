---
created: 2026-08-17T14:02:17.237Z
title: Local host sessions are invisible to the monitor - hooks silent on Windows and scan() drops non-container jsonls
area: general
severity: minor
files:
  - monitor.py:1130-1141
  - hooks/settings-snippet.json
---

## Problem

Verificato live (2026-08-17, sessione locale 3f836ffd su Windows host): le sessioni Claude Code LOCALI (fuori container) non compaiono MAI nel monitor. Due cause indipendenti, entrambe confermate:

1. **Gli hook non scattano sul host Windows.** Nessun file di stato in monitor-state e nessuna riga in hook-events.log per la sessione locale, mentre i container ne producono in continuazione. I comandi hook in settings.json sono `bash "$HOME/.claude/hooks/state-writer.sh"` — path/espansione pensati per il container Linux (`/usr/local/bin/node`, `/home/dev/...`); su Windows falliscono silenziosamente.

2. **Anche il fallback legacy scarta la sessione locale.** In `scan()` (monitor.py:1130-1141) una jsonl CON sessionId che non corrisponde a nessun container vivo viene droppata (`continue` quando name resta None): la guardia anti-fantasma pensata per i sibling container killati elimina di fatto ogni sessione host. Il fallback dir-based richiede `proj_dir.name in label_map`, e label_map è costruita solo dai container.

Conseguenza pratica osservata: l'utente lavora in VS Code in locale sul repo claude-greenlight e il monitor non mostra nulla che diventi grigio; le due righe "claude-greenlight" visibili erano entrambe del container omonimo (sessione reale 9ee8f166 + riga fantasma dal probe.json lasciato dal test di quick-260817-ixs, ripulito a mano il 2026-08-17).

NB: questo todo sostituisce il precedente "Local session rows linger up to 1h after abrupt VS Code close", scritto sulla premessa errata che la riga vista fosse la sessione locale. Il caso "linger 1h dopo kill" resta reale ma solo per i container (già coperto dal todo ghost-jsonl del 2026-07-30).

## Solution

Decidere prima se le sessioni host sono IN SCOPE per il monitor (finora è di fatto container-only via launcher). Se sì:

(a) far funzionare gli hook su Windows host — comandi hook portabili (es. `bash -c` con path assoluto Git Bash, o variante .cmd/node) così state-writer.sh scrive lo state file anche in locale; a quel punto il motore state-file rende la riga senza toccare scan();

(b) in alternativa/complemento, allentare la guardia di scan(): una jsonl il cui proj_dir NON è la workdir di nessun container è per definizione una sessione host — non può essere il fantasma di un sibling killato — e potrebbe essere etichettata dal nome della directory invece di essere droppata.

Serve anche un liveness check per il processo locale (PID nello state file?) per non reintrodurre il linger da 1h sulle sessioni host una volta rese visibili.
