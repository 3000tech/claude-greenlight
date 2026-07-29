# Phase 2: State Writer & Shadow Mode - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-29
**Phase:** 2-state-writer-shadow-mode
**Areas discussed:** Shadow mode e criterio di flip, Nome delle sessioni, Sessioni ferme (staleness), Colore needs_input

---

## 1. Periodo di prova (shadow mode) e criterio di flip

| Option | Description | Selected |
|--------|-------------|----------|
| Differenze visibili nell'overlay | Indizio visivo durante lo shadow | |
| Differenze su file, analisi delegata a Claude | L'agente confronta e riporta | ✓ |
| Flip automatico dopo N giorni | Promozione senza conferma | |
| Flip deciso insieme dopo N giorni senza divergenze | Revisione congiunta | ✓ |

**User's choice:** "puoi confrontare tu col nuovo per vedere se divergono, scelta insieme tra N giorni quando abbiamo N giorni senza divergenze"
**Notes:** "per me l'attuale funziona bene, magari troviamo divergenze in meglio" — le divergenze possono essere migliorie del nuovo motore, non solo bug; il log deve permettere di giudicare chi aveva ragione.

---

## 2. Nome delle sessioni

| Option | Description | Selected |
|--------|-------------|----------|
| Nome container docker (automatico) | | |
| Solo alias manuale | | |
| Automatico + rinominabile | | |
| Come funziona adesso | Nessun cambiamento | ✓ |

**User's choice:** "come funziona adesso va benissimo"
**Notes:** la collisione cwd resta un problema interno del motore (identità container come dato, non come UI).

---

## 3. Sessioni ferme (staleness)

| Option | Description | Selected |
|--------|-------------|----------|
| Nuove soglie / rese distinte per paused/morte | | |
| Come ora | Soglie e comportamenti attuali | ✓ |

**User's choice:** "come ora"

---

## 4. Colore quando Claude aspetta l'utente

| Option | Description | Selected |
|--------|-------------|----------|
| Distinguere fine-turno da richiesta-permesso | Colore/notifica diversi | |
| Uguali come adesso | Verde per entrambi | ✓ |

**User's choice:** "come adesso uguali"

---

## Claude's Discretion

- Schema dello state file oltre il minimo SW-02; formato/posizione del log divergenze; pulizia state file orfani; dettagli implementativi staleness; naming del flag `--state-files`.

## Deferred Ideas

- Todo ricertificazione hook (rivisto, non piegato): materiale da Phase 3/cleanup.
- Swap visivo del badge unificato ◉N: al flip di Phase 3, non durante lo shadow.
