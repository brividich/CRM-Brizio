# BUILD SPEC — App `gestione_specifiche` (NOVICROM HUB)
### Esecuzione autonoma end-to-end · Fasi F1 → F9

> **Come si usa**: apri il progetto NOVICROM HUB in VS Code, metti questo file in `docs/specs/gestione_specifiche/BUILD_SPEC.md` e dallo Claude Code dicendo: *"Esegui `docs/specs/gestione_specifiche/BUILD_SPEC.md` end-to-end secondo il contratto di autonomia."*
> Questo documento è l'unica fonte di verità. Sostituisce qualunque prompt parziale precedente.

---

## 0. MISSIONE

Costruire l'app Django `gestione_specifiche` che digitalizza il **Flusso Specifiche + MOD.133** (ciclo di vita di specifiche tecniche, comunicazioni e piani di qualità da cliente/generica, con sotto-processo MOD.133 di flow-down requisiti, generazione OFI verso MOD.174, verifica periodica, distribuzione tracciata). Obiettivo trasversale: **tracciabilità end-to-end per audit ISO 9001 §7.5 / EN 9100**. Sostituisce un workflow Excel/cartaceo, in alternativa ad ARXivar NEXT.

Devi portare il lavoro **da F1 a F9** in modo autonomo, lasciando a ogni passo il repository in stato funzionante e testato.

---

## 1. CONTRATTO DI AUTONOMIA (leggi attentamente)

1. **Vai avanti da solo.** Esegui le fasi in ordine (F1→F9). Non aspettare conferme tra una fase e l'altra: completa, testa, committa, passa alla successiva. Prenditi tutto il tempo necessario.
2. **Auto-recupero.** Se ti blocchi (errore, test rosso, pattern poco chiaro): **diagnostica → ispeziona i pattern del repo → prova fino a 3 approcci alternativi documentati**. Solo se ancora bloccato, registra un BLOCKER nel build log (vedi §3) e **prosegui con il lavoro indipendente** di altre fasi/parti che non dipendono dal blocco. Non fermarti del tutto se esiste lavoro utile residuo.
3. **Mai lasciare il repo rotto.** Ogni commit deve compilare, migrare ed essere verde sui test. Se una modifica rompe qualcosa, ripristina o isola dietro feature flag prima di committare.
4. **Quando chiedere vs quando decidere.** Le decisioni di processo sono già congelate (§4, decisioni F0). Per scelte tecniche **reversibili** non coperte: **decidi tu**, scegli l'opzione più coerente col repo, e annota l'assunzione in `ASSUMPTIONS` del build log. Chiedi all'umano **solo** se la scelta è (a) **irreversibile o distruttiva**, oppure (b) **cambia il comportamento di processo** in modo non deducibile da questa spec, oppure (c) richiede credenziali/azioni che non puoi compiere. In quel caso **accumula le domande** e ponile in blocco (non una per volta), continuando nel frattempo sul lavoro non bloccato.
5. **Passi piccoli e rivedibili.** Un commit per unità logica con messaggio chiaro. Mostra i diff rilevanti nel log di lavoro.
6. **Rispetta il repo.** Riusa pattern esistenti (ACL v2, navigation registry, design system, storage privato, settings split, scoped test command in `CLAUDE.md`). Non reinventare ciò che esiste.

---

## 1-bis. ORCHESTRAZIONE — pattern lead + subagent (NON team parallelo)

Modalità di lavoro decisa per questa build:

**Non** usare un team di agenti in parallelo che modificano il codice contemporaneamente. Le fasi F1→F9 sono in larga parte **sequenziali e con dipendenze** (F2 dipende da F1, F3 da F2…): il parallelismo pesante non dà vantaggio e introduce rischio di conflitti + carico RAM (assunzione: macchina ~32GB). L'obiettivo è affidabilità non presidiata, non velocità.

Usa invece un **pattern lead + subagent**:
- **Lead orchestrator** (sessione principale): possiede `BUILD_LOG.md`, la sequenza delle fasi, i commit e le guardie. È **l'unico** che scrive sul branch.
- **Subagent a contesto isolato** (Task tool) per attività delimitate e a contesto pesante, che riportano un digest al lead senza inquinare il contesto principale:
  - `explorer` → STEP 0 (sola lettura): mappa ACL v2, navigation registry, registro OFI/MOD.174, settings, pattern. Restituisce il riepilogo.
  - `tester` → per ogni fase scrive ed esegue i test, riporta l'esito.
  - `reviewer` → a fine fase verifica il codice contro i criteri di accettazione e i guardrail (§8) prima del commit.
  - `intake-designer` → F8: produce il prospetto di intake dati.
- Regola ferrea: **un solo agente alla volta tocca il codice** (il lead integra). I subagent producono analisi/test/diff proposti; niente scritture concorrenti.

Nota RAM: se ora disponi di memoria sufficiente per Agent Teams in parallelo e vuoi spingere sulla velocità, parallelizza **solo fasi indipendenti** (es. `intake-designer` di F8 mentre procede F7 UI). Per il grosso resta raccomandato lead+subagent, per coerenza di build log e commit.

---

## 2. STEP 0 — ESPLORAZIONE (prima di scrivere codice di prodotto)

Ispeziona e riassumi nel build log:
1. Struttura di un'app rappresentativa (es. `assets`, `dpi`): `models/views/urls/apps/templates`, registrazione nel **navigation registry**.
2. **ACL v2**: dove si definiscono permessi/ruoli, come una view li applica, come funziona il **fallback legacy**.
3. **Gruppi AD/ACL esistenti** mappabili ai ruoli DM, IN1, RDD, MSM, MSO, MSA, SGI, IT Admin. Elenca quali esistono già.
4. **Registro OFI / MOD.174** esistente (app, modello, FK). Da NON modificare: ci si aggancia solo con FK nullable.
5. Eventuale **registro documenti CN** (per `AzioneOFI.documento_cn`).
6. Settings split `config/settings/{base,dev,prod}.py` e stile di configurazione d'app.
7. `requirements`/pip-tools: versioni Django, mssql-django, presenza di **django-fsm-2**; pattern migrazioni; vincoli SQL Server già noti.
8. Pattern HTMX, django-q2 (come si registrano i task/schedule), django-ninja (dove vive l'API), storage privato per allegati.
9. Modello reparto/gruppo usato per destinatari e l'eventuale AI locale già integrata (endpoint, modalità d'uso) per la fase F9.

Scrivi l'esito in `BUILD_LOG.md → §Esplorazione`. Se qualcosa contraddice questa spec, annotalo e adatta seguendo il repo (i pattern del repo vincono sui dettagli implementativi di questa spec, **non** sulle decisioni di processo F0).

---

## 3. BUILD LOG (lo mantieni tu, sempre aggiornato)

Crea e aggiorna `docs/specs/gestione_specifiche/BUILD_LOG.md` con queste sezioni:
- **Stato fasi**: tabella F1…F9 con `todo|in_corso|fatto|bloccato` + data.
- **Esplorazione**: esito STEP 0.
- **ASSUMPTIONS**: ogni assunzione tecnica presa in autonomia, con motivazione.
- **DECISIONS**: scelte reversibili rilevanti e perché.
- **BLOCKERS**: blocchi reali con contesto, alternative tentate e proposta di risoluzione (queste diventano le domande in blocco per l'umano).
- **TEST**: ultimo esito della suite per fase.
- **CHANGELOG**: commit principali per fase.

Aggiorna questo file **a ogni fine fase** e a ogni blocker. È la traccia che l'umano leggerà.

---

## 4. DECISIONI DI PROCESSO CONGELATE (F0) — VINCOLANTI

| # | Tema | Decisione |
|---|---|---|
| 1 | Generazione OFI nel MOD.174 | **Su conferma** del DM/Approvatore (mai automatica) |
| 2 | Approvazione documento CN (azione OFI) | **Configurabile** via setting `APPROVAZIONE_DOC_CN_MODE` ∈ `{mod133_approver, car_flow, rdd_dedicato}` (default `car_flow`) |
| 3 | Presa visione in distribuzione | **Configurabile** per tipo documento e reparto |
| 4 | Copie cartacee | **Warning + deroga** con giustificazione obbligatoria (no blocco rigido) |
| 5 | Import storico | **Solo** specifiche "In validità" |
| 6 | Macchina a stati | **django-fsm-2** |
| 7 | Ruoli → gruppi | **Riuso** gruppi AD/ACL esistenti; crea solo i mancanti **proponendone i nomi** (non crearli senza OK se implicano modifiche AD) |
| 8 | Copilota AI locale | Pre-compilazione MOD.133 + **classificazione TAG** + **ricerca semantica**; l'umano resta sempre in approvazione |
| 9 | Collegamento al resto del HUB | **Modulo isolato** ora; predisponi hook **nullable** `commessa_ref`, `famiglia_ref` (CharField indicizzati, non FK) per agganci futuri |
| 10 | Cruscotto direzionale | **Dashboard KPI qualità dedicata** |
| 11 | Canali di notifica | **Email + notifica in-app HUB** |

---

## 5. MODELLO DATI (fonte di verità)

> **Principio di retention / storico consultabile (requisito di prima classe).** Nulla viene mai cancellato fisicamente: ogni specifica, revisione, transizione, MOD.133, OFI e distribuzione resta **consultabile per sempre** a fini di audit ISO 9001/EN 9100. Lo storico è dato da: la **catena revisioni** (`revisione_precedente`/`revisioni_successive`), lo stato **S4 Superato** (le revisioni passate restano accessibili in sola lettura), gli stati terminali (S6/S7/S8) e l'**audit trail `EventoSpecifica`**. In aggiunta, ad ogni transizione il `payload` di `EventoSpecifica` registra uno **snapshot dei metadati** della specifica in quel momento (codice, rev, titolo, stato, data_verifica, esito MOD.133), così da poter **ricostruire il punto-nel-tempo** com'era una specifica quando era "In validità" prima di essere superata — senza introdurre un modello aggiuntivo.

App `gestione_specifiche`. CharField/TextField (NVARCHAR-compatibili), `JSONField` per payload, indici espliciti, `__str__` e `verbose_name` in italiano.

**`Specifica`** — `codice`(idx), `revisione`, `titolo`, `tipo`∈{specifica,comunicazione,piano_qualita}, `fonte`∈{cliente,generica}, `stato`(**FSMField**, protected), `data_inserimento`(auto), `data_verifica`(Date,null), `note`(Text,blank), `revisione_precedente`(self FK,null,PROTECT,related=revisioni_successive), `master`(self FK,null), `allegato`(FileField storage privato), `stato_precedente`(Char,blank — per ripristino da S9), hook nullable `commessa_ref`/`famiglia_ref`(Char,idx,blank). Indici: codice, stato, (tipo,stato), data_verifica.

**`MOD133`** — `specifica`(OneToOne,CASCADE), `compilatore`(FK user,null), `approvatore`(FK user,null), `data_chiusura_compilazione`(DT,null), `data_approvazione`(DT,null), `esito`∈{approvato,respinto,non_applicabile}(null).

**`RigaMOD133`** — `mod133`(FK,CASCADE,related=righe), `ordine`(PosSmallInt), `rif_paragrafo`, `argomento`, `descrizione_modifiche`(Text), `descrizione_impatto`(Text), `rif_doc_cn`, `rif_paragrafo_cn`, `tag_processo`, `impatto_documenti`(Bool=False), `impatto_operativo`(Bool=False), `genera_ofi`(Bool=False), `ofi`(FK nullable → registro MOD.174 reale; se non agganciabile in sicurezza usa PositiveIntegerField nullable e logga un BLOCKER).

**`AzioneOFI`** — `riga_mod133`(FK), `ofi`(rif come sopra), `documento_cn`(FK se esiste registro CN, altrimenti Char), `tipo_azione`(Char), `stato`(Char/choices), `modo_approvazione`(Char, default da `APPROVAZIONE_DOC_CN_MODE`), `approvatore`(FK user,null), `data_approvazione`(DT,null).

**`Distribuzione`** — `specifica`(FK), `canale`∈{email,notifica,cartaceo}, `destinatari`(M2M Group/reparto reale), `presa_visione_richiesta`(Bool), `cartacea`(Bool), `n_copie_distribuite`(PosSmallInt=0), `n_copie_ritirate`(PosSmallInt=0), `data_distribuzione`(DT,null).

**`EventoSpecifica`** (audit immutabile) — `specifica`(FK,related=eventi), `stato_da`(Char,blank), `stato_a`(Char), `attore`(FK user,null), `timestamp`(auto), `trigger`(Char), `payload`(JSON,default dict). Solo create; impedisci update/delete.

**`ConfigPresaVisione`** — chiave (`tipo_documento` + `reparto/gruppo`) → `richiesta`(Bool). Oppure struttura settings se più coerente: decidi nello STEP 0 e annota in DECISIONS.

**Settings** (`base.py`): `GESTIONE_SPECIFICHE = {"APPROVAZIONE_DOC_CN_MODE":"car_flow","VERIFICA_PERIODICA_MESI":6,"REMINDER_GIORNI":7,"ESCALATION_GIORNI":14}` (o lo stile config del repo).

---

## 6. MACCHINA A STATI (django-fsm-2, su `Specifica.stato`)

Stati: `S1 bozza · S2 flow_down · S3 in_validita · S4 superato · S5 sospeso · S6 annullato · S7 duplicato · S8 respinto · S9 errore_tecnico`. Costanti modulo + choices.

Transizioni `@transition` con side-effect tracciato in `EventoSpecifica` (centralizza via signal `post_transition`):
- `avvia_flow_down` S1→S2: crea `MOD133` vuoto. (DM)
- `approva_flow_down` S2→S3: **guardia** `MOD133.esito==approvato` **e** `approvatore != compilatore`; set `data_verifica = oggi + VERIFICA_PERIODICA_MESI`; **side-effect**: se esiste `revisione_precedente` in S3, portala a **S4** (superamento automatico).
- `respingi_flow_down` S2→S8 (esito non applicabile/respinto).
- `sospendi` {S2,S3}→S5: motivo+data(+riesame) obbligatori; salva `stato_precedente`.
- `ripristina` S5→(S2|S3) secondo `stato_precedente`; motivo obbligatorio.
- `annulla` {S1,S2,S5,S9}→S6: motivo obbligatorio.
- `marca_duplicato` {S1,S2}→S7: `master` obbligatorio.
- `errore_tecnico` *→S9: salva `stato_precedente`; `payload` errore obbligatorio.
- `ripristina_da_errore` S9→`stato_precedente`.

Regole: campi obbligatori mancanti ⇒ `ValidationError` **prima** del cambio stato; transizioni illegali ⇒ `TransitionNotAllowed`. Pausa timer: in F2 solo hook documentato (no scheduling).

---

## 7. FASI (esecuzione sequenziale; ognuna chiude con test verdi + commit + log)

### F1 — Modello dati, migrazioni, admin, ACL, navigation
Crea l'app e i modelli §5. Admin con list_display/filter/search; `EventoSpecifica` e `RigaMOD133` inline read-only dove sensato. Registra permessi ACL v2 (claim/compila/approva/sospendi/annulla/deroga/distribuisci) mappati ai gruppi esistenti (proponi i mancanti). Registra la voce "Gestione Specifiche" nel navigation registry. `makemigrations`+`migrate` su dev; verifica compatibilità SQL Server e segnala rischi.
**Done**: app migrata, admin navigabile, voce nav presente, permessi registrati.

### F2 — Macchina a stati + audit + test
Implementa §6. Crea `tests/` (pytest) con: happy path S1→S2→S3 + data_verifica; guardia compilatore≠approvatore (fail); fail se esito≠approvato; superamento revisione automatico; sospendi/ripristina (S3↔S5, S2↔S5) con motivo obbligatorio; annulla da più sorgenti; marca_duplicato richiede master; errore_tecnico da stato arbitrario + ripristino; ogni transizione genera **esattamente un** EventoSpecifica; transizioni illegali sollevano TransitionNotAllowed; check ACL nega utente senza permesso. Usa lo scoped test command del repo.
**Done**: suite verde su tutti i casi.

### F3 — Flusso MOD.133 (UI HTMX)
Inserimento/modifica metadati `Specifica` (maschera; se è revisione, eredita i campi dal documento precedente e incrementa la rev). Compilazione `MOD133` con **formset HTMX a righe dinamiche** (add/remove senza reload), campi `RigaMOD133` con obbligatorietà condizionale (griglia documenti obbligatoria solo se `impatto_documenti=Y`). Chiusura compilazione (firma compilatore + data) → passaggio ad approvatore. Approvazione/rimando/respingi con guardia compilatore≠approvatore. Presa in carico task ("dito" = claim). Tutto in stile design system HUB (navy/cyan/orange, card, pill di stato). Test su formset, obbligatorietà condizionale, claim, flusso approvativo.
**Done**: un utente completa S1→S2→S3 da UI; test verdi.

### F4 — Timer e scheduling (django-q2) + notifiche
Reminder 7gg (caricamento specifica e assegnazione task MOD.133), escalation 14gg → Approvatore+DM(+SGI opz.), verifica periodica 6 mesi ricorrente da `data_verifica`. **Pausa timer** in S5/S9; stop su presa in carico/uscita stato. Notifiche **email (SMTP esistente) + in-app HUB**. Ogni esecuzione scrive EventoSpecifica. Test su scheduling logico (con clock mockato) e pausa/ripresa.
**Done**: timer registrati e in pausa/ripresa corretti; notifiche su entrambi i canali.

### F5 — OFI → MOD.174 + sotto-flusso modifica documento CN
Su righe con impatto Y, **su conferma DM/Approvatore** (no auto), crea OFI nel registro MOD.174 esistente (FK transazionale). Sotto-flusso `AzioneOFI`: modifica documento CN impattato + approvazione con `modo_approvazione` da `APPROVAZIONE_DOC_CN_MODE` (supporta tutti e 3 i modi). Test su creazione-su-conferma, idempotenza, i 3 modi di approvazione.
**Done**: ciclo requisito→OFI→azione documento CN→approvazione completo; nessuna modifica distruttiva al registro esistente.

### F6 — Distribuzione + tracciamento copie
`Distribuzione` con canale, destinatari, evidenza (Notificato/Presa visione secondo `ConfigPresaVisione`), audit trail. Cartacea: **warning + deroga giustificata** se `n_copie_ritirate` (nuova rev) ≠ `n_copie_distribuite` (rev precedente). Test sull'algoritmo copie e sulla deroga.
**Done**: distribuzione tracciata; regola copie con deroga funzionante.

### F7 — Ricerca, API ninja, UI elenco/cruscotto + storico consultabile
API django-ninja: elenco/ricerca (filtri stato/cliente/tag/tipo), dettaglio, transizioni. UI elenco con pill di stato, colonna stato MOD.133, azioni inline (claim, sospendi/riprendi, distribuisci, storico rev), filtro per TAG/cliente/stato, "Nuova specifica". Coerente col mockup HUB.

**Storico consultabile (esplicito)**:
- **Archivio ricercabile** che include anche le specifiche **superate/terminali** (S4/S6/S7/S8), con toggle "mostra storico" e filtro per intervallo date; default elenco = solo attive, ma lo storico è sempre raggiungibile.
- **Scheda storico della specifica** (read-only): timeline delle **revisioni** (rev N ↔ rev precedente/successiva), **cronologia eventi** completa da `EventoSpecifica` (chi/cosa/quando/da-stato→a-stato), con possibilità di **ricostruzione punto-nel-tempo** dallo snapshot nel payload; collegamenti a MOD.133, righe, OFI generati (MOD.174) e distribuzioni di quella revisione.
- **Esportazione** della cronologia di una specifica (PDF/CSV) per allegati di audit.
Test: archivio include lo storico, scheda mostra timeline + eventi coerenti, ricostruzione punto-nel-tempo, export.
**Done**: elenco navigabile e ricercabile; storico di ogni specifica consultabile end-to-end; API documentata.

### F8 — Import storico (solo "In validità") — con prospetto di intake auto-generato
**Non attendere passivamente la fonte dati.** Il subagent `intake-designer` (o il lead) **produce per primo un prospetto di intake** in `docs/specs/gestione_specifiche/INTAKE_IMPORT_STORICO.md` che definisce esattamente cosa serve dall'umano:
- elenco dei **campi attesi** mappati 1:1 sui modelli (codice, revisione, titolo, tipo, fonte, data_inserimento, data_verifica, stato=`in_validita`, note, eventuale rif. master), con **tipo, obbligatorietà, formato** (date `YYYY-MM-DD`, encoding, valori ammessi per i choices) e regole (solo specifiche In validità);
- un **template** scaricabile `template_import_storico.csv` (+ opzionale `.xlsx`) con intestazioni e 2 righe d'esempio compilate;
- note di **data cleansing** (duplicati, codici/rev malformati, caratteri accentati → NVARCHAR);
- istruzioni su **dove depositare** il file compilato e come lanciare l'import.

Poi, **senza bloccarsi**, implementa tutto ciò che non dipende dai dati reali: il **management command idempotente** di import (dry-run di default), il **validatore** che verifica un file contro il template (righe valide/scartate con motivo), e i **test** su parsing/idempotenza/validazione con **fixture sintetiche** conformi al template. Solo il caricamento dei dati reali resta pending finché l'umano non deposita il file: logga **un singolo BLOCKER** "dati storici attesi" con link al prospetto.
**Done**: prospetto di intake + template generati; command, validatore e test pronti e **verdi su fixture**; manca solo il file reale dell'umano.

### F9 — Copilota AI locale (opzionale ma previsto)
Usando l'AI locale già integrata nel portale: pre-compilazione righe MOD.133 dal PDF della specifica (proposta paragrafi/argomenti/impatti), **classificazione automatica TAG di processo**, **ricerca semantica** sull'archivio specifiche (predisponi lo strato di embedding locale; scegli la tecnologia più coerente col portale e annota in DECISIONS). **Vincolo invalicabile**: l'AI propone, l'umano valida e firma; nessuna transizione/approvazione automatizzata. Dati on-premise. Test che verifichino che l'output AI sia sempre in stato "proposto" e mai applicato senza azione umana.
**Done**: copilota attivo in pre-compilazione/TAG/ricerca, con umano sempre in approvazione.

---

## 8. GUARDRAIL (cosa NON fare, mai)

- Non eseguire operazioni **distruttive** sul DB (drop/flush/hard-delete), non svuotare tabelle, non modificare il **registro OFI/MOD.174** esistente (solo FK nullable).
- Non **creare gruppi AD** o modificare permessi a livello directory senza OK umano (proponi i nomi nei BLOCKERS).
- Non inserire feature non supportate da **mssql-django**; al dubbio, scegli l'alternativa compatibile e annota.
- Non automatizzare creazione OFI (è **su conferma**) né approvazioni AI.
- Non introdurre FK obbligatorie verso commesse/asset (modulo isolato).
- Non usare `localStorage`/storage browser in eventuali widget; non committare segreti.
- Non lasciare il repo rosso o non migrabile.

---

## 9. DISCIPLINA GIT

- Branch dedicato (es. `feature/gestione-specifiche`). Un commit per unità logica, messaggi in italiano chiari (`feat(spec): ...`, `test(spec): ...`).
- A fine di ogni fase: test verdi, build log aggiornato, commit con tag della fase nel messaggio (`[F3]`).
- Niente force-push, niente rebase distruttivi su branch condivisi.

---

## 10. DEFINITION OF DONE (globale)

- F1–F9 completate o, se qualche fase è bloccata, **completate tutte le parti indipendenti** e i blocchi raccolti in `BLOCKERS` con proposta di risoluzione.
- Suite pytest **verde**; nessuna regressione sugli altri moduli; compatibilità SQL Server verificata o rischi documentati.
- ACL, navigation, admin, API, UI coerenti col HUB e col design system.
- `BUILD_LOG.md` completo: stato fasi, assumptions, decisions, blockers, test, changelog.
- Deliverable F8 presenti: `INTAKE_IMPORT_STORICO.md` + `template_import_storico.csv` (+ `.xlsx` opz.), command e validatore testati su fixture.
- Al termine, produci nel log un **riepilogo esecutivo** (cosa è stato fatto, assunzioni prese, domande aperte in blocco) pronto per la mia revisione.

---

### Promemoria finale
Lavora end-to-end e in autonomia. Prenditi il tempo che serve. Se ti blocchi, **riparti da solo** dopo aver provato alternative; isola il blocco e continua sul resto. Chiedi **solo** per scelte irreversibili/distruttive o che cambiano il processo, e **in blocco**. Mantieni il repo sempre verde e il build log sempre aggiornato.
