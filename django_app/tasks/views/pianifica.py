"""Dopo la scheda VRF: «Come procedi?» e la pianificazione rapida delle attività.

Il filo del kickoff: dati commessa -> VRF (compilata o rimandata) -> si sceglie
se pianificare prima le attività o prima l'incontro. Finite le attività si può
convocare l'incontro, che riparte da quelle attività da confermare; nella
convocazione si assegnano attività dai punti dell'ordine del giorno.
"""
from __future__ import annotations

import json

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.audit import log_action

from ..access import can_manage_project, scoped_projects_queryset, task_permissions_required
from ..forms import etichetta_utente, task_active_users_queryset
from ..models import TaskImpostazioni, TaskStatus
from ._shared import _tasks_shell_context, _vrf_status_detail


def _stato(project) -> dict:
    tasks = project.tasks.exclude(status=TaskStatus.CANCELED)
    return {
        "attivita_totali": tasks.count(),
        "attivita_senza_responsabile": tasks.filter(assigned_to__isnull=True).count(),
        "incontri": project.meetings.count(),
        "vrf": _vrf_status_detail(project, TaskImpostazioni.get_singleton()),
    }


@task_permissions_required("tasks_view")
def project_pianifica(request, project_id: int):
    """«Come procedi?»: pianificazione delle attività o dell'incontro."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return redirect("tasks:project_overview", project_id=project.id)
    return render(
        request,
        "tasks/project_pianifica.html",
        {
            **_tasks_shell_context(request, active="overview", project=project),
            "page_title": f"Come procedi - {project.name}",
            "project": project,
            **_stato(project),
        },
    )


def _righe_iniziali(post, utenti_per_id) -> list[dict]:
    righe = []
    if post is not None:
        titoli, resp, scad = post.getlist("att_titolo"), post.getlist("att_resp"), post.getlist("att_scadenza")
        for i, titolo in enumerate(titoli):
            r = resp[i] if i < len(resp) else ""
            d = scad[i] if i < len(scad) else ""
            if (titolo or "").strip() or r or d:
                righe.append({"titolo": titolo, "resp": r if r in utenti_per_id else "",
                              "resp_label": utenti_per_id.get(r, ""), "scadenza": d})
    while len(righe) < 3:
        righe.append({"titolo": "", "resp": "", "resp_label": "", "scadenza": ""})
    return righe


@task_permissions_required("tasks_view", "tasks_create")
def project_attivita_pianifica(request, project_id: int):
    """Pianificazione rapida: una riga per attività (cosa, chi, entro quando).

    Responsabile e scadenza sono facoltativi: la scadenza spesso non si sa.
    «Salva e pianifica l'incontro» porta alla convocazione con queste attività
    nell'ordine del giorno, da confermare in riunione.
    """
    from ..services.kickoff_avvio import crea_attivita, notifica_assegnazioni, righe_dal_post
    from ..services.meeting_tasks import kickoff_bloccato_vrf

    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)
    if kickoff_bloccato_vrf(project):
        messages.error(request, "Kickoff bloccato per VRF mancante: compila la scheda VRF per pianificare le attività.")
        return redirect("tasks:project_vrf_compile", project_id=project.id)

    utenti = [{"id": u.pk, "label": etichetta_utente(u)} for u in task_active_users_queryset()]
    utenti_per_id = {str(u["id"]): u["label"] for u in utenti}

    if request.method == "POST":
        righe = righe_dal_post(request.POST)
        poi_incontro = request.POST.get("poi") == "incontro"
        if not righe and not poi_incontro:
            messages.error(request, "Scrivi almeno un'attività.")
        else:
            with transaction.atomic():
                tasks = crea_attivita(project, righe, request.user)
            notifica_assegnazioni(tasks, actor=request.user)
            log_action(request, "kickoff_attivita_pianificate", "tasks", {
                "project_id": project.id,
                "task_ids": [t.id for t in tasks],
                "message": f"{len(tasks)} attività pianificate nel kickoff #{project.id}",
            })
            if tasks:
                messages.success(request, f"{len(tasks)} attività pianificate.")
            if poi_incontro:
                ids = ",".join(str(t.id) for t in tasks)
                url = reverse("tasks:project_meeting_create", kwargs={"project_id": project.id})
                return redirect(f"{url}?attivita={ids or 'aperte'}")
            return redirect("tasks:project_overview", project_id=project.id)

    esistenti = list(
        project.tasks.exclude(status__in=[TaskStatus.CANCELED, TaskStatus.DONE])
        .select_related("assigned_to").order_by("id")
    )
    return render(
        request,
        "tasks/project_attivita_pianifica.html",
        {
            **_tasks_shell_context(request, active="overview", project=project),
            "page_title": f"Pianifica attività - {project.name}",
            "project": project,
            "att_utenti": utenti,
            # Per lo <script>: niente «</» che chiuda il tag in anticipo.
            "att_utenti_json": json.dumps(utenti).replace("</", "<\\/"),
            "att_righe": _righe_iniziali(request.POST if request.method == "POST" else None, utenti_per_id),
            "attivita_esistenti": esistenti,
        },
    )
