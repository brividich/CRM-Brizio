# MIGLIORAMENTI FORMAZIONE (modulo e-learning)

Analisi statica del modulo e-learning nativo (micro-corsi: slide + quiz) dentro l'app `anagrafica`.
Data analisi: 2026-07-13. Nessuna modifica applicata; test non eseguiti.

Perimetro: modelli in `models_formazione.py` (TrainingSlide, TrainingQuizQuestion/Option, TrainingElearningEnrollment, TrainingQuizAttempt, ElearningConfig), player/quiz in `views.py:14690-14944`, servizi `elearning_markdown.py` / `elearning_import.py` / `elearning_notifications.py`, test in `tests_elearning.py` (28 test) + `test_elearning_reminders.py`. La "tabella audit Completamento" è `TrainingEmployeeRecord`, riusata dal flusso d'aula (`_crea_record_completamento_elearning`, views.py:14138).

## Verdetto sulla domanda chiave (precedente gestione_carichi_macchina)

**La correzione del quiz è fatta bene**: interamente server-side. Le opzioni corrette vengono lette dal DB e confrontate come insiemi (`views.py:14877-14879`), il punteggio è calcolato sul server, il form GET non espone mai il flag `corretta` (verificato in `formazione_online_quiz.html:88-93`), il tentativo è storicizzato con snapshot delle risposte (`risposte_json`) in transazione atomica. Nessuna fiducia nel client sul "quanto hai totalizzato".

**Ma l'integrità del Completamento è violabile sul "cosa hai fruito"**: il quiz non richiede di aver visto le slide, e l'avanzamento slide è fabbricabile con una singola richiesta. I dettagli sotto.

---

## 1. CODICE

### 1.1 ALTO — Completamento registrabile senza aver aperto una sola slide

`formazione_online_quiz` (views.py:14833-14943) verifica: corso e-learning, domande valide, legacy_id presente, limite tentativi. **Non verifica mai l'avanzamento slide**: un discente può andare direttamente su `/formazione/corsi-online/<id>/quiz`, rispondere (o tirare a indovinare fino al superamento, tentativi illimitati di default — `ElearningConfig.max_tentativi_quiz=0`) e ottenere:

- `TrainingElearningEnrollment.stato = COMPLETATO`;
- un `TrainingEmployeeRecord` **con `idoneo=True` e `ore_frequentate = durata_ore_teorica`** (views.py:14148-14156) — cioè un record d'audit che attesta ore di formazione mai fruite;
- chiusura automatica dell'assegnazione obbligatoria (views.py:14923-14925).

Per formazione interna leggera può essere accettabile; per corsi con valenza di compliance (sicurezza, qualità) il record storicizzato dichiara il falso. Il `completion_calculation_snapshot_json` registra solo i dati del quiz, non l'avanzamento slide: nemmeno a posteriori si può distinguere chi ha seguito da chi ha solo indovinato il quiz.

**Proposta (P0):** gate server-side sul POST del quiz: `enr.ultima_slide_ordine >= max(ordine slide attive)` (dato già disponibile), con messaggio "completa prima le slide". Aggiungere `ultima_slide_ordine`/`n_slide_totali` allo snapshot di completamento. Da solo però non basta — vedi 1.2.

### 1.2 ALTO — L'avanzamento slide è un high-water mark fabbricabile con un GET

`formazione_online_slide` (views.py:14783-14829) accetta **qualsiasi `ordine`** e aggiorna `ultima_slide_ordine` al massimo visto (14806-14808). Non c'è vincolo di sequenzialità server-side: una singola `GET /corsi-online/<id>/slide/<ultimo_ordine>` (bastano URL visibili o tentativi) porta l'avanzamento al 100%. La UI offre solo Avanti/Indietro, ma l'URL è direttamente invocabile — lo stesso pattern "il server si fida della richiesta del client" del precedente gestione_carichi_macchina, in forma più subdola: qui il dato finisce in una tabella d'audit.

Aggravante tecnica: **una GET muta stato** (avanzamento + transizione ISCRITTO→IN_CORSO). Oltre alla violazione di idempotenza (un prefetch del browser può "far avanzare" il corso), rende il tracciamento indifendibile.

**Proposta (P0, insieme a 1.1):** consentire l'aggiornamento dell'avanzamento solo a `ordine == successivo consentito` (`<= ultima_slide_ordine + 1` sull'elenco ordinato delle slide attive); le slide oltre restituiscono il partial senza aggiornare (o 403). Idealmente separare lettura (GET, nessun side effect) da avanzamento (POST del bottone Avanti). Se si vuole robustezza da compliance: registrare timestamp per slide (tabella leggera `enrollment_id, slide_id, visto_il`) invece del solo high-water mark — dà anche la durata di fruizione (utile per 3.3).

### 1.3 MEDIO — Corsi non pubblicati: slide leggibili e quiz completabile da chiunque autenticato

Incoerenza nei controlli di pubblicazione:

- `formazione_online_player` (14759) e `formazione_slide_image` (14608) verificano `is_active and stato=="ATTIVO"` ✔
- `formazione_online_slide` (14787) e `formazione_online_quiz` (14836) verificano **solo** `is_elearning=True` ✘

Conseguenze: (a) il contenuto testuale di corsi in bozza/ritirati è leggibile da qualsiasi utente autenticato via URL diretto del partial; (b) si può sostenere e superare il quiz di un corso **ritirato o mai pubblicato**, generando enrollment e record di completamento su materiale non approvato.

**Proposta (P1):** stesso gate del player su slide e quiz (con eccezione per `_can_edit_formazione`, come già fa il player, per l'anteprima autore).

### 1.4 BASSO — Race sul limite tentativi

Il check `n_tentativi >= max_tentativi_quiz` (14866-14870) avviene fuori dalla transazione e l'incremento è read-modify-write senza `select_for_update` (14907): due submit paralleli superano entrambi il check. Anche `_enrollment_corrente` può sollevare IntegrityError su doppia prima-richiesta simultanea (get_or_create su unique_together, non gestito). Scala del rischio bassa (serve malizia deliberata), ma il fix è piccolo: spostare check+incremento dentro la transazione con lock sull'enrollment.

### 1.5 Cose fatte bene (da preservare)

- **Renderer Markdown escape-first** (`elearning_markdown.py`): tutto l'input viene escapato prima delle sostituzioni whitelist; link solo http/https/mailto; niente dipendenze nuove. Testato contro XSS e `javascript:`. Modello da riusare altrove.
- **Immagini slide in storage privato** fuori webroot, servite da view con controllo pubblicazione; delete della slide rimuove il file (signal `_elimina_file_slide`, testato).
- **Domande senza risposta corretta escluse dal quiz** e segnalate all'autore (14844-14850) — fail-safe intelligente contro il quiz impossibile.
- **Import PPTX/PDF robusto** (`elearning_import.py`): LibreOffice headless con profilo isolato e timeout, PyMuPDF per il rendering, cap 80 pagine, messaggi d'errore utente-comprensibili, transazione sull'inserimento.
- Snapshot storici immutabili nel record di completamento (codice/titolo/versione corso, regola di calcolo) — buona pratica d'audit.

### 1.6 Test: buoni sull'authoring, zero sul percorso critico

I 28 test coprono renderer, modelli, endpoint autore, import PDF, esclusione domande invalide, publish/ritiro, CSV, assegnazioni, archiviazione attestato. Ma il docstring ammette (tests_elearning.py:4-6): il flusso discente HTTP non è testato perché le tabelle legacy non esistono nel DB di test — e in realtà **la correzione del quiz (POST) non è testata da nessuna parte**, nemmeno a livello di servizio come il docstring promette. Proprio il percorso che scrive l'audit è l'unico senza rete di protezione.

**Proposta (P1):** il blocco è aggirabile con `mock.patch` su `_current_legacy_anagrafica_id` (come già si mocka SNMP altrove): test del POST quiz con risposte giuste/sbagliate/miste, superamento soglia, creazione record, limite tentativi, e — dopo i fix — gate slide-viste e corso non pubblicato.

---

## 2. FRUIBILITÀ

### 2.1 Discente: esperienza già solida

- **Riprendi da dove eri**: il player riapre sull'ultima slide vista (`slide_iniziale`, views.py:14766-14770) — server-side, sopravvive a cambio device ✔
- **Catalogo con stato personale**: per ogni corso stato, best score, n. slide/domande; i corsi **assegnati e non completati sono in cima** con la scadenza ✔
- **Avviso esplicito** se il profilo non è collegato all'anagrafica ("il completamento non verrà registrato — contatta HR") sia nel player che nel quiz ✔
- **Feedback quiz**: punteggio, soglia, elenco domande giuste/sbagliate. Limite: non mostra né cosa aveva scelto l'utente né le opzioni corrette. Con tentativi limitati è una scelta difendibile (anti-memorizzazione); col default attuale (tentativi illimitati) è solo frustrante — chi sbaglia deve ri-dedurre tutto. **Proposta (P2):** mostrare le proprie scelte (già nello snapshot) sempre; le risposte corrette solo quando i tentativi sono illimitati.

### 2.2 Il buco: nessuno avvisa il dipendente

`elearning_notifications.py` è dichiaratamente una predisposizione (D7): `notify_corso_assegnato` è **NO-OP** e il command promemoria è uno stub non schedulato. Oggi un dipendente scopre di avere un corso obbligatorio con scadenza **solo se entra spontaneamente nel catalogo**. È il singolo miglioramento di fruibilità a più alto impatto: attivare la notifica in-app (il chokepoint `core.notifiche.invia_notifica` esiste già ed è già usato dal promemoria) all'assegnazione, e schedulare `send_elearning_reminders` su django-q2 (intervallo in MINUTI — trappola nota "S" crasha). **(P1, effort basso: l'infrastruttura c'è tutta.)**

### 2.3 Autore: flusso ben progettato

Pagina unica di gestione per corso (salute contenuti con segnalazione domande incomplete, iscritti/esiti, publish/ritiro con blocco se senza slide, CSV, assegnazioni con picker dei dipendenti attivi); creazione corso con preset e-learning; **import PPTX/PDF → slide immagine** che permette di riusare materiale esistente senza ricopiarlo; markdown semplice per slide testuali. Due attriti minori: (a) l'import gira sincrono nella richiesta (fino a 3 minuti col timeout LibreOffice) senza indicatore — con file grossi sembra rotto (P2: spinner o messaggio d'attesa); (b) non c'è modo di **riordinare** le slide dall'interfaccia se non rieditando i numeri `ordine` a mano (P2).

---

## 3. OPPORTUNITÀ AI

Contesto: l'HUB ha già uno stack AI locale (Ollama on-prem, RAG sui documenti SGI) — le proposte sotto non richiedono servizi cloud nuovi.

### 3.1 Generazione domande quiz da procedura SGI — SÌ, è il caso d'uso giusto

Il collo di bottiglia reale dell'authoring non sono le slide (l'import PPTX/PDF lo risolve) ma **scrivere domande e distrattori**. Il RAG SGI indicizza già le procedure: un'azione "Genera bozza domande dal documento X" (LLM locale, output = domande+opzioni **in stato bozza, is_active=False**, che l'autore rivede e attiva) taglia il costo di creazione del quiz senza toccare l'integrità. Guardrail non negoziabili: mai auto-pubblicare; marcare la provenienza (`created_by` + flag `generata_ai`) per l'audit; la domanda resta esclusa dal quiz finché l'autore non conferma la risposta corretta — il meccanismo di esclusione domande incomplete **esiste già** e fa da rete di sicurezza naturale. **(P2, valore alto.)**

### 3.2 Riassunto contenuti "per chi ha poco tempo" — NO

Contraddice lo scopo del modulo: i micro-corsi servono ad **attestare la fruizione** (record d'audit, ore frequentate, idoneità). Un riassunto AI che permette di saltare le slide è esattamente il comportamento che il punto 1.1 chiede di impedire. Per il materiale non obbligatorio il valore è marginale (i corsi sono già "micro"). Da non fare.

### 3.3 Rilevamento tassi anomali — regola deterministica, non AI (e prima servono i dati)

A questa scala (corsi interni, decine di iscritti) un modello è overengineering: bastano soglie nella pagina hub, che ha già il concetto di "salute" del corso — es. pass-rate ≥95% al primo tentativo = quiz troppo facile/risposte condivise; pass-rate <40% = quiz o materiale da rivedere; media tentativi per superamento. **Prerequisito dati mancante**: oggi non esiste telemetria di durata (il segnale più diagnostico — "completato in 90 secondi" — non è registrato). `TrainingQuizAttempt.iniziato_il` esiste ma non viene mai valorizzato (il POST scrive solo `inviato_il`): valorizzarlo al GET del quiz costa una riga e abilita la metrica durata-quiz; la durata-slide arriva gratis dalla tabella per-slide proposta in 1.2. **(P2: prima la telemetria, poi le soglie; niente ML.)**

---

## 4. UI

### 4.1 Navigazione HTMX: fluida e ben fatta

Partial swap su `#fm-slide-target`, caricamento iniziale con `hx-trigger="load"`, progress bar percentuale + "Slide X/Y" in ogni partial, bottoni Avanti/Indietro, ultima slide che offre "Vai al quiz finale" (o "torna al catalogo" se il corso non ha quiz). `hx-push-url="false"` + resume server-side è una combinazione corretta: il refresh riparte dall'ultima slide. Mancano due dettagli: **indicatore di caricamento** sui bottoni di navigazione (`hx-indicator` c'è per i consumabili altrove, qui no — su rete lenta il click sembra perso e induce doppi click) e la **navigazione da tastiera** (frecce ←/→), gradita nelle postazioni con tastiera (P2, piccoli).

### 4.2 Chiarezza avanzamento: buona nel player, ottima nel catalogo

Dentro il corso: barra + contatore slide ✔. Nel catalogo: stato per corso, best score, badge assegnazione con scadenza ✔. Manca solo, nella card del catalogo, il "sei alla slide X di Y" per i corsi IN_CORSO (il dato c'è: `ultima_slide_ordine`/`n_slide_totali`) — utile per decidere "cosa riprendo ora" (P2, piccolissimo).

### 4.3 Tablet/postazione di reparto

- I bottoni di navigazione sono grandi e il layout è a colonna singola (max-width 840-900px): adatto a tablet ✔
- Le **slide-immagine** (import a 144 dpi) sono leggibili ma il testo fitto di un PPTX denso su schermo 10" richiede zoom: nessun supporto pinch/lightbox sull'immagine (P2: click per aprire l'immagine a schermo intero).
- **Dark mode a rischio**: i template quiz/player usano colori hardcoded (`background:#fff`, bordi `#e6ecf3`, badge `#eef2f7` — `formazione_online_quiz.html:110-115`, `formazione_online_player.html:41`) invece dei token del tema. Con `body.theme-dark` questi pannelli restano chiari (fondo bianco su tema scuro) — è esattamente la classe di problemi dell'audit dark mode del portale. Da migrare ai token (P2).
- **Accessibilità**: alt sulle immagini e label sui checkbox ci sono; il limite strutturale è che le slide importate da PPTX/PDF sono **testo dentro immagini** — invisibili a screen reader e non ricercabili. Limite intrinseco della pipeline scelta (accettabile), ma va detto: per contenuti critici la slide testuale Markdown è la forma accessibile.

---

## Priorità riassuntiva

| # | Intervento | Dim. | Severità/Valore | Effort |
|---|-----------|------|-----------------|--------|
| P0-1 | Gate sul POST quiz: tutte le slide viste prima di poter sostenere il quiz; avanzamento nello snapshot di completamento | Codice | ALTO (integrità audit) | Basso |
| P0-2 | Avanzamento slide solo sequenziale (ordine ≤ ultima+1); niente mutazioni di stato su GET (avanzamento su POST) | Codice | ALTO (falsificabile con 1 GET) | Basso-Medio |
| P1-1 | Gate pubblicazione (`is_active`+`stato ATTIVO`) anche su `formazione_online_slide` e `formazione_online_quiz` (eccezione editor) | Codice | MEDIO | Minimo |
| P1-2 | Test HTTP del flusso discente (mock di `_current_legacy_anagrafica_id`): correzione POST, soglia, record, tentativi, gate 1.1/1.2 | Codice | ALTO (il percorso d'audit è oggi senza test) | Medio |
| P1-3 | Attivare notifica assegnazione + schedulare promemoria (infrastruttura già pronta, oggi NO-OP) | Fruibilità | ALTO | Basso |
| P1-4 | Lock transazionale su check+incremento tentativi | Codice | BASSO | Minimo |
| P2-1 | Bozze quiz generate da AI (RAG SGI + Ollama locale), sempre in stato inattivo da approvare | AI | ALTO | Medio |
| P2-2 | Telemetria durata (valorizzare `iniziato_il`; timestamp per slide) + soglie deterministiche pass-rate nella pagina hub | AI→Codice | MEDIO | Basso |
| P2-3 | Feedback quiz: mostrare le proprie scelte; risposte corrette solo se tentativi illimitati | Fruibilità | MEDIO | Basso |
| P2-4 | `hx-indicator` sui bottoni slide; frecce da tastiera; "slide X/Y" nelle card catalogo; lightbox immagini; token tema al posto dei colori hardcoded (dark mode) | UI | MEDIO | Basso |
| P2-5 | Riordino slide da UI; import PPTX con indicatore di attesa (o in background) | Fruibilità | BASSO-MEDIO | Medio |

**Da NON fare:** riassunto AI dei contenuti (3.2 — contraddice lo scopo attestativo del modulo); ML per anomalie sui tassi (bastano soglie).

## Limiti dell'analisi

- Analisi statica; test non eseguiti; flusso HTMX non provato a runtime.
- Non ispezionati in dettaglio: `formazione_slide_save`/`formazione_slide_import` (assunte simmetriche agli endpoint domande/opzioni letti), template catalogo e manage, `_can_edit_formazione`/`_can_view_formazione` (assunti corretti, sono il gate condiviso del modulo formazione), reminders command.
