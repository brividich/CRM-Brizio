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
        # KICK-OFF — sollecito ai responsabili sui «problemi aperti» degli incontri
        # scaduti (MeetingIssue OPEN con due_date passata). Email + notifica in-app.
        "name": "tasks_meeting_issue_reminders",
        "func": "tasks.tasks.run_meeting_issue_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 7 * * 1",        # ogni lunedi alle 07:00
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
        # operativo. Fail-safe: digest no-op senza SiteConfig training_reminder_emails.
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
        # ASSETS — genera gli OdL periodici dovuti dalle MaintenanceRule attive.
        # Idempotente (nessun duplicato se esiste già un WO OPEN). Gira PRIMA del
        # promemoria manutenzione così i nuovi OdL rientrano nella mail del giorno.
        "name": "assets_generate_workorders",
        "func": "assets.tasks.run_generate_scheduled_workorders",
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
        # SUGGESTION CORNER — solleciti DO/CHECK + escalation (§3)
        "name": "suggestion_corner_reminders",
        "func": "suggestion_corner.tasks.run_suggestion_corner_reminders",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "0 8 * * *",        # ogni mattina alle 08:00
        "repeats": -1,
        "kwargs": {},
    },
]


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
    except Exception:
        controls = {}

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

    descr = schedule_descriptions()
    rows = []
    for spec in SCHEDULES:
        name = spec["name"]
        sch = live.get(name)
        last = last_runs.get(spec["func"])
        rows.append({
            "name": name,
            "func": spec["func"],
            "module": str(spec["func"]).split(".", 1)[0],
            "cadence": describe_cadence(spec),
            "description": descr.get(name, ""),
            "enabled": controls.get(name, True),
            "registered": sch is not None,
            "next_run": getattr(sch, "next_run", None),
            "last_run": last[0] if last else None,
            "last_ok": last[1] if last else None,
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
