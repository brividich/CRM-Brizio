# Piano integrazione Asset & Manutenzioni — NOVICROM HUB

> Stato: in corso (2026-06-14). Diagnosi + roadmap a fasi per dare un "filo conduttore" coerente al dominio Asset/Manutenzioni: dashboard → creazione template → creazione regole → gestione/viste → report.

## 1. Diagnosi: dove si spezza la catena

Il dominio è ricco a livello dati (30+ modelli, motore regole/override/stato, contatori, contratti, calendario Outlook, budget). Il problema non è *cosa manca nei dati*, ma che i pezzi non si parlano come **un unico ciclo di vita**. Anelli rotti rilevati nel codice:

| # | Anello rotto | Evidenza |
|---|---|---|
| A | Doppia UI Template/Regole: la tab in `maintenance_impostazioni` convive con le pagine standalone `maintenance_template_list` / `maintenance_rule_list` | `views.py` maintenance_impostazioni vs maintenance_template_list |
| B | Template senza checklist dal portale; gli step (`MaintenanceChecklistStep`) si creano solo da Django admin. E `_prepopulate_workorder_checklist_from_template` NON è chiamato dal generatore → gli OdL periodici automatici nascono senza checklist | `maintenance_template_form.html`, `admin.py`, `generate_scheduled_workorders.py` |
| C | Lo scadenzario regole vede solo i giorni: `build_day_based_maintenance_schedule_rows` salta ore/km/cicli, ma il generatore li gestisce → disallineamento tra ciò che si vede e ciò che si genera | `maintenance.py` |
| D | Regola nuova = tutto "da pianificare": la scadenza dipende da `AssetMaintenanceRuleState.last_execution_date`, popolato solo alla chiusura del primo OdL | `maintenance.py` |
| E | Due sistemi "periodici" paralleli: `PeriodicVerification` (legacy, fornitore, M2M) e `MaintenanceRule` (categoria) | `models.py`, flag `is_legacy` |
| F | Budget modellato ma non gestibile: `AssetMaintenanceBudget` letto ma senza CRUD né confronto budget↔consuntivo | `models.py`, `urls.py` |
| G | Report scollegati dal motore regole: niente PM-compliance né budget vs actual; scope per `asset_type` mentre le regole girano per `asset_category` | `views.py` reports_dashboard |
| H | Tre set di KPI non allineati: hub (conteggi inline), `asset_dashboard` (MTTR/downtime/costo), report (costo/durata). Nessuna fonte unica | `dashboard_kpi.py` |
| I | Il calendario non mostra le PM predette dalle regole | `views.py` _asset_calendar_events |
| J | Creazione non guidata: dopo "salva template" nessun CTA "crea regola"; dopo "salva regola" nessun "imposta stato / genera primo OdL" | `views.py` |

## 2. Il filo conduttore mancante

Il concetto assente come oggetto di prima classe è il **Piano di manutenzione** — la vista che chiude il loop CMMS:

```
TEMPLATE (cosa fare + checklist)
   └─ riusato da → REGOLA (categoria + trigger: giorni|ore|km|cicli + preavviso)
        └─ applicata (con override) a → PIANO ASSET (stato: ultima esecuzione, prossima scadenza)
             └─ genera → ORDINE DI LAVORO (checklist, costi, fermo, contratto, contatore)
                  └─ alla chiusura aggiorna lo stato e alimenta i REPORT (compliance, MTTR/MTBF, budget)
```

Tre tessuti connettivi da introdurre:
1. **Pagina "Piano di manutenzione"** (per categoria e per asset) che mostra regole effettive + stato + prossima scadenza + azione. I dati esistono già (`resolve_asset_maintenance_rules`, `build_day_based_maintenance_schedule_rows`), ma sono sparsi.
2. **Servizio KPI unico** (`maintenance_kpi`) consumato da hub, cruscotto e report.
3. **Navigazione guidata** template → regola → stato iniziale → OdL → report.

Contratto di ingresso OdL: un `WorkOrder` richiede sempre un asset. Ogni CTA globale `+ Nuovo intervento` deve quindi aprire `/assets/workorders/?create=1`, che mostra il selettore asset; solo dopo la scelta si entra in `/assets/workorders/new/<asset>/`. La route senza id resta un fallback compatibile e deve convergere sul selettore, mai sulla lista inerte.

## 3. Spunti da CMMS open-source / commerciali

- **Odoo Maintenance / Frappe-ERPNext**: il *Maintenance Plan* è un oggetto a sé con calendario; KPI MTBF/MTTR/availability in Kanban.
- **Snipe-IT**: lifecycle asset, custom field per categoria, QR check-in/out (già allineati).
- **Fiix / Limble / UpKeep**: **PM compliance %** come KPI principe; trigger a contatore; ricambi scalati sull'OdL; stati OdL più ricchi (Requested→In progress→On hold→Done→Verified).
- **openMAINT / GLPI**: criticità asset + gerarchia padre/figlio per prioritizzare.

Gap prioritari confermati: PM-compliance, trigger a contatore nello scadenzario, budget vs actual, stati OdL più ricchi.

## 4. Roadmap a fasi

### Fase 0 — Consolidamento e quick win (basso rischio) — ✅ FATTA
- [x] 0.1 Eliminare la doppia UI: `maintenance_impostazioni` come hub unico; standalone come gestione avanzata linkata; repoint dei punti d'ingresso.
- [x] 0.2 Fix checklist OdL periodici: chiamare la copia degli step nel `generate_scheduled_workorders` (helper condiviso `copy_template_checklist_to_workorder`).
- [x] 0.3 Editing checklist nel form template (formset `MaintenanceChecklistStep`).
- [x] 0.4 CTA di continuità template→regola→stato.

### Fase 1 — Il "Piano di manutenzione" come pagina — ✅ FATTA (1.1)
- [x] 1.1 Vista Piano per categoria (salute pianificazione aggregata, tab in Impostazioni) + per asset (`asset_maintenance_rule_list`).
- [x] 1.2 Onboarding stato regola ("registra ultima esecuzione") — già presente in `maintenance_schedule` e `asset_maintenance_rule_list`.

### Fase 2 — Completare il motore — ✅ FATTA
- [x] 2.1 Scadenzario a contatore (ore/km/cicli) allineato al generatore (helper `meter_schedule_payload`, `build_maintenance_schedule_rows`).
- [x] 2.2 Calendario con PM predette dalle regole (per-asset).
- [x] 2.3 Convergenza `PeriodicVerification(is_legacy)` → regole (servizio `periodic_migration` + azione UI "Converti in regola" + de-dup scadenzario).

### Fase 3 — Analytics che chiudono il loop
- 3.1 Servizio KPI unico `maintenance_kpi`.
- 3.2 PM-compliance % (eseguite in tempo / dovute).
- 3.3 Budget vs actual (CRUD `AssetMaintenanceBudget`).
- 3.4 Allineare lo scope report a categoria (DOPO il merge category/type in corso).

### Fase 4 — CMMS maturo
- Stati OdL più ricchi; criticità + gerarchia asset; anagrafica ricambi scalati sull'OdL; MTBF/availability.

## 5. Vincoli e dipendenze
- È in corso (altra sessione) il refactor di fusione `asset_category` + `asset_type`: NON modificare la classificazione asset finché non è chiuso. Il gap G (scope report per categoria) dipende da quel refactor.
- Mantenere i pattern SSR/HTMX esistenti; nessuna nuova dipendenza JS.
- ACL: le route admin manutenzione restano gated da `_is_assets_admin`.
