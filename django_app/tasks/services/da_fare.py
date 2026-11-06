"""Cosa deve fare l'utente nel KICK-OFF, per il riepilogo «Le mie attività» del portale."""
from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..access import has_task_permission, scoped_projects_queryset
from .programmi import senza_attivita_aperta
from ..models import (
    MeetingActionItem,
    MeetingActionStatus,
    MeetingIssue,
    MeetingIssueStatus,
    ProjectTechRef,
    Task,
    TaskStatus,
    TechRefStatus,
)

MAX_VOCI = 15


def _voce(code, title, project, due_date, url, oggi, *, done=None, ref=None) -> dict:
    """``done`` = (tipo, id) quando la voce si può chiudere dalla riga."""
    scaduta = bool(due_date and due_date < oggi)
    meta = project.name if project else "Senza commessa"
    if due_date:
        meta += f" · entro il {due_date:%d/%m/%Y}"
    return {
        "code": code,
        "title": title,
        "meta": meta,
        "status": "Scaduta" if scaduta else "Da fare",
        "url": url,
        "due": due_date,
        "done_url": reverse("tasks:mia_voce_stato", args=list(done)) if done else "",
        "done_label": ("Risolto" if done[0] == "problema" else "Fatto") if done else "",
        "path": ref.path if ref is not None and not ref.is_web_path else "",
        "path_href": ref.open_href if ref is not None else "",
        "_ordine": (not scaduta, due_date is None, due_date or oggi),
    }


def voci_kickoff(request) -> dict:
    """Le prime voci, le più urgenti in testa, con i conteggi reali di tutte."""
    if not has_task_permission(request, "tasks_view"):
        return {"items": [], "total": 0, "overdue": 0, "soon": 0}
    oggi = timezone.localdate()
    user = request.user
    progetti = scoped_projects_queryset(request).values("id")
    comuni = {"assigned_to": user, "project_id__in": progetti}

    voci: list[dict] = []
    for t in Task.objects.filter(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS], **comuni).select_related("project"):
        voci.append(_voce("Attività", t.title, t.project, t.due_date, reverse("tasks:detail", args=[t.pk]), oggi))
    for a in MeetingActionItem.objects.filter(status=MeetingActionStatus.OPEN, **comuni).select_related("project"):
        voci.append(_voce("Azione", a.title, a.project, a.due_date, reverse("tasks:mie_azioni"), oggi, done=("azione", a.pk)))
    for i in MeetingIssue.objects.filter(status=MeetingIssueStatus.OPEN, **comuni).select_related("project"):
        voci.append(_voce("Problema", i.title, i.project, i.due_date, reverse("tasks:mie_azioni"), oggi, done=("problema", i.pk)))
    for r in senza_attivita_aperta(ProjectTechRef.objects.filter(status=TechRefStatus.OPEN, **comuni)).select_related("project"):
        titolo = r.code or r.get_kind_display()
        url = reverse("tasks:project_tech_refs", args=[r.project_id])
        voci.append(_voce(r.kind, titolo, r.project, r.due_date, url, oggi, done=("programma", r.pk), ref=r))

    voci.sort(key=lambda v: v.pop("_ordine"))
    fra_7 = oggi + timedelta(days=7)
    return {
        "items": voci[:MAX_VOCI],
        "total": len(voci),
        "overdue": sum(1 for v in voci if v["due"] and v["due"] < oggi),
        "soon": sum(1 for v in voci if v["due"] and oggi <= v["due"] <= fra_7),
    }
