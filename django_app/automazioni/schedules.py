"""
Definizione dei task periodici django-q2 per il modulo automazioni.

Importato da setup_q_schedules per la registrazione idempotente.
Non avviare task qui: usare il management command setup_q_schedules.
"""
from __future__ import annotations

SCHEDULES: list[dict] = [
    {
        "name": "automation_queue",
        "func": "automazioni.tasks.run_automation_queue",
        "schedule_type": "I",   # Schedule.MINUTES (django-q2 non supporta SECONDS)
        "minutes": 1,           # ogni minuto
        "repeats": -1,
        "kwargs": {"limit": 50},
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
        "kwargs": {},
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
        # GESTIONE SPECIFICHE — verifica periodica 6 mesi (ricorrente da data_verifica).
        "name": "gestione_specifiche_verifica_periodica",
        "func": "gestione_specifiche.tasks.run_specifiche_verifica_periodica",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 6 * * *",       # ogni mattina alle 06:30
        "repeats": -1,
        "kwargs": {},
    },
]
