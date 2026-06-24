"""Task django-q2 per gestione_specifiche (F4).

Wrapper sottili con run-log/monitoring uniforme (`@system_job_run`). La logica
vive in `scadenze.py` (testabile con clock mockato). Registrazione schedule in
`automazioni/schedules.py`; attivazione in deploy con `setup_q_schedules`.
"""
from __future__ import annotations

from automazioni.system_runlog import system_job_run

from . import scadenze


@system_job_run("gestione_specifiche_reminder")
def run_specifiche_reminder() -> dict:
    """Reminder 7gg sui MOD.133 non presi in carico (eseguito ~ogni ora)."""
    return scadenze.invia_reminder_mod133()


@system_job_run("gestione_specifiche_escalation")
def run_specifiche_escalation() -> dict:
    """Escalation 14gg sui MOD.133 ancora in flow-down (eseguito ~ogni ora)."""
    return scadenze.invia_escalation_mod133()


@system_job_run("gestione_specifiche_verifica_periodica")
def run_specifiche_verifica_periodica() -> dict:
    """Verifica periodica 6 mesi sulle specifiche in validità (eseguito 1/giorno)."""
    return scadenze.esegui_verifica_periodica()
