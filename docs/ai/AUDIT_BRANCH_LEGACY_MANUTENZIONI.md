# Audit branch legacy manutenzioni

Data audit: 2026-09-04

Target: `feature/assets-manutenzione-refactor` (`97d712b3`)

Metodo: confronto Git locale, sola lettura; nessun merge, rebase o cherry-pick.

## Esito

Tutti i cinque branch richiesti sono antenati del target. Non contengono commit esclusivi da recuperare: il lato branch legacy è sempre `0` nel confronto `target...legacy`.

| Branch | Tip | Target avanti | Legacy avanti | Antenato del target | Azione |
|---|---|---:|---:|---|---|
| `feature/assets-manutentore-fase5` | `b90dc36d` | 67 | 0 | Sì | Non recuperare |
| `feature/assets-manutentore-fase6` | `96c4bb26` | 67 | 0 | Sì | Non recuperare |
| `feature/assets-manutentore-cockpit-p1` | `28aa1c31` | 67 | 0 | Sì | Non recuperare |
| `feature/assets-manutenzione-ux` | `c7cbf782` | 14 | 0 | Sì | Non recuperare |
| `feat/manutenzione-quickwin` | `2558a98b` | 459 | 0 | Sì | Non recuperare |

Interpretazione dei conteggi: per esempio `67 / 0` significa che il target contiene 67 commit successivi al tip legacy e che il legacy non contiene alcun commit assente dal target.

## Verifica funzionale per branch

### `feature/assets-manutentore-fase5`

Tip: `b90dc36d feat(assets): priorità, scadenza, stato operativo e home "Il mio turno"`.

| Capacità | Stato nel target | Evidenza/nota | Azione |
|---|---|---|---|
| Priorità OdL | Presente | Campo/modulo e form/lista OdL esistenti; copertura nei test legacy. | Nessuna |
| Data prevista/due | Presente | `WorkOrder.due_at` e filtri/ordinamenti del cockpit. | Nessuna |
| Stato operativo (iniziato/in attesa) | Presente | `started_at`, `is_waiting`, `wait_note` e azioni dettaglio. | Nessuna |
| “Il mio turno” | Presente | Route `assets/urls.py:108`, vista e sidebar già integrate. | Nessuna |

Non esistono patch residue da cherry-pickare. Le capacità sono però ancora basate sul modello OdL legacy e devono essere riesaminate quando l'OdL è massivo.

### `feature/assets-manutentore-fase6`

Tip: `96c4bb26 feat(assets): checklist tipizzate, blocco chiusura, causa guasto, autosave`.

| Capacità | Stato nel target | Evidenza/nota | Azione |
|---|---|---|---|
| Checklist tipizzate | Presente | `MaintenanceChecklistStep`/`WorkOrderChecklistItem`, endpoint set value/photo/skip. | Nessuna |
| Blocco chiusura | Presente | `blocks_closure` e validazioni di chiusura con test. | Nessuna |
| Causa guasto | Presente | Campo/form e rendering dettaglio/chiusura. | Nessuna |
| Autosave checklist | Presente | Endpoint granulari nel dettaglio OdL. | Nessuna |

La nuova occurrence replica checklist/evidenze per asset, ma gli endpoint storici sul WorkOrder restano globali: non recuperare codice del branch; pianificare solo test di equivalenza massiva.

### `feature/assets-manutentore-cockpit-p1`

Tip: `28aa1c31 fix(assets): "Non risolto" non avanza più la scadenza + quick win manutentore`.

| Capacità | Stato nel target | Evidenza/nota | Azione |
|---|---|---|---|
| “Non risolto” non avanza scadenza | Presente nel flow legacy | La guardia nella chiusura OdL è nel target. Il nuovo flow occurrence separa esecuzione e follow-up: non è una patch da trasporre alla cieca. | Validare semantica, non cherry-pick |
| Filtro `?asset=` | Presente | Le viste legacy conservano il filtro asset. | Nessuna |
| Apertura OdL da QR | Presente | Landing QR e azioni OdL sono nel target. | Nessuna |
| Ruolo dinamico manutentore | Presente | Logica role/capability già confluita. | Nessuna |
| Prefill esecutore | Presente | Form/vista del cockpit già confluiti. | Nessuna |

Nota di dominio: “manutenzione eseguita” e “problema risolto” nel refactor occurrence sono concetti distinti; il follow-up non deve impedire automaticamente la successiva scadenza. Serve una decisione funzionale, non il riuso del vecchio fix.

### `feature/assets-manutenzione-ux`

Tip: `c7cbf782 fix(assets): rimossa la subnav di sezione dal dettaglio OdL`.

| Capacità | Stato nel target | Evidenza/nota | Azione |
|---|---|---|---|
| Dettaglio OdL senza subnav assets | Presente | Il contesto dettaglio imposta `assets_section_nav` a `None` (`views.py:15830-15834`). | Nessuna |
| Ritocchi UX collegati | Presenti | Il target deriva interamente dal branch e aggiunge la nuova UI manutenzioni. | Nessuna |

### `feat/manutenzione-quickwin`

Tip: `2558a98b fix(assets): chiuso il terzo caso di "origin come proxy" - il dedup del generatore`.

| Capacità | Stato nel target | Evidenza/nota | Azione |
|---|---|---|---|
| Dedup generatore legacy indipendente da `origin` | Presente | `generate_scheduled_workorders.py:96-104` raccoglie gli OdL OPEN per coppia asset/regola senza usare origin come discriminante. | Nessuna |
| Report diagnostico origin-proxy | Presente | `report_origin_proxy_damage.py` è disponibile in sola lettura. | Conservare come diagnostica |
| Compatibilità con nuovo dedup occurrence | Separata | Il nuovo motore usa il vincolo `(plan, asset, due_date)` e gli stati occurrence. | Non unificare con cherry-pick |

## Cosa non va confuso con “funzione mancante”

Il fatto che tutti i commit siano già nel target non garantisce che la funzione sia corretta nel nuovo dominio:

- priorità, waiting, checklist e allegati storici sono proprietà dell'OdL; in un massivo possono richiedere uno stato per occurrence;
- filtri, QR, dashboard e report che partono da `WorkOrder.asset` vedono il primary asset, non necessariamente tutti gli asset dell'OdL;
- il dedup legacy per `(asset, MaintenanceRule)` e quello nuovo per `(plan, asset, due_date)` hanno scopi differenti;
- la regola “non risolto” del vecchio close non equivale al nuovo binomio “occurrence eseguita + follow-up correttivo”.

Questi sono gap di integrazione del target, non commit dispersi nei branch legacy.

## Decisione finale

- **Branch da recuperare:** nessuno.
- **Commit da cherry-pickare:** nessuno.
- **Branch da mergiare:** nessuno.
- **Codice da conservare come riferimento:** test e report diagnostico già presenti nel target.
- **Lavoro successivo:** remediation nel branch del refactor, guidata dall'audit legacy/ACL/`WorkOrder.asset`, con commit nuovi e mirati.
