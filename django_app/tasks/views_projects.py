"""View focalizzate sulla fruibilita' delle commesse KICK-OFF."""
from __future__ import annotations

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .action_register import build_project_actions
from .identity import normalize_client_name, normalize_part_number
from .models import MeetingStatus
from .readiness import annotate_readiness_qs, compute_project_readiness
from .views import (
    _can_manage_project,
    _has_task_permission,
    _scoped_projects_queryset,
    _tasks_shell_context,
    task_permissions_required,
)


_IDENTITY_FIELDS = {
    "client": ("client_name", normalize_client_name),
    "part_number": ("part_number", normalize_part_number),
}


def _json_permission_error(request):
    if not request.user.is_authenticated:
        return JsonResponse(
            {"ok": False, "reason": "unauthenticated", "values": []},
            status=401,
        )
    if not _has_task_permission(request, "tasks_view"):
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

    model_field, normalize_query = field_config
    query = normalize_query(request.GET.get("q"))
    if not query:
        return JsonResponse({"values": []})

    values = list(
        _scoped_projects_queryset(request)
        .filter(**{f"{model_field}__istartswith": query})
        .exclude(**{model_field: ""})
        .order_by(model_field)
        .values_list(model_field, flat=True)
        .distinct()[:20]
    )
    return JsonResponse({"values": values})


@task_permissions_required("tasks_view")
def project_actions(request, project_id: int):
    """Mostra in un unico registro issue, attivita' e sotto-attivita'."""
    project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    include_closed = request.GET.get("closed") == "1"
    actions = build_project_actions(project, include_closed=include_closed)
    open_count = sum(row.is_open for row in actions)
    overdue_count = sum(row.is_overdue for row in actions)
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
            "page_title": f"Registro azioni - {project.name}",
            "project": project,
            "actions": actions,
            "include_closed": include_closed,
            "open_count": open_count,
            "overdue_count": overdue_count,
        },
    )


@task_permissions_required("tasks_view")
def project_overview(request, project_id: int):
    """Landing leggibile della commessa con stato e prossime azioni."""
    project_queryset = annotate_readiness_qs(_scoped_projects_queryset(request))
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
    )
    recent_meetings = list(project.meetings.order_by("-numero", "-id")[:3])
    readiness = compute_project_readiness(project)
    can_manage = _can_manage_project(request, project)

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
            "actions": actions,
            "top_actions": actions[:5],
            "action_open_count": action_open_count,
            "next_meeting": next_meeting,
            "planned_task_count": task_counts["planned"],
            "total_task_count": task_counts["total"],
            "recent_meetings": recent_meetings,
            "can_manage": can_manage,
            "hide_readiness_actions": not can_manage,
        },
    )
