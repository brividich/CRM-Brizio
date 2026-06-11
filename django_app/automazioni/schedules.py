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
        # Retention RunLog automazioni (GDPR): elimina i log oltre la finestra
        # configurata (SiteConfig automazioni_runlog_retention_days, default 90gg).
        "name": "cleanup_run_logs",
        "func": "automazioni.tasks.run_cleanup_run_logs",
        "schedule_type": "C",       # Schedule.CRON
        "cron": "30 3 * * *",       # ogni notte alle 03:30
        "repeats": -1,
        "kwargs": {},
    },
]
