"""View focalizzate sulla fruibilita' delle commesse KICK-OFF."""
from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .action_register import build_project_actions
from .identity import normalize_client_name, normalize_part_number
from .views import (
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
            **_tasks_shell_context(request, active="actions", project=project),
            "page_title": f"Registro azioni - {project.name}",
            "project": project,
            "actions": actions,
            "include_closed": include_closed,
            "open_count": open_count,
            "overdue_count": overdue_count,
        },
    )
