# Audit legacy manutenzioni — Codex

Data audit: 2026-09-04

Branch verificato: `feature/assets-manutenzione-refactor` (`97d712b3`)

Branch di lavoro: `codex/audit-manutenzioni`

Perimetro: sola analisi statica e test separati; nessuna modifica al dominio o alla UI.

## Esito esecutivo

Il refactor non è ancora pronto per essere considerato l'unica fonte di verità in produzione.

Il blocco principale è **CRITICO**: `django_app/automazioni/schedules.py:403` continua a schedulare `assets.tasks.run_generate_scheduled_workorders`, che a sua volta esegue il comando legacy `generate_scheduled_workorders` (`django_app/assets/tasks.py:13-24`). Quel comando legge `MaintenanceRule`, override, stato e contatori legacy e crea direttamente `WorkOrder`. Il nuovo comando `generate_maintenance_occurrences` esiste, ma non risulta collegato a uno scheduler applicativo. Se si attivano i nuovi flussi senza dismettere o riconciliare quello vecchio, rimangono due motori con semantiche e dedup differenti.

Altri due blocchi ad alta priorità:

- gli OdL massivi sono modellati correttamente tramite `MaintenanceOccurrence`, ma molte viste e integrazioni storiche continuano a trattare `WorkOrder.asset` come l'intero perimetro dell'OdL;
- i gate ACL verificano la capacità globale (`admin_assets`, `maintenance_planning`, `maintenance_execute`) ma non applicano uno scope per reparto/asset. Un planner autorizzato può selezionare per ID un'occurrence esterna al proprio reparto; il test audit riproduce la scrittura.

## Metodo e conteggi

La scansione è stata effettuata sul contenuto di `django_app/`, includendo Python, template, migrazioni e test. I conteggi seguenti sono occorrenze testuali grezze: servono a misurare la superficie, non equivalgono a query runtime uniche.

| Simbolo/campo | Occorrenze | File |
|---|---:|---:|
| `MaintenanceRule` | 352 | 25 |
| `MaintenanceRuleAssetOverride` | 42 | 10 |
| `AssetMaintenanceRuleState` | 50 | 12 |
| `AssetMeter` | 80 | 12 |
| `WorkMachine.next_maintenance_date` / `next_maintenance_date` | 52 | 12 |
| `AssetAdministrativeDeadline` | 139 | 21 |
| `PeriodicVerification` | 111 | 19 |
| **Totale grezzo** | **826** | — |

La tabella operativa raggruppa riferimenti contigui alla stessa operazione. Una riga può avere più classificazioni. `LEGACY DEAD` significa storico/migrazione one-shot, non necessariamente codice eliminabile senza una decisione di conservazione.

## Inventario classificato dei riferimenti legacy

| # | Riferimento | File/righe principali | Classificazione | Stato e impatto |
|---:|---|---|---|---|
| 1 | Definizioni `MaintenanceRule`, override, state, meter | `assets/models.py:1118-1320`, `2910-3050` | MODEL | Modelli legacy ancora presenti e referenziati a runtime. |
| 2 | Deadline amministrative e relative evidenze | `assets/models.py:778-910` | MODEL | Sottodominio autonomo ancora vivo; non sostituito in modo trasparente dalle occurrence. |
| 3 | `PeriodicVerification` e legame con OdL | `assets/models.py` (modello), `assets/models.py:1206`, `3066-3080` | MODEL | La verifica periodica resta una fonte separata e può generare OdL. |
| 4 | `WorkMachine.next_maintenance_date` | `assets/models.py:1574` | MODEL | Seconda data di scadenza derivata, ancora esposta in più viste/export. |
| 5 | FK legacy su `WorkOrder` e traccia su assignment nuovo | `assets/models.py:2266`, `3491` | MODEL, READ | `WorkOrder.maintenance_rule` resta operativo; `MaintenancePlanAssignment.legacy_rule` è tracciabilità di migrazione. |
| 6 | Migrazioni storiche `0033`-`0089` | `assets/migrations/` | MODEL, LEGACY DEAD | Necessarie alla storia schema; non sono runtime applicativo. Non eliminare. |
| 7 | Risoluzione regole/override per asset | `assets/maintenance.py:92-242`, `438-475` | READ, SERVICE | Motore legacy completo ancora usato da viste e generatore. |
| 8 | Calcolo soglie a contatore | `assets/maintenance.py:267-275`, `339-475`, `639-745` | READ, SERVICE | `AssetMeter` e state legacy determinano scadenze e anteprime. |
| 9 | Aggiornamento stato regola dopo chiusura | `assets/maintenance.py:287-303` | WRITE, SERVICE | Scrive `AssetMaintenanceRuleState`; fonte di verità concorrente alle occurrence. |
| 10 | Snapshot contatore alla chiusura OdL | `assets/models.py:2484-2545` | READ, WRITE, SERVICE | La chiusura dell'OdL legacy legge il meter e salva `meter_value_at_close`. |
| 11 | Avanzamento `next_maintenance_date` | `assets/models.py:2566-2580` | WRITE, SERVICE | Un OdL periodico chiuso aggiorna la data macchina indipendentemente dal nuovo calendario. |
| 12 | Generatore OdL legacy | `assets/management/commands/generate_scheduled_workorders.py:74-280` | READ, WRITE, TASK | Legge rule/override/state/meter e crea OdL. **Runtime attivo**. |
| 13 | Wrapper del generatore legacy | `assets/tasks.py:13-27` | TASK | Chiama il comando legacy e intercetta errori. |
| 14 | Registrazione scheduler | `automazioni/schedules.py:403` | TASK | Punta esclusivamente a `run_generate_scheduled_workorders`. **Blocco critico**. |
| 15 | Generatore occurrence nuovo | `assets/management/commands/generate_maintenance_occurrences.py` | TASK | Disponibile solo come management command; nessun aggancio scheduler trovato. |
| 16 | CRUD regole legacy | `assets/views.py:11229-11620`, `forms.py:1110-1255` | READ, WRITE, UI, FORM | UI ancora raggiungibile: crea/modifica regole che il task schedulato consuma. |
| 17 | CRUD override legacy | `assets/views.py:11681-11835`, `forms.py:1259-1375` | READ, WRITE, DELETE, UI, FORM | Override per asset ancora attivi; il reset elimina anche lo state a `views.py:11592`. |
| 18 | Anteprima/copertura/scadenzario legacy | `assets/views.py:8953`, `12065-12340`, `16662-17390` | READ, UI | Continua a presentare calcoli legacy accanto alle nuove pagine. |
| 19 | Contatori: pagina e aggiornamento | `assets/views.py:13752-13760`, `16256-16320` | READ, WRITE, UI | Flusso meter live; scrive `AssetMeter` e storico. Non è dead code. |
| 20 | Campo prossima manutenzione nei form macchina | `assets/forms.py:1540`, `1625` | WRITE, FORM | L'utente può mantenere manualmente una seconda scadenza. |
| 21 | Prossima manutenzione in liste, dettaglio, export | `assets/views.py:594`, `814`, `1568-1572`, `1799`, `2032`, `4321`, `4532`, `4652`, `6488`, `9271`, `13635`, `16739-16747` | READ, UI | Campo ancora visibile e usato per filtri/alert. |
| 22 | CRUD deadline amministrative | `assets/views.py:10706-11210`, `forms.py:831-880` | READ, WRITE, UI, FORM | Fonte separata ancora completamente operativa. |
| 23 | Chiusura deadline e allegato | `assets/views.py:10829-10839` | WRITE, UI | Crea completion e allegato; non completa un'occurrence nuova. |
| 24 | Deadline in dashboard/calendario/export | `assets/views.py:2942-2983`, `9488`, `10196`, `12382`, `16648-16890`, `18388-18440` | READ, UI | Mantiene conteggi, alert e calendario legacy. |
| 25 | KPI deadline | `assets/services/dashboard_kpi.py:264-315`, `360-619`, `745` | READ, SERVICE | Dashboard continua a interrogare deadline/completion. |
| 26 | CRUD verifiche periodiche | `assets/views.py:13815+` e route `assets/urls.py:124-129` | READ, WRITE, UI, FORM | Funzione ancora esposta e modificabile. |
| 27 | Esecuzione verifica e creazione OdL | `assets/views.py` (flow periodic verification) | WRITE, UI | Può produrre WorkOrder fuori dal nuovo motore occurrence. |
| 28 | Reminder manutenzione legacy | `assets/management/commands/send_maintenance_reminders.py` | READ, TASK | Legge deadline, verifiche periodiche e OdL; non usa `MaintenanceOccurrence` come unica sorgente. |
| 29 | Import/migrazione periodica storica | `assets/services/periodic_migration.py:128-181` | READ, WRITE, SERVICE | Crea `MaintenanceRule` e `AssetMaintenanceRuleState`. Da confinare a migrazione controllata. |
| 30 | Derivazione/classificazione/seed regole | `derive_collaudo_rules.py:184+`, `classify_maintenance_external.py:88-117`, `seed_assets_antincendio.py:224+`, `migrate_periodic_to_rules.py:190+` | READ, WRITE, TASK | Comandi amministrativi legacy ancora capaci di alimentare la vecchia fonte. |
| 31 | Migrazione verso i nuovi piani | `migrate_maintenance_to_plans.py:108-310` | READ, WRITE, LEGACY DEAD | Ponte one-shot: legge rule/override/state/deadline e crea dati nuovi. Deve essere idempotente e poi congelato. |
| 32 | Report diagnostico origin proxy | `report_origin_proxy_damage.py:33-274` | READ, LEGACY DEAD | Strumento di diagnosi; non autore di stato di dominio. |
| 33 | Test legacy regole/scheduler/contatori | `assets/tests.py:~8500-9800`, `test_scadenze_schedules.py` | TEST | Confermano che il vecchio flusso è ancora intenzionalmente coperto. |
| 34 | Test dominio/nuova UI | `tests_maintenance_domain.py`, `tests_maintenance_ui.py` | TEST | Coprono il nuovo motore ma non la coesistenza con il task legacy. |
| 35 | Test audit edge-case | `assets/tests_maintenance_audit_edges.py` | TEST | 23 casi separati; una failure ACL riproducibile, nessuna modifica al dominio. |

### Autori di stato ancora attivi

| Stato | Autori individuati | Rischio |
|---|---|---|
| OdL periodico | generatore legacy; esecuzione `PeriodicVerification`; nuovo `create_workorder_from_occurrences`; creazione manuale/campagna | Duplicati o tracciabilità disomogenea. |
| Prossima scadenza | `MaintenanceOccurrence`; `AssetMaintenanceRuleState`; `WorkMachine.next_maintenance_date`; `AssetAdministrativeDeadline`; `PeriodicVerification.next_due_date` | Più date discordanti per lo stesso concetto operativo. |
| Avanzamento dopo esecuzione | `complete_occurrence`; `WorkOrder.close`; `sync_workorder_maintenance_state`; flow verifiche/deadline | Ordine delle operazioni e risultato dipendono dal percorso UI. |
| Evidenze | attachment occurrence; attachment WorkOrder/execution day; completion deadline | Report e allegati non sono interrogati da un unico registro. |

## Audit completo di `WorkOrder.asset`

### Conclusione

Nel nuovo modello massivo, `WorkOrder.asset` è il **primary asset tecnico** scelto alla creazione (`maintenance_domain.py:636+`), mentre il vero insieme di asset è `work_order.occurrences -> occurrence.asset`. Questa convenzione è valida solo dove dichiarata esplicitamente. Nel codice legacy, invece, `WorkOrder.asset` viene quasi sempre interpretato come unico asset dell'intervento.

### Superfici verificate

| Superficie | Evidenza | Esito per OdL massivo | Priorità |
|---|---|---|---|
| Dettaglio OdL | `views.py:15799-15814`, template `workorder_detail.html:48,78,204` | Header, link asset e contratti descrivono solo il primary asset; il pannello occurrence mostra il set completo ma non corregge gli altri riferimenti. | Alta |
| Chiusura OdL | `views.py:16047-16052`; `models.py:2484-2580`; `maintenance.py:263-294` | Form, meter snapshot, state legacy e `next_maintenance_date` operano sul primary asset. La chiusura occurrence singola è corretta, quella OdL legacy no. | Critica |
| Lista e filtri OdL | `views.py:14889-14955` | Filtri asset/reparto/categoria/testo attraversano `WorkOrder.asset`; un massivo non compare cercando un asset secondario. | Alta |
| Export OdL | `views.py:15115+` e helper riga export | Riusa il queryset/lista primary-only e produce una sola colonna asset. | Alta |
| Scheda e storico asset | `views.py:10181-10188`; `services/__init__.py:112`; `maintenance_register.py:111` | Un massivo non appare sul registro/storico degli asset secondari. | Critica |
| Dashboard/alert | `views.py:8537-8590`, `13683+`, `16611+`; `dashboard_kpi.py:124-745` | Conteggi, alert, reparto/categoria e aging sono attribuiti al primary asset. | Alta |
| KPI/costi | `maintenance_kpi.py:88-101`; `dashboard_kpi.py:407-472` | Costo e volumi dell'OdL massivo vengono imputati alla categoria/reparto del primary asset; manca una regola di allocazione. | Alta |
| Report dashboard | `views.py:17441-17535`; `reports_dashboard.html:344` | Raggruppamento e label usano esclusivamente `workorder.asset`. | Alta |
| AI/tooling | query `WorkOrder.objects.filter(asset_id__in=asset_ids_qs)` nell'AI assets | Domande su asset secondari omettono l'OdL massivo. | Alta |
| Ticket | `tickets/views.py:2830+` | Ticket->OdL è naturalmente single-asset; corretto finché non viene riusato per un massivo. | Bassa |
| Task/reminder legacy | `generate_scheduled_workorders.py`; `send_maintenance_reminders.py:174+` | Sono single-asset per costruzione; restano un canale parallelo. | Alta per coesistenza |
| Notifiche | messaggi/alert costruiti da `workorder.asset` (`views.py:8589-8590`) | Destinatario/testo possono rappresentare solo il primary asset. | Media |
| Allegati | upload path execution day `models.py:2715-2716`; allegati OdL | Percorso storage deriva dal primary asset anche per evidenze di più occurrence. Gli attachment occurrence sono invece asset-specifici. | Media |
| Follow-up | nuovo flow `views_maintenance.py:1029-1065`; legacy close `views.py:16138-16139` | Nuovo follow-up usa `occurrence.asset` ed è corretto; il follow-up legacy usa il primary asset. | Alta |
| Calendario/scadenzario nuovo | query su `MaintenanceOccurrence.asset` | Corretto: l'unità è l'occurrence. | OK |
| Permessi | gate globali, nessun filtro su occurrence/asset | L'ID del primary non limita né protegge gli asset secondari. | Critica |

### Regola consigliata per la successiva remediation

Non sostituire meccanicamente ogni `workorder.asset`. Prima classificare il consumer:

- **identità tecnica/storage legacy**: il primary asset può restare, ma deve essere etichettato come tale;
- **visibilità, filtri, storico, AI, alert, report**: interrogare l'insieme delle occurrence, con fallback a `WorkOrder.asset` solo per OdL non occurrence;
- **costi/KPI**: decidere esplicitamente se duplicare, ripartire o attribuire il costo una volta sola;
- **chiusura/meter/scadenza**: operare per occurrence/asset, mai implicitamente sul primary.

## Audit performance delle nuove viste

Nessuna misura è stata eseguita su dati produzione. Le priorità derivano da query shape e complessità algoritmica.

| Priorità | Punto | Evidenza | Rischio | Miglioria proposta |
|---|---|---|---|---|
| Alta | N+1 nella lista piani | `views_maintenance.py:484` chiama `plan.assignments.all()` per ogni piano senza prefetch | 1 query per piano | `Prefetch` delle assignment attive o annotazione/precalcolo in una query. |
| Alta | Matrice risoluzioni completa | `maintenance_domain.py:142+`; usata a `views_maintenance.py:451,513,681,1122` | Carica asset, piani, assignment e membership e costruisce la matrice in Python; costo circa asset × piani/assignment | Limitare sempre plan/asset, precomputare membership, valutare servizio paginato/cache versionata. |
| Alta | Coverage | `views_maintenance.py:1119-1160` | Fino a 400 asset × tutti i piani, tutte le celle in memoria e HTML | Paginare asset/piani, generare solo viewport, soglia esplicita e metriche query/time. |
| Alta | Scheduler occurrence | `maintenance_domain.py:284-390`, `objects.create` a `376` | Insert singolo per risoluzione; finestra grande produce molte round-trip | Preparazione batch e `bulk_create(ignore_conflicts=...)` dopo aver preservato dedup e audit. |
| Media | Quadro responsabile | limiti `3000` open + `1000` done a `366+` | Aggregazioni Python e troncamento silenzioso alterano KPI oltre soglia | `Count/Min` filtrati SQL; paginazione liste; indicatore “risultati limitati”. |
| Media | Conteggi queryset ripetuti | `open_workorders.count()` a `411` poi iterazione; `follow_ups.count()` a `415` poi `list()` | Query duplicate | Materializzare una volta entro il limite oppure annotare/count separato intenzionale. |
| Media | Lista piani: statistiche | `views_maintenance.py:464-477` | Itera tutte le occurrence open per ricavare minima data e overdue | `values(plan_id).annotate(Min, Count(filter=...))`. |
| Media | Da fare | `views_maintenance.py:228` limita a 1000, poi ripartisce più volte in Python | Troncamento e più passate; le esterne possono comparire anche in un altro blocco | Paginazione e stati/contatori SQL; definire se i blocchi sono esclusivi. |
| Media | Scadenze/report mancanti | `views_maintenance.py:333-335` | Carica 2000 righe e filtra i report mancanti in Python | Tradurre la condizione in `Q()`/annotazione `Exists`. |
| Media | Indici compositi | query frequenti per `(status, due_date, asset/plan)` | Gli indici esistenti coprono solo coppie parziali; i FK hanno indice singolo | Verificare con execution plan e valutare `(status,due_date)`, `(asset,status,due_date)`, `(plan,status,due_date)`. |
| Bassa | Preview assignment | `views_maintenance.py:679-687` | Prima legge gli ID, poi il resolver ricarica gli Asset | Passare/riusare queryset valutato o lista asset senza seconda lettura. |
| Bassa | Progress OdL | contesto occurrence già precaricato, poi `domain.workorder_progress` rilegge relazione | Query ridondante per pagina dettaglio | Calcolare progress dalla collection prefetchata o permettere payload opzionale. |
| OK | Query base occurrence | `views_maintenance.py:104-109` | `select_related` completo + prefetch attachment elimina il principale N+1 delle liste | Mantenere e testare con query-count. |
| OK | Vincolo dedup | unique `(plan, asset, due_date)` in `MaintenanceOccurrence` | Protezione DB corretta contro doppia occurrence stessa data | Conservare anche in un eventuale batch. |

## Audit ACL e accesso diretto

### Matrice attuale

| Ruolo/capacità | Lettura liste | Configura piani/gruppi | Pianifica OdL | Completa/follow-up | Scope reparto |
|---|---|---|---|---|---|
| Superuser / `_is_assets_admin` | Sì | Sì | Sì | Sì | Nessuno |
| `assets/admin_assets` | Sì | Sì | Sì | Sì | Nessuno |
| `assets/maintenance_planning` | Sì | No | Sì | Sì, per ereditarietà del helper | Nessuno |
| `assets/maintenance_execute` | Sì | No | No | Sì | Nessuno |
| Autenticato senza capacità | Sì a livello view, salvo middleware | No (redirect) | No (redirect) | No (redirect) | Nessuno |

`can_execute_maintenance()` restituisce vero anche per chi può pianificare. Questa gerarchia può essere voluta, ma va validata con la matrice ruoli richiesta (manutentore interno/esterno, caporeparto, responsabile manutenzione, admin).

### Endpoint sensibili e direct URL

| Endpoint/famiglia | Gate in view | Esito audit |
|---|---|---|
| `/da-fare`, `/scadenze`, `/quadro`, lista/dettaglio piani, gruppi, piani asset | solo `login_required` | I dati sono globali. La sicurezza dipende dal middleware/route binding. |
| Crea/modifica piani, assignment, gruppi, personalizzazione asset, coverage | `can_manage_maintenance_plans` | Gate azione presente; manca scope oggetto/reparto. |
| Crea OdL, aggiungi/rimuovi occurrence, distribuisci giornata | `can_plan_maintenance` | Gate azione presente; `_selected_occurrences` filtra solo PK e status (`views_maintenance.py:856-864`). IDOR per reparto confermata dal test. |
| Completa occurrence, crea follow-up | `can_execute_maintenance` | Gate azione presente; occurrence globale per PK, nessun vincolo su assegnatario/reparto/fornitore. |
| Download allegato occurrence | solo `login_required` (`views_maintenance.py:1085-1103`) | Ogni utente autenticato che conosce l'ID può scaricare il file. **Alta**. |
| Mutazioni OdL legacy (claim/state/checklist/close) | route legacy + middleware, controlli locali eterogenei | Un OdL massivo eredita endpoint non progettati per scope per-occurrence. Verifica prod obbligatoria. |

### Strict ACL produzione

`assets/acl_bootstrap.py:62-75` crea pulsanti/permessi legacy per le nuove pagine e azioni, ma nella storia migrazioni esaminata non risultano `RoutePermissionBinding` canonici specifici per le nuove route. In `ACL_STRICT_CANONICAL`, il middleware dichiara che una route senza binding canonico deve essere trattata esplicitamente (`core/middleware.py:161-180`, `373`). Prima dell'attivazione strict occorre quindi:

1. inventariare ogni route `assets/urls.py:153-227` nel report di coverage ACL reale;
2. creare binding canonici e grant ruolo per letture e mutazioni;
3. definire una funzione unica di scope asset/reparto/fornitore;
4. testare direct URL con strict attivo, non solo con `LEGACY_AUTH_ENABLED=False`;
5. decidere se i dinieghi HTML devono essere `403` anziché redirect `302` per rendere auditabili i tentativi.

### Failure riprodotta

Test: `MaintenanceACLEdgeAuditTests.test_department_manager_cannot_plan_asset_outside_department`.

- capability `can_plan_maintenance` concessa;
- occurrence selezionata appartenente a `FRESE`, fuori dallo scope simulato `TORNI`;
- atteso: `403` e nessun OdL;
- ottenuto: `302` verso il dettaglio dell'OdL, quindi scrittura avvenuta;
- causa: nessuna verifica di ownership/scoping in `_selected_occurrences` o nel servizio.

Il test è lasciato fallente per rendere il gap visibile; non è stata applicata alcuna correzione.

## Test edge-case aggiunti

File separato: `django_app/assets/tests_maintenance_audit_edges.py`.

Copertura:

- calendario: 31 gennaio, bisestile, febbraio-marzo, trimestrale oltre dicembre, primo lunedì, quinta occorrenza non valida, recupero 29 febbraio, cambio anno;
- occurrence: idempotenza scheduler, assignment disabilitato, precedenza asset>gruppo, conflitto gruppi, preservazione DONE e generazione successiva, occurrence già pianificata;
- OdL massivi: completamento parziale, rimozione, redistribuzione isolata, follow-up mono-asset, singolo asset, molti asset;
- ACL: manutentore senza permessi, POST diretto non autorizzato, planner fuori reparto.

Esito esecuzione mirata: **23 test, 22 passati, 1 fallito intenzionalmente per difetto ACL confermato**. Il system check Django non ha segnalato problemi.

Regressioni preesistenti eseguite separatamente: `assets.tests_maintenance_domain` **35/35 OK** e `assets.tests_maintenance_ui` **24/24 OK**.

## Priorità di intervento raccomandate

1. **P0 — sorgente unica:** sospendere/riconciliare il task legacy e schedulare esplicitamente il nuovo generatore solo dopo prova dry-run e confronto dati.
2. **P0 — ACL oggetto:** introdurre scope centralizzato per asset/reparto e applicarlo a query di lettura, selezione occurrence, OdL e download.
3. **P0 — semantica OdL massivo:** definire contratto formale di `WorkOrder.asset` come primary tecnico e migrare i consumer visibilità/storico/AI/report verso le occurrence.
4. **P1 — chiusura e scadenze:** impedire che `WorkOrder.close` aggiorni solo meter/state/date del primary nei massivi; allineare evidenze per occurrence.
5. **P1 — canonical ACL:** creare route binding/grant e una suite strict-prod per tutti gli endpoint nuovi.
6. **P1 — performance:** rimuovere N+1 lista piani, aggregazioni Python non paginated e matrice completa non limitata.
7. **P2 — decommission legacy:** dopo cutover verificato, rendere read-only o rimuovere dai menu i CRUD di rule/override/deadline/verifiche secondo una decisione di dominio; conservare migrazioni e tracciabilità.

## Cose non modificate

- modelli e migrazioni;
- `recurrence.py` e `maintenance_domain.py`;
- `views_maintenance.py` e `forms_maintenance.py`;
- scheduler occurrence e logica OdL massivi;
- template UI nuovi;
- dati, database, configurazione ACL e dipendenze.
