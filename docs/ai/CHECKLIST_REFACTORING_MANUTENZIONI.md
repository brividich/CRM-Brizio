# Checklist operativa — Refactoring modulo manutenzioni

Stato al **2026-09-04**. Branch di lavoro: `feature/assets-manutenzione-refactor` (base `origin/main` @ `7df6261a`).

Documento sorgente dei requisiti: [CLAUDE_CODE_REFACTORING_MANUTENZIONI_NOVICROM.md](CLAUDE_CODE_REFACTORING_MANUTENZIONI_NOVICROM.md).
Questo file è la **checklist di avanzamento**: autosufficiente, pensata perché un'altra sessione (Claude Code, Codex, o una persona) possa riprendere il lavoro senza rileggere tutto il repository. Aggiornare i checkbox a ogni completamento.

---

## 0. La trasformazione in una riga

```
PRIMA:  MaintenanceRule -> Asset -> WorkOrder          (la scadenza vive dentro l'OdL)
DOPO:   Piano -> Applicazione -> Occorrenza -> OdL     (la scadenza vive nell'occorrenza)
```

L'**occorrenza** è la fonte canonica della scadenza concreta. L'OdL è solo lo strumento che organizza il lavoro. Togliere un asset da un OdL non cancella la manutenzione: l'occorrenza torna "da pianificare".

---

## 1. Mappatura vecchio → nuovo (decisa e implementata)

| Vecchio | Nuovo | Nota |
|---|---|---|
| `MaintenanceInterventionTemplate` | **Piano di manutenzione** (stessa classe, estesa) | La classe NON è stata rinominata: 18k righe di `views.py` + template la referenziano. `verbose_name` = "Piano di manutenzione", la UI parla di Piano. Il rename fisico (`RenameModel`) resta un task meccanico opzionale, vedi §7. |
| `MaintenanceRule` | `MaintenancePlanAssignment` | Il piano non porta più la periodicità: la porta l'applicazione. |
| `MaintenanceRule.scope_type=CATEGORY` | Assignment `target_type=CATEGORY` | |
| `MaintenanceRule.scope_type=ASSETS` | `AssetGroup` (uno per regola, `code="regola-<id>"`) + Assignment `target_type=GROUP` | Il set di asset selezionati *è* un gruppo operativo. |
| `MaintenanceRuleAssetOverride` (personalizzato) | Assignment `target_type=ASSET` | Precedenza ASSET > GRUPPO > CATEGORIA. |
| `MaintenanceRuleAssetOverride.is_disabled` | Assignment `target_type=ASSET, is_excluded=True` | |
| `AssetMaintenanceRuleState.last_execution_date` | `MaintenanceOccurrence` con `status=DONE` | **Elimina la doppia fonte**: l'ultima esecuzione si legge dalle occorrenze eseguite. |
| `AssetAdministrativeDeadline` (+ completions) | Piano `maintenance_type=ADMINISTRATIVE` + Assignment + Occorrenze | `attachment_required` forzato a True, ancoraggio `FIXED_CALENDAR`. |
| `PeriodicVerification` | già assorbite in `MaintenanceRule` dalla migration `0089` → quindi in Assignment | Le residue (`is_legacy=False`) vengono **elencate**, non convertite in silenzio. |
| `AssetMeter` / `AssetMeterHistory` / threshold HOURS-KM-CYCLES / `meter_value_at_close` / `meter_is_stale` | **niente** | Fuori dal nuovo flusso. Vedi §5. |
| `WorkOrderExecutionDay` | esteso (`notes`, `completed_by`, `completed_at`, `occurrences`, `attachments`) | Non è stato creato un modello nuovo. |
| `WorkOrder.follow_up_of` | mantenuto + `follow_up_occurrence`, `follow_up_checklist_item`, `follow_up_reason` | Il follow-up resta un OdL correttivo: nessun modello nuovo, storico intatto. |

### Decisioni non ovvie, e perché

- **`WorkOrder.asset` resta NOT NULL anche sugli OdL massivi.** Punta all'asset *capofila* (prima occorrenza); l'elenco vero è `work_order.occurrences`. Renderlo nullable avrebbe rotto centinaia di `workorder.asset.asset_tag` in view e template. `is_massive` distingue i due casi; rimuovendo il capofila l'OdL riassegna `asset` alla prima occorrenza rimasta.
- **Ricorrenza su campi normalizzati, non JSON** (`frequency`/`interval`/`weekday`/`week_of_month`/`day_of_month`/`month_of_year`). Su SQL Server i lookup JSON sono terreno scivoloso e questi campi vanno filtrati e ordinati.
- **Le scadenze amministrative migrate nascono con `auto_generate=False`** e la nota "periodicità da confermare": il vecchio modello *non registrava* una periodicità e inventarne una in silenzio avrebbe prodotto scadenze finte. L'occorrenza corrente viene comunque creata, quindi nulla sparisce dalle liste operative.
- **Il conflitto tra gruppi blocca la generazione** invece di scegliere una periodicità: `generate_occurrences` conta i conflitti e non crea nulla per quella coppia.

---

## 2. Fatto (commit `1e5ac197`)

### Fase B — Nuovo dominio
- [x] `AssetGroup` + `AssetGroupMembership` (un asset in più gruppi logici)
- [x] Piano: `TYPE_ADMINISTRATIVE`, `execution_mode`, `default_supplier`, `default_assignee`, `attachment_required`, `schedule_anchor`, property `is_administrative` / `default_schedule_anchor` / `is_external`
- [x] `MaintenancePlanAssignment` con precedenza, esclusione, override di modalità/fornitore/assegnatario
- [x] `MaintenanceOccurrence` + `MaintenanceOccurrenceAttachment` (allegato per asset, storage privato)
- [x] Campi follow-up e `is_massive` su `WorkOrder`; `notes`/`completed_by`/`completed_at` su `WorkOrderExecutionDay`; `execution_day` su `WorkOrderAttachment`
- [x] Migration `assets/0098_assetgroup_and_more` (schema, nessun dato toccato)

### Fase C — Motore
- [x] `assets/services/recurrence.py`: giorni/settimane/mesi/anni, trimestre, semestre, «primo lunedì», «ultimo giorno del mese», annuale a data fissa; `describe_recurrence` in italiano; `RECURRENCE_PRESETS` per la UI
- [x] Due ancoraggi: `FROM_COMPLETION` (ordinaria) e `FIXED_CALENDAR` (amministrativa)
- [x] `assets/services/maintenance_domain.py`: risoluzione in blocco (3 query, niente N+1), conflitti, generazione idempotente, chiusura con avanzamento per asset, stati derivati
- [x] `generate_maintenance_occurrences` con `--dry-run`, `--plan`, `--horizon-days`

### Fase D — OdL massivi
- [x] `create_workorder_from_occurrences`, `add_occurrences_to_workorder` (mai automatico), `remove_occurrence_from_workorder` (non chiude, non annulla), `assign_occurrences_to_day`, `workorder_progress`

### Fase F (parziale) — Migrazione dati
- [x] `migrate_maintenance_to_plans` con `--dry-run`, `--skip-rules/--skip-history/--skip-deadlines`, conteggi, elenco dei residui

### Test
- [x] 35 test in `assets/tests_maintenance_domain.py` — coprono §64.1→§64.14 della specifica. Verdi.
- [x] 24 test in `assets/tests_maintenance_ui.py` sulle pagine e sui flussi. Verdi.

```powershell
python django_app\manage.py test assets.tests_maintenance_domain assets.tests_maintenance_ui --settings=config.settings.test --keepdb
```

---

## 3. Fase E (UI) — fatta, con i residui elencati

Commit della fase: `feature/assets-manutenzione-refactor`. Nuove pagine sotto `/assets/manutenzione/`, viste in `assets/views_maintenance.py`, form in `assets/forms_maintenance.py` (moduli separati: `views.py` è a 18k righe e `forms.py` a 3k, entrambi toccati da rami paralleli).

### E1 — Piani
- [x] Elenco `/assets/manutenzione/piani/`: tipo, asset coperti, periodicità applicate, prossima scadenza, scadute, conflitti
- [x] Scheda piano: applicazioni con periodicità leggibile e ancoraggio, conflitti in testa con link «Personalizza», prossime scadenze, OdL aperti, storico con ritardo
- [x] Form piano a sezioni numerate (Cosa / Chi / Documenti e calendario / Pubblicazione) — **non** un wizard multi-pagina: un form progressivo a step numerati copre lo stesso bisogno senza stato intermedio da gestire
- [x] Periodicità da preset leggibili (`RECURRENCE_PRESETS`); i sei campi grezzi compaiono solo con «Personalizzata»
- [x] Anteprima impatto AJAX prima del salvataggio: quanti asset coinvolge, quante scadenze aperte esistono già, quanti conflitti
- [x] Anteprima con **le prime scadenze** raggruppate per mese («3 entro settembre 2026»). Il preset di periodicità vince sui sei campi grezzi: scegliendo «ogni trimestre» quei campi restano ai valori iniziali del form, e l'anteprima calcolerebbe le date con una periodicità che nessuno ha scelto

### E2 — Da fare
- [x] Blocchi SCADUTE / ENTRO 7 GIORNI / PROGRAMMATE / IN ATTESA / ESTERNE
- [x] Switch di raggruppamento Piano / Famiglia / Asset (parametro `?by=`, non `?group=`: quello è il filtro per gruppo)
- [x] Riepilogo in testa cliccabile (scadute, entro 7 giorni, in programma, appuntamenti esterni)
- [x] Selezione multipla → «Crea ordine di lavoro» (barra che compare solo a selezione non vuota). La selezione sta **solo** nella sezione raggruppata: i blocchi in alto sono di lettura, altrimenti la stessa occorrenza sarebbe selezionabile due volte
- [x] Ordinamento per urgenza (`VIEW_STATE_ORDER`)

### E3 — Scadenze
- [x] Tab Scadute / 30 / 90 / Tutte / Amministrative / Ordinarie
- [x] Tutti i filtri della specifica §26 (piano, asset, gruppo, reparto, tipo, esecuzione, con/senza OdL, assegnatario, fornitore, rapporto mancante, ricerca)

### E4 — OdL massivi
- [x] Pannello «Manutenzioni raccolte» nel dettaglio OdL, raggruppato per giornata di esecuzione
- [x] Contatori «Completate · da fare · totale iniziale» + «parzialmente completato»
- [x] Rimozione di un asset che **non** chiude e **non** annulla (con conferma esplicita che lo dice)
- [x] «Distribuisci sulla giornata» sulla selezione
- [x] Chiusura per singola occorrenza, con allegato e blocco sulle amministrative
- [x] Follow-up agganciato a occorrenza + asset (accetta `?step=<id>` per lo step di checklist)
- [x] **«Apri follow-up» dentro la checklist** su uno step fuori range o saltato con motivazione. Il follow-up nasce da un'occorrenza, quindi su un OdL massivo la pagina chiede *su quale macchina* invece di sceglierne una d'ufficio; se un follow-up su quello step esiste già, mostra quello. Corretto anche il fatto che uno step fuori range fosse marcato «fatto» (barrato e verde) proprio nella riga che conteneva l'anomalia

### E5 — Dashboard
- [x] Quadro responsabile `/assets/manutenzione/quadro/`: scadute, in scadenza, non pianificate, OdL aperti/in corso, in attesa, rapporti mancanti, follow-up, conflitti
- [x] Sezione «manutenzioni dovute ma non pianificate» in evidenza
- [x] Matrice copertura `/assets/manutenzione/copertura/` con `✓ / P / X / ! / –`, celle cliccabili verso la personalizzazione
- [x] **Caporeparto**: «Da fare» e «Scadenze» preimpostano il filtro sui reparti guidati dall'utente (fonte autorevole `Reparto.caporeparto_legacy_id`, ponte `Profile.legacy_user_id`). È una preimpostazione **dichiarata in pagina** con «Mostra tutti i reparti» accanto, non una barriera: la visibilità in lista non è un confine di sicurezza. Se i nomi non combaciano — il `reparto` sull'asset è testo libero — il filtro non si applica affatto, perché una pagina vuota per disallineamento si legge come «non c'è lavoro»

### E6 — Scheda asset e gruppi
- [x] `/assets/manutenzione/asset/<id>/piani/`: periodicità, origine («Ereditato dal gruppo» / «Personalizzato» / «Escluso» / «Conflitto»), prossima scadenza, storico. La parola «override» non compare
- [x] Quando personalizzato mostra anche lo standard del gruppo
- [x] Personalizza / Escludi / torna al gruppo, con motivo
- [x] CRUD gruppi asset con selezione multipla degli asset
- [x] Blocco piani **dentro** la scheda asset `/assets/view/<id>/`: piano, periodicità, origine, prossima scadenza e stato, con link alla pagina di gestione. Quando l'asset ha piani, il blocco storico a regole tace: due fonti sulla stessa scheda direbbero la stessa manutenzione con due date diverse

### E7 — Navigazione
- [x] Subnav manutenzione: Da fare · Scadenze · Quadro · Piani · Gruppi asset · Interventi · Storico · Impostazioni · Report · Fornitori
- [x] «Oggi» e «Scadenzario» tolti dalla barra (le pagine restano per URL e evidenziano la voce nuova equivalente); «Catalogo e piani» → «Impostazioni»; l'azione «+ Nuovo piano» punta al nuovo form
- [ ] La voce «Scadenze amministrative» della sidebar asset resta finché la migrazione dei dati non è eseguita (fase F)

### E8 — ACL
- [x] Route registrate in `assets/acl_bootstrap.py` (cache key `v10`) e `/api/assets/manutenzione/` in `API_ACL_GATE_PATHS`
- [x] Tre gate: `can_manage_maintenance_plans`, `can_plan_maintenance`, `can_execute_maintenance` — ognuno passa da `user_can_modulo_action`, quindi i permessi granulari contano davvero
- [x] Due azioni concedibili dal pannello Accessi: `maintenance_planning`, `maintenance_execute`
- [ ] Da eseguire in ambiente: `bootstrap_acl_v2` / `acl_coverage_report` dopo il deploy, per confermare che le route nuove risultino coperte

### Verificato a video
Pagine aperte nel browser su un'istanza SQLite di prova, **tema chiaro e tema scuro**. Difetti trovati e corretti in questa fase:
- i commenti `{# … #}` multi-riga in cima ai partial venivano **stampati a video** (in Django `{# #}` commenta una riga sola) → convertiti in `{% comment %}`
- `display:grid` sulle classi dei campi vinceva sull'`[hidden]{display:none}` del browser, quindi i blocchi che il JS nasconde restavano visibili → aggiunta la regola esplicita
- l'enhancer `fm-table` aggiungeva una seconda casella di ricerca accanto a quella server-side → `data-fm-hide-search="1"` sulle tabelle del pacchetto

### Test
`assets/tests_maintenance_ui.py` — 24 test: rendering di tutte le pagine, raggruppamenti, filtri, matrice, OdL massivo (creazione, rimozione senza chiusura, distribuzione, completamento parziale, aggiunta esplicita), chiusura amministrativa con e senza documento, follow-up, preset di periodicità, esclusione, anteprima impatto, permessi negati.

---

## 4. Fase F (amministrative e legacy) — codice fatto, resta l'esecuzione sui dati

### Fatto in questa ondata

- [x] **Promemoria sulle occorrenze.** `send_maintenance_reminders` ha una fonte sola: se esiste anche una sola `MaintenanceOccurrence` la mail parla di occorrenze e le sorgenti legacy (scadenze amministrative, verifiche periodiche, righe da regola, contatori fermi) tacciono. Finché il nuovo dominio è vuoto vale il comportamento storico, così il promemoria non smette di partire durante la migrazione. Blocchi: SCADUTE · ESEGUITE MA SENZA RAPPORTO · in scadenza · OdL in ritardo. Le occorrenze già raccolte in un OdL aperto non compaiono tra le scadenze: le copre il blocco OdL
  - la nota precedente («le scadute spariscono dalle mail») **era già superata**: il blocco `!!! SCADUTE` esisteva
- [x] **Scheduler.** `assets_generate_workorders` → `assets_generate_occurrences` (`assets.tasks.run_generate_maintenance_occurrences`). Lo scheduler non apre più un OdL per asset
- [x] `RETIRED_SCHEDULE_NAMES` in `automazioni/schedules.py` + pulizia in `setup_q_schedules`: togliere una voce da `SCHEDULES` **non** rimuove il record django-q, e il vecchio job continuerebbe a girare dopo il deploy, invisibile alla Centrale di comando
- [x] **Import storico** (§34/§62): `assets/services/maintenance_history_import.py`, pagina `/assets/manutenzione/importa-storico/` (upload → anteprima riga per riga → conferma), modello Excel scaricabile, comando `import_maintenance_history` (`--template`, anteprima di default, `--apply`). Ripetibile: le righe già importate risultano «già presente». Una scadenza aperta preesistente **non** viene spostata sulla data calcolata dallo storico, e il conteggio lo dice

### Ricognizione sul DB di sviluppo — fatta il 2026-09-04 (sola lettura)

DB dev: `localhost\SQLEXPRESS`, database `PORTALE NOVICROM`, migrazioni assets ferme a `0097` (**`0098` non applicata**).

Per interrogare il DB dev **dal worktree**, senza copiare `.env` (che non va copiato: contiene `DB_ENGINE=sqlserver` anche per il profilo dev):

```powershell
$env:PORTAL_CONFIG_ENV_FILE = "C:\Dev\Portale Novicrom\django_app\.env"
python django_app\manage.py <comando> --settings=config.settings.dev
```

Cosa c'è da convertire, misurato:

| Grandezza | Valore | Conseguenza |
|---|---:|---|
| Regole attive | 18 | tutte `scope=CATEGORY` → 18 applicazioni su categoria |
| di cui a contatore (ore/km/cicli) | **0** | niente va perso nella dismissione dei contatori |
| Override per asset | 0 | nessuna personalizzazione da convertire, **nessun conflitto possibile** |
| Stati ultima esecuzione | 187 | 187 occorrenze eseguite |
| Scadenze amministrative attive | 2 | 2 piani amministrativi + 2 occorrenze aperte |
| `PeriodicVerification` con `is_legacy=False` | 4 | elencate dal comando, **non** convertite |
| Coppie piano/asset generate | 561 | 17 regole × 33 asset (la 18ª tocca una categoria senza asset in uso) |

**Il punto che decide la riuscita del passaggio**: delle 561 coppie, **187 hanno una data di ultima esecuzione e 374 no**. Tutte e 18 le regole hanno `first_due_date` a NULL, quindi per quelle 374 coppie il motore non ha né storico né data di partenza: `compute_due_date_for` restituisce **oggi**, e alla prima generazione nascerebbero 374 scadenze tutte dovute lo stesso giorno. È esattamente lo scenario che l'import dello storico esiste per evitare.

Foglio precompilato con le 374 righe da compilare (asset · piano · ultima esecuzione · note) generato in `scratchpad/storico_da_compilare.xlsx` — script `scratchpad/genera_foglio_storico.py`, legge solo il vecchio motore e gira anche prima della `0098`.

Dati puliti, nessun caso limite: 0 regole senza piano, 0 regole `CATEGORY` senza categoria, 0 con `auto_generate=False`.

### Da eseguire in ambiente (scrivono sul DB)

- [ ] **`migrate assets 0098`** sul DB dev — prerequisito di tutto: senza le colonne nuove su `MaintenanceInterventionTemplate` qualunque query sui piani fallisce (`Il nome di colonna 'execution_mode' non è valido`). La migration è additiva (5 `CreateModel`, 15 `AddField`, 2 `AlterField` di soli `help_text`/`choices`) e reversibile
- [ ] `migrate_maintenance_to_plans --dry-run`, confronto con la tabella qui sopra, poi senza `--dry-run`
- [ ] Compilare le 374 righe del foglio e caricarle (`import_maintenance_history <file>` per l'anteprima, poi `--apply`) **prima** della prima generazione
- [ ] Rivedere le 2 applicazioni amministrative nate con `auto_generate=False` e impostare la periodicità reale
- [ ] Decidere sulle 4 `PeriodicVerification` con `is_legacy=False` elencate dal comando
- [ ] `setup_q_schedules` (ritira `assets_generate_workorders`, registra `assets_generate_occurrences`)

> **Ordine vincolante**: `migrate 0098` → `migrate_maintenance_to_plans` → import dello storico → `setup_q_schedules`. Anticipare l'ultimo passo lascia un giorno senza generazione; saltare l'import fa nascere 374 scadenze finte tutte dovute oggi.

---

## 5. Da fare — Fase G (deprecazione). **Non iniziare prima che la UI nuova sia in uso.**

Ordine obbligatorio: prima si migra, si verifica, e *solo dopo* si rimuove.

### G1 — fatta il 2026-09-04

Sul DB dev il sottosistema contatori è **vuoto**: 0 `AssetMeter`, 0 `AssetMeterHistory`, 0 regole a soglia diversa da giorni, 0 `meter_value_at_close`, `next_maintenance_date` mai valorizzato su 38 macchine. È codice che non ha mai contenuto una riga, quindi rimuoverlo non tocca dati né comportamento.

- [x] Contatori fuori dal **flusso manutentivo**: via `meter_schedule_payload`, `_snapshot_workorder_meter_value_at_close`, `get_meter_stale_days`, `meter_days_since_update`, il ramo a contatore di `build_maintenance_schedule_rows` e dell'anteprima impatto regola, il ramo a contatore di `generate_scheduled_workorders`, la sezione «contatori fermi» del reminder, il badge nello scadenzario
- [x] `WorkOrder.close()` non scrive più `meter_value_at_close`
- [x] Le soglie a contatore **non si possono più creare**: `MaintenanceRuleForm` e il form override offrono solo «Giorni». Le regole esistenti restano leggibili finché il vecchio motore non viene ritirato del tutto
- [x] `WorkOrder.close()` non scrive più `WorkMachine.next_maintenance_date`. Era una seconda fonte di verità sulla scadenza, per giunta parziale: si aggiornava **solo** per gli OdL con `origin=PERIODIC`, quindi chiudendo un'esecuzione registrata a mano il campo restava indietro senza che nessuno lo notasse
- [x] `MeterStalenessTests` e `AssetMeterScheduleTests` sostituiti da `MissingScheduleRowTests`: la garanzia che sopravvive — «mai eseguita» è rossa e in cima, non grigia e in fondo — resta coperta per le regole a giorni, più un test che verifica che le soglie a contatore non producano righe

**Cosa NON è stato toccato, e perché**

- I **modelli** `AssetMeter`/`AssetMeterHistory` e il campo `WorkOrder.meter_value_at_close` restano definiti, e le tabelle non sono droppate: su dev sono vuote ma la produzione non è ispezionabile da qui. Il drop è una migration a sé, dopo aver verificato che anche in prod siano vuote
- Il **pannello letture contatore** nella scheda asset resta: cancellare l'unico posto dove si registra un dato è una decisione di prodotto, non un passo di refactoring, e il requisito della specifica («i contatori escono dal flusso manutentivo») è già soddisfatto
- `report_origin_proxy_damage` resta intatto: è uno strumento **forense** sul mondo pre-refactoring, e togliergli l'analisi dei contatori significherebbe perdere la possibilità di valutare il danno storico in produzione
- `WorkMachine.next_maintenance_date` **resta come campo**: non è solo una cache, è modificabile a mano e alimenta il piano del mese, la dashboard macchine e i report. Toglierlo è fase G2, insieme al resto del vecchio motore
### G2 — bloccata dalla fase F

Non si rimuove il vecchio motore prima di aver convertito i suoi dati: sul DB dev ci sono **18 regole attive e 187 stati di ultima esecuzione**. Finché `migrate_maintenance_to_plans` non è stato eseguito, toglierli lascerebbe il portale senza alcuna manutenzione programmata.

- [ ] Ritirare `generate_scheduled_workorders` (dopo che lo schedulatore usa il nuovo comando)
- [ ] Ritirare `AssetMaintenanceRuleState` e `sync_workorder_maintenance_state`
- [ ] Ritirare `MaintenanceRule` / `MaintenanceRuleAssetOverride` (soft: `is_active=False` + rimozione dalla UI, drop tabelle solo a valle)
- [ ] `AssetAdministrativeDeadline`: mantenere in sola lettura finché lo storico non è verificato

---

## 6. Verifiche prima di dire "fatto"

- [ ] `python django_app\manage.py test assets --settings=config.settings.test --keepdb`
  - **baseline nota**: 2 fallimenti pre-esistenti su `main` in `MaintenanceGeneratorDedupTests` (`origin` PERIODIC vs MANUAL: la view a `views.py:15440` imposta PERIODIC quando c'è una regola, il test si aspetta MANUAL). Non sono regressioni di questo lavoro
- [ ] `python django_app\manage.py makemigrations --check --settings=config.settings.test`
- [ ] Aprire davvero le pagine nel browser, **tema chiaro e scuro** — status 200 non è una verifica
- [ ] `CHANGELOG.md` e `README.md` aggiornati
- [ ] Bump di versione se cambia il comportamento visibile (vedi `06_TESTING_AND_QUALITY_GATES.md`)

---

## 7. Task opzionali, non bloccanti

- [ ] Rename fisico `MaintenanceInterventionTemplate` → `MaintenancePlan` (`migrations.RenameModel` + sed su views/forms/tests/template). Meccanico ma ad ampio raggio: farlo da solo, in un commit dedicato, a UI stabilizzata
- [ ] Versionamento delle checklist template (§35): oggi la checklist viene copiata nell'OdL alla creazione, quindi una modifica al template **non** altera gli OdL già eseguiti — il requisito minimo è già soddisfatto. Manca il numero di revisione visibile nello storico
- [ ] Costi per singola occorrenza (§41): oggi restano sull'OdL, `downtime_minutes` è già per occorrenza
- [ ] KPI `total_waiting_time` (§18)

---

## 8. Trappole del repository da non riscoprire

- **Sessioni parallele**: mai lavorare in `C:\Dev\Portale Novicrom` (checkout condiviso). Worktree dedicato: `git worktree add C:\Dev\pn-<tema> -B <branch> origin/main`. Al 2026-09-04 esiste già un altro worktree attivo su `feature/assets-manutenzione-ux` in `C:\Dev\pn-manutenzione-ux`.
- **Branch manutenzione: riconciliazione fatta il 2026-09-04.** Non resta nulla da mergiare oltre a questo ramo.
  - già in `main`: `feature/assets-manutentore-fase5`, `feature/assets-manutentore-fase6`, `feature/assets-manutentore-cockpit-p1`, `feature/assets-manutenzione-ux` (`git branch -r --merged origin/main` li elenca);
  - `feat/manutenzione-quickwin` (3 commit) e `feature/assets-shell-responsive`: **superati**. Git li vede non mergiati perché gli SHA differiscono, ma il contenuto è in `main` — verificato file per file (`send_maintenance_reminders.py`, `notifications.py`, `report_origin_proxy_damage.py` identici; il generatore legge già `AssetMaintenanceRuleState` e stampa «OdL #N ancora aperto»; il blocco `@media (max-width: 860px)` e il campo `internal_number` ci sono). Il loro diff verso `main` è fatto quasi solo di *rimozioni*: precedono la dismissione di SharePoint da assets;
  - `fix/assets-periodic-scope-all-assets`: **era l'unico ancora vivo**. Riportato su `main` come `fix/assets-periodic-scope-rebased` (`535aee47`), branch indipendente da questo refactoring perché la correzione può andare in produzione senza aspettarlo.
- **Collisione numeri migration**: dopo ogni merge, `makemigrations --check`. Questo lavoro usa `assets/0098`.
- **`{# #}` in Django commenta solo una riga**: su più righe i `{% %}` interni vengono comunque eseguiti.
- **`runserver` non ricarica i template**: dopo una modifica `.html` va riavviato.
- **SQL Server**: `Meta.ordering` + `.values().annotate()` o `.distinct()` → errore 8127, si risolve con `.order_by()` esplicito.
- **Nei worktree manca `.env`**: 3 test di `automazioni` falliscono, non è una regressione.
- **Test dev**: usare il python del venv `C:\Dev\Portale Novicrom\.venv\Scripts\python.exe` e label `assets.<modulo_test>` (senza prefisso `django_app`).

---

## 9. API del dominio, per chi scrive la UI

```python
from assets.services import maintenance_domain as domain
from assets.services.recurrence import describe_recurrence, RECURRENCE_PRESETS

# Chi si applica a chi (3 query, sicuro per matrice e dashboard)
resolutions = domain.build_plan_resolutions(asset_queryset=..., plan_ids=[...])
res = resolutions[(plan_id, asset_id)]
res.is_applied / res.is_conflict / res.is_excluded
res.source_label            # "Personalizzato" | "Ereditato dal gruppo" | ...
res.recurrence_label        # "Ogni 90 giorni"
res.inherited_recurrence_label
res.conflict_description()  # [{"target": "DMG MORI", "recurrence": "Ogni 90 giorni"}, ...]

domain.resolve_asset_plans(asset)            # scheda asset

# Generazione
domain.generate_occurrences(today=..., dry_run=True, horizon_days=None)

# Stato mostrato all'utente (derivato, non persistito)
domain.occurrence_state_payload(occurrence)  # state / label / badge_class / order / days_until_due

# OdL
wo = domain.create_workorder_from_occurrences([occ1, occ2], user=request.user)
domain.add_occurrences_to_workorder(wo, [occ3], user=request.user)
domain.remove_occurrence_from_workorder(occ2, user=request.user, reason="in produzione")
domain.assign_occurrences_to_day(wo, [occ1], execution_date=date(2026, 10, 20))
domain.workorder_progress(wo)                # total / done / todo / canceled / is_partial

# Chiusura (solleva OccurrenceCompletionError se manca l'allegato obbligatorio)
next_occ = domain.complete_occurrence(occ1, completed_on=..., user=request.user)
```
