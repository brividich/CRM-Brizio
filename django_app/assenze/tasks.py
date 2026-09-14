"""Task django-q2 del modulo assenze: sincronizzazione con la lista SharePoint.

Registrati via automazioni.schedules + setup_q_schedules. Le pagine del modulo
non chiamano mai Graph: tutto il traffico verso SharePoint passa da qui.
"""
from __future__ import annotations

import logging

from automazioni.system_runlog import system_job_run

logger = logging.getLogger("assenze.tasks")


@system_job_run("assenze_sharepoint_sync")
def run_assenze_sharepoint_sync() -> dict:
    """Giro periodico: coda locale -> SharePoint, poi modifiche SharePoint -> DB.

    L'invio viene prima della lettura, cosi' la lettura trova SharePoint gia'
    allineato alle modifiche fatte sul portale.
    """
    from assenze import views

    if not views._graph_configured():
        return {"skipped": "SharePoint non configurato"}

    out = {"push": views._sp_push_outbox()}
    out["pull"] = views._maybe_pull(force=True)
    try:
        views._sp_refresh_motivazioni()
    except Exception:
        logger.warning("run_assenze_sharepoint_sync: motivazioni non aggiornate", exc_info=True)
    return out


def run_assenze_sharepoint_push() -> dict:
    """Invio immediato della coda, accodato dalle view dopo un salvataggio.

    Se il cluster non lo esegue, o se un altro invio e' gia' in corso, la coda la
    svuota comunque il giro periodico.
    """
    from assenze import views

    return views._sp_push_outbox()
