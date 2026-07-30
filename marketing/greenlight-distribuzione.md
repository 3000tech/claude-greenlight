# claude-greenlight — checklist di pubblicazione

Una sera, quaranta minuti. Non è marketing: sono azioni finite che si eseguono
e poi non chiedono più niente. Spunta e chiudi.

Regola: **la release non è "il codice funziona", è "il codice funziona E questa
lista è spuntata".** Se resta una fase separata, arriva quando l'interesse è già
finito, e a quel punto è persa.

---

## Fase 0 — Preparazione (~30 min)

- [ ] **GIF demo, 10-15 secondi**
      Sessione che lavora → diventa verde → toast di Windows.
      Tool: ScreenToGif. Mettila in cima al README, sopra gli screenshot statici.
      *Perché:* il valore del tool è temporale, uno screenshot non lo mostra.
      È la singola cosa che converte di più.

- [x] **Tag di release `v0.1.0`** con note di rilascio
      *Perché:* cambia la percezione da "repo in corso" a "cosa usabile",
      e ti dà un link stabile da citare ovunque.

- [ ] **Topics GitHub** — aggiungi ai 6 esistenti:
      `claude-code-hooks`, `developer-tools`, `notifications`, `productivity`
      *Perché:* è così che ti trovano navigando per topic.

- [ ] **La frase-problema**, in cima al README prima di tutto il resto:
      > Su Windows con Claude Code dentro container WSL2/Docker, nessun monitor
      > vede lo stato live delle sessioni.

      *Perché:* è quello che una persona cerca su Google alle 23.
      Usa **questa** in ogni post, non "attention monitor per Claude Code" —
      generico, ce ne sono venti.

---

## Fase 1 — Il minimo indispensabile (~15 min)

Se fai solo tre cose, sono queste.

- [ ] GIF demo (sopra)
- [ ] Post su **r/ClaudeAI**
      Titolo orientato al problema, non al nome del tool.
      Resta a rispondere ai commenti per le prime ore: è lì che si decide.
- [ ] PR alla awesome-list di **hesreallyhim**
      La più autorevole, curata a mano, accetta anche repo piccoli.

---

## Fase 2 — Il resto delle liste (~15 min)

- [ ] PR a `jqueryscript/awesome-claude-code`
- [ ] PR a `rohitg00/awesome-claude-code-toolkit`
- [ ] ~~`subinium/awesome-claude-code`~~ — **salta**: accetta solo repo con 1.000+ stelle

---

## Fase 3 — Canali secondari (~20 min)

- [ ] **r/ClaudeCode** — stesso post, pubblico denso
- [ ] **r/bashonubuntuonwindows** — nicchia piccola, ma il tuo caso d'uso è
      esattamente il loro dolore quotidiano. Spesso rende più di un post generalista
- [ ] **r/docker** — idem
- [ ] **Discord Anthropic**, canale tool/showcase della community
- [ ] **Show HN** su Hacker News — bassa probabilità con 0 stelle, ma costa 2 minuti.
      Martedì-giovedì, mattina ora USA
- [ ] **Issue nei repo concorrenti** (Sessionly, cctop, claude-semaphore):
      cerca issue aperte tipo *"doesn't work with Docker/WSL2"* e rispondi in modo
      utile linkando il tuo. Distribuzione mirata, non spam
- [ ] **LinkedIn** come 3000Tech — non porta stelle, porta credibilità con i clienti.
      Un tool open source pubblicato vale più di una riga di CV

---

## Dopo

Non c'è un "dopo". Spuntata la lista, greenlight vive o muore da solo e va bene
così. Nessun obbligo di curare una community, presenziare, ripetersi.
Se decolla, decidi allora cosa farne. Se non decolla, hai comunque finito —
e questa volta fino in fondo.

## Se anche così non ti va

La distribuzione la può fare qualcun altro senza che sia barare:
qualcuno che sta già su quei subreddit, con un accordo del tipo
"tu posti, io ti metto nei contributor".
