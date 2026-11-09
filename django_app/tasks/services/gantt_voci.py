"""Incontri e scadenze della commessa da mostrare sul Gantt, accanto alle attività.

Prima il Gantt mostrava solo le attività: incontri, azioni e problemi aperti e
programmi CAM/CMM/FAI si vedevano in pagine diverse e il piano non diceva
quando c'era la prossima riunione o cosa scadeva fuori dalle barre.

Regola: una voce collegata a un'attività ancora aperta compare come etichetta
sulla riga di quell'attività (è lei a portarla avanti); le altre voci aperte
hanno una riga loro, con un segno sulla data di scadenza.
"""
from __future__ import annotations

from datetime import date

from django.urls import reverse
from django.utils import timezone

from ..models import (
    MeetingActionItem,
    MeetingActionStatus,
    MeetingIssue,
    MeetingIssueStatus,
    MeetingStatus,
    ProjectTechRef,
    TaskStatus,
    TechRefStatus,
)

_ATTIVITA_APERTE = (TaskStatus.TODO, TaskStatus.IN_PROGRESS)


def _nome(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


def gantt_voci(project, tasks) -> dict:
    """Ritorna ``incontri``, ``voci`` (righe proprie), ``per_attivita`` (etichette) e ``date``."""
    oggi = timezone.localdate()
    aperte = {t.id for t in tasks if t.status in _ATTIVITA_APERTE}

    incontri = []
    for m in project.meetings.exclude(stato=MeetingStatus.ANNULLATO).order_by("data", "ora", "id"):
        if not m.data:
            continue
        incontri.append({
            "data": m.data,
            "ora": m.ora,
            "titolo": m.titolo or f"Incontro {m.numero}",
            "numero": m.numero,
            "svolto": m.stato == MeetingStatus.SVOLTO,
            "url": reverse("tasks:project_meeting_detail", args=[project.id, m.id]),
        })

    voci: list[dict] = []
    per_attivita: dict[int, list[dict]] = {}

    def aggiungi(*, tipo, chiave, titolo, scadenza, chi, url, task_id):
        voce = {
            "tipo": tipo,
            "chiave": chiave,
            "titolo": titolo,
            "scadenza": scadenza,
            "chi": chi,
            "url": url,
            "scaduta": bool(scadenza and scadenza < oggi),
        }
        if task_id and task_id in aperte:
            per_attivita.setdefault(task_id, []).append(voce)
        else:
            voci.append(voce)

    for a in MeetingActionItem.objects.filter(project=project, status=MeetingActionStatus.OPEN).select_related(
        "assigned_to", "source_meeting"
    ):
        url = (
            reverse("tasks:project_meeting_detail", args=[project.id, a.source_meeting_id])
            if a.source_meeting_id else reverse("tasks:project_actions", args=[project.id])
        )
        aggiungi(tipo="Azione", chiave="azione", titolo=a.title, scadenza=a.due_date,
                 chi=_nome(a.assigned_to), url=url, task_id=a.linked_task_id)

    for i in MeetingIssue.objects.filter(project=project, status=MeetingIssueStatus.OPEN).select_related(
        "assigned_to", "source_meeting"
    ):
        url = (
            reverse("tasks:project_meeting_detail", args=[project.id, i.source_meeting_id])
            if i.source_meeting_id else reverse("tasks:project_actions", args=[project.id])
        )
        aggiungi(tipo="Problema", chiave="problema", titolo=i.title, scadenza=i.due_date,
                 chi=_nome(i.assigned_to), url=url, task_id=i.linked_task_id)

    for r in ProjectTechRef.objects.filter(project=project, status=TechRefStatus.OPEN).select_related("assigned_to"):
        aggiungi(tipo=r.get_kind_display(), chiave="programma",
                 titolo=r.code or ("da inserire" if not r.path else r.path), scadenza=r.due_date,
                 chi=_nome(r.assigned_to), url=reverse("tasks:project_tech_refs", args=[project.id]),
                 task_id=r.task_id)

    # Scadute prima, poi per data; le senza data in fondo.
    voci.sort(key=lambda v: (v["scadenza"] is None, v["scadenza"] or date.max, v["titolo"].casefold()))
    date_utili = [m["data"] for m in incontri] + [v["scadenza"] for v in voci if v["scadenza"]]
    return {"incontri": incontri, "voci": voci, "per_attivita": per_attivita, "date": date_utili}


def posiziona(elementi, campo: str, inizio: date, giorni: int) -> list[dict]:
    """Aggiunge ``idx`` (colonna del giorno) agli elementi che cadono nel periodo mostrato."""
    for e in elementi:
        valore = e.get(campo)
        idx = (valore - inizio).days if valore else None
        e["idx"] = idx if idx is not None and 0 <= idx < giorni else None
    return elementi
