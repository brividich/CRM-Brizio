# `automazioni` — workflow engine visuale

Area **Automation** · URL `/automazioni/` · codice [`django_app/automazioni/`](../../django_app/automazioni/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Designer visuale, trigger SQL, queue processor, approvazioni email/Teams, import Power Automate, **regole KICK-OFF: «Minuta incontro» (AU52) e «Convocazione incontro» (AU53)** — invio email di verbale/ordine del giorno ai partecipanti (source `tasks_kickoff` + azioni custom `send_meeting_minute`/`send_meeting_invite`, CC + PDF + task dai next-step + `.ics`, anti-doppioni `cooldown_group`), **alert progetto KICK-OFF: «Impatto sicurezza» (AU54) e «VRF non caricato» (AU55)** (source `tasks_project` + azione `send_project_alert` a PM/capo commessa), **cambio mansione: email SDS da leggere (AU56)** (nuova source `anagrafica_dipendenti` con trigger su `mansione`, campi virtuali conteggio SDS/URL calcolati riusando `schede_sicurezza`, link "conferma tutte" verso `/schede-sicurezza/da-leggere/conferma-tutte/`)

## Dettaglio

Il modulo più complesso del portale: motore di automazione event-driven con designer visuale, approvazioni multi-canale e integrazione Power Automate.

- **10 modelli**: AutomationRule, AutomationCondition, AutomationAction, AutomationRunLog, AutomationActionLog, DashboardMetricValue, AutomationApproval, TeamsWebhookPreset, AutomationDeliveryEndpoint, AutomationCooldownGroup
- **Designer visuale** con builder classico + diagramma Power Automate-style
- **Trigger SQL Server** auto-generati (CREATE OR ALTER TRIGGER) con applicazione one-click dal portale
- **Queue** `automation_event_queue` persistente con processor command
- **Azioni disponibili**: `send_email`, `write_log`, `insert_record`, `update_record`, `update_trigger_record`, `split_assenza_giornaliera`, `send_approval`, `do_until`, `for_each`, `branch`, `count_branch`, `run_if`
- **Controllo flusso visuale**: pannelli guidati Se Vero/Se Falso, Corpo loop/Timeout, Azioni per ogni record
- **Routing per tipo con `branch` annidati**: una sola regola può instradare su rami diversi in base ai campi del record (es. package unico assenze: Ferie/Permesso/Flessibilità con sotto-ramo durata per le ferie lunghe). Una regola parte sempre e decide internamente — niente esclusione implicita fra regole. Nota: la condizione then/else del `branch` usa `condition_field/operator/value`, non `run_if` (che sull'azione branch è un gate di esecuzione)
- **Gruppi di esclusione con priorità e fallback (opt-in, non attivo di default)**: capacità del motore disponibile ma non usata dai pacchetti — regole con lo stesso `exclusion_group` che matchano lo stesso record si escludono a vicenda (parte solo la `priority` più alta; in errore si prova a cascata la successiva, le altre run-log `SKIPPED`). Con `exclusion_group` vuoto (default) il comportamento è quello storico. Configurabile da package JSON e admin
- **Approvazioni a catena**: `send_approval` annidabili nei rami approvato/rifiutato (doppia/tripla firma, max 3 livelli), validate ricorsivamente all'import
- **Operatori condizione temporali**: `days_from_now_lte/gte` (scadenze rispetto a oggi) e `days_span_gt/gte` (durata fra due campi data, es. "ferie > 10 giorni")
- **`count_branch`**: conta i record di una sorgente (filtro + finestra temporale) e dirama su soglia — esprime regole "N eventi in M giorni" (es. 3 ticket stesso asset in 90 giorni)
- **`cooldown_group` (debounce per gruppo)**: operatore condizione che evita notifiche multiple ravvicinate sulla stessa entità (es. 1 mail ogni 5 min per OP). Lettura pura (`namespace:minuti`, valore dal campo); il motore registra l'invio in `AutomationCooldownGroup` solo dopo l'esecuzione riuscita (no burn su fallimento). Namespace condivisibile fra regole (insert+update). Usato da AU51 (mail anomalie capocommessa)
- **Pacchetti regola pronti** (`automazioni/packages/*.automation_package.json`): 39 flussi importabili via designer (anomalie, approvazioni a catena, escalation, KPI, presidio scadenze, istruttoria incidenti, sorveglianza sanitaria, conversioni Power Automate), tutti draft+disattivi all'import
- **Arricchimento payload per sorgente**: tickets (nome/tag asset), assenze (email caporeparto/dipendente), anomalie (`modified_by_role` CC/CAR per notifiche filtrate per ruolo)
- **Approvazioni multi-canale**: email classica, webhook Teams legacy, **Teams chat Flow** (Power Automate), Entra Application Proxy one-click
- **Link di approvazione personali** (ottobre 2026): ogni destinatario riceve il proprio link `/approval-actions/r/<segreto>/approva|rifiuta/` (a DB solo l'hash, monouso, scade con la richiesta). Chi lo apre decide a nome di quel destinatario senza login; GET mostra solo la conferma. I link della richiesta (`/automazioni/approvazione/<uuid>/…`, `/approval-actions/approve|reject/<uuid>/`) e il webhook Teams condiviso richiedono il login di un approvatore. Nessun header HTTP di identità viene letto. L'uuid resta il RID delle risposte via casella mail
- **Ramo riprendibile**: dopo la decisione le azioni salvano il progresso (`branch_status`/`branch_progress`); lo schedule `approval_branch_recovery` (15 min, comando `recover_approval_branches [--dry-run]`) riprende i rami interrotti dall'azione successiva
- **Azione HTTP**: solo URL `http`/`https`, timeout massimo 30 secondi
- **Template email approvazioni** riutilizzabili con `portal_links` / `mail_reply` / `hybrid`
- **Mailbox poller Graph** (Microsoft 365 compatible, no Basic Auth): policy "first valid decision wins", dedup persistente, fail-closed sui mittenti
- **Import Power Automate** (`.zip`/`.json`) con analisi, remediation, preview, handoff a draft nel designer
- **Converter integrato** con selettore target table dal catalogo del portale
- **Test inline**: esegui regola con record reale (ultimi 20) o dati campione, output per azione
- **Pulsante "Ripeti" nel run log** (`/automazioni/run-log/<id>/`): apre la pagina test della regola con `payload_json` e `old_payload_json` del log originale già precompilati — analogo al "Resubmit" di Power Automate. Caricamento via `?from_log=<id>`, validato server-side
- **Job di sistema nel run log**: i task periodici django-q (es. invio mail conferma anomalie differite, escalation) compaiono nel run-log con `source_code` `system:<job>` (filtro "Sorgente" → "Sistema: …"), esito SUCCESS/SKIPPED/ERROR e durata. Helper `automazioni/system_runlog.py` (`@system_job_run`), nessuna regola associata. I run senza attività (no-op) non vengono loggati, per non intasare la tabella sui job al minuto. I poller queue/mailbox restano fuori (già tracciati da `monitoring`)
- **Retention RunLog (GDPR)**: i RunLog possono contenere dati personali nel payload → cleanup giornaliero (`cleanup_run_logs`, schedule `30 3 * * *`) che elimina i log oltre la finestra configurabile (SiteConfig `automazioni_runlog_retention_days`, default 90 giorni). Command con dry-run di default, `--apply`/`--days N`, cancellazione a batch. Non tocca l'audit trail legale (`core.log_action`)
- **Picker valori smart** per condizioni: `allowed_values` registry + valori distinti DB
- **Queue admin** con azioni `Stoppa` / `Elimina`, card salute poller, timezone-aware
- **Schema drift difensivo**: UI resta funzionante anche se migration non ancora applicate (warning leggibili)

## Note di rilascio

#### Flussi dei moduli nel designer Automazioni

Pianificazioni e notifiche applicative censite si gestiscono come flussi nel designer esistente: attivazione, condizioni, azioni, calendario e storico. Il collegamento «Apri flusso» è disponibile nelle pianificazioni e negli eventi. L'azione di modulo conserva la logica operativa; disattivare una notifica non annulla l'operazione aziendale.

Installazione e recupero del worker: [runbook flussi](../../docs/AUTOMAZIONI_FLUSSI_RUNTIME.md). Le personalizzazioni non vengono riscritte al deploy; il recupero dell'arretrato richiede worker fermi e conserva i pacchetti modificati nel database. Nessun servizio Microsoft Power Automate richiesto.

Le due richieste di approvazione Assenze censite possono essere unite con `merge_assenze_flows`: un percorso per tipo/durata, registrazione dell'esito dopo l'ultimo approvatore e fallback al caporeparto. Le regole originali vengono conservate disattivate. La conversione richiede processori fermi; anteprima e ripristino sono descritti nel runbook.
