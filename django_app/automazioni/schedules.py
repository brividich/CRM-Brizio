"""
Definizione dei task periodici django-q2 per il modulo automazioni.

Importato da setup_q_schedules per la registrazione idempotente.
Non avviare task qui: usare il management command setup_q_schedules.
"""
from __future__ import annotations

SCHEDULES: list[dict] = [
    {
        # Riconcilia richieste ancora in attesa oltre la scadenza, senza applicare decisioni.
        "name": "approval_expiry_reconciliation",
        "func": "automazioni.managed_flows.reconcile_expired_approvals",
        "schedule_type": "I", "minutes": 15, "repeats": -1, "kwargs": {},
    },
    {
        # Riprende le azioni post-decisione rimaste a meta' (crash/riavvio durante il ramo).
        "name": "approval_branch_recovery",
        "func": "automazioni.approval_links.recover_stuck_branches",
        "schedule_type": "I", "minutes": 15, "repeats": -1, "kwargs": {},
    },
    {
        # ASSETS — reportistica programmata dalle Impostazioni: controlla le scadenze,
        # archivia snapshot e PDF/Excel, recupera gli errori temporanei (max 3 tentativi).
        "name": "assets_reportistica",
        "func": "assets.services.reporting.dispatch_due_reports",
        "schedule_type": "I",
        "minutes": 1,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSETS — report salvati con invio pianificato (catalogo report): ogni 15 minuti
        # invia quelli in scadenza, solo ai destinatari che hanno ancora accesso al report.
        "name": "assets_report_catalogo_invii",
        "func": "assets.services.report_catalog.invia_report_pianificati",
        "schedule_type": "I",
        "minutes": 15,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSETS — retention dello storico campi (stato, assegnazione, rete) alle 03:15.
        # Con ASSETS_STORICO_RETENTION_GIORNI=0 (default) non elimina nulla; l'ultima
        # voce di ogni campo resta sempre, per la vista "com'era alla data".
        "name": "assets_storico_retention",
        "func": "assets.services.storico_asset.applica_retention",
        "schedule_type": "C",
        "cron": "15 3 * * *",
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CONTATORI — monitor SNMP dei dispositivi attivi, con un job per apparato.
        # Stato, sonde ed errori sono consultabili nella Centrale MFC/SNMP.
        "name": "contatori_poll_snmp",
        "func": "contatori.tasks.run_poll_snmp",
        "schedule_type": "I",
        "minutes": 5,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CONTATORI — retention delle rilevazioni SNMP di NVR e telecamere (TVCC) alle 03:40.
        # Giorni da Impostazioni SNMP (default 14); gli altri dispositivi non vengono toccati.
        "name": "contatori_pulizia_tvcc",
        "func": "contatori.tasks.pulisci_rilevazioni_tvcc",
        "schedule_type": "C",
        "cron": "40 3 * * *",
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CONTATORI — snapshot mensile MFC il giorno 1 alle 00:00 (fuso del portale):
        # coincide con la chiusura usata dal fornitore in fattura ("Lett. al 30/09").
        # Una lettura per macchina/mese; Esegui ora recupera solo le letture mancanti.
        # Lo storico mensile non sovrascrive le letture trimestrali di riconciliazione.
        "name": "contatori_letture_mensili",
        "func": "contatori.tasks.run_letture_mensili",
        "schedule_type": "C",
        "cron": "0 0 1 * *",
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CONTATORI — recupero per le MFC spente o in sospensione a mezzanotte: ogni
        # 15 minuti dal giorno 1 al 7 accoda solo quelle ancora senza lettura del mese,
        # cosi' una macchina viene letta entro 15 minuti da quando si riaccende.
        # Stesso nome di prima: setup_q_schedules aggiorna il cron, nessuna schedule orfana.
        "name": "contatori_letture_mensili_recupero",
        "func": "contatori.tasks.run_letture_mensili",
        "schedule_type": "C",
        "cron": "*/15 * 1-7 * *",
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CONTATORI — livelli dei consumabili MFC ogni mattina alle 07:30, un job per MFC.
        # Alimenta storico, stima dei giorni residui e la voce «Da fare» della Centrale.
        "name": "contatori_consumabili",
        "func": "contatori.tasks.run_letture_consumabili",
        "schedule_type": "C",
        "cron": "30 7 * * *",
        "repeats": -1,
        "kwargs": {},
    },
    {
        "name": "automation_queue",
        "func": "automazioni.tasks.run_automation_queue",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 1,           # ogni minuto
        "repeats": -1,
        "kwargs": {"limit": 50},
    },
    {
        # SECURITY CENTER — letture Defender/Entra/Veeam/Secure Score, regole, heartbeat sorgenti,
        # KPI e notifiche. Le caselle mail sono nel lavoro security_caselle.
        "name": "security_cycle",
        "func": "security.tasks.run_security_cycle_task",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 15,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SECURITY CENTER — lettura delle caselle mail dei report (Graph/IMAP): parser e regole su ogni
        # mail importata. Lavoro a sé, separato dal security_cycle, con timeout dedicato: un arretrato di
        # mail non ferma più regole, battito e KPI del ciclo.
        "name": "security_caselle",
        "func": "security.tasks.run_security_caselle_task",
        "schedule_type": "I",   # Schedule.MINUTES
        "minutes": 15,
        "repeats": -1,
        "kwargs": {"q_options": {"timeout": 300}},
    },
    {
        # SECURITY CENTER — arricchimento CVE (NVD, CISA KEV, EPSS) e impatto sugli asset.
        # Si ferma entro 90 s (timeout worker 120 s); spento finché non acceso da /soc/impostazioni/.
        "name": "security_cve_enrichment",
        "func": "security.tasks.enrich_cve_task",
        "schedule_type": "H",   # Schedule.HOURLY
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SECURITY CENTER — sintesi del giorno della Panoramica preparata dall'AI locale, ogni 30 minuti
        # dalle 6 alle 19 (lun-sab), solo se i punti da guardare sono cambiati: la pagina la mostra già scritta.
        "name": "security_ai_sintesi",
        "func": "security.tasks.ai_sintesi_giorno_task",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "0,30 6-19 * * 1-6",
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SECURITY CENTER — lettura assistita dall'AI locale: propone i campi delle letture
        # «da verificare» e classifica le mail che nessun parser riconosce. Solo proposte, mai alert.
        # Spenta finché non accesa da /soc/impostazioni/; massimo N elementi per giro, nessuna nuova richiesta dopo 60 s.
        "name": "security_ai_lettura",
        "func": "security.tasks.ai_lettura_assistita_task",
        "schedule_type": "I",   # Schedule.MINUTES
        "minutes": 30,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SECURITY CENTER — proposte dell'AI locale sui casi «da verificare» del calcolo CVE: il CPE
        # di un software scelto fra quelli delle CVE note, o l'esito per PC quando la versione non si
        # confronta. Solo proposte da accettare o rifiutare. Spenta finché non accesa da /soc/impostazioni/;
        # massimo N casi per giro, nessuna richiesta se Ollama non risponde. Lettura «cpe_ai».
        "name": "security_ai_cpe",
        "func": "security.tasks.ai_cpe_proposte_task",
        "schedule_type": "I",   # Schedule.MINUTES
        "minutes": 360,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SECURITY CENTER — proposte di chiusura dell'AI locale sugli alert aperti, con apprendimento
        # dalle decisioni delle persone; chiude da sola solo i tipi di alert imparati. Lettura «ai_proposte».
        "name": "security_ai_proposte",
        "func": "security.tasks.ai_proposte_task",
        "schedule_type": "I",   # Schedule.MINUTES
        "minutes": 15,
        "repeats": -1,
        "kwargs": {},
    },
    {
        "name": "approval_mailbox",
        "func": "automazioni.tasks.run_approval_mailbox",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 2,           # ogni 2 minuti
        "repeats": -1,
        "kwargs": {"limit": 25},
    },
    {
        # Cadenza fissa (lunedi 06:00); attivazione e parametri si gestiscono
        # dalla pagina Impostazioni automazioni (SiteConfig), non da qui.
        "name": "report_scadenze_settimanale",
        "func": "automazioni.tasks.run_report_scadenze_settimanale",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 6 * * 1",        # ogni lunedi alle 06:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Fallback debounce per la mail di conferma aggiornamenti anomalie:
        # invia il riepilogo per gli OP modificati e fermi da > 5 minuti.
        "name": "anomalie_pending_notifications",
        "func": "anomalie.tasks.run_anomalie_pending_notifications",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 1,           # controllo ogni minuto
        "repeats": -1,
        "kwargs": {"threshold_minutes": 5},
    },
    {
        # Promemoria dashboard (sempre) + resoconto email "OP da controllare".
        # Cadenza oraria: il task aggiorna i promemoria a ogni run e invia il
        # resoconto solo nei giorni lavorativi all'ora configurata (default 06:00),
        # se l'escalation è attivata da Impostazioni anomalie (SiteConfig).
        "name": "anomalie_escalation",
        "func": "anomalie.tasks.run_anomalie_escalation",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 * * * *",        # ogni ora in punto
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Promemoria dashboard (sempre) + resoconto email "ticket urgenti non
        # assegnati". Cadenza oraria: il task aggiorna i promemoria a ogni run e
        # invia il resoconto solo nei giorni lavorativi all'ora configurata
        # (default 08:00), se l'escalation è attivata da Impostazioni ticket.
        "name": "tickets_escalation",
        "func": "tickets.tasks.run_tickets_escalation",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 * * * *",        # ogni ora in punto
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Attiva gli spostamenti organizzativi programmati la cui decorrenza e'
        # arrivata (reparto/area/mansione/ruolo del dipendente). Presto al
        # mattino, prima che chiunque apra il portale, cosi la giornata inizia
        # gia' con l'assetto nuovo. Idempotente e no-op se non ce n'e' nessuno.
        "name": "attiva_assegnazioni_programmate",
        "func": "anagrafica.tasks.run_attiva_assegnazioni_programmate",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "5 0 * * *",        # ogni giorno alle 00:05
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Digest "idoneità alla mansione" (non idonei / con riserve) per RSPP /
        # medico competente / HR. Fail-safe: no-op se non sono configurati i
        # destinatari (SiteConfig idoneita_reminder_emails).
        "name": "idoneita_digest",
        "func": "anagrafica.tasks.run_idoneita_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 7 * * 1",        # ogni lunedi alle 07:00 (dopo il report scadenze 06:00)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Archiviazione notturna degli attestati mancanti nel box documenti del
        # dipendente. No-op se il salvataggio automatico è disattivato (opt-in da
        # Impostazioni → Template attestato), quindi sicuro da tenere sempre attivo.
        "name": "archivia_attestati_mancanti",
        "func": "anagrafica.tasks.run_archivia_attestati_mancanti",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 2 * * *",       # ogni notte alle 02:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Fogli firme depositati dalla fotocopiatrice in una cartella di rete:
        # il QR dice a quale giornata appartengono, quindi non serve nessuna
        # convenzione sul nome del file. Spento finché non lo si accende da
        # Impostazioni → Acquisizione scansioni, e no-op se la share non
        # risponde: una cartella irraggiungibile non è un guasto del portale.
        "name": "intake_scansioni_formazione",
        "func": "anagrafica.tasks.run_intake_scansioni_formazione",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 2,           # abbastanza spesso da sembrare immediato
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Certificati di idoneità depositati dalla fotocopiatrice in una cartella
        # di rete. Qui non c'è nessun QR: il dipendente si riconosce dal blocco
        # anagrafico e si conferma sulla data di nascita, quindi l'esito normale
        # è una proposta in coda, non una registrazione. Spento finché non lo si
        # accende da Impostazioni → Acquisizione referti.
        # Passo più lungo dei fogli firme: la lettura costa ~2 secondi a
        # certificato (OCR), e nessuno aspetta un referto in tempo reale.
        "name": "intake_referti_sanitari",
        "func": "anagrafica.tasks.run_intake_referti_sanitari",
        "schedule_type": "I",   # Schedule.MINUTES
        "minutes": 10,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Fogli delle verifiche periodiche (luci di emergenza, differenziali...)
        # depositati dallo scanner nella cartella di pescaggio: il QR dice a quale
        # verifica appartengono, i punti segnati restano da confermare. Spento
        # finche' non lo si accende da Verifiche periodiche > Cartella scansioni;
        # no-op se la share non risponde.
        "name": "intake_verifiche_periodiche",
        "func": "assets.tasks.run_periodic_check_intake",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 2,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Promemoria sessioni formative imminenti (T-7 e T-1) agli iscritti, con
        # invito calendario .ics + notifica in-app. Fail-safe / no-op se non ci sono
        # edizioni pianificate nelle date bersaglio.
        "name": "formazione_session_reminders",
        "func": "anagrafica.tasks.run_formazione_session_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * *",       # ogni mattina alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Import dei saldi cedolini (ratei ferie/ROL/ex-festività) dal file XLSX
        # su SharePoint, il primo del mese a mezzanotte: il file a quell'ora
        # contiene già il mese appena chiuso. No-op se il link non è configurato
        # (Anagrafica → Importazione cedolini).
        "name": "import_cedolini_sharepoint",
        "func": "anagrafica.tasks.run_import_cedolini_sharepoint",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 0 1 * *",        # il 1° di ogni mese alle 00:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Retention RunLog automazioni (GDPR): elimina i log oltre la finestra
        # configurata (SiteConfig automazioni_runlog_retention_days, default 90gg).
        "name": "cleanup_run_logs",
        "func": "automazioni.tasks.run_cleanup_run_logs",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 3 * * *",       # ogni notte alle 03:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Pulizia notturna delle cartelle allegati anomalie orfane (id non più in
        # tabella anomalie). Conservativo: elimina solo cartelle ferme da oltre 30
        # giorni, max 500 per run. Idempotente.
        "name": "anomalie_cleanup_allegati",
        "func": "anomalie.tasks.run_anomalie_cleanup_allegati",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "45 3 * * *",       # ogni notte alle 03:45
        "repeats": -1,
        "kwargs": {"older_than_days": 30, "limit": 500},
    },
    {
        # Warmup del modello chat Ollama: pre-carica i pesi in memoria così la
        # prima richiesta utente non paga il cold start (causa principale dei
        # timeout «Timeout dopo Ns durante la risposta di Ollama»). Cadenza < del
        # keep_alive (default 30m): ogni run rinnova il timer, il modello resta
        # sempre caldo SENZA dover toccare l'.env. Fail-safe / no-op se l'AI è
        # disabilitata o il provider è Open WebUI (keep_alive è primitiva Ollama).
        "name": "ai_warmup_ollama",
        "func": "ai_assistant.tasks.run_warmup_ollama",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 25,          # ogni 25 min (< keep_alive 30m)
        "repeats": -1,
        # Il warmup aspetta Ollama fino a 300 s: oltre il timeout di 120 s del
        # cluster il worker veniva ucciso a metà.
        "kwargs": {"q_options": {"timeout": 330}},
    },
    {
        # Warm dell'indice RAG + cache embeddings del corpus documentale SGI
        # (specifiche in vigore / procedure correnti). La PRIMA build è la più
        # costosa (estrazione PDF + embedding); il run notturno la anticipa così
        # non è la prima chat della giornata a pagarla. Utile soprattutto con
        # OLLAMA_EMBED_ENABLED=1; con embeddings spenti ricostruisce solo l'indice
        # BM25 (cheap). Fail-safe / no-op se RAG o SGI sono disattivi o Ollama è giù.
        "name": "ai_index_sgi_documents",
        "func": "ai_assistant.tasks.run_index_sgi_documents",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "30 3 * * *",   # ogni notte alle 03:30 (off-peak)
        "repeats": -1,
        # Audit S5: la build completa supera i 120 s del cluster e veniva uccisa a
        # meta'. Timeout dedicato; la riconsegna del broker (retry 180 s) trova il
        # lock del task in corso e termina subito.
        "kwargs": {"q_options": {"timeout": 900}},
    },
    {
        # Storico chat dell'assistente AI: cancella le conversazioni ferme da più di
        # AI_CHAT_HISTORY_RETENTION_DAYS (default 90). Fail-safe.
        "name": "ai_pulisci_conversazioni",
        "func": "ai_assistant.tasks.run_pulisci_conversazioni",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "15 2 * * *",   # ogni notte alle 02:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Qualità del RAG SGI: dopo il warm dell'indice (03:30) misura recall/MRR
        # con ai_eval --rag-sgi e avvisa gli admin se l'indice è vuoto (sgi_chunks=0)
        # o la recall scende sotto OLLAMA_RAG_SGI_MIN_RECALL. Complementare alla
        # liveness (ai_readiness_alert): qui si verifica che il RAG "risponda bene".
        # Giornaliero (l'eval ricostruisce l'indice). Fail-safe / rate-limited.
        "name": "ai_rag_quality_alert",
        "func": "ai_assistant.tasks.run_rag_quality_alert",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "0 4 * * *",    # ogni notte alle 04:00 (dopo l'indicizzazione 03:30)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Watchdog "drift" del corpus SGI: confronta la share col DB e apre una Issue
        # INFORMATIVA se ci sono documenti nuovi/aggiornati non ancora importati. L'import
        # resta MANUALE (import_sgi_da_share --apply + index_sgi_documents): qui si
        # NOTIFICA soltanto, così i nuovi MT/MOD non restano invisibili all'AI. Fail-safe
        # / no-op se PROCEDURE_REFRESH_SGI_SHARE_ROOT non e' impostato o la share e' giu'.
        "name": "sgi_share_check",
        "func": "procedure_refresh.tasks.run_sgi_share_check",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "30 4 * * *",   # ogni notte alle 04:30 (dopo l'indicizzazione 03:30)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Sincronizzazione automatica del corpus SGI dalla share (perimetro sicuro):
        # applica solo documenti nuovi o interamente figli dell'import, MAI quelli in
        # presa visione o gestiti a mano. Dietro flag SiteConfig pr_sgi_auto_sync_attivo
        # (default off). Gira alle 03:00 così i nuovi documenti sono già indicizzati dal
        # re-index RAG delle 03:30. Fail-safe / no-op se flag off o share giù.
        "name": "pr_sgi_auto_sync",
        "func": "procedure_refresh.tasks.run_sgi_auto_sync",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "0 3 * * *",    # ogni notte alle 03:00 (prima del re-index RAG 03:30)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CN-SGI «sempre aggiornata»: ogni 15 minuti confronta un'impronta leggera della share
        # (percorso, dimensione, data dei file: nessun file aperto) e, solo se cambia,
        # lancia la sincronizzazione a perimetro sicuro. Stesso flag pr_sgi_auto_sync_attivo.
        # La share è solo letta. Fail-safe / no-op se flag spento o share giù.
        "name": "pr_sgi_controllo_orario",
        "func": "procedure_refresh.tasks.run_sgi_controllo_orario",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "*/15 * * * *",  # ogni 15 minuti (solo elenco e date dei file: leggero)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Motore scadenze presa visione (ISO 9001/EN 9100): marca SEMPRE "Scaduta"
        # le assegnazioni oltre due_date (stato dei dati, evidenza audit); con
        # pr_reminder_attivo=1 invia anche promemoria pre-scadenza, solleciti agli
        # inadempienti e il digest ai gestori (config SiteConfig pr_reminder_* dalla
        # dashboard admin del modulo). Email su email_notifica. Fail-safe.
        "name": "pr_assignment_lifecycle",
        "func": "procedure_refresh.tasks.run_assignment_lifecycle",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "45 6 * * *",   # ogni mattina alle 06:45 (prima dell'orario d'ufficio)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Digest giornaliero "stato portale" via email agli admin del monitoring:
        # servizi (readyz), Assistente AI, automazioni e issue per severità in un
        # colpo d'occhio. Heartbeat: per default invia sempre (anche "tutto ok"),
        # con MONITORING_DIGEST_ALWAYS=False solo se c'è qualcosa da segnalare.
        "name": "system_digest",
        "func": "monitoring.tasks.run_system_digest",
        "schedule_type": "C",   # Schedule.CRON
        "cron": "0 7 * * *",    # ogni mattina alle 07:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Health-check AI (Ollama/TEI) + servizi readyz, con alert email su degrado.
        # Riusa i destinatari/rate-limit del monitoring; invia solo al cambio di
        # stato (no spam). Fail-safe: ogni check cattura le proprie eccezioni e l'AI
        # è comunque fail-safe (degrada a BM25), quindi un suo problema = WARN/FAIL
        # solo informativo, mai un blocco. Cadenza frequente: pochi probe di rete.
        "name": "ai_readiness_alert",
        "func": "monitoring.tasks.run_ai_readiness_alert",
        "schedule_type": "I",       # Schedule.MINUTES
        "minutes": 15,
        "repeats": -1,
        "kwargs": {"include_services": True},
    },
    {
        # Backup e ripristino (BUILD_SPEC R2): età dell'ultimo FULL, catena dei log,
        # prova di ripristino, Recovery Kit, capacità del DB. Issue nella centrale per
        # WARN/FAIL, email solo per i FAIL (dedup + quiet hours). I backup veri girano
        # da Task Scheduler (register-backup-tasks.ps1), non da qui: questo solo controlla.
        "name": "backup_health_alert",
        "func": "monitoring.tasks.run_backup_health_alert",
        "schedule_type": "I",       # Schedule.MINUTES
        "minutes": 30,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Server: qcluster, coda django-q, spazio su disco, certificato https. Issue nella
        # centrale per WARN/FAIL, email solo per i FAIL (dedup + quiet hours). Il controllo
        # «qcluster fermo» da qui non può avvisare se il qcluster è fermo: per quello
        # c'è anche il comando infra_health_alert da Utilità di pianificazione.
        "name": "infra_health_alert",
        "func": "monitoring.tasks.run_infra_health_alert",
        "schedule_type": "I",       # Schedule.MINUTES
        "minutes": 30,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Promemoria scadenza attività KICK-OFF: materializza i TaskReminder in
        # scadenza come notifiche portale (idempotente, fired flag). Porta i
        # promemoria nello scheduler centralizzato al posto del Task Windows.
        "name": "tasks_send_reminders",
        "func": "tasks.tasks.run_send_task_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * *",       # ogni mattina alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # KICK-OFF — digest unico incontri: "domani hai un incontro" (ogni giorno)
        # + sollecito «problemi aperti» degli incontri scaduti (il lunedi, dentro
        # la stessa funzione). Una sola email per persona quando coincidono,
        # invece di due job/invii separati.
        "name": "tasks_meetings_digest",
        "func": "tasks.tasks.run_meetings_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 17 * * *",       # ogni pomeriggio alle 17:00 (il giorno prima dell'incontro)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # GESTIONE SPECIFICHE — reminder 7gg sui MOD.133 non presi in carico.
        # Timer in pausa per le specifiche sospese/in errore (gestito nel job).
        "name": "gestione_specifiche_reminder",
        "func": "gestione_specifiche.tasks.run_specifiche_reminder",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 7 * * *",        # ogni mattina alle 07:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # GESTIONE SPECIFICHE — escalation 14gg → Approvatore + DM.
        "name": "gestione_specifiche_escalation",
        "func": "gestione_specifiche.tasks.run_specifiche_escalation",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 7 * * *",       # ogni mattina alle 07:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # GESTIONE SPECIFICHE — catalogo allineato alla cartella della share: ogni 15 minuti
        # elenca i PDF (sola lettura, esclusa _SUPERATO) e, se qualcosa è cambiato, crea le
        # specifiche nuove e le nuove revisioni (in bozza, con avviso a chi prende in carico) e
        # ricollega i file spostati. Interruttore in Amministrazione (gs_sync_cartelle_attivo).
        "name": "gestione_specifiche_sync_cartelle",
        "func": "gestione_specifiche.tasks.run_sync_cartelle",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "*/15 * * * *",     # ogni 15 minuti
        "repeats": -1,
        "kwargs": {},
    },
    {
        # GESTIONE SPECIFICHE — verifica periodica 6 mesi (ricorrente da data_verifica).
        "name": "gestione_specifiche_verifica_periodica",
        "func": "gestione_specifiche.tasks.run_specifiche_verifica_periodica",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 6 * * *",       # ogni mattina alle 06:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — ricalcolo notturno delle scadenze dal motore unico dei requisiti:
        # cache formazione (TrainingDeadline, prima mai ricalcolata: stati vecchi nello
        # scadenzario e nei promemoria) e scadenza effettiva delle visite (ricalcolo
        # prudente al cambio di periodicità). Dopo il cambio di giorno, prima dei promemoria.
        "name": "anagrafica_ricalcolo_scadenze",
        "func": "anagrafica.tasks.run_ricalcolo_scadenze",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "20 0 * * *",       # ogni notte alle 00:20
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — e-learning: assegna i corsi online obbligatori non ancora
        # soddisfatti (dal motore dei requisiti) e apre i cicli di aggiornamento
        # in scadenza; chiude le sessioni del player abbandonate. Idempotente.
        "name": "elearning_assegnazioni",
        "func": "anagrafica.tasks.run_elearning_assegnazioni",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "50 0 * * *",       # ogni notte alle 00:50, dopo il ricalcolo scadenze
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — cambio mansione: adempimenti in ritardo + persone con stato
        # operativo da verificare (visita del cambio mansione mancante, non idoneita').
        # No-op senza destinatari (SiteConfig cambio_mansione_emails). Nessun dato clinico.
        "name": "cambio_mansione_digest",
        "func": "anagrafica.tasks.run_cambio_mansione_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * 1-5",     # giorni feriali alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — controllo di integrita' requisiti/adempimenti/visite: il
        # report finisce in monitoring (vedi anagrafica.services.integrita_scadenze).
        "name": "anagrafica_integrita_sicurezza",
        "func": "anagrafica.tasks.run_integrita_sicurezza",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "40 0 * * *",       # ogni notte alle 00:40, dopo il ricalcolo scadenze
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — retention GDPR in SOLA LETTURA: conta documenti e candidati
        # oltre la conservazione e apre/risolve una Issue in monitoring. Non cancella:
        # la cancellazione resta il comando cleanup_expired_documents --apply.
        "name": "anagrafica_report_retention",
        "func": "anagrafica.tasks.run_report_retention",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 6 * * 1",       # ogni lunedi alle 06:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — reminder visite mediche scadute/in scadenza: digest ai
        # responsabili (card+badge nel frame HUB) + notifica in-app al dipendente.
        # Destinatari visite_reminder_emails con fallback amministrativo da verificare.
        "name": "visite_expiry_reminders",
        "func": "anagrafica.tasks.run_visite_expiry_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "45 7 * * *",       # ogni mattina alle 07:45
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — contratti a termine + periodi di prova in scadenza.
        # Destinatari contratti_reminder_emails con fallback amministrativo da verificare.
        "name": "contratti_expiry_reminders",
        "func": "anagrafica.tasks.run_contratti_expiry_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "50 7 * * *",       # ogni mattina alle 07:50
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA — digest trimestrale formazione (abilitazioni in scadenza) per
        # audit ISO. NB destinatari placeholder (admin/superuser) finché non si
        # configura una fonte HR/RSPP dedicata.
        "name": "formazione_audit_digest",
        "func": "anagrafica.tasks.run_formazione_audit_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 8 1 1,4,7,10 *", # 1° di gen/apr/lug/ott alle 08:00 (trimestrale)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA — digest mensile visite mediche in scadenza (HR). In parte
        # ridondante con visite_expiry_reminders: disattivabile dalla Centrale di
        # comando. Destinatari placeholder (admin/superuser).
        "name": "visite_mediche_digest",
        "func": "anagrafica.tasks.run_visite_mediche_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 8 1 * *",        # il 1° del mese alle 08:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CORE — archivio automatico notifiche in-app: archivia le non lette e le
        # lette oltre soglia, elimina le archiviate oltre la conservazione.
        # Soglie in SiteConfig (Admin portale → Gestione notifiche); 0 = mai.
        "name": "notifiche_archivio",
        "func": "core.tasks.run_notifiche_archivio",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 2 * * *",       # ogni notte alle 02:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CORE — GDPR: conservazione degli archivi tecnici (monitoring, feedback
        # chat, link e posta di approvazione, posta e AI del SOC, axes, sessioni).
        # Termini in SiteConfig gdpr_ret_<regola>_giorni (core/gdpr_retention.py).
        "name": "gdpr_retention",
        "func": "core.tasks.run_gdpr_retention",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 3 * * *",       # ogni notte alle 03:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CORE — Centro report: elimina dal registro emissioni le righe oltre la
        # conservazione (SiteConfig, Admin portale → Centro report; 0 = mai).
        "name": "report_emissioni_pulizia",
        "func": "core.tasks.run_report_emissioni_pulizia",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "45 2 * * *",       # ogni notte alle 02:45
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CORE — Centro report: genera e invia per mail i report pianificati
        # arrivati a scadenza (Admin portale → Centro report → Pianificazioni).
        # Fail-safe: senza pianificazioni attive non fa nulla.
        "name": "report_pianificati",
        "func": "core.tasks.run_report_pianificati",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "5 * * * *",        # ogni ora al minuto 5
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CORE — digest mattutino caporeparto: DPI in attesa + incidenti aperti del
        # reparto (fonte capi = Reparto.caporeparto_legacy_id; email = email_notifica).
        # Fail-safe: no-op senza capi/voci; assenze (SharePoint dismesso) e ticket
        # (nessun legame reparto) esclusi per design.
        "name": "caporeparto_morning_digest",
        "func": "core.tasks.run_caporeparto_morning_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 7 * * 1-5",      # ogni mattina feriale alle 07:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA — reminder scadenze formazione OBBLIGATORIA (corsi scaduti/in
        # scadenza dalla cache TrainingDeadline): digest HR + notifica al dipendente.
        # Complementare a formazione_audit_digest (trimestrale): qui è il reminder
        # operativo. Destinatari training_reminder_emails con fallback amministrativo da verificare.
        "name": "training_expiry_reminders",
        "func": "anagrafica.tasks.run_training_expiry_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "5 8 * * *",        # ogni mattina alle 08:05
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA — promemoria micro-corsi e-learning non completati: digest HR +
        # notifica in-app al discente. Le notifiche in-app partono comunque; il
        # digest è fail-safe (no-op senza SiteConfig elearning_reminder_emails).
        "name": "elearning_reminders",
        "func": "anagrafica.tasks.run_elearning_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "55 7 * * *",       # ogni mattina alle 07:55
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSETS — genera le OCCORRENZE di manutenzione dovute dai piani attivi.
        # Non apre più un OdL per ogni asset: raggruppare le manutenzioni in ordini di
        # lavoro è una decisione umana (pagina "Da fare"). Idempotente: la terna
        # (piano, asset, scadenza) è unica a DB. Gira PRIMA del promemoria manutenzione
        # così le nuove scadenze rientrano nella mail del giorno.
        "name": "assets_generate_occurrences",
        "func": "assets.tasks.run_generate_maintenance_occurrences",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 6 * * *",        # ogni mattina alle 06:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSETS — promemoria scadenze manutenzione / verifiche periodiche + OdL
        # scaduti. Destinatari SiteConfig assets_reminder_emails con FALLBACK su
        # ADMINS/superuser (non no-op puro): disattivabile dalla Centrale di comando.
        "name": "assets_maintenance_reminders",
        "func": "assets.tasks.run_maintenance_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 7 * * *",        # ogni mattina alle 07:00 (dopo la generazione OdL)
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSETS — PART 145: scadenze entro 90 giorni (contratto, processi, requisiti,
        # tarature, certificazioni) a Qualità, destinatari MOD.128 mpq_msm_reminder_emails.
        # Nessuna scadenza = nessuna mail. Disattivabile dalla Centrale di comando.
        "name": "part145_scadenze",
        "func": "assets.tasks.run_part145_scadenze",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * 1",       # ogni lunedi alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSETS — avvisi del monitoraggio IT: dispositivi SNMP in errore o muti,
        # consumabili MFC sotto soglia. Digest a SiteConfig assets_it_monitoring_emails
        # (poi assets_reminder_emails, poi ADMINS/superuser) + notifica in app solo
        # per i problemi nuovi. Disattivabile dalla Centrale di comando.
        "name": "assets_it_monitoring_alerts",
        "func": "assets.tasks.run_it_monitoring_alerts",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 7 * * *",       # ogni mattina alle 07:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SOC — software installato sui PC collegati a Microsoft Defender for Endpoint nell'inventario
        # (CVE e impatti). Gira solo con «Leggi il software dei PC» acceso in /soc/impostazioni/.
        "name": "defender_software_sync",
        "func": "security.tasks.run_defender_software_task",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "20 6 * * *",       # ogni mattina alle 06:20
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SOC — CVE viste da Defender, accanto al calcolo del SOC nel pannello CVE. Gira solo con
        # «Confronta le CVE con Defender» acceso in /soc/impostazioni/.
        "name": "defender_vulnerabilita_sync",
        "func": "security.tasks.run_defender_vulnerabilita_task",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "25 6 * * *",       # ogni mattina alle 06:25
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SOC — WatchGuard Cloud (API): PC e protezione, software, patch mancanti. Ogni parte gira
        # solo con il suo interruttore in /soc/impostazioni/ e le credenziali API salvate.
        "name": "watchguard_api_sync",
        "func": "security.tasks.run_watchguard_api_task",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "10 6,13 * * *",    # alle 06:10 e alle 13:10
        "repeats": -1,
        # Software e patch di tutti i PC possono superare i 120 s del cluster; la riconsegna
        # della coda (retry 180 s) trova il giro in corso nel registro delle letture e non riparte.
        "kwargs": {"q_options": {"timeout": 600}},
    },
    {
        # SOC — pacchetto mensile di evidenze ISO/IEC 27001: il giorno 1 alle 06:30 genera il PDF del mese
        # prima (esito dei controlli dell'Annex A, CVE corrette, esposizioni scadute, incidenti con lezioni
        # apprese), lo archivia con l'impronta SHA-256 nell'audit e, se acceso in /soc/impostazioni/,
        # lo copia nella cartella SharePoint dell'audit. Si vede in Letture automatiche e nel Battito del SOC.
        "name": "security_pacchetto_iso",
        "func": "security.tasks.pacchetto_iso_task",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 6 1 * *",       # il 1° del mese alle 06:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SOC — librerie Python del portale contro il database pubblico OSV (lo stesso di pip-audit):
        # vulnerabilità nuove e risolte in Dispositivi › Librerie del portale, alert per libreria e versione.
        # Spegnibile da /soc/impostazioni/; si vede in Letture automatiche e nel Battito del SOC.
        "name": "security_dipendenze_portale",
        "func": "security.tasks.dipendenze_portale_task",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "50 6 * * *",       # ogni mattina alle 06:50
        "repeats": -1,
        "kwargs": {"q_options": {"timeout": 600}},
    },
    {
        # CONTATORI — tabella MAC degli switch «Rete» (sola lettura): a quale porta è collegato ogni PC.
        "name": "contatori_tabella_mac",
        "func": "contatori.tasks.run_tabella_mac",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 5 * * *",       # ogni notte alle 05:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Microsoft 365 — abbonamenti (posti, stato, rinnovo) nel modulo Licenze software.
        # Serve il permesso Graph Organization.Read.All (+ LicenseAssignment.Read.All per le date).
        "name": "m365_licenze_sync",
        "func": "assets.tasks.run_m365_licenze_sync",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "40 6 * * *",       # ogni mattina alle 06:40
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Officina — stato reale delle CNC dagli agent MTConnect (solo lettura, rete interna):
        # mappa officina, allarmi, ore e pezzi sui contatori. Senza collegamenti non fa nulla.
        "name": "mtconnect_poll",
        "func": "assets.tasks.run_mtconnect_poll",
        "schedule_type": "I",
        "minutes": 2,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Asset IT — indirizzi IP dal DHCP e dal DNS di Windows Server (PowerShell locale,
        # moduli RSAT). Senza RETE_DHCP_SERVERS / RETE_DNS_SERVER nel .env non fa nulla.
        "name": "rete_windows_sync",
        "func": "assets.tasks.run_rete_windows_sync",
        "schedule_type": "I",
        "minutes": 60,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Registro accessi (log dei server): controllo del raccoglitore, fonti mute, sigilli
        # giornalieri dell'archivio, copie, conservazione, invio al SOC. Spento = non fa nulla.
        "name": "registro_log_ciclo",
        "func": "registro_log.tasks.run_ciclo",
        "schedule_type": "I",
        "minutes": 5,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Registro accessi — account di Active Directory via LDAP (sola lettura).
        "name": "registro_log_ad",
        "func": "registro_log.tasks.run_ad_sync",
        "schedule_type": "I",
        "minutes": 360,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Registro accessi — stato di ESXi/vCenter e iLO/iDRAC (sola lettura, solo ultima fotografia).
        "name": "registro_log_infra",
        "func": "registro_log.tasks.run_infra",
        "schedule_type": "I",
        "minutes": 60,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Microsoft Intune — dispositivi gestiti (conformità, cifratura, ultima sync):
        # prima degli avvisi IT delle 07:15, che ne riportano i problemi.
        # Serve il permesso Graph DeviceManagementManagedDevices.Read.All.
        "name": "intune_sync",
        "func": "assets.tasks.run_intune_sync",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "45 6 * * *",       # ogni mattina alle 06:45
        "repeats": -1,
        "kwargs": {},
    },
    {
        # DPI — promemoria DPI scaduti / in scadenza (+ notifica in-app). Destinatari
        # da impostazioni DPI/SiteConfig con fallback ADMINS/superuser (non no-op
        # puro): disattivabile dalla Centrale di comando.
        "name": "dpi_expiry_reminders",
        "func": "dpi.tasks.run_dpi_expiry_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "10 7 * * *",       # ogni mattina alle 07:10
        "repeats": -1,
        "kwargs": {},
    },
    {
        # DPI — mail e PDF delle consegne dal banco rimasti in sospeso perche' il browser
        # si e' chiuso nei secondi dell'annullo. Senza lavoro non fa nulla.
        "name": "dpi_avvisi_consegna",
        "func": "dpi.tasks.run_dpi_avvisi_consegna",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "*/5 * * * *",
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CORE — sigillo mensile dell'audit: sigilla i mesi conclusi (catena di hash),
        # verifica tutta la catena (mail agli ADMINS se rotta) ed esporta su SharePoint
        # se la cartella è configurata (SiteConfig audit_export_sp_*). Il giorno 1 e il 2
        # (riprova dell'export se il primo giro non è riuscito).
        "name": "audit_sigilli",
        "func": "core.tasks.run_audit_sigilli",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "40 3 1,2 * *",     # giorni 1 e 2 del mese alle 03:40
        "repeats": -1,
        "kwargs": {},
    },
    {
        # Scadenzario → calendario Outlook personale («Scadenze NOVICROM HUB») di chi l'ha
        # scelto in Impostazioni notifiche. Graph Calendars.ReadWrite (applicazione).
        "name": "scadenze_outlook_sync",
        "func": "dashboard.tasks.run_scadenze_outlook",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 6 * * *",       # ogni mattina alle 06:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # DASHBOARD — riepilogo personale dello Scadenzario globale per mail, solo
        # agli utenti che l'hanno attivato in Notifiche → Impostazioni (no-op
        # altrimenti); giorni feriali, una mail al giorno al massimo.
        "name": "scadenze_digest_personale",
        "func": "dashboard.tasks.run_scadenze_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * 1-5",     # lun-ven alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SCADENZARIO — avvisi delle scadenze generiche alle email delle attività
        # (preavviso, ripetizione ogni N giorni, anche dopo la scadenza se la categoria lo vuole).
        "name": "scadenzario_avvisi_attivita",
        "func": "scadenzario.tasks.run_avvisi_attivita",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 7 * * *",       # ogni giorno alle 07:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SCADENZARIO — fotografia giornaliera dei numeri per fonte (vista «Andamento»).
        "name": "scadenzario_foto_giornaliera",
        "func": "scadenzario.tasks.run_foto_giornaliera",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "45 6 * * *",       # ogni giorno alle 06:45
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SCADENZARIO — riepilogo mensile per categoria alle email della categoria.
        "name": "scadenzario_riepilogo_mensile",
        "func": "scadenzario.tasks.run_riepiloghi_categorie",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 8 1 * *",        # il 1° del mese alle 08:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CHECKLIST OPERATIVA — promemoria in-app ai responsabili con task non
        # confermati per le chiusure aziendali in arrivo (soglie 7/3/1/0 giorni).
        "name": "checklist_chiusura_reminders",
        "func": "checklist_operativa.tasks.run_checklist_chiusura_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 7 * * *",       # ogni mattina alle 07:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # RENTRI — alert registri non confermati/inviati oltre soglia, agli admin.
        # Da attivare dove il modulo RENTRI è operativo.
        "name": "rentri_scadenze_check",
        "func": "rentri.tasks.run_rentri_scadenze_check",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "20 7 * * *",       # ogni mattina alle 07:20
        "repeats": -1,
        "kwargs": {},
    },
    {
        # RENTRI — promemoria in-app: scarico originale senza scarico effettivo
        # oltre soglia (SiteConfig rentri_promemoria_m_giorni, di serie 60).
        "name": "rentri_promemoria_scarico_effettivo",
        "func": "rentri.tasks.run_rentri_promemoria_scarico_effettivo",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "25 7 * * *",       # ogni mattina alle 07:25
        "repeats": -1,
        "kwargs": {},
    },
    {
        # TICKETS — promemoria SLA scaduto all'ASSEGNATARIO (complementare a
        # tickets_escalation, che copre gli urgenti non assegnati).
        "name": "tickets_sla_reminders",
        "func": "tickets.tasks.run_sla_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 8 * * *",       # ogni mattina alle 08:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # TICKETS — digest mattutino "i miei ticket di oggi" per assegnatario
        # (aperti in scadenza oggi o già scaduti).
        "name": "tickets_daily_digest",
        "func": "tickets.tasks.run_ticket_daily_digest",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "40 7 * * *",       # ogni mattina alle 07:40
        "repeats": -1,
        "kwargs": {},
    },
    {
        # TICKETS — ticket MAN <-> lista SharePoint «Ticket» (CNManutenzioni):
        # invia la coda delle modifiche locali e legge solo gli elementi cambiati
        # (delta query). No-op finche' l'interruttore in Impostazioni e' spento.
        "name": "tickets_man_sharepoint_sync",
        "func": "tickets.tasks.run_ticket_man_sharepoint_sync",
        "schedule_type": "I",   # Schedule.MINUTES
        "minutes": 5,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSENZE — convivenza con la lista SharePoint: invia la coda delle
        # modifiche locali e legge da SharePoint solo gli elementi cambiati
        # (delta query). No-op se Graph non e' configurato.
        "name": "assenze_sharepoint_sync",
        "func": "assenze.tasks.run_assenze_sharepoint_sync",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 5,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSENZE — le assenze approvate nel calendario Outlook del capo (Graph,
        # Calendars.ReadWrite). No-op finché l'interruttore in Area HR è spento.
        "name": "assenze_outlook_sync",
        "func": "assenze.tasks.run_assenze_outlook_sync",
        "schedule_type": "I",       # Schedule.MINUTES
        "minutes": 10,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSENZE — promemoria ai capi per le richieste ferme «In attesa» (una
        # mail per capo). Soglie e interruttore in Assenze → HR → Impostazioni.
        "name": "assenze_solleciti",
        "func": "assenze.tasks.run_assenze_solleciti",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 8 * * 1-5",     # ogni mattina feriale alle 08:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ASSENZE — avviso ad assenza@ per le malattie senza certificato medico
        # dopo N giorni (una mail con l'elenco, ogni malattia una volta sola).
        # Soglia e interruttore in Assenze → HR → Impostazioni.
        "name": "assenze_certificato_avviso",
        "func": "assenze.tasks.run_assenze_certificato_avviso",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 8 * * 1-5",     # ogni mattina feriale alle 08:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # SUGGESTION CORNER — solleciti DO/CHECK + escalation (§3)
        "name": "suggestion_corner_reminders",
        "func": "suggestion_corner.tasks.run_suggestion_corner_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 8 * * *",        # ogni mattina alle 08:00
        "repeats": -1,
        "kwargs": {},
    },
    {
        # AUDIT INTERNI — solleciti CAR in ritardo (analisi 1 mese, chiusura 3 mesi o proroga,
        # verifica di efficacia programmata) e una sola escalation a RSGI oltre soglia.
        "name": "sistema_gestione_car_solleciti",
        "func": "sistema_gestione.tasks.run_car_solleciti",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "15 7 * * 1-5",     # giorni feriali alle 07:15
        "repeats": -1,
        "kwargs": {},
    },
    {
        # CERTIFICAZIONI E AUDIT ESTERNI — certificati scaduti/in scadenza (90 gg), sorveglianze
        # entro 30 giorni, piani azioni da inviare all'ente: un riepilogo settimanale a RSGI.
        "name": "sistema_gestione_scadenze_esterni",
        "func": "sistema_gestione.tasks.run_scadenze_audit_esterni",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * 1",       # lunedì alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # PRESENTI IN AZIENDA — PDF dei presenti su SharePoint (CN-PRESENZE.pdf), al posto dello
        # script ReportPresenze del diskstation. No-op se disattivato nelle Impostazioni del modulo.
        "name": "presenti_pubblica_pdf",
        "func": "presenti.tasks.run_pubblica_pdf_presenti",
        "schedule_type": "I",
        "minutes": 30,
        "repeats": -1,
        "kwargs": {},
    },
    {
        # PRESENTI IN AZIENDA — uscite non timbrate degli ultimi 3 giorni: notifica e mail al capo.
        "name": "presenti_avvisi_uscite",
        "func": "presenti.tasks.run_avvisi_uscite_mancanti",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 7 * * 1-6",     # lunedì-sabato alle 07:30
        "repeats": -1,
        "kwargs": {},
    },
    {
        # FORNITORI — ditta entrata dal GuestPortal con documenti di sicurezza non in regola:
        # notifica in-app a RSPP/ASPP (mai mail), una volta per visita.
        "name": "fornitori_avvisi_ingressi_non_in_regola",
        "func": "fornitori.tasks.run_avvisi_ingressi_non_in_regola",
        "schedule_type": "I", "minutes": 10, "repeats": -1, "kwargs": {},
    },
    {
        # RECEPTION — mail al referente quando arriva il visitatore. Non fa niente finché RECEPTION_NATIVA è spenta.
        "name": "reception_avvisi_referenti",
        "func": "reception.tasks.run_avvisi_referenti",
        "schedule_type": "I", "minutes": 1, "repeats": -1, "kwargs": {},
    },
    {
        # RECEPTION — ogni notte: pre-registrazioni passate e dati oltre i 12 mesi dell'informativa.
        "name": "reception_pulizia",
        "func": "reception.tasks.run_pulizia",
        "schedule_type": "C", "cron": "40 3 * * *", "repeats": -1, "kwargs": {},
    },
    {
        # FORNITORI — a fine giornata, chi risulta ancora dentro: notifica ai ruoli configurati (per ora IT).
        "name": "fornitori_avvisi_usciti_dimenticati",
        "func": "fornitori.tasks.run_avvisi_usciti_dimenticati",
        "schedule_type": "C", "cron": "0 19 * * 1-5", "repeats": -1, "kwargs": {},
    },
    {
        # FORNITORI — ditta attesa (manutenzione, OdL o ticket aperti) che non sarà in regola
        # con i documenti di sicurezza: notifica in-app a RSPP/ASPP (mai mail), prima che entri.
        "name": "fornitori_avvisi_ditte_attese",
        "func": "fornitori.tasks.run_avvisi_ditte_attese",
        "schedule_type": "C", "cron": "10 7 * * 1-5", "repeats": -1, "kwargs": {},
    },
]



# Schedule ritirati: restano elencati qui perché ``setup_q_schedules`` li rimuova dal
# DB. Togliere una voce da SCHEDULES non basta — il record django-q sopravvive al
# deploy e il job continuerebbe a girare, invisibile alla Centrale di comando.
RETIRED_SCHEDULE_NAMES: list[str] = [
    # Sostituito da "assets_generate_occurrences": generava un OdL per asset dalle
    # MaintenanceRule. Se restasse attivo produrrebbe una seconda fonte di scadenze.
    "assets_generate_workorders",
]


# Raccoglitore «Digest e promemoria» della pagina Task pianificati: i lavori che mandano
# riepiloghi o solleciti a persone, sospendibili fino a una data (ScheduleControl.sospeso_fino).
# Restano fuori i job che cambiano lo stato dei dati insieme alla mail (es. pr_assignment_lifecycle
# marca «Scaduta», anomalie/tickets_escalation aggiornano i promemoria in dashboard) e gli avvisi
# di sicurezza sulle ditte esterne (fornitori_avvisi_*). Valore = a chi arriva.
DIGEST_E_PROMEMORIA: dict[str, str] = {
    "system_digest": "Amministratori del monitoring",
    "caporeparto_morning_digest": "Capireparto (email di notifica)",
    "scadenze_digest_personale": "Chi l'ha attivato in Notifiche → Impostazioni",
    "report_scadenze_settimanale": "Destinatari delle Impostazioni automazioni",
    "assets_maintenance_reminders": "Destinatari manutenzioni (o amministratori)",
    "assets_it_monitoring_alerts": "Destinatari monitoraggio IT (o amministratori)",
    "part145_scadenze": "Qualità (destinatari MOD.128)",
    "dpi_expiry_reminders": "Destinatari DPI (o amministratori)",
    "visite_expiry_reminders": "Responsabili visite + notifica al dipendente",
    "visite_mediche_digest": "HR (amministratori)",
    "contratti_expiry_reminders": "Destinatari contratti",
    "training_expiry_reminders": "HR + notifica al dipendente",
    "elearning_reminders": "HR + notifica al discente",
    "formazione_session_reminders": "Iscritti alle sessioni",
    "formazione_audit_digest": "HR / amministratori",
    "idoneita_digest": "RSPP, medico competente, HR",
    "cambio_mansione_digest": "Destinatari cambio mansione",
    "tickets_daily_digest": "Assegnatari dei ticket",
    "tickets_sla_reminders": "Assegnatari con SLA scaduto",
    "tasks_send_reminders": "Responsabili delle attività KICK-OFF",
    "tasks_meetings_digest": "Partecipanti agli incontri",
    "gestione_specifiche_reminder": "Incaricati delle specifiche",
    "gestione_specifiche_escalation": "Approvatore e DM",
    "gestione_specifiche_verifica_periodica": "Incaricati delle specifiche",
    "gestione_specifiche_sync_cartelle": "Incaricati delle specifiche (specifiche nuove dalla cartella)",
    "scadenzario_avvisi_attivita": "Email delle attività",
    "scadenzario_riepilogo_mensile": "Email delle categorie",
    "checklist_chiusura_reminders": "Responsabili della checklist",
    "rentri_scadenze_check": "Amministratori",
    "rentri_promemoria_scarico_effettivo": "Utenti RENTRI (notifica in-app)",
    "assenze_solleciti": "Capi con richieste in attesa",
    "assenze_certificato_avviso": "Casella assenze",
    "suggestion_corner_reminders": "Responsabili DO/CHECK",
    "sistema_gestione_car_solleciti": "Responsabili CAR, poi RSGI",
    "sistema_gestione_scadenze_esterni": "RSGI",
    "presenti_avvisi_uscite": "Capi (uscite non timbrate)",
}

# Oggetto delle mail dei digest, come lo compongono i comandi (N = numero, ‹…› = testo variabile).
# Il primo è quello principale, gli altri sono le varianti; tupla vuota = solo notifica in-app.
# Un oggetto personalizzato da «Configura mail» (ScheduledMailText) prevale: vedi schedule_rows.
# Se cambi l'oggetto in un comando, aggiornalo anche qui.
DIGEST_OGGETTO: dict[str, tuple[str, ...]] = {
    "system_digest": ("[Portale] Digest stato sistema — tutto ok", "[Portale] Digest stato sistema — attenzioni presenti"),
    "caporeparto_morning_digest": ("[Caporeparto] Riepilogo ‹reparti› - gg-mm-aaaa",),
    "scadenze_digest_personale": ("[SCADENZE] N scadute, N entro N giorni - gg-mm-aaaa",),
    "report_scadenze_settimanale": (
        "[Scadenze] Visite mediche in scadenza (N)",
        "[Scadenze] Contratti e periodi di prova in scadenza (N)",
        "[Scadenze] Qualifiche e abilitazioni in scadenza (N)",
    ),
    "assets_maintenance_reminders": ("[Manutenzione] N SCADUTE + N non valutabili + N senza rapporto + N licenze/contratti — gg-mm-aaaa",),
    "assets_it_monitoring_alerts": ("[Monitoraggio IT] N problemi aperti — gg-mm-aaaa",),
    "part145_scadenze": ("[PART 145] Scadenze entro N giorni (N)",),
    "dpi_expiry_reminders": (
        "[DPI] N scaduti + N in scadenza - gg-mm-aaaa",
        "[DPI] DPI scaduti o in scadenza nella tua squadra (N) - gg-mm-aaaa",
    ),
    "visite_expiry_reminders": ("[VISITE MEDICHE] N scadute + N in scadenza - gg-mm-aaaa",),
    "visite_mediche_digest": ("[Visite mediche] N in scadenza entro Ngg - gg-mm-aaaa",),
    "contratti_expiry_reminders": ("[CONTRATTI] N scaduti + N in scadenza + N fine prova - gg-mm-aaaa",),
    "training_expiry_reminders": ("[FORMAZIONE] N scaduti + N in scadenza - gg-mm-aaaa",),
    "elearning_reminders": ("[E-LEARNING] N corsi da completare - gg-mm-aaaa",),
    "formazione_session_reminders": ("Promemoria corso: ‹corso› il gg-mm-aaaa",),
    "formazione_audit_digest": ("[Formazione ISO] N abilitazioni in scadenza entro Ngg - gg-mm-aaaa",),
    "idoneita_digest": ("[Idoneità] N non idonei, N con riserve - gg-mm-aaaa",),
    "cambio_mansione_digest": (
        "[Cambio mansione] N persone da verificare, N adempimenti in ritardo",
        "[Cambio mansione] ‹persona›: N adempimenti da completare",
    ),
    "tickets_daily_digest": ("[Ticket] N da gestire oggi - gg-mm-aaaa",),
    "tickets_sla_reminders": ("[SLA SCADUTO] Ticket ‹numero›",),
    "tasks_send_reminders": (),
    "tasks_meetings_digest": (
        "Promemoria KICK-OFF: prossimo incontro e scadenze",
        "Promemoria incontro ‹domani› — ‹incontro›",
        "Scadenze KICK-OFF (N)",
    ),
    "gestione_specifiche_reminder": ("Promemoria MOD.133 — ‹codice›",),
    "gestione_specifiche_escalation": ("ESCALATION MOD.133 — ‹codice›",),
    "gestione_specifiche_verifica_periodica": ("Verifica periodica — ‹codice›",),
    "gestione_specifiche_sync_cartelle": ("Nuova specifica ‹codice› da prendere in carico",),
    "scadenzario_avvisi_attivita": ("[SCADENZA] ‹attività› - gg/mm/aaaa",),
    "scadenzario_riepilogo_mensile": ("[RIEPILOGO SCADENZE] ‹categoria› - prossimi N giorni",),
    "checklist_chiusura_reminders": ("Checklist chiusura «‹chiusura›»: N da confermare",),
    "rentri_scadenze_check": ("[RENTRI] N registrazioni in scadenza — soglia N giorni",),
    "rentri_promemoria_scarico_effettivo": (),
    "assenze_solleciti": ("N richieste di assenza da approvare", "Richiesta di assenza da approvare: ‹DIPENDENTE›"),
    "assenze_certificato_avviso": ("Certificato medico non arrivato: N malattie",),
    "suggestion_corner_reminders": (
        "[Suggestion Corner] Sollecito ‹fase› — SC#N",
        "[Suggestion Corner] ESCALATION ‹fase› — SC#N",
    ),
    "sistema_gestione_car_solleciti": ("CAR in ritardo oltre N giorni: N",),
    "sistema_gestione_scadenze_esterni": ("Certificazioni e audit esterni: N scadenze",),
    "presenti_avvisi_uscite": (
        "[NOVICROM HUB] N uscite non timbrate nella tua squadra",
        "[NOVICROM HUB] Uscita non timbrata: ‹Cognome Nome› il gg/mm/aaaa",
    ),
}

# Pausa massima a tempo: oltre si usa «Disattiva», che è una scelta esplicita e durevole.
SOSPENSIONE_MAX_GIORNI = 60


def orario_cron(spec: dict) -> str:
    """«HH:MM» di un cron giornaliero/settimanale, per ordinare i digest; "" se non c'è."""
    parts = str(spec.get("cron") or "").split()
    if spec.get("schedule_type") != "C" or len(parts) != 5:
        return ""
    try:
        return f"{int(parts[1]):02d}:{int(parts[0]):02d}"
    except ValueError:
        return ""


def sospeso_fino(name: str, oggi=None):
    """Data fino a cui lo schedule è sospeso (compresa), o None se non lo è oggi."""
    from django.utils import timezone

    try:
        from monitoring.models import ScheduleControl

        fino = ScheduleControl.objects.filter(name=name).values_list("sospeso_fino", flat=True).first()
    except Exception:
        return None
    oggi = oggi or timezone.localdate()
    return fino if fino and fino >= oggi else None


def spec_by_name(name: str):
    """Spec statico di uno schedule per nome (None se non esiste)."""
    return next((s for s in SCHEDULES if s.get("name") == name), None)


# ── Presentazione (riusata da genera_doc_automazioni e dalla pagina admin) ─────

_GIORNI = {"0": "dom", "1": "lun", "2": "mar", "3": "mer", "4": "gio", "5": "ven", "6": "sab", "7": "dom"}
_MESI = {"1": "gen", "2": "feb", "3": "mar", "4": "apr", "5": "mag", "6": "giu",
         "7": "lug", "8": "ago", "9": "set", "10": "ott", "11": "nov", "12": "dic"}


def _describe_cron(cron: str) -> str:
    parts = str(cron or "").split()
    if len(parts) != 5:
        return f"cron `{cron}`"
    minute, hour, dom, month, dow = parts
    if hour == "*" and minute == "*":
        quando = "in continuazione"
    elif hour == "*" and minute.startswith("*/") and minute[2:].isdigit():
        quando = f"ogni {int(minute[2:])} minuti"
    elif hour == "*":
        quando = f"ogni ora al minuto {minute}"
    else:
        try:
            quando = f"alle {int(hour):02d}:{int(minute):02d}"
        except ValueError:
            quando = f"({minute} {hour})"
    freq = "ogni giorno"
    if dow != "*":
        if "-" in dow:
            a, b = dow.split("-", 1)
            freq = f"da {_GIORNI.get(a, a)} a {_GIORNI.get(b, b)}"
        else:
            freq = "ogni " + ", ".join(_GIORNI.get(g, g) for g in dow.split(","))
    elif dom != "*":
        mesi = (" di " + "/".join(_MESI.get(m, m) for m in month.split(","))) if month != "*" else ""
        freq = f"il giorno {dom}{mesi} del mese"
    elif month != "*":
        freq = "nei mesi " + "/".join(_MESI.get(m, m) for m in month.split(","))
    return f"{freq}, {quando}"


def describe_cadence(spec: dict) -> str:
    """Cadenza di uno schedule in linguaggio naturale (italiano)."""
    if spec.get("schedule_type") == "C":
        return _describe_cron(spec.get("cron", ""))
    minutes = spec.get("minutes")
    return "ogni minuto" if minutes == 1 else f"ogni {minutes} minuti"


def schedule_descriptions() -> dict:
    """Mappa nome-schedule → spiegazione, estratta dai commenti di questo file.

    I commenti stanno tra ``{`` (apertura dict) e la riga ``"name":``.
    """
    import re
    from pathlib import Path

    commenti: dict[str, str] = {}
    buffer: list[str] = []
    try:
        righe = Path(__file__).read_text(encoding="utf-8").splitlines()
    except Exception:
        return commenti
    for riga in righe:
        s = riga.strip()
        if s.startswith("{"):
            buffer = []
        elif s.startswith("#"):
            buffer.append(s.lstrip("#").strip())
        else:
            m = re.match(r'"name"\s*:\s*"([^"]+)"', s)
            if m:
                if buffer:
                    commenti[m.group(1)] = " ".join(x for x in buffer if x)
                buffer = []
    return commenti


def _oggetto_riga(name: str, personalizzato: str = "") -> dict:
    """Oggetto mail da mostrare: quello personalizzato, se c'è, altrimenti il primo di serie."""
    serie = DIGEST_OGGETTO.get(name, ())
    if personalizzato:
        return {"oggetto": personalizzato, "oggetto_varianti": (), "oggetto_personalizzato": True}
    return {"oggetto": serie[0] if serie else "", "oggetto_varianti": serie[1:], "oggetto_personalizzato": False}


def schedule_rows() -> list[dict]:
    """Righe pronte per la UI: statico (SCHEDULES) + stato runtime (django_q) + on/off.

    Ogni riga: name, func, module, cadence (naturale), description, enabled, registered,
    next_run. Fail-safe: se django_q/ScheduleControl non sono disponibili, degrada.
    """
    live: dict = {}
    controls: dict = {}
    try:
        from django_q.models import Schedule

        live = {s.name: s for s in Schedule.objects.all()}
    except Exception:
        live = {}
    try:
        from monitoring.models import ScheduleControl

        controls = {c.name: c.enabled for c in ScheduleControl.objects.all()}
        from django.utils import timezone

        oggi = timezone.localdate()
        sospesi = dict(ScheduleControl.objects.filter(sospeso_fino__gte=oggi)
                       .values_list("name", "sospeso_fino"))
    except Exception:
        controls = {}
        sospesi = {}

    # Ultimo esito per func (ultimo Task django-q completato).
    last_runs: dict = {}
    try:
        from django_q.models import Task

        funcs = [s["func"] for s in SCHEDULES]
        for t in (Task.objects.filter(func__in=funcs)
                  .order_by("func", "-stopped").values("func", "stopped", "success")):
            last_runs.setdefault(t["func"], (t["stopped"], t["success"]))
    except Exception:
        last_runs = {}

    # Oggetti personalizzati da «Configura mail»: sostituiscono quello di serie.
    try:
        from .models import ScheduledMailText

        oggetti_custom = {t: s.strip() for t, s in ScheduledMailText.objects.values_list("task_name", "subject")
                          if (s or "").strip()}
    except Exception:
        oggetti_custom = {}

    from .models import ManagedFlow
    bindings = {b.code: b for b in ManagedFlow.objects.select_related("rule").all()}
    descr = schedule_descriptions()
    rows = []
    for spec in SCHEDULES:
        name = spec["name"]
        sch = live.get(name)
        last = last_runs.get(spec["func"])
        binding = bindings.get(name)
        effective = dict(spec)
        if binding:
            effective.update(schedule_type=binding.schedule_type, minutes=binding.minutes, cron=binding.cron)
            if binding.rule.last_run_at:
                latest = binding.rule.run_logs.order_by("-started_at").first()
                last = (binding.rule.last_run_at, latest.status == "success" if latest else None)
        rows.append({
            "rule_id": binding.rule_id if binding else None,
            "name": name,
            "func": spec["func"],
            "module": str(spec["func"]).split(".", 1)[0],
            "cadence": describe_cadence(effective),
            "description": descr.get(name, ""),
            "enabled": (binding.rule.is_active and not binding.rule.is_draft) if binding else controls.get(name, True),
            "registered": sch is not None,
            "next_run": getattr(sch, "next_run", None),
            "last_run": last[0] if last else None,
            "last_ok": last[1] if last else None,
            "digest": name in DIGEST_E_PROMEMORIA,
            "a_chi": DIGEST_E_PROMEMORIA.get(name, ""),
            **_oggetto_riga(name, oggetti_custom.get(name, "")),
            "orario": orario_cron(effective),
            "sospeso_fino": sospesi.get(name),
        })
    return rows


def _schedule_defaults(spec: dict) -> dict:
    import json

    from django.utils import timezone

    defaults = {
        "func": spec["func"],
        "schedule_type": spec["schedule_type"],
        "repeats": spec.get("repeats", -1),
        "kwargs": json.dumps(spec.get("kwargs") or {}),
    }
    if spec.get("schedule_type") == "C":
        defaults["cron"] = spec["cron"]
        defaults["minutes"] = None
    else:
        # Solo MINUTES ("I") ha bisogno dei minuti: HOURLY/DAILY no. Con spec["minutes"] una spec oraria
        # senza il campo faceva cadere setup_q_schedules a metà (gli schedule successivi non registrati).
        defaults["minutes"] = spec.get("minutes")
        # riallinea il next_run a "ora" così riparte subito dopo la (re)registrazione
        defaults["next_run"] = timezone.now()
    return defaults


def register_schedule(spec: dict):
    """Crea/aggiorna lo Schedule django-q allo stato del codice. Ritorna (obj, created)."""
    import json

    from django_q.models import Schedule

    from .models import ManagedFlow
    from django.utils import timezone
    binding = ManagedFlow.objects.select_related("rule").filter(code=spec["name"], kind="schedule").first()
    defaults = _schedule_defaults(spec)
    if binding:
        if not binding.rule.is_active or binding.rule.is_draft:
            delete_schedule(binding.code)
            return None, False
        # Il timeout dedicato (q_options) resta sullo Schedule anche quando passa dal flusso gestito.
        q_options = (spec.get("kwargs") or {}).get("q_options")
        defaults.update(func="automazioni.managed_flows.run_managed_flow", args=repr(binding.code),
                        kwargs=json.dumps({"q_options": q_options} if q_options else {}),
                        schedule_type=binding.schedule_type, minutes=binding.minutes if binding.schedule_type == "I" else None,
                        cron=binding.cron if binding.schedule_type == "C" else None)
    # Preserve next_run on ordinary deploy; compute first cron in the portal timezone.
    current = Schedule.objects.filter(name=spec["name"]).first()
    changed = current and any(getattr(current, k) != defaults.get(k) for k in ("schedule_type", "minutes", "cron"))
    defaults.pop("next_run", None)
    if not current or changed:
        now = timezone.localtime()
        if defaults["schedule_type"] == "C":
            from croniter import croniter
            from datetime import datetime
            defaults["next_run"] = croniter(defaults["cron"], now).get_next(datetime)
        else:
            defaults["next_run"] = now
    return Schedule.objects.update_or_create(name=spec["name"], defaults=defaults)


def delete_schedule(name: str) -> int:
    """Elimina lo Schedule django-q (no-op se assente). Ritorna quanti eliminati."""
    from django_q.models import Schedule

    deleted, _ = Schedule.objects.filter(name=name).delete()
    return deleted


def disabled_schedule_names() -> set:
    """Nomi degli schedule disabilitati dalla centrale (monitoring.ScheduleControl).
    Lazy import per evitare cicli al load. Fail-safe: set vuoto se non disponibile."""
    try:
        from monitoring.models import ScheduleControl

        return set(ScheduleControl.objects.filter(enabled=False).values_list("name", flat=True))
    except Exception:
        return set()
