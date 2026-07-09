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
    {
        # ANAGRAFICA HR — reminder visite mediche scadute/in scadenza: digest ai
        # responsabili (card+badge nel frame HUB) + notifica in-app al dipendente.
        # Fail-safe: no-op senza SiteConfig visite_reminder_emails.
        "name": "visite_expiry_reminders",
        "func": "anagrafica.tasks.run_visite_expiry_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "45 7 * * *",       # ogni mattina alle 07:45
        "repeats": -1,
        "kwargs": {},
    },
    {
        # ANAGRAFICA HR — contratti a termine + periodi di prova in scadenza.
        # Fail-safe: no-op senza SiteConfig contratti_reminder_emails.
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
]


def spec_by_name(name: str):
    """Spec statico di uno schedule per nome (None se non esiste)."""
    return next((s for s in SCHEDULES if s.get("name") == name), None)


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
        defaults["minutes"] = spec["minutes"]
        # riallinea il next_run a "ora" così riparte subito dopo la (re)registrazione
        defaults["next_run"] = timezone.now()
    return defaults


def register_schedule(spec: dict):
    """Crea/aggiorna lo Schedule django-q allo stato del codice. Ritorna (obj, created)."""
    from django_q.models import Schedule

    return Schedule.objects.update_or_create(name=spec["name"], defaults=_schedule_defaults(spec))


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
