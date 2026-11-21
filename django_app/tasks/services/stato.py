"""Regole del cambio di stato di un'attività, in un posto solo.

Lo stato si cambia da quattro punti (scheda, «Le mie attività», menu «⋯»,
Gantt) e ognuno aveva le sue regole: l'incaricato poteva riaprire un'attività
annullata da una pagina e non dall'altra, o salvare lo stato dal Gantt senza
nessun controllo. Qui la regola è una:

- chi gestisce l'attività (`can_manage_task`) o l'incaricato muove fra
  «Da fare», «In corso» e «Completata»;
- annullare, o riaprire un'attività annullata, lo decide chi ha i pieni poteri
  sulla commessa (senza commessa: chi gestisce l'attività).
"""
from __future__ import annotations

from ..access import can_manage_task, ha_pieni_poteri
from ..models import TaskStatus

MESSAGGIO_CAPOCOMMESSA = "Annullare un'attività, o riaprirne una annullata, lo decide il capocommessa."
MESSAGGIO_NON_TUA = "Puoi aggiornare solo le attività di cui sei responsabile."


def puo_annullare_o_ripristinare(request, task) -> bool:
    """Pieni poteri sulla commessa; per un'attività senza commessa basta gestirla."""
    if task.project_id:
        return ha_pieni_poteri(request, task.project)
    return can_manage_task(request, task)


def errore_cambio_stato(request, task, vecchio: str, nuovo: str) -> str | None:
    """Motivo per cui il passaggio ``vecchio`` -> ``nuovo`` non è permesso, o None."""
    if vecchio == nuovo:
        return None
    incaricato = bool(task.assigned_to_id) and task.assigned_to_id == getattr(request.user, "id", None)
    if not (incaricato or can_manage_task(request, task)):
        return MESSAGGIO_NON_TUA
    if TaskStatus.CANCELED in (vecchio, nuovo) and not puo_annullare_o_ripristinare(request, task):
        return MESSAGGIO_CAPOCOMMESSA
    return None


def allinea_avanzamento(task, vecchio: str) -> None:
    """Completata = 100%; riaperta da completata non resta al 100%."""
    if task.status == TaskStatus.DONE:
        if (task.progress or 0) < 100:
            task.progress = 100
    elif vecchio == TaskStatus.DONE and (task.progress or 0) >= 100:
        task.progress = 0
