"""Permessi e visibilita' del modulo KICK-OFF: gate di modulo (ACL v2 con
fallback legacy), livelli di accesso per ruolo e queryset filtrati per utente."""
from __future__ import annotations

import logging
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.db.models import Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import render

from admin_portale.decorators import _is_json_request
from core.acl import evaluate_modulo_action_access
from core.legacy_utils import get_legacy_user

from .models import (
    Project,
    SubTask,
    TaskAccessLevel,
    Task,
    TaskAttachment,
    TaskComment,
    TaskEvent,
    TaskRoleAssignment,
    TaskRoleAccessRule,
    TaskUserAccessRule,
)

logger = logging.getLogger(__name__)
TASK_MODULE_CODE = "tasks"
TASK_ACCESS_LEVEL_ORDER = {
    TaskAccessLevel.NONE: 0,
    TaskAccessLevel.READ_ALL: 1,
    TaskAccessLevel.EDIT_ASSIGNED: 2,
    TaskAccessLevel.EDIT_ALL: 3,
}


def _request_legacy_user(request):
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is None:
        legacy_user = get_legacy_user(request.user)
        request.legacy_user = legacy_user
    return legacy_user


def _check_task_action_for_legacy(legacy_user, action_code: str) -> bool:
    """Permesso modulo+azione KICK-OFF tramite il valutatore comune.

    ``evaluate_modulo_action_access`` consulta prima il binding canonico ACL v2
    e solo in sua assenza l'override per-utente e la mappa del ruolo legacy:
    qui prima si leggeva solo il legacy, quindi una concessione o un divieto
    impostati dal pannello Accessi v2 non avevano effetto sul modulo.
    """
    if not legacy_user:
        return False
    if not str(action_code or "").strip():
        return False
    return bool(
        evaluate_modulo_action_access(
            legacy_user=legacy_user,
            modulo=TASK_MODULE_CODE,
            azione=action_code,
        ).get("allowed", False)
    )


MODULO = "kickoff"
# Codici d'azione storici del modulo -> azioni della matrice dei ruoli.
_AZIONI_RUOLI = {
    "tasks_view": "vedere",
    "view_tasks": "vedere",
    "tasks_comment": "vedere",
    "tasks_create": "creare",
    "tasks_edit": "modificare",
}


def _ruoli_attivi() -> bool:
    from core.permessi import sistema_ruoli_attivo

    return sistema_ruoli_attivo()


def _ambito(request, azione: str) -> str:
    """Ruoli attivi: ambito concesso (propri/team/tutti) o '' se negato."""
    from core.permessi import decisione

    esito = decisione(request, MODULO, azione)
    return esito.ambito if esito.consentito else ""


def _team_users_q(request, *campi: str) -> Q:
    """Q sui record il cui utente (nei campi indicati) e' nel team d'organigramma."""
    from core.permessi.motore import contesto_per

    team = list(contesto_per(request).team)
    q = Q(pk__in=[])
    if team:
        for campo in campi:
            q |= Q(**{f"{campo}__profile__legacy_user_id__in": team})
    return q


def has_task_permission(request, action_code: str) -> bool:
    if getattr(request.user, "is_authenticated", False) and not request.user.is_superuser and _ruoli_attivi():
        key = str(action_code or "").strip().lower()
        if key in {"tasks_admin", "admin_tasks"}:
            return _ambito(request, "gestire") == "tutti"
        return bool(_ambito(request, _AZIONI_RUOLI.get(key, "gestire")))
    cache = getattr(request, "_task_perm_cache", None)
    if cache is None:
        cache = {}
        request._task_perm_cache = cache

    key = str(action_code or "").strip().lower()
    if key in cache:
        return bool(cache[key])

    if not request.user.is_authenticated:
        cache[key] = False
        return False
    if request.user.is_superuser:
        cache[key] = True
        return True

    legacy_user = _request_legacy_user(request)
    allowed = _check_task_action_for_legacy(legacy_user, action_code)
    cache[key] = bool(allowed)
    return bool(allowed)


def task_permissions_required(*action_codes: str, api: bool = False):
    """Gate di modulo. ``api=True`` per gli endpoint JSON: rispondono 401/403
    in JSON invece del redirect al login o della pagina HTML di divieto."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            wants_json = api or _is_json_request(request)
            if not request.user.is_authenticated:
                if wants_json:
                    return JsonResponse(
                        {"ok": False, "error": "Autenticazione richiesta.", "reason": "unauthenticated"},
                        status=401,
                    )
                return redirect_to_login(request.get_full_path())
            for action_code in action_codes:
                if not has_task_permission(request, action_code):
                    if wants_json:
                        return JsonResponse(
                            {"ok": False, "error": "Permessi insufficienti.", "reason": "forbidden"},
                            status=403,
                        )
                    return render(
                        request,
                        "core/pages/forbidden.html",
                        {"page_title": "Accesso negato"},
                        status=403,
                    )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def _task_access_rank(level: str | None) -> int:
    return int(TASK_ACCESS_LEVEL_ORDER.get(str(level or "").strip(), 0))


def _task_access_allows_read(level: str | None) -> bool:
    return _task_access_rank(level) >= _task_access_rank(TaskAccessLevel.READ_ALL)


def _task_access_allows_edit_assigned(level: str | None) -> bool:
    return _task_access_rank(level) >= _task_access_rank(TaskAccessLevel.EDIT_ASSIGNED)


def _task_access_allows_edit_all(level: str | None) -> bool:
    return _task_access_rank(level) >= _task_access_rank(TaskAccessLevel.EDIT_ALL)


def _request_task_role_access_map(request) -> dict[str, str]:
    cached = getattr(request, "_task_role_access_map", None)
    if cached is not None:
        return cached
    cached = {
        role_type: access_level
        for role_type, access_level in TaskRoleAccessRule.objects.values_list("role_type", "access_level")
    }
    request._task_role_access_map = cached
    return cached


def _request_task_user_access_level(request) -> str:
    cached = getattr(request, "_task_user_access_level", None)
    if cached is not None:
        return cached
    if not getattr(request.user, "is_authenticated", False):
        cached = TaskAccessLevel.NONE
    else:
        cached = (
            TaskUserAccessRule.objects.filter(user=request.user)
            .values_list("access_level", flat=True)
            .first()
            or TaskAccessLevel.NONE
        )
    request._task_user_access_level = cached
    return cached


def _request_task_user_role_codes(request) -> set[str]:
    cached = getattr(request, "_task_user_role_codes", None)
    if cached is not None:
        return cached
    if not getattr(request.user, "is_authenticated", False):
        cached = set()
    else:
        cached = set(
            TaskRoleAssignment.objects.filter(user=request.user)
            .values_list("role_type", flat=True)
        )
    request._task_user_role_codes = cached
    return cached


def _project_role_access_level(request, project: Project | None) -> str:
    if project is None or not getattr(project, "pk", None):
        return TaskAccessLevel.NONE
    if not getattr(request.user, "is_authenticated", False):
        return TaskAccessLevel.NONE

    role_map = _request_task_role_access_map(request)
    user_id = request.user.id
    levels: list[str] = [
        role_map.get(role_code, TaskAccessLevel.NONE)
        for role_code in project.role_types_for_user(user_id)
    ]
    if not levels:
        return TaskAccessLevel.NONE
    return max(levels, key=_task_access_rank)


def _task_role_access_level(request, task: Task | None) -> str:
    if task is None:
        return TaskAccessLevel.NONE
    levels = [_project_role_access_level(request, getattr(task, "project", None))]
    role_type = getattr(task, "category", None)
    role_type = getattr(role_type, "role_type", "") or ""
    if role_type and role_type in _request_task_user_role_codes(request):
        levels.append(_request_task_role_access_map(request).get(role_type, TaskAccessLevel.NONE))
    return max(levels, key=_task_access_rank)


def _readable_team_codes(role_map: dict[str, str]) -> list[str]:
    """Ruoli del team che, per regola di accesso, danno visibilita' sul kickoff."""
    return [
        code
        for _field, _label, code in Project.TEAM_ROLES
        if _task_access_allows_read(role_map.get(code))
    ]


def _task_scope_filter_q(request) -> Q:
    user = request.user
    q = Q(created_by=user) | Q(assigned_to=user) | Q(subscribers=user)
    role_map = _request_task_role_access_map(request)
    team_codes = _readable_team_codes(role_map)
    if team_codes:
        q |= Project.team_q(user, team_codes, prefix="project__")
    category_role_codes = [
        role_code
        for role_code in _request_task_user_role_codes(request)
        if _task_access_allows_read(role_map.get(role_code))
    ]
    if category_role_codes:
        q |= Q(category__role_type__in=category_role_codes)
    return q


def _project_scope_filter_q(request) -> Q:
    user = request.user
    q = (
        Q(created_by=user)
        | Q(tasks__created_by=user)
        | Q(tasks__assigned_to=user)
        | Q(tasks__subscribers=user)
        # I kickoff programmati devono comparire a chi vi partecipa o li ha creati,
        # anche senza task nel progetto (bug: sparivano dalla dashboard).
        | Q(meetings__partecipanti_utenti=user)
        | Q(meetings__created_by=user)
    )
    role_map = _request_task_role_access_map(request)
    team_codes = _readable_team_codes(role_map)
    if team_codes:
        q |= Project.team_q(user, team_codes, prefix="")
    category_role_codes = [
        role_code
        for role_code in _request_task_user_role_codes(request)
        if _task_access_allows_read(role_map.get(role_code))
    ]
    if category_role_codes:
        q |= Q(tasks__category__role_type__in=category_role_codes)
    return q




def scoped_tasks_queryset(request):
    qs = Task.objects.select_related(
        "created_by",
        "assigned_to",
        "category",
        "project",
        "project__similar_project",
    ).prefetch_related(Project.team_prefetch("project__"))
    if has_task_permission(request, "tasks_admin"):
        return qs
    if not request.user.is_superuser and _ruoli_attivi():
        # Ruoli: tutte; o quelle a cui si partecipa piu' quelle del team; o solo le proprie.
        ambito = _ambito(request, "vedere")
        if ambito == "tutti":
            return qs
        if not ambito:
            return qs.none()
        q = _task_scope_filter_q(request)
        if ambito == "team":
            q |= _team_users_q(request, "assigned_to", "created_by")
        return qs.filter(q).distinct()
    if _task_access_allows_read(_request_task_user_access_level(request)):
        return qs
    return qs.filter(_task_scope_filter_q(request)).distinct()


def scoped_projects_queryset(request):
    qs = Project.objects.select_related(
        "created_by",
        "similar_project",
    ).prefetch_related(Project.team_prefetch())
    if has_task_permission(request, "tasks_admin"):
        return qs
    if not request.user.is_superuser and _ruoli_attivi():
        ambito = _ambito(request, "vedere")
        if ambito == "tutti":
            return qs
        if not ambito:
            return qs.none()
        q = _project_scope_filter_q(request)
        if ambito == "team":
            q |= _team_users_q(request, "created_by", "tasks__assigned_to")
        return qs.filter(q).distinct()
    if _task_access_allows_read(_request_task_user_access_level(request)):
        return qs
    return qs.filter(_project_scope_filter_q(request)).distinct()


def _detail_queryset(request):
    return scoped_tasks_queryset(request).prefetch_related(
        "subscribers",
        Prefetch("subtasks", queryset=SubTask.objects.select_related("assigned_to").order_by("order_index", "id")),
        Prefetch("comments", queryset=TaskComment.objects.select_related("author", "target_user").order_by("-created_at", "-id")),
        Prefetch("events", queryset=TaskEvent.objects.select_related("actor").order_by("-created_at", "-id")),
        Prefetch("attachments", queryset=TaskAttachment.objects.select_related("uploaded_by").order_by("-created_at", "-id")),
        Prefetch(
            "project__attachments",
            queryset=TaskAttachment.objects.select_related("uploaded_by").order_by("-created_at", "-id"),
        ),
    )


def _can_edit_project_schedule(request, project: Project) -> bool:
    if has_task_permission(request, "tasks_admin"):
        return True
    if project.created_by_id == request.user.id:
        return True
    if _ruoli_attivi() and _ambito(request, "modificare") == "tutti":
        return True
    global_level = _request_task_user_access_level(request)
    if _task_access_allows_edit_all(global_level):
        return True
    role_level = _project_role_access_level(request, project)
    if _task_access_allows_edit_all(role_level):
        return True
    if _task_access_allows_edit_assigned(global_level) and project.tasks.filter(assigned_to=request.user).exists():
        return True
    if _task_access_allows_edit_assigned(role_level) and project.tasks.filter(assigned_to=request.user).exists():
        return True
    return False


def can_manage_project(request, project: Project) -> bool:
    if has_task_permission(request, "tasks_admin"):
        return True
    if project.created_by_id == request.user.id:
        return True
    if _ruoli_attivi() and _ambito(request, "modificare") == "tutti":
        return True
    global_level = _request_task_user_access_level(request)
    if _task_access_allows_edit_all(global_level):
        return True
    role_level = _project_role_access_level(request, project)
    return _task_access_allows_edit_all(role_level)


def _is_project_lead_for_task(user, task: Task) -> bool:
    return bool(task.project_id and task.project and task.project.created_by_id == getattr(user, "id", None))


def can_manage_task(request, task: Task) -> bool:
    if has_task_permission(request, "tasks_admin"):
        return True
    if task.created_by_id == getattr(request.user, "id", None):
        return True
    if _is_project_lead_for_task(request.user, task):
        return True
    if _ruoli_attivi():
        ambito = _ambito(request, "modificare")
        if ambito == "tutti":
            return True
        if ambito == "team":
            from core.permessi import puo_fare

            if puo_fare(request, MODULO, "modificare", task):
                return True
    global_level = _request_task_user_access_level(request)
    if _task_access_allows_edit_all(global_level):
        return True
    role_level = _task_role_access_level(request, task)
    if _task_access_allows_edit_all(role_level):
        return True
    if task.assigned_to_id == getattr(request.user, "id", None):
        return _task_access_allows_edit_assigned(global_level) or _task_access_allows_edit_assigned(role_level)
    return False


def _can_update_task_due_date(request, task: Task) -> bool:
    if has_task_permission(request, "tasks_admin"):
        return True
    if can_manage_task(request, task):
        return True
    return bool(task.assigned_to_id and task.assigned_to_id == request.user.id)
