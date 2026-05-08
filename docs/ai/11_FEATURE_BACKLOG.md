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

## Note di utilizzo

- Questo file è la fonte di verità per il backlog funzionale; aggiungi righe liberamente.
- Prima di implementare un item, aprire il doc AI del modulo coinvolto (vedi `docs/ai/00_INDEX.md`).
- Al completamento: aggiornare lo stato a `[x]`, aggiornare `CHANGELOG.md` e verificare se serve aggiornare `README.md`.
- Items con `[~]` richiedono prima una verifica dello stato attuale nel codice.
