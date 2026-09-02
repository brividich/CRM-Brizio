# 10 — Piano di ammodernamento sezione Manutenzione

_Versione: 2026-05-08 · Owner: brividich_

Questo documento è la checklist operativa del piano di ammodernamento del modulo manutenzione di NOVICROM HUB.  
Ogni item include descrizione, file coinvolti e criteri di completamento.  
**Aggiornare i checkbox man mano che i task vengono completati.**

---

## Indice fasi

- [Fase 1 — Quick win](#fase-1--quick-win)
- [Fase 2 — Interventi strutturali](#fase-2--interventi-strutturali)
- [Fase 3 — Funzionalità avanzate](#fase-3--funzionalità-avanzate)

---

## Contesto architetturale

### Modelli manutenzione esistenti

| Modello | Scopo | Note |
|---|---|---|
| `WorkOrder` | OdL correttivi/preventivi/sicurezza/taratura | ✅ Operativo. Campi: `kind`, `status`, `origin`, `intervention_duration_minutes`, `downtime_minutes`, `labor_cost_eur`, `materials_cost_eur`, `cost_eur`, `executed_by`, `maintenance_rule` FK, `periodic_verification` FK, `ticket` FK |
| `AssetAdministrativeDeadline` | Scadenze manuali (certificati, revisioni, collaudi) | ✅ Operativo. Ha `Completion` con costo + allegati + Outlook calendar |
| `MaintenanceRule` | Regole periodiche per categoria (giorni/ore/km/cicli) | ⚠️ Solo `DAYS` operative. `HOURS/KM/CYCLES` modellati ma non attivi |
| `MaintenanceRuleAssetOverride` | Override soglia/template per singolo asset | ✅ Operativo |
| `MaintenanceInterventionTemplate` | Template interventi riutilizzabili (code + label) | ✅ Operativo |
| `PeriodicVerification` | Verifiche M2M asset↔fornitore con frequenza mesi | ⚠️ Semi-disconnesso dall'engine regole |
| `WorkMachine.next_maintenance_date` | Data prossima manutenzione su macchina utensile | ⚠️ Campo manuale, non integrato con regole |
| `AssistanceContract` | Contratti assistenza/garanzia/full-service | ✅ Operativo |
| `AssetCalendarEvent` | Evento Outlook da scadenze/schedule | ✅ Operativo (admin-only) |

### Service layer esistente

| File | Funzioni | Stato |
|---|---|---|
| `assets/services/dashboard_kpi.py` | `get_family_dashboard_kpis`, `get_families_distribution`, `get_maintenance_by_family`, `get_downtime_by_family`, `get_maintenance_kpis_for_types`, `get_maintenance_status_by_family`, `get_fire_safety_kpis` | ✅ Operativo |

### Integrazioni moduli coinvolte

- **tickets**: `Ticket.tipo = TipoTicket.MAN` + `include_in_maintenance_register=True` → già usato in `_base_ticket_man_qs()`. Link bidirezionale `WorkOrder.ticket` FK.
- **anagrafica**: `Fornitore` usato da `PeriodicVerification` e `WorkOrder.supplier`
- **tasks**: `TaskExtraRef` lega task a asset; le macchine usano `is_machine_work=True`
- **anomalie**: anomalie di produzione potenzialmente correlate a guasti → integrazione futura

---

## Fase 1 — Quick win

> Dati già presenti nei modelli. Richiedono solo nuove aggregazioni, service functions o template aggiornati.

---

### P1.1 — KPI dashboard manutenzione (MTTR, Downtime, Costi, Backlog)

**Obiettivo**: Aggiungere nella `asset_dashboard` una sezione "Performance manutenzione" con metriche operative aggregate che oggi non sono visualizzate in nessun punto del portale.

**Metriche da calcolare**:

| Metrica | Definizione | Fonte dati |
|---|---|---|
| MTTR (ore) | Media `intervention_duration_minutes / 60` degli OdL correttivi chiusi nel mese | `WorkOrder` con `kind=CORRECTIVE`, `status=DONE`, `closed_at >= primo del mese` |
| Downtime ore (mese) | Somma `downtime_minutes / 60` degli OdL chiusi nel mese | `WorkOrder` con `status=DONE`, `closed_at >= primo del mese` |
| Costo manutenzione (mese) | Somma `resolved_total_cost_eur` degli OdL chiusi nel mese | `WorkOrder`, usa `cost_eur` o `labor_cost_eur + materials_cost_eur` |
| OdL aperti per tipo | Count per `kind` degli OdL con `status=OPEN` | `WorkOrder` |
| OdL chiusi nel mese | Già presente in `_compute_dashboard_kpis` come `wo_chiuse_mese` | Riusare |
| Ticket man aperti | Ticket di tipo MAN con stato aperto | `_base_ticket_man_qs()` già in `dashboard_kpi.py` |

**Integrazioni moduli**:
- `tickets`: mostrare `ticket_man_aperti` affianco agli OdL per dare una visione unificata delle richieste di intervento pendenti
- Collegare i numeri cliccabili alle rispettive list view (`wo_list`, `asset_administrative_deadline_list`)

**File da modificare**:
- `assets/services/dashboard_kpi.py` — nuova funzione `get_maintenance_performance_kpis(today, lookback_days=30)`
- `assets/views.py:asset_dashboard` — aggiungere chiamata e context
- `assets/templates/assets/pages/asset_dashboard.html` — nuova sezione "Performance manutenzione"
- `django_app/CHANGELOG.md`

**Criteri di completamento**:
- [x] Funzione `get_maintenance_performance_kpis` scritta in `dashboard_kpi.py` con test-safe (try/except)
- [x] Context arricchito nella view `asset_dashboard`
- [x] Sezione "Performance manutenzione" visibile nella dashboard con MTTR, downtime, costi, backlog per tipo
- [x] Numeri cliccabili verso le view pertinenti
- [x] Nessun errore su DB vuoto (valori zero se non ci sono dati)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-07

- `assets/services/dashboard_kpi.py`: `get_maintenance_performance_kpis` aggiunta con MTTR, downtime, costi, backlog per tipo + ticket MAN
- `assets/views.py:asset_dashboard`: chiamata e context `maintenance_perf`
- `assets/templates/assets/pages/asset_dashboard.html`: sezione `.ad-perf` con 4 card + 2 minibar panel, dark mode, numeri cliccabili

---

### P1.2 — Timeline storica unificata per asset

**Obiettivo**: Nella pagina `asset_detail`, aggiungere una sezione "Cronologia" che mostri in ordine cronologico inverso tutti gli eventi di manutenzione di quell'asset: OdL chiusi, completamenti scadenze amministrative, verifiche periodiche eseguite.

**Struttura dati timeline**:
Ogni riga avrà: `tipo` (WO/Scadenza/Verifica), `data`, `titolo`, `stato/esito`, `costo` (se presente), `link` (verso dettaglio).

**File da modificare**:
- `assets/views.py:asset_detail` — query aggiuntive per merge cronologico
- `assets/templates/assets/pages/asset_detail.html` — nuova tab o sezione "Cronologia"
- `django_app/CHANGELOG.md`

**Criteri di completamento**:

- [x] Timeline con completamenti scadenze amministrative (fonte principale mancante)
- [x] Ordinamento cronologico inverso (`-completed_on, -id`)
- [x] Limit 20 eventi più recenti
- [x] Link cliccabile verso la scadenza collegata
- [x] Nessuna query N+1 (`select_related("deadline", "completed_by")`)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/views.py:asset_detail`: `deadline_completion_history` query aggiunta al contesto
- `assets/templates/assets/pages/asset_detail.html`: tabella "Scadenze amministrative eseguite" nella card MAINTENANCE

---

### P1.3 — Auto-aggiornamento `next_maintenance_date` alla chiusura OdL

**Obiettivo**: Quando un `WorkOrder` con `origin=PERIODIC` viene chiuso e ha una `maintenance_rule` FK valorizzata, il sistema deve ricalcolare automaticamente `WorkMachine.next_maintenance_date` basandosi sulla data di chiusura + `threshold_value` in giorni della regola.

**Logica**:
```
WO.close() → se origin=PERIODIC e maintenance_rule e asset ha WorkMachine associata:
    new_date = closed_at.date() + timedelta(days=rule.threshold_value)
    WorkMachine.next_maintenance_date = new_date
    WorkMachine.save(update_fields=["next_maintenance_date"])
```

**Attenzione**: `WorkMachine` e `Asset` sono modelli separati. Verificare la relazione (`WorkMachine.asset` FK o campo separato).

**File da modificare**:
- `assets/models.py:WorkOrder.close()` — aggiunta logica post-chiusura
- oppure `assets/views.py:workorder_close` — se preferibile tenere la logica nella view
- `django_app/CHANGELOG.md`

**Criteri di completamento**:

- [x] Chiusura OdL periodico aggiorna `next_maintenance_date` sulla macchina collegata
- [x] Solo per `threshold_type=DAYS` (HOURS/KM/CYCLES non operativi)
- [x] Nessun effetto collaterale su OdL correttivi/manuali (guard su `origin` + `maintenance_rule_id`)
- [x] Silenzioso su errore — non blocca la chiusura OdL (try/except esterno)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/models.py:WorkOrder.close()`: aggiunto blocco post-save per aggiornare `WorkMachine.next_maintenance_date`

---

### P1.4 — Management command `send_maintenance_reminders`

**Obiettivo**: Management command schedulabile via Windows Task Scheduler che invia email agli admin assets per:
- Scadenze amministrative che scadono entro N giorni (default: 7 e 30)
- Verifiche periodiche che scadono entro N giorni
- OdL aperti da più di X giorni (default: 21, già usato nel portale)

**Pattern di riferimento**: guardare gli altri management command esistenti in `core/management/commands/` per il pattern di logging/output.

**Configurazione**: i valori soglia devono essere configurabili da `SiteConfig` o parametri CLI, non hardcoded.

**File da creare/modificare**:
- `assets/management/commands/send_maintenance_reminders.py` — nuovo command
- `django_app/CHANGELOG.md`, `README.md`

**Criteri di completamento**:

- [x] Command eseguibile con `python manage.py send_maintenance_reminders`
- [x] `--deadline-days` configurabile (default da `SiteConfig.assets_reminder_days`, fallback 30)
- [x] `--wo-overdue-days` configurabile (default 21)
- [x] `--recipients` override destinatari da CLI; fallback automatico su `SiteConfig.assets_reminder_emails` → `settings.ADMINS` → superuser con email
- [x] Dry-run mode con `--dry-run`
- [x] Nessuna email inviata se non ci sono scadenze imminenti (early return)
- [x] Controlla 3 fonti: `AssetAdministrativeDeadline` + `PeriodicVerification` + `WorkOrder` aperti in ritardo
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/management/commands/send_maintenance_reminders.py`: creato (nuovo file)

---

## Fase 2 — Interventi strutturali

> Richiedono nuovi meccanismi, nuovi modelli o modifiche significative all'engine esistente.

---

### P2.1 — Generazione automatica OdL da `MaintenanceRule`

**Obiettivo**: Management command `generate_scheduled_workorders` che, per ogni `MaintenanceRule` attiva con `threshold_type=DAYS`, verifica se è necessario creare un nuovo WorkOrder in base all'ultimo OdL chiuso per quella regola/asset. Schedulabile via Windows Task Scheduler (es. ogni mattina).

**Logica**:
```
Per ogni (asset, rule) in MaintenanceRule attive:
    last_wo = WO con origin=PERIODIC e maintenance_rule=rule su quell'asset, status=DONE, più recente
    if last_wo esiste:
        next_due = last_wo.closed_at.date() + timedelta(days=rule.threshold_value)
    else:
        next_due = today  # primo OdL mai creato
    if next_due <= today + warning_days:
        if non esiste già un WO OPEN per questa regola/asset:
            crea WorkOrder(origin=PERIODIC, maintenance_rule=rule, asset=asset, ...)
```

**Aggiunta modello suggerita**: campo `last_generated_at` su `MaintenanceRule` o query diretta sull'ultimo WO.

**File da creare/modificare**:
- `assets/management/commands/generate_scheduled_workorders.py` — nuovo command
- `assets/models.py:MaintenanceRule` — eventuale campo `last_generated_at`
- `assets/migrations/` — se si aggiunge il campo
- `django_app/CHANGELOG.md`, `README.md`

**Criteri di completamento**:

- [x] Command crea OdL solo se non ne esiste già uno aperto per regola+asset (guard in-memory + DB)
- [x] Dry-run mode con `--dry-run`
- [x] Log degli OdL creati/saltati con contatori
- [x] OdL generati con `origin=PERIODIC`, `kind=PREVENTIVE`, titolo da `intervention_template.label`
- [x] Nessun duplicato su esecuzioni multiple (idempotente)
- [x] Rispetta `MaintenanceRuleAssetOverride` (soglia e template personalizzati per asset)
- [x] `--category` per limitare a una singola categoria; `--limit` per batch parziali
- [x] Precarica override e OdL aperti in batch (no N+1)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/management/commands/generate_scheduled_workorders.py`: creato (nuovo file)

---

### P2.2 — Soglie ore/km/cicli operative (`AssetMeter`)

**Obiettivo**: Rendere operative le soglie `HOURS/KM/CYCLES` di `MaintenanceRule` tramite un nuovo modello `AssetMeter` che traccia il valore corrente dei contatori di ogni asset. Il command `generate_scheduled_workorders` usa questi valori per il trigger invece dei giorni.

**Nuovo modello**:
```python
class AssetMeter(models.Model):
    asset = FK(Asset)
    meter_type = CharField(choices: HOURS/KM/CYCLES/OTHER)
    current_value = DecimalField()
    unit_label = CharField()  # "ore", "km", "cicli", ecc.
    updated_at = DateTimeField(auto_now=True)
    updated_by = FK(User, null=True)
    notes = TextField()
```

**Form di aggiornamento rapido**: piccolo form inline nella `asset_detail` e nella `work_machine_dashboard` per aggiornare il contatore dal tablet in officina.

**File da creare/modificare**:
- `assets/models.py` — nuovo `AssetMeter`
- `assets/migrations/` — nuova migrazione
- `assets/views.py` — view aggiornamento contatore + API endpoint
- `assets/templates/assets/pages/asset_detail.html` — sezione contatori
- `assets/management/commands/generate_scheduled_workorders.py` — integrazione trigger
- `django_app/CHANGELOG.md`, `README.md`

**Criteri di completamento**:

- [x] Modello `AssetMeter` creato e migrato (`0064`)
- [x] Modello `AssetMeterHistory` per audit trail aggiornamenti creato e migrato (`0064`)
- [x] Campo `WorkOrder.meter_value_at_close` aggiunto e migrato (`0065`) — registra il valore contatore alla chiusura dell'OdL
- [x] Admin Django per `AssetMeter` con inline storico sola lettura; `AssetMeterHistoryAdmin` sola lettura
- [x] View `asset_meter_update` (GET/POST, HTMX outerHTML) a `/assets/<id>/meters/` — aggiorna contatore e crea record storico, loga con `log_action`
- [x] URL `asset_meter_update` registrata
- [x] Template partial `asset_meter_panel.html` con card valore corrente, form aggiornamento rapido, storico `<details>`, dark mode
- [x] Pannello contatori incluso nella card MAINTENANCE di `asset_detail.html` (caricato lazy via `hx-trigger="load"`)
- [x] `generate_scheduled_workorders` esteso per HOURS/KM/CYCLES: cerca `AssetMeter` del tipo corretto, calcola delta dall'ultimo WO, genera OdL se soglia raggiunta; salta senza errore se contatore mancante
- [x] `django check` pulito (0 issues)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/models.py`: `AssetMeter`, `AssetMeterHistory` aggiunti; `WorkOrder.meter_value_at_close` aggiunto
- `assets/migrations/0064_assetmeter_assetmeterhistory_and_more.py`: migrazione generata
- `assets/migrations/0065_workorder_meter_value_at_close.py`: migrazione generata
- `assets/admin.py`: `AssetMeterAdmin`, `AssetMeterHistoryAdmin`, `AssetMeterHistoryInline` aggiunti
- `assets/views.py`: `asset_meter_update` aggiunta; `AssetMeter`, `AssetMeterHistory` importati
- `assets/urls.py`: URL `asset_meter_update` aggiunta
- `assets/templates/assets/components/asset_meter_panel.html`: creato (nuovo file)
- `assets/templates/assets/pages/asset_detail.html`: pannello contatori inserito nel card MAINTENANCE
- `assets/management/commands/generate_scheduled_workorders.py`: supporto HOURS/KM/CYCLES aggiunto

**Stato**: ✅ Completato — 2026-05-08

---

### P2.3 — Vista "To-do manutenzione" per tecnico/reparto

**Obiettivo**: Nuova pagina `maintenance_todo` (URL: `/assets/manutenzione/todo/`) che mostra in un'unica schermata tutto ciò che richiede attenzione in ottica manutenzione:
- OdL aperti (ordinati per priorità/data apertura), filtrabili per reparto e assegnatario
- Scadenze amministrative in scadenza entro 30 gg (con link a dettaglio)
- Verifiche periodiche in scadenza entro 30 gg
- Work machine con `next_maintenance_date` nel passato o nei prossimi 14 gg

**Integrazioni moduli**:
- tickets: mostrare ticket MAN aperti assegnati all'utente corrente
- tasks: mostrare task `is_machine_work=True` scaduti o imminenti

**File da creare/modificare**:
- `assets/views.py` — nuova view `maintenance_todo`
- `assets/templates/assets/pages/maintenance_todo.html` — nuovo template
- `assets/urls.py` — nuova URL
- `assets/views.py:_default_sidebar_buttons` — aggiungere voce sidebar
- `django_app/CHANGELOG.md`, `README.md`

**Criteri di completamento**:

- [x] Pagina accessibile all'URL `/assets/manutenzione/todo/` (name `maintenance_todo`)
- [x] 5 sezioni: OdL / Scadenze / Verifiche / Macchine / Ticket MAN
- [x] Filtro per reparto (select con submit automatico)
- [x] Filtro per assegnatario: non-admin vedono solo i propri OdL e ticket
- [x] KPI chips nell'header con conteggi e colori semantici
- [x] Link a ogni dettaglio e alle list view di riferimento
- [x] Responsive (tabelle scrollabili, dark mode)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/views.py`: view `maintenance_todo` aggiunta
- `assets/templates/assets/pages/maintenance_todo.html`: creato (nuovo template)
- `assets/urls.py`: URL `maintenance_todo` aggiunta

---

### P2.4 — Consolidamento `PeriodicVerification` → `MaintenanceRule`

**Obiettivo**: Ridurre la duplicazione funzionale tra `PeriodicVerification` (cadenza in mesi, M2M asset) e `MaintenanceRule` (cadenza in giorni/ore/km, FK a categoria). I due sistemi si sovrappongono per le manutenzioni ricorrenti.

**Approccio proposto**:
1. `PeriodicVerification` viene mantenuto **solo come riferimento fornitore** (chi esegue la verifica, a quale fornitore è affidata)
2. Il **trigger temporale** passa a `MaintenanceRule` (più flessibile: giorni/ore/km)
3. Il `WorkOrder` già ha sia `periodic_verification` sia `maintenance_rule` FK — si mantiene il collegamento fornitore via `periodic_verification`
4. Nuovi OdL periodici vengono creati via `generate_scheduled_workorders` (P2.1) anziché da `PeriodicVerification`
5. Le verifiche esistenti vengono migrate con script

**File da modificare**:
- `assets/models.py:PeriodicVerification` — aggiungere `is_legacy=True` deprecation marker
- `assets/views.py:periodic_verification_list` — aggiungere banner deprecation
- `assets/management/commands/migrate_periodic_to_rules.py` — script migrazione dati
- `django_app/CHANGELOG.md`

**Nota**: questa è un'operazione delicata. Eseguire con `--dry-run` esteso prima di applicare.

**Criteri di completamento**:

- [x] Campo `is_legacy` aggiunto a `PeriodicVerification` con migrazione `0062`
- [x] Banner di deprecation visibile in `periodic_verification_list` con conteggio piani già migrati
- [x] Management command `migrate_periodic_to_rules` creato con `--dry-run`, `--apply`, `--pv-id`, `--only-legacy`
- [x] Command idempotente: non crea duplicati di template/regole su esecuzioni multiple
- [x] Suddivide i piani multi-categoria in piani asset-specifici per categoria
- [x] Preserva storico OdL e baseline ultima esecuzione; lascia pendenti solo piani senza asset o con asset non categorizzati
- [x] CHANGELOG aggiornato

**Stato**: ✅ Consolidato — 2026-08-05

- `assets/models.py:PeriodicVerification`: campo `is_legacy` aggiunto
- `assets/migrations/0062_periodicverification_is_legacy.py`: migrazione generata
- `assets/management/commands/migrate_periodic_to_rules.py`: creato (nuovo file)
- `assets/templates/assets/pages/periodic_verification_list.html`: banner deprecation giallo aggiunto
- `assets/views.py:periodic_verification_list`: `legacy_verification_count` nel contesto
- `assets/migrations/0088_*` / `0089_ingest_periodic_verifications_into_plans.py`: `MaintenanceRule` promosso a piano canonico con scope categoria/asset, responsabile, prima scadenza e automazione; ingestione dati automatica e conservativa.
- `/assets/manutenzione/impostazioni/`: catalogo attivita, piani ordinari e copertura separati; il vecchio archivio resta accessibile solo per eccezioni e tracciabilita.

---

## Fase 3 — Funzionalità avanzate

> Valutare ROI caso per caso. Implementare solo se il valore operativo è chiaro.

---

### P3.1 — Checklist step-by-step in OdL

**Obiettivo**: Permettere di aggiungere una checklist operativa a un WorkOrder, con step che il tecnico spunta durante l'esecuzione.

**Nuovo modello**:
```python
class WorkOrderChecklist(models.Model):
    work_order = FK(WorkOrder)
    step_number = IntegerField()
    description = CharField(max_length=255)
    is_done = BooleanField(default=False)
    done_at = DateTimeField(null=True)
    done_by = FK(User, null=True)
```

**Opzione alternativa**: riusare/estendere `MaintenanceInterventionTemplate` aggiungendo steps come sub-record del template, precomplilati all'apertura dell'OdL.

**File da creare/modificare**:
- `assets/models.py` — `WorkOrderChecklist`
- `assets/migrations/`
- `assets/views.py` — API toggle step (HTMX)
- `assets/templates/assets/pages/workorder_detail.html` — sezione checklist

**Criteri di completamento**:

- [x] Modello `WorkOrderChecklist` creato e migrato (`0063`)
- [x] Metodo `toggle(user)` aggiorna `is_done`, `done_at`, `done_by`
- [x] View `workorder_checklist_add` — aggiunge step, ritorna partial HTMX
- [x] View `workorder_checklist_toggle` — inverte stato step, ritorna partial HTMX
- [x] View `workorder_checklist_delete` — elimina step, ritorna partial HTMX
- [x] URL `wo_checklist_add`, `wo_checklist_toggle`, `wo_checklist_delete` registrate
- [x] Template partial `assets/components/workorder_checklist.html` con badge progresso, toggle e delete via `hx-post` + `hx-swap="outerHTML"`, fallback nativo POST
- [x] Sezione inclusa in `workorder_detail.html` con CSS dark mode
- [x] Solo OdL aperti (`status=OPEN`) permettono modifiche alla checklist
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/models.py`: `WorkOrderChecklist` aggiunto
- `assets/migrations/0063_workorderchecklist.py`: migrazione generata
- `assets/views.py`: tre view HTMX + `workorder_detail` arricchito
- `assets/urls.py`: tre URL checklist aggiunte
- `assets/templates/assets/components/workorder_checklist.html`: creato (nuovo file)
- `assets/templates/assets/pages/workorder_detail.html`: partial incluso + stili CSS `.wod-cl-*`

---

### P3.2 — Form segnalazione rapida operatore

**Obiettivo**: Form semplificato accessibile da `/assets/segnala/` per operatori non-admin: seleziona macchina/asset, descrive il problema, invia. Il sistema crea automaticamente un `Ticket` di tipo MAN o apre un OdL bozza.

**Integrazione moduli**: si collega al modulo `tickets` per l'apertura ticket MAN.

**File da creare/modificare**:
- `assets/views.py` — nuova view `asset_quick_report`
- `assets/templates/assets/pages/asset_quick_report.html`
- `assets/urls.py`

**Criteri di completamento**:

- [x] Pagina accessibile a `/assets/segnala/` (name `asset_quick_report`)
- [x] Form: selezione asset (non-IT, IN_USE) + testo libero, titolo, descrizione, categoria MAN, priorità, flag sicurezza
- [x] Crea `Ticket(tipo=MAN, include_in_maintenance_register=True)` con identità richiedente dal legacy user o Django user
- [x] Modelli tickets importati localmente inside-function
- [x] Pre-selezione asset da querystring `?asset=<id>` (utile per link da QR code)
- [x] Banner successo con link al ticket creato; banner errore su validazione fallita
- [x] Voci "To-do manutenzione" e "Segnala un problema" aggiunte alla sidebar assets
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/views.py`: `asset_quick_report` aggiunta; sidebar aggiornata
- `assets/urls.py`: URL `asset_quick_report` aggiunta
- `assets/templates/assets/pages/asset_quick_report.html`: creato (nuovo file)

---

### P3.3 — Landing mobile-first da QR code

**Obiettivo**: URL `/assets/qr/<asset_tag>/` che genera una pagina mobile-ottimizzata con: nome asset, stato, OdL aperti, ultima manutenzione, pulsante "Segnala problema" (→ P3.2). La funzione QR label `asset_label_designer` già genera il QR; serve la landing page.

**File da creare/modificare**:
- `assets/views.py` — `asset_qr_landing`
- `assets/templates/assets/pages/asset_qr_landing.html`
- `assets/urls.py`

**Criteri di completamento**:

- [x] Pagina accessibile a `/assets/qr/<asset_tag>/` (name `asset_qr_landing`)
- [x] Usa `asset_tag` come chiave (corrisponde al QR fisico)
- [x] Mostra: stato asset, giorni dall'ultimo intervento, prossima scadenza, OdL aperti (max 5)
- [x] CTA primaria "Segnala un problema" → P3.2 con `?asset=` precompilato
- [x] Template mobile-first max-width 480px, dark mode, extends `core/base.html`
- [x] Pagina not-found friendly se `asset_tag` non esiste
- [x] Target `landing` aggiunto a `_asset_qr_target_url` per designer etichette
- [x] Pulsante "Vista QR mobile" aggiunto alle quick actions di `asset_detail`
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/views.py`: `asset_qr_landing` + `_asset_qr_target_url` aggiornata + quick action aggiunta
- `assets/urls.py`: URL `asset_qr_landing` aggiunta
- `assets/templates/assets/pages/asset_qr_landing.html`: creato (nuovo file)

---

### P3.4 — Report costi manutenzione per asset/periodo

**Obiettivo**: Nella `asset_detail`, sezione "Analisi costi" con: costo totale per periodo (mese/trimestre/anno), breakdown per tipo intervento (preventivo/correttivo/sicurezza), confronto vs periodo precedente.

**Fonte dati**: `WorkOrder.resolved_total_cost_eur` + `AssetAdministrativeDeadlineCompletion.cost_eur`.

**File da modificare**:
- `assets/services/dashboard_kpi.py` — funzione `get_asset_maintenance_costs(asset_id, period)`
- `assets/views.py:asset_detail`
- `assets/templates/assets/pages/asset_detail.html`

**Criteri di completamento**:

- [x] Funzione `get_asset_maintenance_costs(asset_id, today)` nel service layer (`dashboard_kpi.py`)
- [x] Calcolo costi per mese corrente, trimestre corrente, anno corrente
- [x] Breakdown per tipo intervento (`kind`) con percentuale sul totale
- [x] Delta YoY (anno corrente vs anno precedente) con badge colorato
- [x] Costi scadenze amministrative (`AssetAdministrativeDeadlineCompletion`) inclusi nel totale annuo
- [x] Sezione "Analisi costi" in `asset_detail.html` con griglia KPI 3 colonne, breakdown con progress bar, YoY badge — tutto racchiuso in `{% if asset_maintenance_costs.has_data %}`
- [x] Guard `try/except` nella view per compatibilità mssql-django (nessun `ExpressionWrapper`/`DurationField`)
- [x] `django check` pulito (0 issues)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/services/dashboard_kpi.py`: funzione `get_asset_maintenance_costs` aggiunta
- `assets/views.py:asset_detail`: chiamata con guard try/except, context key `asset_maintenance_costs`
- `assets/templates/assets/pages/asset_detail.html`: sezione "Analisi costi" aggiunta nel card MAINTENANCE

---

### P3.5 — Aggiornamento contatori macchina da tablet (integrazione P2.2)

**Obiettivo**: Form rapido in `work_machine_dashboard` per aggiornare ore/cicli direttamente dall'officina, senza dover aprire il dettaglio asset.

**Dipendenza**: P2.2 deve essere completato prima.

**File modificati**:

- `assets/views.py:work_machine_dashboard` — precarica `AssetMeter` e calcola `machines_with_meters`
- `assets/templates/assets/pages/work_machine_dashboard.html` — nuova sezione "Contatori macchine"

**Criteri di completamento**:

- [x] Sezione "Contatori macchine" visibile nella dashboard solo se esistono macchine con contatori configurati
- [x] Per ogni macchina: nome/tag/reparto + pannello HTMX contatori caricato lazy (`hx-trigger="load"`)
- [x] Riutilizza il partial `asset_meter_panel.html` di P2.2 — form aggiornamento + storico inline
- [x] Precarica batch degli `AssetMeter` nella view (no N+1)
- [x] `django check` pulito (0 issues)
- [x] CHANGELOG aggiornato

**Stato**: ✅ Completato — 2026-05-08

- `assets/views.py:work_machine_dashboard`: `machines_with_meters` e `meters_by_asset_id` aggiunti al context
- `assets/templates/assets/pages/work_machine_dashboard.html`: sezione "Contatori macchine" inserita prima di "Copertura documentazione"

---

## Fase 4 — Cockpit del manutentore (analisi 2026-09-02)

> Analisi richiesta dall'utente sulla prospettiva del **manutentore in officina** (non del pianificatore/responsabile): il modulo ha già un motore dati ricco (piani preventivi, scadenze, OdL, checklist, costi, allegati, QR, storico), ma l'interfaccia oggi è pensata per chi pianifica e controlla, non per chi esegue.

**Flusso ideale individuato**: `Il mio turno / Scansiona QR → contesto e rischi → Inizia → procedura guidata → tempo, ricambi, evidenze → Completa oppure Blocca/Escala`.

### Criticità individuate (per priorità)

| Priorità | Problema | Conseguenza | Stato |
|---|---|---|---|
| **Critica** | `close()`/`sync_workorder_maintenance_state` avanzavano la prossima scadenza anche quando l'esito finale era "Non risolto" (il WO transitava per DONE prima di tornare OPEN) | Scadenza futura potenzialmente falsa, fiducia nei dati compromessa | ✅ **Corretto** — vedi P4.1 |
| Alta | Filtro `?asset=<id>` generato dalla landing QR non era gestito da `workorder_list` | Il link "Vedi tutti gli interventi" dalla QR mostrava tutti gli OdL, non solo quelli dell'asset scansionato | ✅ **Corretto** — vedi P4.2 |
| Alta | Interventi aperti nella landing QR erano solo informativi, non cliccabili | Il manutentore doveva navigare altrove per aprire/chiudere l'intervento visto sul QR | ✅ **Corretto** — vedi P4.3 |
| Alta | Etichetta ruolo hardcoded "Amministratore sistema" in `base_shell.html` | Mostrata identica a ogni utente del modulo, indipendentemente dal ruolo reale | ✅ **Corretto** — vedi P4.4 |
| Alta | Campo "Eseguito da" nel form di chiusura vuoto di default | Il manutentore doveva ricercarsi ogni volta nell'elenco utenti per chiudere un proprio intervento | ✅ **Corretto** — vedi P4.5 |
| Alta | Stati OdL limitati a Aperto/Chiuso/Annullato; niente priorità né due-date esplicita | L'urgenza è dedotta dall'anzianità, non dichiarata | ⏳ Aperto — richiede decisioni di modello dati (vedi Fase 5) |
| Alta | Home non distingue bene "non assegnati a me" nella coda personale | Presa in carico spontanea poco naturale | ⏳ Aperto — vedi Fase 5 |
| Media | Checklist solo sì/no, non tipizzata (misure, foto, firma) | Controlli di sicurezza restano testo libero | ⏳ Aperto — vedi Fase 6 |
| Media | Materiali/durata previsti dal template poco visibili nell'intervento | Il tecnico non vede subito cosa preparare | ⏳ Aperto — vedi Fase 5 |
| Evolutiva | Nessun autosalvataggio/offline nel sottomodulo | Rischio perdita dati in officina | ⏳ Aperto — non prioritario, richiede architettura dedicata (vedi Fase 6) |

Nota: esiste un bug distinto e preesistente (non toccato in questa fase, tracciato anche in memoria `analisi_assets_p0_aperti`) — `MaintenanceGeneratorDedupTests.test_open_manual_workorder_blocks_the_generator`/`test_closed_manual_workorder_releases_the_rule` falliscono già su `main`: l'apertura manuale di un OdL legato a una regola (`wo_create` con `maintenance_rule`) non imposta `origin=MANUAL` come atteso dal test. Da investigare separatamente, non è collegato al fix P4.1.

### P4.1 — Fix "Non risolto" non deve mai avanzare la scadenza (Critica)

**Problema**: in `workorder_close`, il WO veniva chiuso con `status=DONE` (che fa scattare `close()` → aggiornamento `WorkMachine.next_maintenance_date` per regole a giorni, e `sync_workorder_maintenance_state()` → upsert `AssetMaintenanceRuleState`), e **solo dopo** — se l'esito scelto era "Non risolto" — lo stato veniva riportato a `OPEN`. La scadenza risultava quindi già avanzata su una manutenzione che non aveva risolto nulla.

**Fix**: l'esito (`esito`) viene letto **prima** di chiamare `workorder.close()`; se `status richiesto == DONE` e `esito == NOT_RESOLVED`, lo stato effettivo passato a `close()` è direttamente `OPEN` — così `close()` non tocca più `WorkMachine.next_maintenance_date`, non cattura lo snapshot del contatore, e il controllo `sync_workorder_maintenance_state` (che verifica `status == DONE`) non scatta. `WorkOrder.close()` è stato inoltre corretto per non impostare più `closed_at` quando lo stato passato è `OPEN`.

**File modificati**:
- `assets/models.py` — `WorkOrder.close()`: `closed_at` impostato solo se `status != STATUS_OPEN`
- `assets/views.py` — `workorder_close`: calcolo di `reopened_as_unresolved`/`effective_status` prima della chiamata a `close()`; rimossa la logica di "flip-back" post-hoc duplicata
- `assets/tests.py` — nuovo test `test_workorder_close_not_resolved_reopens_without_advancing_schedule`

**Criteri di completamento**:
- [x] `close()` non avanza `next_maintenance_date`/`AssetMaintenanceRuleState` quando l'esito finale è "Non risolto"
- [x] `closed_at` resta `None` quando l'OdL riapre come "Non risolto"
- [x] `meter_value_at_close` non viene catturato in questo caso
- [x] Test di regressione con `MaintenanceRule`/`AssetMaintenanceRuleState`
- [x] Suite `assets` invariata (414/415 test verdi, i 2 fallimenti sono preesistenti e non collegati)

**Stato**: ✅ Completato — 2026-09-02

### P4.2 — Fix filtro asset nella lista OdL

**Problema**: `workorder_list`/`_apply_workorder_list_filters` non leggevano mai `request.GET["asset"]`, nonostante `wo_list_url` nella landing QR lo generasse (`?asset=<id>`).

**Fix**: aggiunto filtro `asset_id` in `_apply_workorder_list_filters`, propagato in `workorder_list` (context `asset_filter`) e come chip rimovibile in `_workorder_list_filter_chips`.

**File modificati**: `assets/views.py`, `assets/tests.py` (`test_workorder_list_filters_by_asset_from_qr_landing_link`).

**Stato**: ✅ Completato — 2026-09-02

### P4.3 — OdL aperti cliccabili dalla landing QR

**Problema**: nella landing QR (`asset_qr_landing.html`), gli OdL aperti erano righe informative senza link.

**Fix**: per utenti autenticati (non QR pubblico) ogni riga OdL è ora un link verso `assets:wo_view`. Il QR pubblico anonimo resta invariato (nessuna azione operativa esposta senza login).

**File modificati**: `assets/templates/assets/pages/asset_qr_landing.html`, `assets/tests.py` (`test_asset_qr_landing_open_workorders_are_clickable_for_authenticated_user`).

**Stato**: ✅ Completato — 2026-09-02

### P4.4 — Etichetta ruolo dinamica nella sidebar Assets

**Problema**: `base_shell.html` mostrava sempre "Amministratore sistema", indipendentemente dal ruolo reale dell'utente.

**Fix**: l'etichetta usa ora `can_gestione_admin` (già presente nel context di `_assets_shell_context`, stessa condizione che mostra la voce di menu "Amministrazione") per distinguere "Amministratore" da "Operatore Assets".

**File modificati**: `assets/templates/assets/base_shell.html`.

**Stato**: ✅ Completato — 2026-09-02

### P4.5 — Precompilazione esecutore nella chiusura OdL

**Problema**: il campo "Eseguito da" nel form di chiusura restava vuoto finché nessuno lo impostava esplicitamente, obbligando il manutentore a ricercarsi ogni volta.

**Fix**: se `workorder.executed_by_id` non è impostato, il valore iniziale del form è l'utente corrente (resta comunque modificabile, ad esempio se chi chiude non è chi ha eseguito il lavoro).

**File modificati**: `assets/views.py` (`workorder_close`), `assets/tests.py` (`test_workorder_close_form_defaults_executed_by_to_current_user`).

**Stato**: ✅ Completato — 2026-09-02

## Fase 5 — Cockpit del manutentore: coda e schermata di esecuzione

> Analisi 2026-09-02, seconda iterazione (dopo i quick win di Fase 4). Ambito concordato con l'utente: modello dati (priorità/stati operativi) + home "Il mio turno" + schermata unica di esecuzione, tutto insieme.

**Decisioni prese con l'utente**: 3 livelli di priorità (Urgente/Normale/Bassa); lo stato operativo (in corso/in attesa) è un **sotto-stato dentro OPEN**, non nuovi valori di `WorkOrder.STATUS_CHOICES` — per non toccare ogni punto del codice che oggi confronta `status == OPEN` (filtri, dashboard, generatore scadenze, ACL).

**Scoperta in fase di analisi**: il "in attesa con motivo" del report (ricambio/fornitore/autorizzazione/...) **esisteva già** — `WorkOrder.is_waiting`/`wait_reason`/`wait_note`/`waiting_since` (migration `0093`). Non è stato duplicato: lo stato operativo `waiting` è derivato da `is_waiting`.

### P5.1 — Priorità, scadenza esplicita e stato operativo derivato

**Fatto**: `WorkOrder.priority` (URGENT/NORMAL/LOW, default NORMAL, `db_index`), `WorkOrder.due_at` (opzionale), `WorkOrder.started_at` (timestamp "Inizia intervento"). `operational_state` è una **property** (non un campo) derivata da `assigned_to_id`/`started_at`/`is_waiting`, per evitare un quarto stato da tenere sincronizzato manualmente — `unassigned` → `assigned` → `in_progress` (via `start()`) → `waiting` (via `is_waiting`, invariato). `start()` è idempotente e riprende automaticamente da un'attesa. `is_overdue` deriva da `due_at`+`status`.

**File**: `assets/models.py`, migration `0095_workorder_due_at_workorder_priority_and_more.py`.

**Stato**: ✅ Completato — 2026-09-02, 10 test nuovi verdi.

### P5.2 — Schermata di esecuzione consolidata nel dettaglio OdL

**Deciso**: non una pagina nuova — il dettaglio OdL esistente (`workorder_detail.html`) era già ricco (checklist, allegati, log, gestione attesa/riassegnazione); vi si sono aggiunti priorità/scadenza/stato operativo e il bottone "Inizia intervento"/"Riprendi lavorazione", invece di introdurre un terzo punto di navigazione oltre a dettaglio e chiusura.

**File**: `assets/views.py` (`workorder_detail`, azioni `start`/`set_priority`), `assets/templates/assets/pages/workorder_detail.html`.

**Stato**: ✅ Completato — 2026-09-02.

### P5.3 — Home "Il mio turno"

**Fatto**: `/assets/manutenzione/il-mio-turno/`, distinta dal Centro Manutenzione del responsabile. Sezioni **Bloccati → Emergenze → Scaduti → Oggi → In corso → Altri assegnati a te → Da prendere in carico**; ogni OdL compare in una sola sezione (la prima applicabile, per non mostrare lo stesso intervento due volte). "Da prendere in carico" usa il claim esistente (`assets:wo_claim`) con redirect di ritorno, non un link che promette un'azione e apre solo il dettaglio.

**File**: `assets/views.py` (`il_mio_turno`), `assets/urls.py`, `assets/templates/assets/pages/il_mio_turno.html`.

**Nota deploy**: la voce di sidebar "Il mio turno" è nel fallback di default (`_default_sidebar_buttons`, non usato quando `AssetSidebarButton` non è vuota) **e** seminata via migration dati (`assets/0097_seed_il_mio_turno_sidebar_button.py`) — si applica da sola al prossimo `migrate` in ogni ambiente, prod incluso, senza intervento manuale.

**Stato**: ✅ Completato — 2026-09-02, 2 test nuovi verdi (sezioni mutuamente esclusive, claim con redirect).

**Verifica**: HTTP autenticato diretto su server dev (login, sezioni popolate, OdL nella sezione attesa) — **corretto dopo**: quel server dev girava sul SQL Server locale reale (`config.settings.dev` non è SQLite su questa macchina), non un vero controllo visivo. Verificare aspetto/tema chiaro-scuro prima del deploy.

## Fase 6 — Qualità del dato sul campo (parziale: punti 1/3/4)

> Ambito concordato con l'utente: punti 1 (checklist tipizzate), 3 (causa guasto codificata) e 4 (autosalvataggio) del backlog Fase 6 originale. Esclusi in questo giro: 2 (ricambi strutturati — richiede decisioni su un catalogo scorte che non esiste nel portale) e 5 (offline-first — richiede architettura dedicata, esplicitamente "dopo aver validato gli altri punti").

**Decisioni prese con l'utente**: catalogo causa guasto = Elettrica/Meccanica/Idraulica/Usura/Errore operatore/Altro; uno step obbligatorio/di sicurezza non compilato **blocca la chiusura** dell'OdL (si può forzare solo con motivazione esplicita salvata); tipi di step aggiunti ora = Misura (con range), Testo, Foto (non Firma).

### P6.1 — Checklist tipizzate + blocco chiusura

**Fatto**: `WorkOrderChecklist`/`MaintenanceChecklistStep` guadagnano `step_type` (Sì/No/Misura/Testo/Foto), `is_mandatory`, `unit`/`range_min`/`range_max` (solo Misura), `value_numeric`/`value_text`, `is_skipped`/`skip_reason` (+ chi/quando). `is_complete` è una property per-tipo (non un secondo booleano da tenere in sync); `blocks_closure` = obbligatorio AND non completo AND non saltato. Le foto si appoggiano al modello `WorkOrderAttachment` esistente (nuovo FK opzionale `checklist_item`), non un modello nuovo. `workorder_close` verifica `blocks_closure` su tutti gli step e rifiuta la chiusura elencando quelli mancanti.

**File**: `assets/models.py`, `assets/maintenance.py` (`copy_template_checklist_to_workorder`), `assets/views.py` (nuove azioni `workorder_checklist_set_value`/`_photo`/`_skip`), `assets/forms.py`/`assets/admin.py` (autoring template: `MaintenanceChecklistStepForm`, `MaintenanceChecklistStepInline`), `assets/templates/assets/components/workorder_checklist.html`, `assets/templates/assets/pages/maintenance_template_form.html`, `assets/templates/assets/pages/workorder_close.html` (banner "checklist incompleta" prima del submit).

**Stato**: ✅ Completato — 2026-09-02, 11 test nuovi, 422/424 `assets` verdi (i 2 falliti sono i 2 preesistenti noti, non collegati).

### P6.2 — Causa guasto codificata

**Fatto**: `WorkOrder.failure_cause` (scelta singola, opzionale) nel form di chiusura. La "soluzione codificata" del report resta fuori scope: `resolution` rimane testo libero — codificarla richiede un catalogo che l'utente non ha ancora deciso.

**File**: `assets/models.py`, `assets/forms.py`, `assets/views.py` (`workorder_close`), `assets/templates/assets/pages/workorder_close.html`.

### P6.3 — Autosalvataggio bozza

**Fatto**: JS puro in `workorder_close.html`, `localStorage` per-viewer chiavato per OdL, nessun draft server-side. Salva su `input`/`change` (debounce 500ms), ripristina al caricamento (con avviso visibile "Bozza precedente ripristinata"), cancellato al submit (anche in caso di redisplay per errori di validazione, perché la cancellazione avviene nell'handler `submit` prima dell'invio).

## Note operative

- Tutti i management command devono supportare `--settings=config.settings.dev` e `--dry-run`
- Ogni fase deve aggiornare `CHANGELOG.md` (obbligatorio per policy di progetto)
- Aggiornare `README.md` se cambiano URL, dipendenze o funzionalità visibili
- Le migrazioni SQL Server devono essere testate su SQLite in dev e su MSSQL in staging
- Nessuna logica business nei template: usare sempre il service layer o la view
- Per le email usare il sistema SMTP già configurato in `SiteConfig` / `settings`
- **⚠️ `config.settings.dev` su questa macchina NON è SQLite**: il `django_app/.env` del checkout condiviso ha `DB_ENGINE=sqlserver` verso `localhost\SQLEXPRESS` (DB `PORTALE NOVICROM`) — un'istanza locale reale, non un DB usa-e-getta. Copiare quel `.env` in un worktree e lanciare `manage.py migrate --settings=config.settings.dev` **scrive sullo stesso DB locale condiviso da tutte le sessioni/worktree**, non su un DB isolato. Vedi memoria `db_locale_dev_e_sqlserver_non_sqlite` per l'incidente (due migration `0095` di branch diversi applicate allo stesso DB) e la procedura corretta prima di un prossimo controllo visivo.
