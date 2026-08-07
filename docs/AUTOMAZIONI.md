# Automazioni schedulate — NOVICROM HUB

> ⚙️ **Documento auto-generato** da `python manage.py genera_doc_automazioni`.
> Fonte unica: `django_app/automazioni/schedules.py`. **Non modificare a mano**:
> si rigenera identico a ogni aggiunta di un'automazione (e a ogni deploy via `setup_q_schedules`).

**Totale automazioni attive:** 42

Ogni automazione è un task periodico gestito da django-q2 e può essere **disattivata** dalla Centrale di comando (Monitoring → ScheduleControl) senza toccare il codice.

---

## Anagrafica · HR, Formazione e Visite

### `archivia_attestati_mancanti`

- **Quando gira:** ogni giorno, alle 02:15
- **Task eseguito:** `anagrafica.tasks.run_archivia_attestati_mancanti`
- **Cosa fa:** Archiviazione notturna degli attestati mancanti nel box documenti del dipendente. No-op se il salvataggio automatico è disattivato (opt-in da Impostazioni → Template attestato), quindi sicuro da tenere sempre attivo.

### `attiva_assegnazioni_programmate`

- **Quando gira:** ogni giorno, alle 00:05
- **Task eseguito:** `anagrafica.tasks.run_attiva_assegnazioni_programmate`
- **Cosa fa:** Attiva gli spostamenti organizzativi programmati la cui decorrenza e' arrivata (reparto/area/mansione/ruolo del dipendente). Presto al mattino, prima che chiunque apra il portale, cosi la giornata inizia gia' con l'assetto nuovo. Idempotente e no-op se non ce n'e' nessuno.

### `contratti_expiry_reminders`

- **Quando gira:** ogni giorno, alle 07:50
- **Task eseguito:** `anagrafica.tasks.run_contratti_expiry_reminders`
- **Cosa fa:** ANAGRAFICA HR — contratti a termine + periodi di prova in scadenza. Fail-safe: no-op senza SiteConfig contratti_reminder_emails.

### `elearning_reminders`

- **Quando gira:** ogni giorno, alle 07:55
- **Task eseguito:** `anagrafica.tasks.run_elearning_reminders`
- **Cosa fa:** ANAGRAFICA — promemoria micro-corsi e-learning non completati: digest HR + notifica in-app al discente. Le notifiche in-app partono comunque; il digest è fail-safe (no-op senza SiteConfig elearning_reminder_emails).

### `formazione_audit_digest`

- **Quando gira:** il giorno 1 di gen/apr/lug/ott del mese, alle 08:00
- **Task eseguito:** `anagrafica.tasks.run_formazione_audit_digest`
- **Cosa fa:** ANAGRAFICA — digest trimestrale formazione (abilitazioni in scadenza) per audit ISO. NB destinatari placeholder (admin/superuser) finché non si configura una fonte HR/RSPP dedicata.

### `formazione_session_reminders`

- **Quando gira:** ogni giorno, alle 07:30
- **Task eseguito:** `anagrafica.tasks.run_formazione_session_reminders`
- **Cosa fa:** Promemoria sessioni formative imminenti (T-7 e T-1) agli iscritti, con invito calendario .ics + notifica in-app. Fail-safe / no-op se non ci sono edizioni pianificate nelle date bersaglio.

### `idoneita_digest`

- **Quando gira:** ogni lun, alle 07:00
- **Task eseguito:** `anagrafica.tasks.run_idoneita_digest`
- **Cosa fa:** Digest "idoneità alla mansione" (non idonei / con riserve) per RSPP / medico competente / HR. Fail-safe: no-op se non sono configurati i destinatari (SiteConfig idoneita_reminder_emails).

### `intake_referti_sanitari`

- **Quando gira:** ogni 10 minuti
- **Task eseguito:** `anagrafica.tasks.run_intake_referti_sanitari`
- **Cosa fa:** Certificati di idoneità depositati dalla fotocopiatrice in una cartella di rete. Qui non c'è nessun QR: il dipendente si riconosce dal blocco anagrafico e si conferma sulla data di nascita, quindi l'esito normale è una proposta in coda, non una registrazione. Spento finché non lo si accende da Impostazioni → Acquisizione referti. Passo più lungo dei fogli firme: la lettura costa ~2 secondi a certificato (OCR), e nessuno aspetta un referto in tempo reale.

### `intake_scansioni_formazione`

- **Quando gira:** ogni 2 minuti
- **Task eseguito:** `anagrafica.tasks.run_intake_scansioni_formazione`
- **Cosa fa:** Fogli firme depositati dalla fotocopiatrice in una cartella di rete: il QR dice a quale giornata appartengono, quindi non serve nessuna convenzione sul nome del file. Spento finché non lo si accende da Impostazioni → Acquisizione scansioni, e no-op se la share non risponde: una cartella irraggiungibile non è un guasto del portale.

### `training_expiry_reminders`

- **Quando gira:** ogni giorno, alle 08:05
- **Task eseguito:** `anagrafica.tasks.run_training_expiry_reminders`
- **Cosa fa:** ANAGRAFICA — reminder scadenze formazione OBBLIGATORIA (corsi scaduti/in scadenza dalla cache TrainingDeadline): digest HR + notifica al dipendente. Complementare a formazione_audit_digest (trimestrale): qui è il reminder operativo. Fail-safe: digest no-op senza SiteConfig training_reminder_emails.

### `visite_expiry_reminders`

- **Quando gira:** ogni giorno, alle 07:45
- **Task eseguito:** `anagrafica.tasks.run_visite_expiry_reminders`
- **Cosa fa:** ANAGRAFICA HR — reminder visite mediche scadute/in scadenza: digest ai responsabili (card+badge nel frame HUB) + notifica in-app al dipendente. Fail-safe: no-op senza SiteConfig visite_reminder_emails.

### `visite_mediche_digest`

- **Quando gira:** il giorno 1 del mese, alle 08:00
- **Task eseguito:** `anagrafica.tasks.run_visite_mediche_digest`
- **Cosa fa:** ANAGRAFICA — digest mensile visite mediche in scadenza (HR). In parte ridondante con visite_expiry_reminders: disattivabile dalla Centrale di comando. Destinatari placeholder (admin/superuser).

## Assets · Manutenzione

### `assets_generate_workorders`

- **Quando gira:** ogni giorno, alle 06:00
- **Task eseguito:** `assets.tasks.run_generate_scheduled_workorders`
- **Cosa fa:** ASSETS — genera gli OdL periodici dovuti dalle MaintenanceRule attive. Idempotente (nessun duplicato se esiste già un WO OPEN). Gira PRIMA del promemoria manutenzione così i nuovi OdL rientrano nella mail del giorno.

### `assets_maintenance_reminders`

- **Quando gira:** ogni giorno, alle 07:00
- **Task eseguito:** `assets.tasks.run_maintenance_reminders`
- **Cosa fa:** ASSETS — promemoria scadenze manutenzione / verifiche periodiche + OdL scaduti. Destinatari SiteConfig assets_reminder_emails con FALLBACK su ADMINS/superuser (non no-op puro): disattivabile dalla Centrale di comando.

## DPI · Sicurezza

### `dpi_expiry_reminders`

- **Quando gira:** ogni giorno, alle 07:10
- **Task eseguito:** `dpi.tasks.run_dpi_expiry_reminders`
- **Cosa fa:** DPI — promemoria DPI scaduti / in scadenza (+ notifica in-app). Destinatari da impostazioni DPI/SiteConfig con fallback ADMINS/superuser (non no-op puro): disattivabile dalla Centrale di comando.

## RENTRI · Ambiente

### `rentri_scadenze_check`

- **Quando gira:** ogni giorno, alle 07:20
- **Task eseguito:** `rentri.tasks.run_rentri_scadenze_check`
- **Cosa fa:** RENTRI — alert registri non confermati/inviati oltre soglia, agli admin. Da attivare dove il modulo RENTRI è operativo.

## Ticket · Assistenza/Manutenzione

### `tickets_daily_digest`

- **Quando gira:** ogni giorno, alle 07:40
- **Task eseguito:** `tickets.tasks.run_ticket_daily_digest`
- **Cosa fa:** TICKETS — digest mattutino "i miei ticket di oggi" per assegnatario (aperti in scadenza oggi o già scaduti).

### `tickets_escalation`

- **Quando gira:** ogni giorno, ogni ora al minuto 0
- **Task eseguito:** `tickets.tasks.run_tickets_escalation`
- **Cosa fa:** Promemoria dashboard (sempre) + resoconto email "ticket urgenti non assegnati". Cadenza oraria: il task aggiorna i promemoria a ogni run e invia il resoconto solo nei giorni lavorativi all'ora configurata (default 08:00), se l'escalation è attivata da Impostazioni ticket.

### `tickets_sla_reminders`

- **Quando gira:** ogni giorno, alle 08:30
- **Task eseguito:** `tickets.tasks.run_sla_reminders`
- **Cosa fa:** TICKETS — promemoria SLA scaduto all'ASSEGNATARIO (complementare a tickets_escalation, che copre gli urgenti non assegnati).

## Anomalie qualità

### `anomalie_cleanup_allegati`

- **Quando gira:** ogni giorno, alle 03:45
- **Task eseguito:** `anomalie.tasks.run_anomalie_cleanup_allegati`
- **Cosa fa:** Pulizia notturna delle cartelle allegati anomalie orfane (id non più in tabella anomalie). Conservativo: elimina solo cartelle ferme da oltre 30 giorni, max 500 per run. Idempotente.

### `anomalie_escalation`

- **Quando gira:** ogni giorno, ogni ora al minuto 0
- **Task eseguito:** `anomalie.tasks.run_anomalie_escalation`
- **Cosa fa:** Promemoria dashboard (sempre) + resoconto email "OP da controllare". Cadenza oraria: il task aggiorna i promemoria a ogni run e invia il resoconto solo nei giorni lavorativi all'ora configurata (default 06:00), se l'escalation è attivata da Impostazioni anomalie (SiteConfig).

### `anomalie_pending_notifications`

- **Quando gira:** ogni minuto
- **Task eseguito:** `anomalie.tasks.run_anomalie_pending_notifications`
- **Cosa fa:** Fallback debounce per la mail di conferma aggiornamenti anomalie: invia il riepilogo per gli OP modificati e fermi da > 5 minuti.

## Gestione Specifiche

### `gestione_specifiche_escalation`

- **Quando gira:** ogni giorno, alle 07:15
- **Task eseguito:** `gestione_specifiche.tasks.run_specifiche_escalation`
- **Cosa fa:** GESTIONE SPECIFICHE — escalation 14gg → Approvatore + DM.

### `gestione_specifiche_reminder`

- **Quando gira:** ogni giorno, alle 07:00
- **Task eseguito:** `gestione_specifiche.tasks.run_specifiche_reminder`
- **Cosa fa:** GESTIONE SPECIFICHE — reminder 7gg sui MOD.133 non presi in carico. Timer in pausa per le specifiche sospese/in errore (gestito nel job).

### `gestione_specifiche_verifica_periodica`

- **Quando gira:** ogni giorno, alle 06:30
- **Task eseguito:** `gestione_specifiche.tasks.run_specifiche_verifica_periodica`
- **Cosa fa:** GESTIONE SPECIFICHE — verifica periodica 6 mesi (ricorrente da data_verifica).

## Procedure · SGI

### `pr_assignment_lifecycle`

- **Quando gira:** ogni giorno, alle 06:45
- **Task eseguito:** `procedure_refresh.tasks.run_assignment_lifecycle`
- **Cosa fa:** Motore scadenze presa visione (ISO 9001/EN 9100): marca SEMPRE "Scaduta" le assegnazioni oltre due_date (stato dei dati, evidenza audit); con pr_reminder_attivo=1 invia anche promemoria pre-scadenza, solleciti agli inadempienti e il digest ai gestori (config SiteConfig pr_reminder_* dalla dashboard admin del modulo). Email su email_notifica. Fail-safe.

### `pr_sgi_auto_sync`

- **Quando gira:** ogni giorno, alle 03:00
- **Task eseguito:** `procedure_refresh.tasks.run_sgi_auto_sync`
- **Cosa fa:** Sincronizzazione automatica del corpus SGI dalla share (perimetro sicuro): applica solo documenti nuovi o interamente figli dell'import, MAI quelli in presa visione o gestiti a mano. Dietro flag SiteConfig pr_sgi_auto_sync_attivo (default off). Gira alle 03:00 così i nuovi documenti sono già indicizzati dal re-index RAG delle 03:30. Fail-safe / no-op se flag off o share giù.

### `sgi_share_check`

- **Quando gira:** ogni giorno, alle 04:30
- **Task eseguito:** `procedure_refresh.tasks.run_sgi_share_check`
- **Cosa fa:** Watchdog "drift" del corpus SGI: confronta la share col DB e apre una Issue INFORMATIVA se ci sono documenti nuovi/aggiornati non ancora importati. L'import resta MANUALE (import_sgi_da_share --apply + index_sgi_documents): qui si NOTIFICA soltanto, così i nuovi MT/MOD non restano invisibili all'AI. Fail-safe / no-op se PROCEDURE_REFRESH_SGI_SHARE_ROOT non e' impostato o la share e' giu'.

## Monitoraggio sistema

### `ai_readiness_alert`

- **Quando gira:** ogni 15 minuti
- **Task eseguito:** `monitoring.tasks.run_ai_readiness_alert`
- **Cosa fa:** Health-check AI (Ollama/TEI) + servizi readyz, con alert email su degrado. Riusa i destinatari/rate-limit del monitoring; invia solo al cambio di stato (no spam). Fail-safe: ogni check cattura le proprie eccezioni e l'AI è comunque fail-safe (degrada a BM25), quindi un suo problema = WARN/FAIL solo informativo, mai un blocco. Cadenza frequente: pochi probe di rete.

### `system_digest`

- **Quando gira:** ogni giorno, alle 07:00
- **Task eseguito:** `monitoring.tasks.run_system_digest`
- **Cosa fa:** Digest giornaliero "stato portale" via email agli admin del monitoring: servizi (readyz), Assistente AI, automazioni e issue per severità in un colpo d'occhio. Heartbeat: per default invia sempre (anche "tutto ok"), con MONITORING_DIGEST_ALWAYS=False solo se c'è qualcosa da segnalare.

## Assistente AI

### `ai_index_sgi_documents`

- **Quando gira:** ogni giorno, alle 03:30
- **Task eseguito:** `ai_assistant.tasks.run_index_sgi_documents`
- **Cosa fa:** Warm dell'indice RAG + cache embeddings del corpus documentale SGI (specifiche in vigore / procedure correnti). La PRIMA build è la più costosa (estrazione PDF + embedding); il run notturno la anticipa così non è la prima chat della giornata a pagarla. Utile soprattutto con OLLAMA_EMBED_ENABLED=1; con embeddings spenti ricostruisce solo l'indice BM25 (cheap). Fail-safe / no-op se RAG o SGI sono disattivi o Ollama è giù.

### `ai_rag_quality_alert`

- **Quando gira:** ogni giorno, alle 04:00
- **Task eseguito:** `ai_assistant.tasks.run_rag_quality_alert`
- **Cosa fa:** Qualità del RAG SGI: dopo il warm dell'indice (03:30) misura recall/MRR con ai_eval --rag-sgi e avvisa gli admin se l'indice è vuoto (sgi_chunks=0) o la recall scende sotto OLLAMA_RAG_SGI_MIN_RECALL. Complementare alla liveness (ai_readiness_alert): qui si verifica che il RAG "risponda bene". Giornaliero (l'eval ricostruisce l'indice). Fail-safe / rate-limited.

### `ai_warmup_ollama`

- **Quando gira:** ogni 25 minuti
- **Task eseguito:** `ai_assistant.tasks.run_warmup_ollama`
- **Cosa fa:** Warmup del modello chat Ollama: pre-carica i pesi in memoria così la prima richiesta utente non paga il cold start (causa principale dei timeout «Timeout dopo Ns durante la risposta di Ollama»). Cadenza < del keep_alive (default 30m): ogni run rinnova il timer, il modello resta sempre caldo SENZA dover toccare l'.env. Fail-safe / no-op se l'AI è disabilitata o il provider è Open WebUI (keep_alive è primitiva Ollama).

## KICK-OFF · Attività

### `tasks_meeting_issue_reminders`

- **Quando gira:** ogni lun, alle 07:00
- **Task eseguito:** `tasks.tasks.run_meeting_issue_reminders`
- **Cosa fa:** KICK-OFF — sollecito ai responsabili sui «problemi aperti» degli incontri scaduti (MeetingIssue OPEN con due_date passata). Email + notifica in-app.

### `tasks_send_reminders`

- **Quando gira:** ogni giorno, alle 07:30
- **Task eseguito:** `tasks.tasks.run_send_task_reminders`
- **Cosa fa:** Promemoria scadenza attività KICK-OFF: materializza i TaskReminder in scadenza come notifiche portale (idempotente, fired flag). Porta i promemoria nello scheduler centralizzato al posto del Task Windows.

## Trasversale (Core)

### `caporeparto_morning_digest`

- **Quando gira:** da lun a ven, alle 07:00
- **Task eseguito:** `core.tasks.run_caporeparto_morning_digest`
- **Cosa fa:** CORE — digest mattutino caporeparto: DPI in attesa + incidenti aperti del reparto (fonte capi = Reparto.caporeparto_legacy_id; email = email_notifica). Fail-safe: no-op senza capi/voci; assenze (SharePoint dismesso) e ticket (nessun legame reparto) esclusi per design.

## Motore automazioni

### `approval_mailbox`

- **Quando gira:** ogni 2 minuti
- **Task eseguito:** `automazioni.tasks.run_approval_mailbox`

### `automation_queue`

- **Quando gira:** ogni minuto
- **Task eseguito:** `automazioni.tasks.run_automation_queue`

### `cleanup_run_logs`

- **Quando gira:** ogni giorno, alle 03:30
- **Task eseguito:** `automazioni.tasks.run_cleanup_run_logs`
- **Cosa fa:** Retention RunLog automazioni (GDPR): elimina i log oltre la finestra configurata (SiteConfig automazioni_runlog_retention_days, default 90gg).

### `report_scadenze_settimanale`

- **Quando gira:** ogni lun, alle 06:00
- **Task eseguito:** `automazioni.tasks.run_report_scadenze_settimanale`
- **Cosa fa:** Cadenza fissa (lunedi 06:00); attivazione e parametri si gestiscono dalla pagina Impostazioni automazioni (SiteConfig), non da qui.

## Altro

### `checklist_chiusura_reminders`

- **Quando gira:** ogni giorno, alle 07:15
- **Task eseguito:** `checklist_operativa.tasks.run_checklist_chiusura_reminders`
- **Cosa fa:** CHECKLIST OPERATIVA — promemoria in-app ai responsabili con task non confermati per le chiusure aziendali in arrivo (soglie 7/3/1/0 giorni).

### `suggestion_corner_reminders`

- **Quando gira:** ogni giorno, alle 08:00
- **Task eseguito:** `suggestion_corner.tasks.run_suggestion_corner_reminders`
- **Cosa fa:** SUGGESTION CORNER — solleciti DO/CHECK + escalation (§3)

---

_Legenda cadenza_: le frasi «alle HH:MM / ogni N minuti» derivano dall'espressione di schedulazione; l'orario è quello del server.
