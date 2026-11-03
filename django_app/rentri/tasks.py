"""Task periodici django-q2 del modulo rentri.

Registrati in modo idempotente da ``automazioni.schedules`` /
``setup_q_schedules``. Non avviare task qui: usare il management command.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_rentri_scadenze_check() -> dict:
    """Controllo registri RENTRI non confermati/inviati oltre soglia → alert admin.

    Wrappa il management command ``check_rentri_scadenze`` (soglia giorni di default
    del comando). Invia email agli amministratori: da attivare dove il modulo RENTRI
    è operativo.
    """
    from django.core.management import call_command

    try:
        call_command("check_rentri_scadenze", verbosity=0)
        return {"ok": True}
    except Exception:
        logger.exception("run_rentri_scadenze_check: eccezione inattesa")
        raise


def run_rentri_promemoria_scarico_effettivo() -> dict:
    """Avviso in-app per gli scarichi originali ancora senza scarico effettivo (vedi ``rentri.promemoria``)."""
    from .promemoria import invia_promemoria

    try:
        return {"ok": True, **invia_promemoria()}
    except Exception:
        logger.exception("run_rentri_promemoria_scarico_effettivo: eccezione inattesa")
        raise
