"""View focalizzate sulla fruibilita' delle commesse KICK-OFF."""
from __future__ import annotations

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from ..access import (
    can_manage_project,
    has_task_permission,
    scoped_projects_queryset,
    task_permissions_required,
)
from ..action_register import ACTION_ORIGIN_CHOICES, build_project_actions, filter_action_rows
from ..identity import normalize_client_name, normalize_part_number
from ..models import MeetingStatus, TaskStatus
from ..readiness import annotate_readiness_qs, compute_project_readiness
from ..services.modifiche import storico_pagina
from ._shared import _tasks_shell_context, percentuale_avanzamento
from .tappe import tappe_context


def _testo(value) -> str:
    return " ".join(str(value or "").split())[:120]


# Campi ricercabili: chiave del parametro ``field`` -> (sorgente, campo, normalizzazione).
# «progetti» = kickoff visibili all'utente; «incontri» = incontri di quei kickoff.
_IDENTITY_FIELDS = {
    "client": ("progetti", "client_name", normalize_client_name),
    "part_number": ("progetti", "part_number", normalize_part_number),
    "descrizione_pezzo": ("progetti", "descrizione_pezzo", _testo),
    "revisione": ("progetti", "revisione", _testo),
    "versione": ("progetti", "versione", _testo),
    "control_method": ("progetti", "control_method", _testo),
    "vrf_quote_number": ("progetti", "vrf_quote_number", _testo),
    "vrf_esp": ("progetti", "vrf_esp", _testo),
    "meeting_titolo": ("incontri", "titolo", _testo),
    "meeting_luogo": ("incontri", "luogo", _testo),
}


def _json_permission_error(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"ok": False, "reason": "unauthenticated", "values": []},
            status=401,
        )
    if not has_task_permission(request, "tasks_view"):
        return JsonResponse(
            {"ok": False, "reason": "forbidden", "values": []},
            status=403,
        )
    return None


def identity_suggest(request):
    """Suggerisce clienti o P/N visibili all'utente senza uscire dal suo scope."""
    permission_error = _json_permission_error(request)
    if permission_error is not None:
        return permission_error

    field = (request.GET.get("field") or "").strip()
    field_config = _IDENTITY_FIELDS.get(field)
    if field_config is None:
        return JsonResponse(
            {"ok": False, "reason": "invalid_field", "values": []},
            status=400,
        )

    sorgente, model_field, normalize_query = field_config
    query = normalize_query(request.GET.get("q"))
    progetti = scoped_projects_queryset(request)
    if sorgente == "incontri":
        from ..models import KickoffMeeting

        qs = KickoffMeeting.objects.filter(project__in=progetti.values("pk"))
    else:
        qs = progetti
    # Campo vuoto: i valori già usati, per scegliere senza scrivere. Con del
    # testo: quelli che lo contengono, prima quelli che iniziano così.
    qs = qs.exclude(**{model_field: ""}).exclude(**{f"{model_field}__isnull": True})
    if query:
        qs = qs.filter(**{f"{model_field}__icontains": query})
    values = list(qs.order_by(model_field).values_list(model_field, flat=True).distinct()[:200])
    visti, unici = set(), []
    for value in values:
        chiave = value.casefold()
        if chiave not in visti:
            visti.add(chiave)
            unici.append(value)
    if query:
        q = query.casefold()
        unici.sort(key=lambda v: (not v.casefold().startswith(q), v.casefold()))
    return JsonResponse({"values": unici[:20]})


def identity_check(request):
    """Dice se P/N + revisione + versione corrispondono a un kickoff che esiste già.

    Serve al form «Nuovo kickoff»: lo stesso controllo lo fa `ProjectKickoffForm`
    al salvataggio (e riapre quel kickoff), qui l'utente lo sa mentre scrive.
    Stesso ambito del form: solo i kickoff visibili a chi chiede.
    """
    permission_error = _json_permission_error(request)
    if permission_error is not None:
        return permission_error

    part_number = _testo(request.GET.get("part_number"))
    if not part_number:
        return JsonResponse({"exists": False})
    match = (
        scoped_projects_queryset(request)
        .filter(
            part_number__iexact=part_number,
            revisione__iexact=_testo(request.GET.get("revisione")),
            versione__iexact=_testo(request.GET.get("versione")),
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if match is None:
        return JsonResponse({"exists": False})
    return JsonResponse({
        "exists": True,
        "name": match.name,
        "url": reverse("tasks:project_overview", kwargs={"project_id": match.pk}),
    })


@task_permissions_required("tasks_view")
def project_actions(request, project_id: int):
    """Mostra in un unico registro issue, attivita' e sotto-attivita'."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    include_closed = request.GET.get("closed") == "1"
    all_actions = build_project_actions(project, include_closed=include_closed)
    # KPI = stessa funzione dei filtri della tabella: ogni tessera apre il
    # registro con il filtro che riproduce esattamente il suo numero.
    open_count = len(filter_action_rows(all_actions, stato="aperte"))
    overdue_count = len(filter_action_rows(all_actions, scadenza="scadute"))
    closed_count = len(filter_action_rows(all_actions, stato="chiuse"))
    unassigned_count = len(filter_action_rows(all_actions, stato="aperte", responsabile="nessuno"))
    no_due_count = len(filter_action_rows(all_actions, scadenza="senza"))

    # Filtri: i KPI restano sull'intero registro, la tabella mostra il filtrato.
    stato = (request.GET.get("stato") or "").strip()
    filters = {
        "stato": stato if stato in {"aperte", "chiuse"} else "",
        "tipo": (request.GET.get("tipo") or "").strip(),
        "responsabile": (request.GET.get("responsabile") or "").strip(),
        "scadenza": (request.GET.get("scadenza") or "").strip(),
        "q": (request.GET.get("q") or "").strip(),
    }
    actions = filter_action_rows(all_actions, **filters)
    owners = sorted(
        {(row.owner_id, row.owner_label) for row in all_actions if row.owner_id},
        key=lambda pair: pair[1].casefold(),
    )
    # Le attività si aggiornano sul posto (stato e scadenza): chi può lo decide
    # il server, qui la pagina mostra i controlli solo a chi li può usare.
    from ..access import can_manage_task, puo_spostare_subito
    from ..forms import task_active_users_queryset
    from ..services.striscia import striscia_commessa

    gestisce = can_manage_project(request, project)
    elenco_attivita = list(project.tasks.select_related("assigned_to", "project"))
    attivita = {t.pk: t for t in elenco_attivita}
    # Dipende solo dalla commessa: chi non sposta subito chiede, con il motivo.
    sposta_subito = puo_spostare_subito(request, elenco_attivita[0]) if elenco_attivita else True
    righe = []
    for row in actions:
        task = attivita.get(row.obj_id) if row.origin == "task" else None
        puo = bool(task) and task.status != TaskStatus.CANCELED and (
            gestisce or task.assigned_to_id == request.user.id or can_manage_task(request, task)
        )
        righe.append({"voce": row, "task": task, "puo": puo})
    return render(
        request,
        "tasks/project_actions.html",
        {
            **_tasks_shell_context(
                request,
                active="actions",
                project=project,
                action_count=open_count,
            ),
            "page_title": f"Registro attività - {project.name}",
            "project": project,
            "actions": actions,
            "righe": righe,
            "sposta_subito": sposta_subito,
            "striscia": striscia_commessa(project, timezone.localdate(), tasks=elenco_attivita),
            "puo_aggiungere": gestisce and has_task_permission(request, "tasks_create"),
            "persone": [
                {"id": u.pk, "nome": (u.get_full_name() or u.get_username()).strip()}
                for u in task_active_users_queryset()
            ] if gestisce else [],
            "stati_attivita": [
                (TaskStatus.TODO, "Da fare", "reopen"), (TaskStatus.IN_PROGRESS, "In corso", "start"),
                (TaskStatus.DONE, "Completata", "done"),
            ],
            "filters": filters,
            "filters_active": any(filters.values()),
            "owners": owners,
            "tipo_choices": ACTION_ORIGIN_CHOICES,
            "include_closed": include_closed,
            "open_count": open_count,
            "overdue_count": overdue_count,
            "closed_count": closed_count,
            "unassigned_count": unassigned_count,
            "no_due_count": no_due_count,
        },
    )


@task_permissions_required("tasks_view")
def project_overview(request, project_id: int):
    """Landing leggibile della commessa con stato e prossime azioni."""
    project_queryset = annotate_readiness_qs(scoped_projects_queryset(request))
    project = get_object_or_404(project_queryset, pk=project_id)
    actions = build_project_actions(project)
    action_open_count = len(actions)
    today = timezone.localdate()
    next_meeting = (
        project.meetings.filter(
            stato=MeetingStatus.PIANIFICATO,
            data__gte=today,
        )
        .order_by("data", "ora", "numero", "id")
        .first()
    )
    task_counts = project.tasks.aggregate(
        total=Count("id"),
        planned=Count("id", filter=Q(due_date__isnull=False)),
        done=Count("id", filter=Q(status=TaskStatus.DONE)),
        attive=Count("id", filter=~Q(status=TaskStatus.CANCELED)),
    )
    recent_meetings = list(project.meetings.order_by("-numero", "-id")[:3])
    # Data di inizio della commessa: primo incontro non annullato.
    first_meeting_date = (
        project.meetings.exclude(stato=MeetingStatus.ANNULLATO)
        .order_by("data")
        .values_list("data", flat=True)
        .first()
    )
    readiness = compute_project_readiness(project)
    can_manage = can_manage_project(request, project)
    from ._shared import _puo_modificare_kickoff

    if not _puo_modificare_kickoff(request, project):
        # «Correggi» del team porta a Modifica kickoff: chi non può aprirla
        # finiva su «Accesso negato».
        from dataclasses import replace

        readiness = replace(readiness, criteria=[
            replace(c, action_url=None) if c.key == "team" else c for c in readiness.criteria
        ])
    from ..services.filo import prossimi_passi

    _filo = tappe_context(request, project)
    _filo["prossimi_passi"] = prossimi_passi(project, tappe=_filo["tappe"], can_manage=can_manage)
    from ..access import ha_pieni_poteri
    from ..services.filo import stato_consegna

    _filo["consegna"] = stato_consegna(project)
    _filo["puo_chiudere"] = ha_pieni_poteri(request, project)
    _filo["attivita_aperte"] = project.tasks.exclude(status__in=[TaskStatus.DONE, TaskStatus.CANCELED]).count()
    # CN-SGI: piani qualità del cliente e procedure collegate al KICK-OFF (fail-safe).
    try:
        from procedure_refresh.collegamenti import documenti_per_kickoff

        _filo["documenti_sgi"] = documenti_per_kickoff(request, project.client_name)
    except Exception:
        _filo["documenti_sgi"] = []
    if next_meeting is not None:
        from .meetings import _sala_stato

        _filo["next_meeting_sala"] = _sala_stato(next_meeting)

    return render(
        request,
        "tasks/project_overview.html",
        {
            **_tasks_shell_context(
                request,
                active="overview",
                project=project,
                action_count=action_open_count,
            ),
            "page_title": f"Panoramica - {project.name}",
            "project": project,
            "readiness": readiness,
            **_filo,
            "actions": actions,
            "top_actions": actions[:5],
            "action_open_count": action_open_count,
            "next_meeting": next_meeting,
            "first_meeting_date": first_meeting_date,
            "planned_task_count": task_counts["planned"],
            "total_task_count": task_counts["total"],
            "done_task_count": task_counts["done"],
            "unplanned_task_count": task_counts["total"] - task_counts["planned"],
            "active_task_count": task_counts["attive"],
            "progress_pct": percentuale_avanzamento(task_counts["done"], task_counts["attive"]),
            "recent_meetings": recent_meetings,
            "storico_modifiche": storico_pagina(project),
            "can_manage": can_manage,
            "hide_readiness_actions": not can_manage,
        },
    )
