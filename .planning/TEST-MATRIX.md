# Live test matrix — hook coverage verification

Goal: before (and during) the hook-driven refactor, verify for each real-world
case **which hook event fires** and whether it is enough to derive the correct
state — or whether jsonl/lock fallback remains necessary (hybrid model).

How to use: the instrument already exists — `hooks/event-logger.sh`
(installed/removed via `hooks/install.sh` and `hooks/install.sh
--remove-logger`) appends every Claude Code hook event as one JSONL line to
`~/.claude/hook-events.log`. Follow
[01-UAT.md](phases/01-hook-coverage-verification/01-UAT.md) end to end — it
gives the exact trigger and the exact observation command for every row
below — and fill in the last two columns of this table as you go. Cases
marked ⚠ are the ones that historically broke transcript parsing — they
decide the hybrid question.

Expected states: `working` (grey), `waiting` (green, notify), `needs_input`
(green, notify — permission/AUQ).

| # | Case | How to trigger | Expected state | Candidate hook signal | Suspected gap / fallback | Verified (date, CC version, outcome) |
|---|------|----------------|----------------|----------------------|--------------------------|--------------------------------------|
| 1 | Turn start | Submit any prompt | working | `UserPromptSubmit` | — | 2026-07-29 / cc 2.1.220 / CONFERMATO — fire su ogni prompt (14 righe, 3 sessioni, run opportunistico) |
| 2 | Normal turn end (text reply) | Short Q&A prompt | waiting | `Stop` | Verify `Stop` fires AFTER rendering (would fix early-notify by construction) | 2026-07-29 / cc 2.1.220 / PARZIALE — Stop fire affidabile a fine turno (10/10 turni); sub-domanda "dopo il rendering" richiede ancora confronto visivo con overlay |
| 3 | ⚠ Long multi-tool turn (10+ min) | Big task, many tool calls | working throughout | `PostToolUse` heartbeat | Gaps > heartbeat window during pure thinking/generation stretches? | 2026-07-29 / cc 2.1.220 / PARZIALE — heartbeat = PreToolUse/PostToolUse + NUOVO evento PostToolBatch (tool result batchati, porta tool_calls); osservato gap muto di 29s in pura generazione testo (PostToolBatch 09:33:04 → Stop 09:33:33); turno 10+min non ancora esercitato. AGG h13: heartbeat include anche PostToolUseFailure (tool falliti emettono evento, 4 osservati, porta error/duration_ms/is_interrupt) |
| 4 | ⚠ Permission prompt | Tool not in allowlist (e.g. dangerous rm) | needs_input | `Notification` | Does it fire for ALL prompt types (Bash, MCP, file writes)? | 2026-07-29 / cc 2.1.220 / CONFERMATO — all apparizione del prompt: PreToolUse + PermissionRequest ISTANTANEI; Notification(notification_type=permission_prompt) arriva ~6s dopo (prima Notification su 1300+ righe). needs_input hook-nativo via PermissionRequest, più tempestivo e affidabile di Notification (su cui poggia l attuale fix auq-lock). In bypassPermissions il prompt non esiste proprio |
| 5 | Permission answered → resumes | Approve the prompt in #4; also test DENY (Claude continues with a refusal message) | working | next `PostToolUse`? `PreToolUse`? | Window between approval and next event where state is stale; deny path has no tool execution at all | 2026-07-29 / cc 2.1.220 / CONFERMATO — approva: PostToolUse marca la ripresa nell istante, nessuna finestra stale. Nega: dopo PermissionRequest silenzio hook TOTALE — PermissionDenied mai fire (0 su tutta la campagna), niente Stop: il turno muore come un Esc → stesso fallback staleness |
| 6 | ⚠ AskUserQuestion modal | Ask Claude to use AskUserQuestion | needs_input | No PreToolUse/PostToolUse hook fires — research-confirmed via issues 28273, 12605, 15872; awaiting live confirmation on tester's version | auq-lock remains the needs_input source — research-confirmed, not yet live-confirmed | 2026-07-29 / cc 2.1.220 / SMENTITA LA RICERCA — il modale AUQ EMETTE PreToolUse(tool_name=AskUserQuestion) + PermissionRequest nello stesso istante (prima occorrenza su 600+ eventi); le issue 28273/12605/15872 valevano per versioni precedenti. needs_input derivabile hook-nativamente: PreToolUse/PermissionRequest(AUQ)=aperto → PostToolUse(AUQ)=chiuso. auq-lock potenzialmente superfluo nel design Phase 2 |
| 7 | AUQ answered → resumes | Answer the modal in #6 | working | `UserPromptSubmit`? `PostToolUse`? | | 2026-07-29 / cc 2.1.220 / CONFERMATO — la risposta al modale emette PostToolUse(tool_name=AskUserQuestion) al momento della risposta (+PostToolBatch); nessun UserPromptSubmit |
| 8 | User interrupt (Esc mid-turn) | Esc during a long turn; also the "yuno" variant: Esc right after a foreground agent returns | waiting | Stop does not fire on interrupt — research-confirmed via official docs + issue 9516; awaiting live confirmation on tester's version | stale-working recovery cannot rely on Stop — research-confirmed, not yet live-confirmed | 2026-07-29 / cc 2.1.220 / CONFERMATO — Esc con tool in esecuzione: dopo PreToolUse silenzio hook TOTALE (no PostToolUse, no PostToolUseFailure/is_interrupt, no Stop) fino al prompt successivo. Fallback stale-working NON può contare su alcun evento: serve heartbeat/staleness. Variante yuno (Esc dopo rientro agent) non ancora testata |
| 9 | ⚠ Session killed mid-turn | `docker kill` / close terminal during a turn | stale file detected | none (by definition) | Staleness design: heartbeat silence ~10 min + `docker ps` cross-check | 2026-07-29 / cc 2.1.220 / CONFERMATO — docker kill: ZERO eventi hook, nessun SessionEnd, la sessione sparisce in silenzio. Al momento del kill il turno era già chiuso con bg task in volo (Stop btc=1, primo campione live del conteggio); variante kill-a-metà-turno non campionata ma hook-side identica per definizione. Staleness heartbeat+docker ps irrinunciabile. AGG: anche docker stop garbato (SIGTERM da UI) NON emette SessionEnd (ultimo evento: PreToolUse mid-turn); docker pause ×2 invisibile agli hook → la staleness deve distinguere status paused (vivo ma congelato) da exited (morto) |
| 10 | `/resume` of a past session | Resume an ended session | working on next prompt | `SessionStart` (source=resume) | Old session's leftover state file; session_id continuity | 2026-07-29 / cc 2.1.220 / CONFERMATO (3 osservazioni) — pattern: sessione-picker temporanea (source=startup) → SessionEnd(reason=resume) sulla picker + SessionStart(source=resume) sull id ORIGINALE della conversazione, stabile attraverso i restart. Lo state file della conversazione ripresa è lo stesso file; unico residuo da gestire: quello della picker (~10s di vita) |
| 11 | `/clear` and `/compact` | Run mid-session | no spurious notify | `SessionStart` (source=clear/compact) | Must not look like a fresh "turn ended" → false green + toast | 2026-07-29 / cc 2.1.220 / CONFERMATO — /clear: SessionEnd(reason=clear)+SessionStart(source=clear) con NUOVO session_id; /compact: PreCompact(trigger=manual)+SessionStart(source=compact) con STESSO id senza SessionEnd; nessuno dei due emette Stop → niente falso verde, marker espliciti. Nota: /clear orfana lo state file del vecchio id (stessa pulizia della picker resume) |
| 12 | Foreground subagent (Agent tool) | Task that spawns gsd-* agent | working (parent) | `SubagentStop` must be IGNORED | Subagent end mistaken for turn end → premature green (the "yuno case") | 2026-07-29 / cc 2.1.220 / CONFERMATO — SubagentStop fire per ogni subagent (9×, porta agent_id/agent_type) e può arrivare DOPO lo Stop del parent (2 occorrenze, +2-3s): va ignorato per lo stato. AGG h13: esiste anche SubagentStart (porta agent_type/agent_id) ma ASIMMETRICO — 2 start vs 26 stop: inaffidabile da solo |
| 13 | Background agent / bg bash completes and re-invokes Claude | `run_in_background` task finishing while idle | working during re-invoked turn | `UserPromptSubmit`? (probably NOT — no user prompt) | If no event: turn invisible until first `PostToolUse` | 2026-07-29 / cc 2.1.220 / CONFERMATO (ipotesi SMENTITA) — la re-invocazione da bg task EMETTE UserPromptSubmit nell istante del completamento (13:03:02): il turno re-invocato è visibile dall inizio come un turno utente normale, nessuna finestra cieca |
| 14 | Clean session exit | Exit Claude Code normally | session disappears | `SessionEnd` | Fires on crash too? (overlap with #9) | 2026-07-29 / cc 2.1.220 / PARZIALE — exit pulito emette SessionEnd reason=prompt_input_exit (2×); il resume-exit usa reason=resume (distinguibili); variante crash RISOLTA: docker kill NON emette SessionEnd (sessione 84f529f7, 13:29) — SessionEnd esiste solo per uscite pulite |
| 15 | Multi-container, sessions in parallel | 2-3 containers, same host `.claude` | independent per-session states | one state file per session_id | session_id collisions; cwd→label mapping from hook payload | 2026-07-29 / cc 2.1.220 / CONFERMATO CON PROBLEMA — 3 container in parallelo (greenlight, cloudrun-jobs, nursy) loggano sullo stesso file senza corruzione (flock ok su mount 9p), session_id distinti; MA cwd NON discrimina il progetto: greenlight e nursy montano entrambi /workspace e i loro jsonl condividono projects/-workspace/ → mapping cwd→label confermato rotto, lo state-writer Phase 2 deve catturare identità container (es. HOSTNAME) nel payload |
| 16 | Two sessions, same project dir | Two terminals in one repo | both visible, distinct | per-session file (id ≠ path) | Legacy parsing had the "killed sibling steals label" bug — must not regress | 2026-07-29 / cc 2.1.220 / CONFERMATO — secondo terminale stesso repo: SessionStart(startup) con id nuovo, stessa cwd; 3 sessioni concorrenti su cwd=/workspace interleaved senza contaminazione. Con state file per-id il furto di label è strutturalmente impossibile; resta la questione display (etichetta), legata all identità container del caso 15 |
| 17 | ⚠ Turn ends with async work in flight (bg shell / Monitor / async agent) | Ask for a bg task, let the turn end | **grey, no notify** (current design: in-flight async work = working) | `Stop` fires at turn end → would flip green | **Design divergence**, not just detection: hooks-only notifies while work is still running. Decide: keep current semantics (needs shell_tracker) or accept green-on-Stop | 2026-07-29 / cc 2.1.220 / DATO — il payload di Stop (e SubagentStop) porta un campo background_tasks: possibile segnale hook-nativo per async-in-flight; run deliberato con bg task pendente. AGG h13: run FATTO — Stop fire con bg task in volo (13:02:38, task vivo fino a 13:03:02): verde-su-Stop confermato come rischio reale, MA lo stesso Stop porta background_tasks nel payload → il segnale per restare grigi è nell evento. Proposta: catturare background_tasks count (solo lunghezza array). Overlay verificato dall utente durante il run: GRIGIO per tutta la durata del bg task — semantica attuale corretta, da replicare |
| 18 | Bg shell / Monitor badges (🔧 count, ⏳) | Bg bash, Monitor tool, KillShell/TaskStop | badge appears/disappears correctly | none in state-file design — `shell_tracker` stays jsonl-based per NOTES.md | "Zero jsonl parsing" is not literally true unless badges are dropped or rebuilt from `PostToolUse` payloads (tool_input/response carry shell/task ids) | |
| 19 | ⚠ Abandoned prompt (no tool ever runs) | Submit prompt, kill Claude's process before first token, keep terminal open | working briefly, then green (today: dedicated prompt-expiry window) | `UserPromptSubmit` only — heartbeat starts at first `PostToolUse`, i.e. never | Staleness design assumes tool-call heartbeats; a turn that dies pre-tool has none. `docker ps` cross-check misses it (container alive) | |
| 20 | Corrupt / partially-written state file | Kill a hook mid-write (or truncate a file by hand) | session unaffected or worst-case shown idle — never crash | — | Hooks must write atomically (tmp + rename); monitor must tolerate garbage, like today's malformed-jsonl tests | |
| 21 | Container without hooks installed | Run a session from an old image, no `settings.json` hooks | visible with degraded state (or explicit "unknown") — not invisible | none, by definition | Migration/hybrid question: fall back to legacy parsing per-session, or require hooks and show "no data"? | |

## Verdict to extract

Fill in every slot below after the live run in
[01-UAT.md](phases/01-hook-coverage-verification/01-UAT.md). This section
cannot be completed vaguely — every hook-silent case needs exactly one row
naming a concrete fallback.

### 1. Hooks-only viable?

- **Yes / No:** _(fill in)_
- **Justification:** _(one line — reference the specific cases that decide
  it: #6 AUQ, #8 interrupt, and the #17/#18 design question)_

### 2. Which fallbacks survive?

For every case whose live run showed no usable hook signal, add exactly one
row. The fallback must be a concrete named mechanism from the available set
— the existing **auq-lock**, **shell_tracker**, a **targeted jsonl peek**, or
the **`docker ps` cross-check** — not "TBD" and not a description of a
mechanism that does not exist yet.

| Case # | Hook signal observed | Fallback that covers it | Why this fallback |
|--------|----------------------|--------------------------|--------------------|
| _(fill in)_ | | | |

### 3. Notification timing (case #2)

- **Measured gap** between perceived render end and the `Stop` event's
  `ts_ms`: _(fill in)_
- **Decision:** drop the NOTES.md debounce idea entirely, or keep it —
  _(fill in)_

### 4. Async-work-in-flight design (case #17)

- **What the live data showed:** _(fill in — does `Stop` fire while
  background shells/agents are still running?)_
- **Decision:** keep current grey-while-working semantics (needs
  `shell_tracker`), or accept green-on-`Stop` — per D-07, preserve current
  semantics unless live data contradicts them: _(fill in)_

---

These answers are the direct input to Phase 2's **ENG-06** fallback coverage
requirement and to the state-writer's event-to-state mapping in
[NOTES.md](NOTES.md) (shadow mode phase).
