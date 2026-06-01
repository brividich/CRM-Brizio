# Feature Backlog — NOVICROM HUB

Checklist di avanzamento per le funzionalità pianificate, organizzate per modulo e priorità.
Aggiornare lo stato di ogni item al termine dell'implementazione.

**Legenda stato:**
- `[ ]` — non iniziato
- `[~]` — in corso / parzialmente implementato
- `[x]` — completato
- `[-]` — scartato / rimandato (motivazione inline)

**Legenda priorità:** 🔴 alta · 🟡 media · 🔵 bassa

---

## KICK-OFF (`tasks`)

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| T1 | 🟡 | **% avanzamento attività** — campo `progress` 0–100 su `Task`; progress bar in ogni riga Gantt e quick-edit | Migration 0028; `TaskForm` e `ProjectTaskGanttUpdateForm` aggiornati | `[x]` |
| T2 | 🟡 | **Dashboard portfolio aggregata** — filtri cliente/P/N/stato VRF, ordinamento, semaforo RAL | Toolbar filtri GET in `project_list`; RAL da `task_overdue` annotato; dropdown clienti dinamico | `[x]` |
| T3 | 🔴 | **Baseline Gantt** — snapshot date task; badge scostamento giorni in ogni riga; azioni Fissa/Rimuovi baseline | Migration 0029 `GanttBaseline`; view `fix_baseline`/`clear_baseline`; banner baseline attiva | `[x]` |
| T4 | 🔵 | **Dipendenze tra attività FS/SS/FF/SF** — freccia predecessore in riga Gantt; pannello lista + form AJAX | Migration 0030 `TaskDependency`; endpoint `add_dependency`/`remove_dependency`; JS `addDependency`/`removeDependency` | `[x]` |

---

## Anomalie / Ticket (`anomalie`, `tickets`)

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| A1 | 🔴 | **SLA automatico** — tempi risposta/risoluzione per `CategoriaTicket`; colore rosso su ticket scaduti; reminder via automazioni | Campo `sla_hours_response` e `sla_hours_resolution` su `CategoriaTicket`; calcolo scadenza al cambio stato; automazione SQL o management command per reminder | `[x]` |
| A2 | 🟡 | **Dashboard ricorrenza ticket** — top 5 cause ricorrenti negli ultimi 90 gg | Query aggregata su `causa_radice` filtrando `ricorrente=True`; widget nella pagina impostazioni o dashboard tickets | `[x]` |

---

## Asset  (`assets`)

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| AS1 | 🔵 | **QR code per asset** — PDF con QR che punta a `/assets/<id>/` | Verificare stato attuale di `AssetLabelTemplate`; se già implementato marcare `[x]` | `[~]` |
| AS2 | 🟡 | **Costo manutenzione cumulato (TCO)** — campo `costo_euro` su `WorkOrder`; TCO aggregato nel dettaglio asset | `tco_cumulative` in `get_asset_maintenance_costs`; widget nel pannello costi `asset_detail` | `[x]` |
| AS3 | 🔵 | **Budget manutenzione** — target annuo per categoria asset; grafico speso/residuo | Modello `AssetMaintenanceBudget` (migration 0066); widget barra progresso verde/arancione/rosso nel dettaglio asset | `[x]` |
| AS4 | 🟡 | **Timeline storico tecnico asset** — vista verticale cronologica (OdL, verifiche, incidenti, cambi stato) | FK `asset` opzionale su `RilevazioneIncidente` (migration 0005); sezione "Storico tecnico" verticale nel dettaglio asset | `[x]` |

---

## DPI (`dpi`)

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| D1 | 🔴 | **Vita utile rimanente** — scadenza calcolata da `data_consegna + vita_utile` di `CategoriaDPI`; semaforo nel dettaglio e nella lista; reminder automatico | Campo `scadenza_calcolata` property su `ConsegnaDPI`; management command `send_dpi_expiry_reminders` schedulato come task Windows | `[x]` |
| D2 | 🟡 | **Report conformità per dipendente** — dipendente ha tutti i DPI previsti dal mansionario? Quali sono scaduti? | Vista aggregata per utente/dipendente; filtro per categoria DPI obbligatoria (da configurare in `DPIImpostazioni` o `CategoriaDPI`) | `[x]` |
| D3 | 🔵 | **Firma digitale consegna** — canvas HTML5 al momento della consegna; immagine PNG allegata a `ConsegnaDPI` | Campo `firma_immagine` su `ConsegnaDPI`; widget canvas lato client, POST base64 → salvataggio storage privato | `[x]` |

---

## Sicurezza / Preposto (`diario_preposto`, `rilevazione_incidenti`)

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| S1 | 🔴 | **KPI sicurezza automatici** — TRIR, giorni senza infortuni, trend mensile; widget nel `dashboard` | Calcolo da `RilevazioneIncidente` + headcount da `anagrafica`; widget configurabile nella `DashboardConfig` esistente | `[x]` |
| S2 | 🟡 | **Near-miss tracking** — categoria separata da "incidente" in `RilevazioneIncidente` | Campo `tipo_evento` con scelte `incidente / near_miss / unsafe_condition`; filtri e KPI separati | `[x]` |
| S3 | 🟡 | **Ispezioni/checklist periodiche** — il preposto compila ispezioni ricorrenti da template strutturato (area/macchina/voce) | Riuso modello `Checklist` esistente in `core`; nuova view `diario_preposto` per compilazione ricorrente con frequenza configurabile | `[x]` |
| S4 | 🔵 | **Heatmap incidenti su planimetria** — overlay punti incidente sulla planimetria esistente | Richiede `planimetria` non vuota; FK opzionale `RilevazioneIncidente → PlantArea`; render SVG overlay | `[x]` |

---

## Procedure (`procedure_refresh`)

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| P1 | 🟡 | **Scadenza revisione obbligatoria** — ogni `ProcedureDocument` ha frequenza revisione; segnalazione procedure scadute/in scadenza | Campo `revision_frequency_months` su `ProcedureDocument`; check in management command o query dashboard | `[ ]` |
| P2 | 🟡 | **Matrice formazione** — "chi deve leggere cosa" con % completamento per reparto; export per audit ISO | Vista pivot `ProcedureCampaignDocument × reparto`; export CSV con mixin generico | `[x]` |
| P3 | 🔵 | **Quiz post-lettura** — 2–3 domande a risposta multipla dopo la conferma di presa visione; non bloccante, tracciato | Nuovo modello `ProcedureQuiz` (FK `ProcedureRevision`); `ProcedureQuizAttempt` per tracking; non obbligatorio per `read_confirmed` | `[x]` |

---

## Core / Trasversale

| # | Priorità | Feature | Note tecniche | Stato |
|---|----------|---------|---------------|-------|
| C1 | 🔴 | **Centro notifiche consolidato** — campanella con badge e pannello unificato (scadenze asset, reminder DPI, anomalie, SLA ticket) | `core.Notifica` esiste già; aggiungere sorgenti mancanti (DPI, SLA); campanella in `base.html` con HTMX polling leggero | `[x]` |
| C2 | 🟡 | **Export universale CSV/Excel** — pulsante su qualsiasi lista con filtri applicati | Mixin Django `ExportMixin` riutilizzabile; `openpyxl` già in requirements; parametri filtro passati via GET | `[x]` |
| C3 | 🟡 | **Ricerca globale migliorata** — la ricerca esiste; estenderla con risultati per modulo, shortcut tastiera, preview risultato | Analisi della ricerca attuale prima di toccare; miglioramento incrementale senza riscrivere | `[x]` |
| C4 | 🔵 | **Vista attività utente** — "cosa ha fatto questo utente negli ultimi 30 gg" da `AuditLog` | Query aggregata su `AuditLog` per utente; pagina in `hub_tools` o `admin_portale`; nessun nuovo modello | `[x]` |

---

## Automazioni — Stato motore (2026-05-29)

**Estensioni motore applicate** (vedi `django_app/automazioni/packages/HANDOFF_AUTOMAZIONI.md` e CHANGELOG):
approvazioni a **catena** (`send_approval` annidate, max 3); operatori condizione **temporali**
(`days_from_now_lte/gte`, `days_span_gt/gte`); **validazione** import per `for_each`/`branch`/`do_until`;
campi virtuali `modified_by_id/role` nel registry anomalie (da popolare lato trigger SQL per AU42 "per ruolo").
Migrazione `0015_alter_automationcondition_operator`. Decisione: i flussi "crea ticket" restano **notifiche**
(insert raw bypasserebbe `Ticket.save()`/unique `numero_ticket`).

**Fix controllo-flusso (2026-05-29, batch 2)**: corrette 3 divergenze che impedivano l'esecuzione reale
dei `for_each`/`branch` da pacchetto: (1) la validazione placeholder dei container ora esclude i placeholder
delle azioni figlie (abilita `for_each` **cross-source**, es. offboarding→dpi); (2) runtime `for_each` accetta
`loop_actions`/`actions` e `max_iterations`; (3) runtime `branch` accetta `run_if`+`then/else_actions`;
(4) le azioni inline con parametri top-level vengono promosse a config (niente più config vuota a runtime).
Provato end-to-end in dev (locmem email).

**Fix run_if azione (batch 3, 2026-05-29)**: `_resolve_action_run_if` accetta il valore atteso sia come
`expected_value` sia come `value` (prima un `run_if` con `value`, es. AU35 `equals IN_CORSO`, confrontava
stringa vuota e veniva sempre saltato). Provato a runtime.

**Primitiva conteggio + escalation + digest (batch 4, 2026-05-29)**: nuovo action_type **`count_branch`**
(conta record di una sorgente con filtro + finestra temporale, confronta con `threshold`, esegue then/else;
migrazione `0016`). Sblocca le soglie "N eventi in M giorni": **AU36/AU37/AU38**. Aggiunte escalation
**AU49/AU50** (delay + run_if a cascata). Creati 4 **scaffold management command** (job schedulati Windows,
NON regole designer) per i digest **AU45/AU47/AU51/AU52**.

**AU-GAP1 completato + trigger anomalie (batch 5, 2026-05-29)**: trigger `trg_anomalie_automation.sql`
(auto-applicato da `apply_sql_triggers`); la view di salvataggio anomalia popola `modified_by_user_id`;
`_enrich_anomalie_payload` risolve `modified_by_role` (CC/CAR) via `AnomalieRoleAssignment`; registry con
`old_avanzamento`/`old_chiudere`. Sblocca **AU42b "per ruolo"** (notifica solo se modifica CC/CAR).
⚠️ PREREQUISITO DDL prod: colonna `modified_by_user_id` sulla tabella legacy `anomalie`.
**27 pacchetti** pronti in `packages/` + 4 management command. `manage.py check` OK, nessuna migrazione mancante.

## Automazioni — Flussi proposti (`automazioni`)

Proposte di regole per il designer automazioni, basate sulle sorgenti reali del `source_registry`
(trigger insert/update + campi `old_*` per i cambi stato) e sui tipi azione disponibili
(`send_email`, `insert_record`, `update_record`, `update_trigger_record`, `send_approval`,
`update_dashboard_metric`, `delay_schedule`, `for_each`, `branch`, `teams_webhook`, ecc.).
Bozze da rivedere prima dell'implementazione.

| # | Priorità | Flusso | Trigger / Condizione | Azioni | Stato |
|---|----------|--------|----------------------|--------|-------|
| AU1 | 🔴 | **Near Miss / unsafe → segnalazione + notifica** | `rilevazione_incidenti` insert (Near Miss e le altre tipologie) | **Solo** `send_email` a persone scelte (no ticket, no blocco). Rivisto da feedback utente | `[ ]` |
| AU2 | 🔴 | **Incidente senza DPI → segnalazione + notifica** | `rilevazione_incidenti` con `utilizzo_dpi=false` | **Solo** `send_email` a persone scelte (no ticket, no blocco). Rivisto da feedback utente | `[ ]` |
| AU3 | 🔴 | **Incidente → approvazione sequenziale RLS poi RSPP/ASPP** | `rilevazione_incidenti` insert, **indipendentemente dalla tipologia** | `send_approval` #1 a **RLS**; in approved → `send_approval` #2 a **RSPP/ASPP**. Doppia firma obbligatoria. Rivisto da feedback utente | `[~]` Pacchetto `au3_incidente_approvazione_rls_rspp.automation_package.json` con **doppia firma cascata** (motore esteso) + notifica direzione. Validato in dev. Destinatari da configurare |
| AU4 | 🔴 | ~~Visita medica NON IDONEA → blocco operativo~~ | — | **Scartato** da feedback utente | `[-]` |
| AU5 | 🟡 | **Corso fallito → re-iscrizione via approvazione (opzionale)** | `anagrafica_formazione_enrollment` con `stato` changed_to `NON_IDONEO`/`ASSENTE` | `send_approval` al responsabile formazione. **Attivabile in fase di creazione corso** (flag per-corso). Rivisto da feedback utente | `[ ]` |
| AU6 | 🔴 | **Offboarding aperto → checklist multi-modulo a cascata** | `anagrafica_offboarding` insert | `branch`/`for_each`: ticket IT revoca account+asset, notifica caporeparto (`{reparto}`), promemoria ritiro DPI | `[~]` Pacchetto `au6_offboarding_checklist_notifiche.automation_package.json` (3 notifiche email IT/magazzino/HR). ⚠️ Ticket IT NON creabile (insert_record solo su `core_notifica`); for_each DPI rimandato. Validato in dev |
| AU7 | 🔴 | **Ticket con fermo TOTALE → KPI + mail ticket standard** | `tickets` con `tipo_fermo` changed_to `TOTALE` | **Solo** `update_dashboard_metric` ore fermo (`{ore_fermo_macchina}`) + la solita mail di ticket. Rivisto da feedback utente | `[ ]` |
| AU8 | 🟡 | **Guasto ricorrente → arricchimento automatico** | `tickets` con `ricorrente=true` AND `ticket_origine_id` non vuoto | `update_trigger_record`: nota interna "già visto #{ticket_origine_id}" + `priorita`=CRITICA | `[~]` Pacchetto `au8_guasto_ricorrente_arricchimento.automation_package.json`. Validato in dev |
| AU9 | 🟡 | **Movimento RENTRI → promemoria caricamento dopo 5 giorni** | `rentri` insert, **indipendentemente dal tipo di rifiuto** | `delay_schedule` 5 giorni → se non è stato inserito/modificato il codice di caricamento RENTRI → `send_email` promemoria. Rivisto da feedback utente | `[ ]` |
| AU10 | 🔵 | **Notizia obbligatoria pubblicata → broadcast presa visione** | `notizie` con `obbligatoria=true` AND `stato` changed_to `pubblicata` | `send_email`/notifica broadcast (parallelo alle campagne procedure) | `[~]` Pacchetto `au10_notizia_obbligatoria_broadcast.automation_package.json`. Validato in dev |
| AU11 | 🟡 | **Procedura scaduta non letta → escalation gerarchica** | `procedure_assegnazioni` con `status` changed_to `overdue` | `send_email` all'utente, poi `delay_schedule` → responsabile se `read_confirmed_flag=false` | `[~]` Pacchetto `au11_procedura_overdue_escalation.automation_package.json` (sollecito + delay 3gg + escalation con run_if). Validato in dev |
| AU12 | 🟡 | **Qualifica in scadenza → ticket formativo preventivo** | `anagrafica_qualifiche` con `data_scadenza` in avvicinamento | `insert_record` richiesta rinnovo / notifica anticipata HR | `[~]` Pacchetto `au12_qualifica_scadenza_notifica.automation_package.json` (notifica HR con nuovo operatore `days_from_now_lte` 60gg). Validato in dev |

---

## Automazioni — Flussi con approvazione (`automazioni`)

Flussi imperniati sull'azione `send_approval`: l'evento mette in pausa il flusso, un umano decide
via **email** (bottoni Approva/Rifiuta, token monouso con scadenza `expires_at`), e
`process_approval_decision` esegue il ramo `approved_actions` oppure `rejected_actions`
(azioni inline: insert/update/email/notifica). Canale di consegna deciso: **Email**.
Cascata (doppia firma) prevista dove c'è valore economico o rischio legale.

| # | Priorità | Flusso | Trigger / Condizione | Ramo APPROVED | Ramo REJECTED | Stato |
|---|----------|--------|----------------------|---------------|---------------|-------|
| AU13 | 🔴 | **Ferie lunghe → doppia approvazione a cascata (caporeparto → HR)** | `assenze` insert, `tipo_assenza`=ferie, durata (`data_fine`−`data_inizio`) > 10 gg | `send_approval` #1 al `{capo_email}`; in approved → `send_approval` #2 a HR; in approved → conferma a `{dipendente_email}` | A ogni livello: email di rifiuto al dipendente | `[~]` Pacchetto `au13_ferie_lunghe_doppia_approvazione.automation_package.json` con **doppia firma cascata** (motore esteso) e durata >10gg via operatore `days_span_gt`. Validato in dev. HR da configurare |
| AU14 | 🔴 | **DPI → approvazione caporeparto se richiedente non è capo/preposto, poi magazzino** | `dpi` con `stato` changed_to `INVIATA` | Se il richiedente **non è** CAPOREPARTO/PREPOSTO: `send_approval` al **proprio caporeparto**; in approved → notifica a **magazzino**. Se è già capo/preposto: notifica diretta a magazzino | `update_trigger_record` `stato`=RIFIUTATA, scrive `{note_gestione}` | `[~]` Pacchetto `au14_dpi_approvazione_caporeparto_magazzino.automation_package.json`. ⚠️ Filtro "non capo/preposto" non esprimibile (ruolo non nel payload); email capo fissa da configurare. Validato in dev |
| AU15 | 🟡 | ~~Spesa fornitore/fermo totale → autorizzazione~~ | — | **Per ora no** (feedback utente) | — | `[-]` |
| AU16 | 🟡 | ~~Nuovo fornitore → onboarding approvato~~ | — | **Per ora no** (feedback utente) | — | `[-]` |

### Flussi multi-azione senza approvazione (dettagliati)

| # | Priorità | Flusso | Trigger / Condizione | Azioni in sequenza | Stato |
|---|----------|--------|----------------------|--------------------|-------|
| AU17 | 🔴 | **Incidente "Accident" → istruttoria completa** | `rilevazione_incidenti` insert, `tipologia_scheda`=Accident | email RSPP+RLS+direzione · `insert_record` notifica `core_notifica` al preposto · `delay_schedule` 72h → se `chiusura_rspp=false` sollecito · `update_dashboard_metric` "infortuni YTD" | `[ ]` | OK
| AU18 | 🟡 | **Visita idonea CON prescrizioni → vincolo tracciato** | `anagrafica_visite_mediche`, `esito` in_csv `IDONEO_PRESCR,IDONEO_LIM,IDONEO_LIM_PRESCR` | email caporeparto con `{prescrizioni}` + `insert_record` notifica persistente nel centro notifiche | `[ ]` | OK 
| AU19 | 🟡 | **Corso con scadenza → pre-pianificazione rinnovo** | `anagrafica_formazione_record` insert con `data_scadenza` non null | `delay_schedule` su `data_scadenza`−60gg → notifica HR "rinnovare {course_title_snapshot} per dipendente {legacy_anagrafica_id}" | `[ ]` | OK
| AU20 | 🟡 | ~~Segnalazione preposto → ticket + diario incrociati~~ | — | **Scartato** (feedback utente) | `[-]` |

---

## Automazioni — Notifiche su anomalie (`automazioni`)

I flussi base richiesti dall'utente: notifica alla creazione e alla modifica di un'anomalia.

| # | Priorità | Flusso | Trigger / Condizione | Azioni | Stato |
|---|----------|--------|----------------------|--------|-------|
| AU41 | 🔴 | **Anomalia creata → notifica responsabile** | `anomalie` insert (`all_inserts`) | `send_email` (con campo `cc` configurabile in design) con `{id}`, `{ex_op_nominativo}` (OP), `{seriale}` (PN), `{avanzamento}` | `[~]` Pacchetto `au41_anomalia_creata_notifica.automation_package.json` creato, campo `cc` predisposto, validato in dev (1/1). Destinatari `to`/`cc` da scegliere in designer all'attivazione |
| AU42 | 🔴 | **Avanzamento anomalia cambiato → notifica** | `anomalie` `specific_field` su `avanzamento`, operatore `changed` | `send_email` (con `cc` configurabile) "Anomalia {id} → stato {avanzamento}". Due versioni: "per campo" e "per ruolo" (AU-GAP1) | `[~]` **2 pacchetti**: `au42_anomalia_avanzamento_cambiato_notifica` (per campo) + `au42_anomalia_avanzamento_per_ruolo` (per ruolo, condizione `modified_by_role in_csv CC,CAR`, sbloccato da AU-GAP1). Entrambi validati in dev. Destinatari da scegliere in designer |
| AU43 | 🟡 | **Anomalia chiusa → conferma** | `anomalie` `specific_field` su `chiudere`, `changed_to=true` | `send_email` (con `cc` configurabile) conferma chiusura | `[~]` Pacchetto `au43_anomalia_chiusa_conferma_autore.automation_package.json` creato, `cc` predisposto, validato in dev (1/1). Destinatari da scegliere in designer |
| AU-GAP1 | 🔴 | **[Prerequisito tecnico] Esporre "chi ha modificato" nel payload anomalie** | — | Aggiungere a `source_registry` (sorgente `anomalie`) un campo `modified_by_id`/`modified_by_role` e popolarlo dal trigger SQL che alimenta `automation_event_queue`. Abilita le notifiche filtrate per ruolo (es. "solo se modifica CAPOCOMMESSA/CAR"). Richiesto da feedback utente | `[x]` Trigger `trg_anomalie_automation.sql` (auto-applicato da apply_sql_triggers) + `modified_by_user_id` popolato dalla view + `_enrich_anomalie_payload` risolve `modified_by_role` (CC/CAR) via `AnomalieRoleAssignment`. Testato in dev. ⚠️ PREREQUISITO DDL prod: colonna `modified_by_user_id` sulla tabella legacy `anomalie`. OK |

---

## Automazioni — Integrazione Microsoft/Teams (`automazioni`)

`HTTP_REQUEST` ristretto all'ecosistema **Microsoft/Power Automate/Teams** (scelta utente; Telegram solo come ipotesi futura).

| # | Priorità | Flusso | Trigger / Condizione | Azioni | Stato |
|---|----------|--------|----------------------|--------|-------|
| AU21 | 🟡 | **Fornitore delegato su ticket → notifica via Power Automate** | `tickets` con `delegato_fornitore_id` valorizzato AND `stato` changed_to `IN_CARICO` | `http_request` POST a flow Power Automate con `{numero_ticket}`, `{titolo}`, `{asset_nome}`, `{data_prevista_risoluzione}` | `[ ]` |NO
| AU22 | 🔵 | **Incidente grave → push immediato a Teams** | `rilevazione_incidenti`, `tipologia_scheda`=Accident | `teams_webhook`/`http_request` verso canale Teams reperibilità | `[ ]` |NO

---

## Automazioni — Orchestrazione FOR_EACH (`automazioni`)

Iterazione su record correlati (`for_each` con `filter_field` / `filter_value_template`).

| # | Priorità | Flusso | Trigger / Condizione | Azioni | Stato |
|---|----------|--------|----------------------|--------|-------|
| AU23 | 🟡 | **Offboarding chiuso → revoca DPI in blocco** | `anagrafica_offboarding` con `stato` changed_to `CHIUSA` | `for_each` su `dpi` filtrato per `richiedente_legacy_id={legacy_anagrafica_id}` → notifica magazzino ritiro per ogni richiesta | `[~]` Pacchetto `au23_offboarding_chiuso_foreach_dpi.automation_package.json` (for_each cross-source). Validato + provato a runtime in dev. Magazzino da configurare. OK |
| AU24 | 🟡 | **Campagna procedure chiusa → report inadempienti** | `procedure_campagne` con `status` changed_to `closed` | `for_each` su `procedure_assegnazioni` filtrato per `campaign_id={id}`, ramo se `read_confirmed_flag=false` → email utente + nota manager | `[~]` Pacchetto `au24_campagna_chiusa_foreach_inadempienti.automation_package.json` (for_each + branch run_if). Validato + provato a runtime in dev. OK |
| AU29 | 🟡 | **Visita NON IDONEA → sospendi formazione attiva** | `anagrafica_visite_mediche`, `esito` changed_to `NON_IDONEO_TEMP` | `for_each` su `anagrafica_formazione_enrollment` filtrato per `legacy_anagrafica_id`, ramo se `stato` in ISCRITTO/IN_CORSO → notifica resp. formazione | `[~]` Pacchetto `au29_visita_non_idonea_notifica.automation_package.json` — SOLO notifica resp. formazione (no for_each/sospensione, da feedback). Validato in dev. NO,SOLO NOTIFICA |
| AU30 | 🟡 | **Asset dismesso → segnala ticket aperti collegati** | `assets` con `status` changed_to `dismissed` | `for_each` su `tickets` filtrato per `asset_id={id}`, ramo se `stato` non in CHIUSA/ANNULLATA → nota interna + notifica assegnatario | `[~]` Pacchetto `au30_asset_dismesso_foreach_ticket.automation_package.json` (for_each + branch). Validato in dev. ⚠️ branch run_if singola condizione: filtra `stato=APERTA` (estendere in designer). OK |
| AU39 | 🔵 | **Fornitore disattivato → segnala ticket che lo usano** | `anagrafica_fornitori` con `is_active` changed_to `false` | `for_each` su `tickets` filtrato per `delegato_fornitore_id` + stato aperto → nota interna "ri-assegnare" | `[ ]` |
PER ORA NON IMPORTA 
---

## Automazioni — KPI dashboard live (`automazioni`)

`update_dashboard_metric` (operation increment/set) per cruscotti che si aggiornano da soli.

| # | Priorità | Flusso | Trigger / Condizione | Azioni | Stato |
|---|----------|--------|----------------------|--------|-------|
| AU25 | 🟡 | **Ticket chiuso → MTTR e contatori live** | `tickets` con `stato` changed_to `CHIUSA` | `update_dashboard_metric` increment "ticket_chiusi_mese" + somma `{ore_fermo_macchina}` su "downtime_totale" | `[~]` Pacchetto `au25_ticket_chiuso_kpi_live.automation_package.json` (2 metriche increment). Validato in dev. ⚠️ i codici metrica vanno creati in dashboard. OK |
| AU26 | 🔵 | **Formazione completata → % copertura per reparto** | `anagrafica_formazione_record` insert con `idoneo=true` | `update_dashboard_metric` increment metrica per reparto (KPI ISO) | `[ ]` | OK

---

## Automazioni — Presidio stati morti & soglie (`automazioni`)

Record dimenticati che diventano rischi, e conteggi via `for_each` che scattano oltre soglia.

| # | Priorità | Flusso | Trigger / Condizione | Azioni | Stato |
|---|----------|--------|----------------------|--------|-------|
| AU31 | 🟡 | **Scarico rifiuti senza FIR → blocco compliance** | `rentri` con `tipo`=O AND `arrivo_fir` vuoto | notifica resp. ambientale + `update_trigger_record` `salva=false` finché non sistemato | `[~]` Pacchetto `au31_scarico_senza_fir_notifica.automation_package.json` — SOLO notifica (no `salva=false`: evitato l'update SQL raw su record legacy RENTRI). Validato in dev. OK |
| AU32 | 🔵 | **Giacenza rifiuti pericolosi → alert deposito temporaneo** | `rentri` insert con `pericolosita` non vuota | `for_each` somma quantità stesso CER; se > soglia legge → alert smaltimento | `[ ]` | PER ORA NO
| AU33 | 🟡 | **Anomalia aperta da troppo → sollecito autore** | `anomalie` insert con `chiudere=false` | `delay_schedule` 7gg → se `chiudere` ancora false e `avanzamento` invariato → notifica `created_by` | `[~]` Pacchetto `au33_anomalia_aperta_troppo_sollecito.automation_package.json` (delay 7gg + run_if `chiudere is_false`). Validato in dev. ⚠️ autore=ID legacy non email → destinatario configurabile. OK, POI CAMBIO IO I GIORNI NEL CASO |
| AU34 | 🟡 | **Segnalazione preposto senza follow-up → escalation RSPP** | `diario_preposto` insert | `delay_schedule` 14gg → se nessuna azione collegata → notifica RSPP "{codice_identificativo} senza follow-up" | `[~]` Pacchetto `au34_segnalazione_preposto_followup_rspp.automation_package.json` (delay 14gg → promemoria RSPP). Validato in dev. ⚠️ run_if "nessuna azione" non esprimibile (payload non espone stato follow-up): promemoria sempre. OK |
| AU35 | 🔴 | **Offboarding non chiuso oltre ultimo giorno → alert HR** | `anagrafica_offboarding` insert | `delay_schedule` until `{ultimo_giorno_operativo}` → se `stato`=IN_CORSO → email HR (rischio account ancora attivi) | `[~]` Pacchetto `au35_offboarding_non_chiuso_alert_it.automation_package.json` (delay until + run_if `stato equals IN_CORSO`). Validato + run_if provato a runtime. ALERT A IT |
| AU36 | 🔵 | **3ª richiesta DPI stessa categoria in 30gg → anomalia consumo** | `dpi` insert | `for_each` su `dpi` per `richiedente_legacy_id` + categoria, 30gg; se count ≥ 3 → notifica gestore | `[~]` Pacchetto `au36_dpi_consumo_anomalo_count.automation_package.json` (azione `count_branch`, soglia ≥3 in 30gg). Validato + runtime. ⚠️ filtro per richiedente (non per categoria: count_branch ha un solo filter_field). OK |
| AU37 | 🟡 | **Ticket ricorrente su stesso asset → proposta manutenzione straord.** | `tickets` con `ricorrente=true` | `for_each` su `tickets` per `asset_id` 90gg; se count ≥ 3 → `send_approval` resp. manutenzione | `[~]` Pacchetto `au37_ticket_ricorrente_approvazione_manutenzione.automation_package.json` — **UPGRADE a soglia reale**: `count_branch` ≥3 ticket/asset in 90gg → `send_approval` annidata. Validato + runtime. OK |
| AU38 | 🟡 | **Incidenti ripetuti stesso reparto → audit sicurezza** | `rilevazione_incidenti` insert | `for_each` per `reparto` 60gg; se count ≥ soglia → `insert_record` ticket audit + alert RSPP | `[~]` Pacchetto `au38_incidenti_ripetuti_reparto_audit.automation_package.json` (`count_branch` ≥3/reparto in 60gg → alert RSPP). ⚠️ ticket audit NON creabile (whitelist insert): solo alert. Validato in dev. OK |
| AU40 | 🟡 | **Qualifica scaduta → coerenza con formazione** | `anagrafica_qualifiche`, `data_scadenza` raggiunta (delay until) | notifica HR + `run_if` esiste corso rinnovo pianificato; se no → `insert_record` promemoria | `[ ]` | NO

---

## Automazioni — Escalation gerarchica multi-step (`automazioni`)

Pattern "se nessuno risponde, sali di livello" con `delay_schedule` + `run_if` a cascata.

| # | Priorità | Flusso | Trigger / Condizione | Azioni a cascata | Stato |
|---|----------|--------|----------------------|------------------|-------|
| AU48 | 🔴 | **Ticket critico non preso in carico → escalation 3 livelli** | `tickets` insert con `priorita`=CRITICA | L1 assegnatario → +2h se `data_presa_in_carico` vuoto → L2 resp. manutenzione → +2h → L3 direzione | `[~]` Pacchetto `au48_ticket_critico_escalation_3_livelli.automation_package.json` (delay_schedule + run_if `is_empty` a cascata). Validato + gate run_if provato a runtime in dev. Tempi 2h e destinatari da modificare in designer. OK POI MODIFICO IO NEL CASO |
| AU49 | 🟡 | **Approvazione assenza non evasa → solleciti + auto-inoltro** | `assenze` insert | `send_approval` caporeparto → +24h se PENDING → sollecito → +24h → reinoltro automatico a HR | `[~]` Pacchetto `au49_assenza_non_evasa_sollecito_reinoltro.automation_package.json` (send_approval + delay + run_if `moderation_status`). Validato in dev. ⚠️ VERIFICARE valore numerico "pending" di moderation_status. OK. SCEGLIERO IO INOLTRO |
| AU50 | 🟡 | **Incidente non chiuso → escalation normativa crescente** | `rilevazione_incidenti`, `tipologia_scheda`=Accident | 24h preposto · 72h RSPP · 7gg RLS+direzione, ognuno con `run_if` su `chiusura_rspp=false` | `[~]` Pacchetto `au50_incidente_non_chiuso_escalation_normativa.automation_package.json` (delay 24/72h/7gg + run_if `chiusura_rspp is_false`). Validato in dev. OK |

---

## Automazioni — Job schedulati: digest & ricorrenti

⚠️ **Non sono regole del designer**: richiedono management command + task Windows (pattern già usato: `send_dpi_expiry_reminders`, `send_sla_reminders`). Inseriti qui per completezza del piano automazioni.

| # | Priorità | Flusso | Schedulazione | Contenuto | Stato |
|---|----------|--------|---------------|-----------|-------|
| AU44 | 🟡 | **Digest settimanale sicurezza** | Lunedì 08:00 | incidenti/near-miss settimana, near-miss aperti, audit reparto → RSPP+direzione | `[ ]` | NO
| AU45 | 🟡 | **Reminder mensile visite mediche** | 1° del mese | visite con `data_scadenza` nei 60gg → digest HR + medico competente per reparto | `[~]` Scaffold `anagrafica/management/commands/send_visite_mediche_digest.py` (query reale VisitaMedica, --dry-run OK). Da rifinire destinatari + schedulare task Windows. OK |
| AU46 | 🔵 | **Promemoria DPI stagionali** | 1° ott / 1° apr | notifica gestore DPI "avviare distribuzione stagionale" | `[ ]` | MM NO
| AU47 | 🔵 | **Digest trimestrale formazione (audit ISO)** | trimestrale | % copertura per reparto, corsi in scadenza → HR/RSPP (si aggancia a P2) | `[~]` Scaffold `anagrafica/management/commands/send_formazione_audit_digest.py` (query reale TrainingEmployeeRecord, --dry-run OK). TODO P2: % copertura per reparto. OK |
| AU51 | 🟡 | **Digest mattutino caporeparto** | giornaliero | per ogni capo: assenze da approvare, ticket reparto, incidenti aperti, DPI in attesa | `[~]` Scaffold `core/management/commands/send_caporeparto_morning_digest.py` (struttura + --dry-run). ⚠️ aggregazione per-capo e query cross-modulo da completare (TODO espliciti). OK |
| AU52 | 🔵 | **Digest manutentore "i miei ticket di oggi"** | giornaliero | ticket assegnati con scadenza oggi/scaduti → email all'assegnatario | `[~]` Scaffold `tickets/management/commands/send_ticket_daily_digest.py` (raggruppa per assegnato_email, --dry-run OK). Funzionante. OK |

---

## Note di utilizzo

- Questo file è la fonte di verità per il backlog funzionale; aggiungi righe liberamente.
- Prima di implementare un item, aprire il doc AI del modulo coinvolto (vedi `docs/ai/00_INDEX.md`).
- Al completamento: aggiornare lo stato a `[x]`, aggiornare `CHANGELOG.md` e verificare se serve aggiornare `README.md`.
- Items con `[~]` richiedono prima una verifica dello stato attuale nel codice.
