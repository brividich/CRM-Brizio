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
- [ ] L'anteprima non elenca ancora **le prime scadenze** («8 entro ottobre, 6 entro novembre» della specifica §29): mostra solo i conteggi

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
- [ ] Manca il **pulsante «Crea follow-up» dentro la checklist** quando uno step è KO o fuori range: la view lo supporta già via `?step=`, va aggiunto il link in `components/workorder_checklist.html`

### E5 — Dashboard
- [x] Quadro responsabile `/assets/manutenzione/quadro/`: scadute, in scadenza, non pianificate, OdL aperti/in corso, in attesa, rapporti mancanti, follow-up, conflitti
- [x] Sezione «manutenzioni dovute ma non pianificate» in evidenza
- [x] Matrice copertura `/assets/manutenzione/copertura/` con `✓ / P / X / ! / –`, celle cliccabili verso la personalizzazione
- [ ] **Caporeparto**: esiste il filtro per reparto, non uno scope automatico sul proprio reparto. Va deciso se derivarlo dall'anagrafica (attenzione: `reparto` sull'asset è testo libero) o da un permesso dedicato

### E6 — Scheda asset e gruppi
- [x] `/assets/manutenzione/asset/<id>/piani/`: periodicità, origine («Ereditato dal gruppo» / «Personalizzato» / «Escluso» / «Conflitto»), prossima scadenza, storico. La parola «override» non compare
- [x] Quando personalizzato mostra anche lo standard del gruppo
- [x] Personalizza / Escludi / torna al gruppo, con motivo
- [x] CRUD gruppi asset con selezione multipla degli asset
- [ ] Il blocco piani **non è ancora incorporato** nella scheda asset `/assets/view/<id>/`: è una pagina a sé, raggiunta dai link delle liste

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

## 4. Da fare — Fase F (amministrative e legacy)

- [ ] Eseguire `migrate_maintenance_to_plans --dry-run` in dev e **confrontare i conteggi** con quelli attesi (§65 della specifica: n. regole, n. asset coinvolti, n. state, n. OdL periodici, n. verifiche legacy)
- [ ] Rivedere a mano le applicazioni amministrative nate con `auto_generate=False` e impostare la periodicità reale
- [ ] Convertire o archiviare le `PeriodicVerification` con `is_legacy=False` elencate dal comando
- [ ] Import iniziale storico (§34/§62): wizard `asset_tag | piano | ultima esecuzione | note` con template Excel, anteprima, errori per riga, conferma. **Non ancora scritto.**
- [ ] Reindirizzare `send_maintenance_reminders` sulle occorrenze (oggi legge regole/verifiche/scadenze). Nota: oggi filtra `due_date >= today`, quindi **le scadute spariscono dalle mail** — da correggere nello stesso passaggio
- [ ] `automazioni/schedules.py:399` schedula `generate_scheduled_workorders`: sostituire con `generate_maintenance_occurrences`

---

## 5. Da fare — Fase G (deprecazione). **Non iniziare prima che la UI nuova sia in uso.**

Ordine obbligatorio: prima si migra, si verifica, e *solo dopo* si rimuove.

- [ ] Togliere i contatori dal flusso: `AssetMeter`, `AssetMeterHistory`, threshold HOURS/KM/CYCLES, `WorkOrder.meter_value_at_close`, `meter_is_stale`, badge e filtri relativi
  - punti da toccare: `maintenance.py` (`_snapshot_workorder_meter_value_at_close`, `meter_schedule_payload`, il ramo meter di `build_maintenance_schedule_rows`), `models.py` (`WorkOrder.close`), `generate_scheduled_workorders.py`, `views.py` (~29 riferimenti), `forms.py` (3), `tests.py` (~61)
  - i modelli si possono **deprecare** prima di droppare le tabelle; il codice nuovo non deve dipenderne
- [ ] `WorkMachine.next_maintenance_date` (`models.py`, scritto in `WorkOrder.close`): **oggi è una seconda fonte di verità.** Renderlo cache derivata dall'occorrenza aperta più vicina, o rimuoverlo
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
- **Branch manutenzione non mergiati** che toccano la stessa area e vanno riconciliati prima o dopo: `feature/assets-manutentore-fase5`, `feature/assets-manutentore-fase6`, `feature/assets-manutentore-cockpit-p1`, `feature/assets-manutenzione-ux`, `feat/manutenzione-quickwin`.
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
