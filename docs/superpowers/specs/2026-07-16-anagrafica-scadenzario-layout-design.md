# Design — Anagrafica: Scadenzario & Formazione-sessione (layout, viste e rinnovi)

Data: 2026-07-16 · Stato: approvato (brainstorming) · Modulo: `anagrafica`

## Contesto

Punch-list del capo (`docs/ANAGRAFICA - PERSONE.md`, sezioni «ANAGRAFICA – PERSONE»
e «ANAGRAFICA – FORMAZIONE»). Riguarda **come si guarda** lo scadenzario e **come si
avvia un rinnovo**, non la logica di calcolo delle scadenze (già consolidata).

Lo scadenzario HR unificato esiste ed è la fonte unica delle scadenze:

- `_build_scadenzario_voci(request, *, filtro_tipo, filtro_stato, filtro_reparto, dip_map)`
  — `django_app/anagrafica/views.py:7141` — produce le voci per 4 sorgenti gated
  (`qualifica`, `visita`, `formazione`, `contratto`), ognuna con
  `kind, kind_label, legacy_id, cognome, nome, reparto, tipo_nome, categoria,
  data_scadenza, giorni, scaduta`. Solo la voce **qualifica** porta oggi `tipo_id`
  (riga 7203); la voce **visita** NON ce l'ha (righe 7230-7242).
- `_raggruppa_scadenze_per_tipo(voci)` — `views.py:7346` — raggruppa per
  `(kind, tipo_nome)` per la vista a `<details>` espandibili.
- `scadenzario(request)` — `views.py:7377` — passa al template `gruppi`, `page_obj`
  (lista piatta), `can_view_visite`, `can_view_formazione`, `can_view_contratti`,
  `is_qual_admin`, e i KPI formazione `fm_n_*`.
- Template `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html`:
  vista a gruppi (`<details>` con `{% if g.has_scadute %} open{% endif %}`, riga 73),
  vista «elenco completo» piatta, e in fondo un **pannello «Scadenzario formazione»
  (righe 181-195) che è solo KPI + link alla pagina dedicata** `formazione_scadenzario`.

Sul lato formazione **tutto l'impianto sessioni esiste già** ed è la strada da riusare:

- `TrainingSession` (`models_formazione.py:588`, richiede `corso`, `codice_sessione`
  unico, `data_inizio`, `data_fine`), `TrainingEnrollment` (`:683`),
  `TrainingDeadline` (`:947`).
- `formazione_sessione_create` (`views.py:11600`, form `TrainingSessionForm`, accetta
  `?corso=<id>` come initial), `formazione_sessione_iscritti` (`:11989`),
  `formazione_iscrizione_bulk` (`:12287`, iscrive in blocco i selezionati con
  `TrainingEnrollment.get_or_create`, idempotente).
- `formazione_scadenzario` (`views.py:12590`, template omonimo) con già il bottone
  «Pianifica edizione di rinnovo» → `formazione_sessione_create?corso=X` (solo quando
  è filtrato un corso).
- `formazione_plan` (`views.py:12761`) ha **già la vista `?view=calendario`** (griglia
  mensile) oltre a `mese`/`matrice`.
- Helper riusabili: `_build_nomi_map()` (`:10004`), `_dipendenti_picker_rows()`
  (`:5607`), `_add_months` (usato in `formazione_plan`), pattern
  `qualifica_sessione_create` (`:6630`) per «tipo + dipendenti selezionati in un POST».

## Coordinamento con il piano «Giornata visite» (VINCOLANTE)

Esiste un piano in corso — `docs/superpowers/plans/2026-07-16-visite-giornata-sessioni.md`
— il cui **Task 9** tocca gli stessi punti di questo stream:

- aggiunge `"tipo_id": v.tipo_id` alla **voce visita** in `_build_scadenzario_voci`;
- aggiunge `"tipo_id"` al gruppo in `_raggruppa_scadenze_per_tipo`;
- aggiunge in `scadenzario.html` il pulsante «↻ Rinnovo» **per GRUPPO** (summary) e nella
  lista piatta, con deep-link `visite_mediche_nuova_sessione?tipo=<id>`.

Questo stream aggiunge il «↻ Rinnovo» **per SINGOLA visita** (#3), che **dipende dallo
stesso `tipo_id` sulla voce visita**, e riscrive porzioni dello stesso `scadenzario.html`
(collapse visite, formazione inline, toggle vista). C'è quindi **sia dipendenza sia
conflitto di merge** sullo stesso file e sulle stesse funzioni.

Regola adottata (dettagliata nel piano, sezione «Coordinamento»):

1. **Preferenza: il piano visite atterra per primo** (introduce `tipo_id` sulla voce
   visita e il ↻ per gruppo). Questo stream vi si innesta.
2. **Se questo stream parte prima o in parallelo**: il primo task **aggiunge da sé
   `tipo_id` alla voce visita e al gruppo in modo idempotente** (guardato con
   `.setdefault`/`if "tipo_id" not in ...`), così i due piani non si sovrascrivono; il
   `↻ Rinnovo per gruppo` del piano visite e il `↻ Rinnovo per singola` di questo
   convivono (regioni distinte del template).
3. Le modifiche al template si concentrano su **blocchi diversi** (il piano visite: il
   `<summary>` del gruppo e la cella «Descrizione» della lista piatta; questo stream: il
   flag `open` del `<details>`, il pannello formazione in fondo, l'header con il toggle
   vista). In caso di rebase, **conservare entrambe le CTA**, mai rimuovere quella
   dell'altro piano.

## Obiettivi (mappati alla punch-list)

- **#1 Scadenzario — visite collassate di default**: nella vista a gruppi, i gruppi
  `kind == "visita"` non si auto-aprono (niente `open`) anche se hanno scadute.
- **#1 Scadenzario — formazione INLINE (no redirect)**: il pannello in fondo che oggi
  mostra solo KPI + link alla pagina dedicata viene sostituito da una **sezione
  formazione inline** (tabella delle scadenze formazione visibile direttamente,
  raggruppata per corso). Il link alla pagina dedicata resta come scorciatoia
  secondaria, non come unico accesso.
- **#2 Scelta vista**: un **toggle di layout** (`?layout=`) con almeno:
  - `gruppi` (default, quello attuale),
  - `calendario` — griglia mensile delle scadenze (stessa resa di
    `formazione_plan?view=calendario`, riusando `_add_months` e l'approccio a settimane×giorni),
  - `affiancata` — due colonne **Visite │ Formazione**, ciascuna con la propria tabella.
- **#3 «↻ Rinnovo» per singola visita**: accanto a ogni voce visita (vista gruppi e
  lista piatta) un deep-link `visite_mediche_nuova_sessione?tipo=<tipo_id>`, gated
  `can_view_visite`.
- **#4 Formazione — «seleziona dipendenti» → sessione di rinnovo**: nella sezione
  formazione dello scadenzario, checkbox per dipendente raggruppati per corso e un
  pulsante «Crea sessione di rinnovo con i selezionati» che **avvia il flusso standard**
  (`formazione_sessione_create?corso=X`), portando con sé i dipendenti selezionati; al
  salvataggio della sessione i selezionati vengono iscritti in blocco (riuso di
  `TrainingEnrollment.get_or_create`, come `formazione_iscrizione_bulk`).
- **#5 Formazione — «scadenzario = plan»**: sulla pagina `formazione_scadenzario` (e
  nella sezione inline) un toggle «Elenco │ Calendario» che porta alla vista calendario
  del plan già esistente (`formazione_plan?view=calendario`). Nessun nuovo motore
  calendario per la formazione: si riusa il plan.

## Non-obiettivi

- Nuovo modello dati (non serve: `VisitaSessione` la introduce il piano visite;
  `TrainingSession`/`TrainingEnrollment` esistono). Questo stream è **senza migrazione**.
- Riscrivere la logica di calcolo scadenze o l'idoneità formativa.
- Toccare il flusso «Giornata visite» (di competenza dell'altro piano) — qui si
  consumano solo i suoi deep-link.
- Notifiche, PDF, prenotazioni.

## Design

### 1. Scadenzario — parametro `layout` + collapse visite + ↻ per singola visita

`scadenzario(request)`:
- legge `layout = request.GET.get("layout", "gruppi")` ∈ `{gruppi, calendario, affiancata}`
  (valore sconosciuto → `gruppi`), lo passa al context.
- per `calendario`/`affiancata` prepara le strutture aggiuntive:
  - `affiancata`: `voci_visite = [v for v in voci if kind=="visita"]`,
    `voci_formazione = [... kind=="formazione"]` (gated già dentro `_build_scadenzario_voci`).
  - `calendario`: costruisce una griglia mensile (mese corrente centrabile con
    `?anno=&mese=`) mappando `voci` per `data_scadenza`, con lo stesso schema
    settimane×giorni di `formazione_plan` (riuso di `_add_months` e `calendar`).

`_build_scadenzario_voci`: alla voce **visita** aggiungere `"tipo_id": v.tipo_id`
(idempotente rispetto al piano visite). `_raggruppa_scadenze_per_tipo`: propagare
`"tipo_id": gv[0].get("tipo_id")` al gruppo.

`scadenzario.html`:
- header pagina: un gruppo di tab/bottoni **Gruppi · Calendario · Affiancata** che
  cambiano `?layout=` preservando gli altri filtri.
- vista gruppi: `<details ...{% if g.has_scadute and g.kind != "visita" %} open{% endif %}>`
  (visite collassate anche se scadute).
- ↻ Rinnovo per singola visita: nella riga voce (gruppi e lista piatta), se
  `v.kind == "visita" and can_view_visite and v.tipo_id`, link
  `visite_mediche_nuova_sessione?tipo={{ v.tipo_id }}`.

### 2. Sezione formazione inline + «seleziona dipendenti» → sessione di rinnovo

Sostituire il pannello «Scadenzario formazione» (solo KPI + link) con una **sezione
inline**: le voci `kind=="formazione"` raggruppate per corso (`tipo_nome`), ognuna con:
- checkbox `dipendenti_selezionati=<legacy_id>` per riga,
- pulsante «Crea sessione di rinnovo con i selezionati» dentro un `<form method="post">`
  che invia `corso_id` + i `dipendenti_selezionati` a un endpoint nuovo.

Serve esporre il `corso_id` sulla voce formazione: in `_build_scadenzario_voci` aggiungere
`"corso_id": d.corso_id` alla voce formazione (oggi ha solo `tipo_nome = d.corso.titolo`).

Endpoint nuovo `formazione_rinnovo_da_scadenzario(request)` (POST, gated
`_can_edit_formazione`):
- valida `corso_id` (TrainingCourse attivo) e raccoglie i `dipendenti_selezionati`;
- **stasha** gli id in `request.session["rinnovo_preselect"] = {"corso": <id>, "ids": [...]}`;
- `redirect("anagrafica:formazione_sessione_create") + "?corso=<id>"` — il **flusso
  standard** di creazione sessione.

`formazione_sessione_create` (modifica minima, ramo POST dopo `sessione.save()`):
- se in sessione c'è `rinnovo_preselect` per lo stesso corso, iscrive in blocco gli id
  (stessa `get_or_create` di `formazione_iscrizione_bulk`), pulisce la chiave di sessione,
  e `redirect` alla pagina **iscritti** con messaggio «N dipendenti iscritti».

Così «seguirà poi il flusso standard»: l'utente compila davvero data/codice della
sessione; i selezionati non si perdono e finiscono iscritti al salvataggio.

### 3. Layout «Affiancata» e «Calendario»

- **Affiancata**: due colonne `Visite │ Formazione`, ciascuna una tabella compatta
  (persona, tipo, scadenza, stato) coi rispettivi ↻ Rinnovo (visita → giornata visite;
  formazione → seleziona dipendenti). Rispetta il gating: se una sorgente non è visibile,
  la colonna mostra il messaggio «non visibile col tuo accesso».
- **Calendario**: griglia mensile server-side costruita da `voci` (tutte le sorgenti),
  ogni giorno elenca le scadenze con badge per `kind`; navigazione mese precedente/successivo
  con `?layout=calendario&anno=&mese=`. Nessun JS necessario (progressive enhancement).

### 4. Formazione scadenzario dedicato = plan (#5) + seleziona dipendenti (#4 specchio)

`formazione_scadenzario.html`: aggiungere in header un toggle **Elenco │ Calendario**;
«Calendario» punta a `formazione_plan?view=calendario`. Aggiungere anche qui la selezione
dipendenti → `formazione_rinnovo_da_scadenzario` (stesso endpoint), raggruppando per corso,
così il punto d'ingresso #4 esiste sia nello scadenzario HR generale sia in quello
formazione dedicato.

### 5. Privacy / ACL

Gating invariato e già dentro `_build_scadenzario_voci` (visite = sanitario, formazione/
contratti = HR). Il nuovo endpoint formazione è gated `_can_edit_formazione`. Nessun esito
sanitario esposto: le visite nello scadenzario mostrano solo tipo/scadenza/stato. Il ↻
Rinnovo visita non registra nulla, apre solo la giornata.

## Test (label `anagrafica`, `--keepdb`, `config.settings.test`)

- `_build_scadenzario_voci`: la voce visita porta `tipo_id`; la voce formazione porta
  `corso_id`. Il gruppo visita porta `tipo_id`.
- `scadenzario`: `?layout=` valido/invalido → context `layout` corretto; vista gruppi
  → i gruppi visita non hanno `open`; ↻ Rinnovo singola visita presente col deep-link.
- `?layout=affiancata` → due colonne rese (stringhe marcatori Visite/Formazione).
- `?layout=calendario` → griglia mensile resa; navigazione mese.
- Sezione formazione inline: checkbox `dipendenti_selezionati` + form verso il nuovo
  endpoint; niente più «solo link» come unico accesso.
- `formazione_rinnovo_da_scadenzario`: POST con corso + ids → 302 verso
  `formazione_sessione_create?corso=` e ids stashati in sessione; 403 senza permesso;
  nessun id → warning e redirect indietro.
- `formazione_sessione_create` (POST) con `rinnovo_preselect` in sessione → crea la
  TrainingSession, iscrive gli id in blocco (idempotente), pulisce la sessione, redirect
  a iscritti.
- `formazione_scadenzario`: toggle calendario presente (link a `formazione_plan?view=calendario`).
- Regressione: `ScadenzarioEstesoTests` e i test formazione esistenti non regrediscono
  (il test cosmetico pre-esistente eventualmente rosso non è di questo stream).

## Rischi

- **Conflitto su `scadenzario.html` e sulle 2 funzioni scadenzario con il piano visite**
  (vedi «Coordinamento»): mitigato eseguendo il piano visite prima o rendendo idempotenti
  le aggiunte di `tipo_id`.
- Il layout `calendario` re-implementa una griglia già presente in `formazione_plan`:
  per non duplicare, riusare `_add_months` e lo stesso schema; se cresce, estrarre un
  helper condiviso in una patch successiva (fuori scope ora).
- Il rinnovo formazione «seleziona dipendenti» attraversa una sessione HTTP (`request.session`):
  se l'utente abbandona la creazione, la chiave resta stantia — la si consuma/pulisce sia
  al salvataggio sia se il corso non combacia.
- `TrainingSession.codice_sessione` è unico e obbligatorio: la creazione resta a carico del
  form standard (l'utente lo compila), non si autogenerano sessioni mezze vuote.
