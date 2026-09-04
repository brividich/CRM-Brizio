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

```powershell
python django_app\manage.py test assets.tests_maintenance_domain --settings=config.settings.test --keepdb
```

---

## 3. Da fare — Fase E (UI). **È il blocco più grosso rimasto.**

Nessuna view/template/URL è stata ancora scritta: il dominio è pronto e testato, l'interfaccia parla ancora il vecchio linguaggio.

### E1 — Piani
- [ ] Elenco piani (`/assets/manutenzione/piani/`): nome, tipo, n. asset coperti, periodicità applicate, prossima scadenza, scadute, attivo
- [ ] Scheda piano: applicazioni (gruppo/asset + periodicità + preavviso), prossime scadenze, OdL aperti, storico, follow-up
- [ ] Wizard nuovo piano a 5 step (Cosa / Dove / Quando / Chi / Anteprima). Step 5 deve mostrare «Questo piano interesserà N asset, X entro ottobre, Y conflitti»
- [ ] Riusare `RECURRENCE_PRESETS`: mai esporre cron o i sei campi grezzi
- [ ] Anteprima impatto prima del salvataggio di un'applicazione (analogo di `preview_maintenance_rule_impact`, ma sulle occorrenze)

### E2 — Da fare (pagina quotidiana del manutentore)
- [ ] Blocchi: SCADUTE / QUESTA SETTIMANA / PROGRAMMATE / IN ATTESA / ESTERNE
- [ ] Switch vista: per Piano / per Famiglia (gruppo) / per Asset
- [ ] Riepilogo in testa: scadute, entro 7 giorni, in programma, appuntamenti esterni
- [ ] Selezione multipla → `[Crea OdL]` (usa `create_workorder_from_occurrences`)
- [ ] Ordinamento: scadute → in scadenza → da pianificare → programmate → future (`VIEW_STATE_ORDER` esiste già)

### E3 — Scadenze
- [ ] Vista temporale: tab Scadute / 30 giorni / 90 giorni / Tutte / Amministrative / Ordinarie
- [ ] Filtri §26: piano, asset, gruppo, reparto, tipo, stato, assegnatario, fornitore, interna/esterna, con-senza OdL, rapporto mancante, follow-up aperto, periodo

### E4 — OdL
- [ ] Dettaglio OdL massivo: elenco occorrenze con checkbox, contatori «Completate / Da fare / Rimosse / Totale iniziale»
- [ ] Deselezionare un asset → `remove_occurrence_from_workorder` (mai chiusura/annullamento)
- [ ] `[Distribuisci su più giorni]` → `assign_occurrences_to_day`, raggruppamento per giornata, rapportino per giornata
- [ ] Chiusura per singola occorrenza (`complete_occurrence`), non per lotto
- [ ] Da step checklist KO/fuori range: `[Crea follow-up]` precompilato (asset, piano, occorrenza, OdL, step, descrizione)

### E5 — Dashboard
- [ ] Responsabile: SCADUTE, IN SCADENZA, NON PIANIFICATE, ODL APERTI/IN CORSO, IN ATTESA, RAPPORTI MANCANTI, FOLLOW-UP APERTI + sezione «manutenzioni senza OdL»
- [ ] Caporeparto: filtro sul proprio reparto (riusare i ruoli/ACL esistenti, non inventare un sistema parallelo)
- [ ] Matrice copertura asset × piani con `✓ ereditato / P personalizzato / X escluso / ! conflitto / - non applicato` (dati già pronti da `build_plan_resolutions`)

### E6 — Scheda asset e gruppi
- [ ] Blocco «Piani di manutenzione» nella scheda asset: periodicità, «Ereditato da: TORNI», prossima scadenza, azioni `[Personalizza] [Escludi] [Storico]` (mai la parola "override")
- [ ] Quando personalizzato, mostrare anche lo standard del gruppo (`inherited_recurrence_label` esiste già)
- [ ] CRUD gruppi asset + gestione membership

### E7 — Navigazione
- [ ] Voce «Manutenzione»: Da fare / Scadenze / Ordini di lavoro / Piani / Gruppi asset / Storico / Follow-up / Fornitori / Contratti
- [ ] Rimuovere «Scadenze amministrative» come sezione separata
- [ ] **Trappola nota**: la subnav non è hardcodata, si gestisce con `NavigationItem`; le voci nuove vanno seedate via migration (vedi `0076_maintenance_sidebar_unified.py` come esempio)

### E8 — ACL
- [ ] Registrare le nuove route in ACL v2 e in `API_ACL_GATE_PATHS` per gli endpoint AJAX — **senza questo `ACL_STRICT_CANONICAL` le nega con 403 in prod**
- [ ] Aggiornare `assets/acl_bootstrap.py`
- [ ] Ruoli: admin / responsabile / manutentore / caporeparto sui permessi già esistenti

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
