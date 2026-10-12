"""Impostazioni e amministrazione del modulo KICK-OFF."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_or_acl_required
from core.audit import log_action
from core.legacy_models import UtenteLegacy
from core.legacy_utils import sync_django_user_from_legacy
from core.models import AuditLog, Profile
from core.notifiche import invia_notifica
from core.module_branding import get_module_branding_context, handle_module_branding_post

from ..forms import (
    etichetta_utente,
    task_active_users_queryset,
)
from ..models import (
    KickoffMeeting,
    MeetingAgendaTemplate,
    Project,
    TaskAccessLevel,
    Task,
    TaskCategory,
    TaskCategoryField,
    TaskCategoryFieldType,
    TaskImpostazioni,
    TaskReminder,
    TaskRoleAssignment,
    TaskRoleAccessRule,
    TaskRoleDefinition,
    TaskRoleType,
    TaskStatus,
    TaskUserAccessRule,
)
from ..services.agenda import (
    _parse_agenda_template_items,
)
from ._shared import (
    _coerce_positive_int,
    _tasks_shell_context,
)

logger = logging.getLogger(__name__)
User = get_user_model()

SYSTEM_TASK_ROLE_DEFINITIONS = (
    (TaskRoleType.PROJECT_MANAGER, "Project manager", "Ruolo collegato al campo Project manager del kickoff.", 10),
    (TaskRoleType.CAPO_COMMESSA, "Capocommessa", "Ruolo collegato al campo Capocommessa del kickoff.", 20),
    (TaskRoleType.PROGRAMMER, "Programmatore", "Ruolo collegato al campo Programmatore del kickoff.", 30),
)
TASK_SETTINGS_TABS = ("config", "riepilogo", "record", "log", "ruoli", "accessi", "promemoria", "tipi", "modelli")


def _normalize_tasks_settings_tab(raw_tab: str | None, *, default: str = "config") -> str:
    tab = str(raw_tab or "").strip().lower()
    if tab in TASK_SETTINGS_TABS:
        return tab
    return default


def _ensure_system_task_roles() -> None:
    for code, name, description, order_index in SYSTEM_TASK_ROLE_DEFINITIONS:
        role, created = TaskRoleDefinition.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "is_system": True,
                "is_active": True,
                "order_index": order_index,
            },
        )
        if not created and not role.is_system:
            role.is_system = True
            role.save(update_fields=["is_system", "updated_at"])


def _task_role_definitions(*, include_inactive: bool = False) -> list[TaskRoleDefinition]:
    _ensure_system_task_roles()
    qs = TaskRoleDefinition.objects.all()
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("order_index", "name", "id"))


def _task_role_label_map() -> dict[str, str]:
    return {role.code: role.name for role in _task_role_definitions(include_inactive=True)}


def _filter_task_user_rows(users, query: str):
    users = list(users)
    query = str(query or "").strip().casefold()
    if not query:
        return users

    legacy_ids = []
    for user in users:
        profile = getattr(user, "profile", None)
        legacy_user_id = getattr(profile, "legacy_user_id", None) if profile is not None else None
        if legacy_user_id:
            legacy_ids.append(legacy_user_id)

    legacy_by_id = {}
    if legacy_ids:
        try:
            legacy_by_id = {
                row["id"]: row
                for row in UtenteLegacy.objects.filter(id__in=legacy_ids).values("id", "nome", "email", "ruolo")
            }
        except DatabaseError:
            legacy_by_id = {}

    def _haystack(user) -> str:
        parts = [
            user.get_full_name(),
            getattr(user, "first_name", ""),
            getattr(user, "last_name", ""),
            getattr(user, "username", ""),
            getattr(user, "email", ""),
        ]
        profile = getattr(user, "profile", None)
        if profile is not None:
            legacy_user_id = getattr(profile, "legacy_user_id", None)
            parts.append(str(legacy_user_id or ""))
            legacy_row = legacy_by_id.get(legacy_user_id)
            if legacy_row:
                parts.extend([legacy_row.get("nome"), legacy_row.get("email"), legacy_row.get("ruolo")])
        return " ".join(str(part or "") for part in parts).casefold()

    return [user for user in users if query in _haystack(user)]


def _task_settings_users_queryset():
    """Utenti visibili nelle impostazioni task, sincronizzati dal legacy.

    La schermata admin utenti mostra `utenti` legacy; le assegnazioni task usano
    invece FK Django. Qui creiamo/aggiorniamo i corrispondenti auth_user mancanti
    solo per le pagine impostazioni, cosi' la matrice ruoli resta completa.
    """
    try:
        active_legacy_users = list(
            UtenteLegacy.objects.filter(attivo=True).only("id", "nome", "email", "ruolo", "ruolo_id")
        )
    except DatabaseError:
        return task_active_users_queryset()

    if not active_legacy_users:
        return task_active_users_queryset()

    active_legacy_ids = [int(user.id) for user in active_legacy_users]
    mapped_ids = set(
        Profile.objects.filter(legacy_user_id__in=active_legacy_ids).values_list("legacy_user_id", flat=True)
    )
    for legacy_user in active_legacy_users:
        if int(legacy_user.id) in mapped_ids:
            continue
        try:
            sync_django_user_from_legacy(legacy_user)
        except Exception:
            logger.exception(
                "Impossibile sincronizzare utente legacy task legacy_user_id=%s",
                getattr(legacy_user, "id", None),
            )

    return task_active_users_queryset()


def _build_tasks_settings_context(request, *, tab: str) -> dict:
    from django.core.paginator import Paginator

    today = timezone.localdate()
    total_tasks = Task.objects.count()
    total_projects = Project.objects.count()
    tasks_by_status_raw = dict(Task.objects.values_list("status").annotate(n=Count("id")).order_by())
    tasks_overdue = Task.objects.filter(
        due_date__lt=today,
        status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS],
    ).count()

    context: dict[str, object] = {
        "tab": tab,
        "total_tasks": total_tasks,
        "total_projects": total_projects,
        "tasks_overdue": tasks_overdue,
        "todo_count": tasks_by_status_raw.get(TaskStatus.TODO, 0),
        "in_progress_count": tasks_by_status_raw.get(TaskStatus.IN_PROGRESS, 0),
        "done_count": tasks_by_status_raw.get(TaskStatus.DONE, 0),
    }

    if tab == "config":
        cfg_cc = TaskImpostazioni.get_singleton()
        scelti = set(cfg_cc.cc_predefiniti_utenti.values_list("pk", flat=True))
        context["cc_predefiniti_ids"] = scelti
        context["cc_utenti_disponibili"] = [
            {"pk": utente.pk, "etichetta": etichetta_utente(utente)}
            for utente in task_active_users_queryset()
        ]

    if tab == "riepilogo":
        context["tasks_by_status"] = [
            (value, label, tasks_by_status_raw.get(value, 0))
            for value, label in TaskStatus.choices
        ]
        context["top_assignees"] = list(
            Task.objects.filter(assigned_to__isnull=False)
            .values("assigned_to__username")
            .annotate(n=Count("id"))
            .order_by("-n")[:10]
        )

    if tab == "record":
        q_task = request.GET.get("q_task", "").strip()
        q_proj = request.GET.get("q_proj", "").strip()
        filter_status = request.GET.get("filter_status", "").strip()

        tasks_qs = Task.objects.select_related("project", "assigned_to").order_by("-updated_at")
        if q_task:
            tasks_qs = tasks_qs.filter(title__icontains=q_task)
        if filter_status:
            tasks_qs = tasks_qs.filter(status=filter_status)

        projects_qs = Project.objects.prefetch_related("project_managers").order_by("-updated_at")
        if q_proj:
            projects_qs = projects_qs.filter(Q(name__icontains=q_proj) | Q(client_name__icontains=q_proj))

        context.update(
            {
                "tasks_page": Paginator(tasks_qs, 50).get_page(request.GET.get("task_page")),
                "projects_page": Paginator(projects_qs, 50).get_page(request.GET.get("proj_page")),
                "q_task": q_task,
                "q_proj": q_proj,
                "filter_status": filter_status,
                "task_status_choices": TaskStatus.choices,
            }
        )

    if tab == "log":
        context["audit_entries"] = AuditLog.objects.filter(modulo="tasks").order_by("-created_at")[:100]

    if tab == "modelli":
        context["agenda_templates"] = list(MeetingAgendaTemplate.objects.all())

    if tab == "ruoli":
        cfg = TaskImpostazioni.get_singleton()
        roles_source = cfg.roles_source
        role_definitions = _task_role_definitions(include_inactive=True)
        ruoli_filter_q = request.GET.get("q_user", "").strip()
        all_users = list(_task_settings_users_queryset())
        filtered_users = _filter_task_user_rows(all_users, ruoli_filter_q)
        assignments_raw = list(
            TaskRoleAssignment.objects.values_list("user_id", "role_type")
        )
        by_user: dict[int, set[str]] = {}
        for uid, rtype in assignments_raw:
            by_user.setdefault(uid, set()).add(rtype)

        # In modalità anagrafica, CR (Caporeparto) è derivato dai Reparti
        cr_anagrafica_ids: set[int] = set()
        if roles_source == "anagrafica":
            try:
                from anagrafica.models import Reparto
                legacy_ids = set(
                    Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False)
                    .exclude(caporeparto_legacy_id=0)
                    .values_list("caporeparto_legacy_id", flat=True)
                )
                if legacy_ids:
                    cr_anagrafica_ids = set(
                        User.objects.filter(
                            profile__legacy_user_id__in=legacy_ids, is_active=True
                        ).values_list("id", flat=True)
                    )
            except Exception:
                pass

        roster = []
        for u in filtered_users:
            user_label = (u.get_full_name() or u.username)
            assigned_roles = by_user.get(u.id, set())
            role_cells = []
            for role in role_definitions:
                if role.code == "CR" and roles_source == "anagrafica":
                    role_cells.append({
                        "code": role.code,
                        "checked": u.id in cr_anagrafica_ids,
                        "readonly": True,
                    })
                else:
                    role_cells.append({
                        "code": role.code,
                        "checked": role.code in assigned_roles,
                        "readonly": False,
                    })
            roster.append({
                "id": u.id,
                "label": user_label,
                "email": u.email or "",
                "role_cells": role_cells,
            })
        context.update({
            "ruoli_filter_q": ruoli_filter_q,
            "ruoli_roster": roster,
            "ruoli_role_definitions": role_definitions,
            "ruoli_colspan": 2 + len(role_definitions),
            "ruoli_source": roles_source,
            "ruoli_stats": {
                "roles": len(role_definitions),
                "assignments": sum(len(v) for v in by_user.values()),
                "total_users": len(all_users),
                "filtered_users": len(roster),
            },
        })

    if tab == "accessi":
        role_definitions = _task_role_definitions(include_inactive=True)
        access_filter_q = request.GET.get("q_access_user", "").strip()
        all_users = list(_task_settings_users_queryset())
        filtered_users = _filter_task_user_rows(all_users, access_filter_q)
        role_rule_map = {
            role_type: access_level
            for role_type, access_level in TaskRoleAccessRule.objects.values_list("role_type", "access_level")
        }
        user_rule_map = {
            user_id: access_level
            for user_id, access_level in TaskUserAccessRule.objects.values_list("user_id", "access_level")
        }
        context.update(
            {
                "access_filter_q": access_filter_q,
                "access_role_rows": [
                    {
                        "code": role.code,
                        "label": role.name,
                        "help": role.description or (
                            "Valida sui task dei tipi associati a questo ruolo."
                        ),
                        "is_system": role.is_system,
                        "access_level": role_rule_map.get(role.code, TaskAccessLevel.NONE),
                    }
                    for role in role_definitions
                ],
                "access_user_rows": [
                    {
                        "id": user.id,
                        "label": user.get_full_name() or user.username,
                        "email": user.email or "",
                        "access_level": user_rule_map.get(user.id, ""),
                    }
                    for user in filtered_users
                ],
                "access_role_choices": [
                    (TaskAccessLevel.NONE, "Nessun accesso extra"),
                    (TaskAccessLevel.READ_ALL, "Vede tutti i task del kickoff"),
                    (TaskAccessLevel.EDIT_ASSIGNED, "Vede tutto + modifica solo i task assegnati"),
                    (TaskAccessLevel.EDIT_ALL, "Vede e modifica tutto il kickoff"),
                ],
                "access_user_choices": [
                    ("", "Eredita scope standard"),
                    (TaskAccessLevel.READ_ALL, "Vede tutto il modulo"),
                    (TaskAccessLevel.EDIT_ASSIGNED, "Vede tutto + modifica solo i task assegnati"),
                    (TaskAccessLevel.EDIT_ALL, "Vede e modifica tutto il modulo"),
                ],
                "access_stats": {
                    "role_rules": len(role_rule_map),
                    "user_overrides": len(user_rule_map),
                    "edit_all_roles": sum(1 for level in role_rule_map.values() if level == TaskAccessLevel.EDIT_ALL),
                    "edit_all_users": sum(1 for level in user_rule_map.values() if level == TaskAccessLevel.EDIT_ALL),
                    "total_users": len(all_users),
                    "filtered_users": len(filtered_users),
                },
            }
        )

    if tab == "promemoria":
        q_filter = (request.GET.get("filter_status") or "pending").strip().lower()
        qs = (
            TaskReminder.objects.select_related("task", "task__project", "task__assigned_to")
            .order_by("fire_at", "id")
        )
        if q_filter == "pending":
            qs = qs.filter(fired=False)
        elif q_filter == "fired":
            qs = qs.filter(fired=True)
        # else: all

        today = timezone.localdate()
        reminders_list = []
        for r in qs[:200]:
            reminders_list.append({
                "id": r.id,
                "task_id": r.task_id,
                "task_title": r.task.title if r.task else "(task eliminato)",
                "project_name": (r.task.project.name if r.task and r.task.project_id else ""),
                "assignee": (
                    r.task.assigned_to.get_full_name() or r.task.assigned_to.username
                ) if r.task and r.task.assigned_to_id else "",
                "legacy_user_id": r.legacy_user_id,
                "fire_at": r.fire_at,
                "due_date": r.task.due_date if r.task else None,
                "fired": r.fired,
                "fired_at": r.fired_at,
                "overdue": (not r.fired) and r.fire_at < today,
            })
        context.update({
            "promemoria_filter": q_filter,
            "promemoria_list": reminders_list,
            "promemoria_count_pending": TaskReminder.objects.filter(fired=False).count(),
            "promemoria_count_fired":   TaskReminder.objects.filter(fired=True).count(),
            "promemoria_count_overdue": TaskReminder.objects.filter(fired=False, fire_at__lt=today).count(),
            "promemoria_count_next7":   TaskReminder.objects.filter(
                fired=False, fire_at__gte=today, fire_at__lte=today + timedelta(days=7),
            ).count(),
        })

    if tab == "tipi":
        role_definitions = _task_role_definitions(include_inactive=True)
        categories = list(
            TaskCategory.objects.prefetch_related("fields").order_by("order_index", "name")
        )
        focus_id_raw = (request.GET.get("cat") or "").strip()
        focus_category = None
        try:
            focus_id = int(focus_id_raw)
        except (TypeError, ValueError):
            focus_id = 0
        if focus_id:
            for cat in categories:
                if cat.id == focus_id:
                    focus_category = cat
                    break
        if focus_category is None and categories:
            focus_category = categories[0]

        asset_type_choices: list[tuple[str, str]] = []
        asset_categories: list[dict] = []
        try:
            from assets.models import Asset, AssetCategory
            asset_type_choices = list(Asset.TYPE_CHOICES)
            asset_categories = [
                {"id": c.id, "label": getattr(c, "label", "") or c.code}
                for c in AssetCategory.objects.filter(is_active=True).order_by("sort_order", "label", "id")
            ]
        except Exception:
            pass
        context.update({
            "tipi_categories": categories,
            "tipi_focus_category": focus_category,
            "tipi_field_types": TaskCategoryFieldType.choices,
            "tipi_role_choices": [("", "Nessun ruolo dedicato")] + [
                (role.code, role.name) for role in role_definitions if role.is_active
            ],
            "tipi_role_label_map": _task_role_label_map(),
            "tipi_tasks_with_category": Task.objects.filter(category__isnull=False).count(),
            "tipi_asset_type_choices": asset_type_choices,
            "tipi_asset_categories": asset_categories,
        })

    return context


@legacy_admin_or_acl_required("tasks", "gestione_admin")
def gestione_admin(request):
    """Compat legacy: la vecchia gestione admin confluisce nelle impostazioni."""
    params = request.GET.copy()
    params["tab"] = _normalize_tasks_settings_tab(params.get("tab"), default="riepilogo")
    target_url = reverse("tasks:impostazioni")
    query_string = params.urlencode()
    if query_string:
        target_url = f"{target_url}?{query_string}"
    return redirect(target_url)


def _handle_tasks_roles_post(request):
    """POST tab ruoli: set completo delle assegnazioni ricalcolato dal form."""
    target_url = f"{reverse('tasks:impostazioni')}?tab=ruoli"
    q_user = request.POST.get("q_user", "").strip()
    if q_user:
        target_url = f"{target_url}&q_user={q_user}"

    role_admin_action = (request.POST.get("role_admin_action") or "").strip()

    if role_admin_action == "save_source":
        new_source = (request.POST.get("roles_source") or "anagrafica").strip()
        if new_source not in ("anagrafica", "manual"):
            new_source = "anagrafica"
        cfg = TaskImpostazioni.get_singleton()
        old_source = cfg.roles_source
        cfg.roles_source = new_source
        cfg.save(update_fields=["roles_source"])
        if new_source == "anagrafica" and old_source != "anagrafica":
            # Sincronizza le assegnazioni CR dai Reparti
            try:
                from anagrafica.models import Reparto
                legacy_ids = set(
                    Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=False)
                    .exclude(caporeparto_legacy_id=0)
                    .values_list("caporeparto_legacy_id", flat=True)
                )
                cr_user_ids = set(
                    User.objects.filter(
                        profile__legacy_user_id__in=legacy_ids, is_active=True
                    ).values_list("id", flat=True)
                ) if legacy_ids else set()
                with transaction.atomic():
                    TaskRoleAssignment.objects.filter(role_type="CR").delete()
                    TaskRoleAssignment.objects.bulk_create([
                        TaskRoleAssignment(user_id=uid, role_type="CR")
                        for uid in cr_user_ids
                    ])
            except Exception:
                pass
        log_action(request, "ruoli_source_modificata", "tasks", {
            "message": f"Fonte ruoli cambiata: {old_source} → {new_source}",
        })
        label = "Da anagrafica" if new_source == "anagrafica" else "Manuale"
        messages.success(request, f"Fonte ruoli impostata su «{label}».")
        return redirect(target_url)

    if role_admin_action == "create_role":
        name = (request.POST.get("role_name") or "").strip()
        description = (request.POST.get("role_description") or "").strip()[:255]
        if not name:
            messages.error(request, "Indica il nome del nuovo ruolo.")
            return redirect(target_url)
        base_code = slugify(name).upper().replace("-", "_")[:32] or "RUOLO"
        code = base_code
        n = 2
        while TaskRoleDefinition.objects.filter(code=code).exists():
            suffix = f"_{n}"
            code = f"{base_code[:32 - len(suffix)]}{suffix}"
            n += 1
        max_order = TaskRoleDefinition.objects.aggregate(m=Max("order_index")).get("m") or 30
        role = TaskRoleDefinition.objects.create(
            code=code,
            name=name[:80],
            description=description,
            is_system=False,
            is_active=True,
            order_index=max_order + 10,
        )
        log_action(request, "ruolo_creato", "tasks", {"message": f"Creato ruolo operativo {role.name}", "role": role.code})
        messages.success(request, f"Ruolo '{role.name}' creato.")
        return redirect(target_url)

    if role_admin_action == "delete_role":
        role_code = (request.POST.get("role_code") or "").strip()
        try:
            role = TaskRoleDefinition.objects.get(code=role_code, is_system=False)
        except TaskRoleDefinition.DoesNotExist:
            messages.error(request, "Ruolo non eliminabile o non trovato.")
            return redirect(target_url)
        role_name = role.name
        with transaction.atomic():
            TaskRoleAssignment.objects.filter(role_type=role.code).delete()
            TaskRoleAccessRule.objects.filter(role_type=role.code).delete()
            TaskCategory.objects.filter(role_type=role.code).update(role_type="")
            role.delete()
        log_action(request, "ruolo_eliminato", "tasks", {"message": f"Eliminato ruolo operativo {role_name}", "role": role_code})
        messages.success(request, f"Ruolo '{role_name}' eliminato.")
        return redirect(target_url)

    cfg_source = TaskImpostazioni.get_singleton().roles_source
    valid_role_codes = {role.code for role in _task_role_definitions(include_inactive=False)}

    # raccoglie tutti i checkbox inviati: name="role__<ROLE_CODE>__<user_id>"
    desired: set[tuple[int, str]] = set()
    for key in request.POST:
        if not key.startswith("role__"):
            continue
        parts = key.split("__")
        if len(parts) != 3:
            continue
        _, role_code, uid_raw = parts
        if role_code not in valid_role_codes:
            continue
        # In modalità anagrafica i checkbox CR sono read-only: ignorati dal form
        if role_code == "CR" and cfg_source == "anagrafica":
            continue
        try:
            uid = int(uid_raw)
        except (TypeError, ValueError):
            continue
        desired.add((uid, role_code))

    # valutiamo solo gli utenti visibili nel form (non tocchiamo utenti filtrati fuori)
    visible_uids = [int(x) for x in request.POST.getlist("visible_user_id")]
    if not visible_uids:
        messages.warning(request, "Nessun utente visibile: nessuna modifica ai ruoli.")
        return redirect(target_url)

    # delete + recreate (diff sul subset visible)
    existing_qs = TaskRoleAssignment.objects.filter(user_id__in=visible_uids)
    # In modalità anagrafica, le assegnazioni CR non vengono toccate dal form manuale
    if cfg_source == "anagrafica":
        existing_qs = existing_qs.exclude(role_type="CR")
    existing = set(existing_qs.values_list("user_id", "role_type"))
    to_add = {pair for pair in desired if pair[0] in visible_uids} - existing
    to_remove = existing - {pair for pair in desired if pair[0] in visible_uids}

    with transaction.atomic():
        if to_remove:
            q = Q()
            for uid, rtype in to_remove:
                q |= Q(user_id=uid, role_type=rtype)
            TaskRoleAssignment.objects.filter(q).delete()
        TaskRoleAssignment.objects.bulk_create([
            TaskRoleAssignment(user_id=uid, role_type=rtype)
            for uid, rtype in to_add
        ])

    log_action(request, "ruoli_aggiornati", "tasks", {
        "message": f"Aggiornati ruoli operativi kickoff: +{len(to_add)} -{len(to_remove)}",
        "added": sorted(to_add),
        "removed": sorted(to_remove),
    })
    messages.success(
        request,
        f"Ruoli aggiornati: +{len(to_add)} aggiunti, {len(to_remove)} rimossi.",
    )
    return redirect(target_url)


def _handle_tasks_access_post(request):
    """POST tab accessi: regole ruolo operativo + override singolo utente."""
    from urllib.parse import urlencode

    params = {"tab": "accessi"}
    q_user = request.POST.get("q_access_user", "").strip()
    if q_user:
        params["q_access_user"] = q_user
    target_url = f"{reverse('tasks:impostazioni')}?{urlencode(params)}"

    valid_role_values = {
        TaskAccessLevel.NONE,
        TaskAccessLevel.READ_ALL,
        TaskAccessLevel.EDIT_ASSIGNED,
        TaskAccessLevel.EDIT_ALL,
    }
    valid_user_values = {
        TaskAccessLevel.READ_ALL,
        TaskAccessLevel.EDIT_ASSIGNED,
        TaskAccessLevel.EDIT_ALL,
    }

    role_updates: dict[str, str] = {}
    for role in _task_role_definitions(include_inactive=False):
        role_code = role.code
        raw_value = (request.POST.get(f"access_role__{role_code}") or TaskAccessLevel.NONE).strip()
        role_updates[role_code] = raw_value if raw_value in valid_role_values else TaskAccessLevel.NONE

    existing_role_map = {
        role_type: access_level
        for role_type, access_level in TaskRoleAccessRule.objects.values_list("role_type", "access_level")
    }
    role_changes = 0
    with transaction.atomic():
        for role_code, desired_level in role_updates.items():
            current_level = existing_role_map.get(role_code)
            if desired_level == TaskAccessLevel.NONE:
                if current_level is not None:
                    TaskRoleAccessRule.objects.filter(role_type=role_code).delete()
                    role_changes += 1
                continue
            if current_level != desired_level:
                TaskRoleAccessRule.objects.update_or_create(
                    role_type=role_code,
                    defaults={"access_level": desired_level},
                )
                role_changes += 1

        visible_uids: list[int] = []
        for raw_uid in request.POST.getlist("visible_access_user_id"):
            try:
                visible_uids.append(int(raw_uid))
            except (TypeError, ValueError):
                continue
        visible_uids = sorted(set(visible_uids))

        existing_user_map = {
            user_id: access_level
            for user_id, access_level in TaskUserAccessRule.objects.filter(user_id__in=visible_uids).values_list("user_id", "access_level")
        }
        desired_user_map: dict[int, str] = {}
        for user_id in visible_uids:
            raw_value = (request.POST.get(f"access_user__{user_id}") or "").strip()
            if raw_value in valid_user_values:
                desired_user_map[user_id] = raw_value

        user_changes = 0
        to_remove = sorted(set(existing_user_map) - set(desired_user_map))
        if to_remove:
            TaskUserAccessRule.objects.filter(user_id__in=to_remove).delete()
            user_changes += len(to_remove)

        for user_id, desired_level in desired_user_map.items():
            if existing_user_map.get(user_id) == desired_level:
                continue
            TaskUserAccessRule.objects.update_or_create(
                user_id=user_id,
                defaults={"access_level": desired_level},
            )
            user_changes += 1

    log_action(
        request,
        "accessi_aggiornati",
        "tasks",
        {
            "message": (
                f"Aggiornate regole accesso KICK-OFF: {role_changes} regole ruolo, "
                f"{user_changes} override utente."
            ),
            "role_updates": role_updates,
            "visible_users": visible_uids,
        },
    )
    messages.success(
        request,
        f"Regole accesso aggiornate: {role_changes} ruoli, {user_changes} override utente.",
    )
    return redirect(target_url)


def _handle_tasks_reminders_post(request):
    """POST tab promemoria: azioni su TaskReminder (delete/postpone/fire_now)."""
    target_url = f"{reverse('tasks:impostazioni')}?tab=promemoria"
    filter_status = (request.POST.get("filter_status") or "").strip()
    if filter_status:
        target_url = f"{target_url}&filter_status={filter_status}"

    action = (request.POST.get("reminder_action") or "").strip()
    ids_raw = request.POST.getlist("reminder_id")
    ids: list[int] = []
    for r in ids_raw:
        try:
            ids.append(int(r))
        except (TypeError, ValueError):
            pass

    if not ids:
        messages.warning(request, "Nessun promemoria selezionato.")
        return redirect(target_url)

    qs = TaskReminder.objects.filter(id__in=ids)

    if action == "delete":
        n = qs.count()
        qs.delete()
        log_action(request, "reminder_eliminati", "tasks", {
            "message": f"Eliminati {n} promemoria kickoff",
            "ids": ids,
        })
        messages.success(request, f"{n} promemoria eliminati.")
        return redirect(target_url)

    if action == "postpone":
        try:
            days = max(1, int(request.POST.get("postpone_days") or 0))
        except (TypeError, ValueError):
            days = 0
        if not days:
            messages.error(request, "Specifica il numero di giorni di rinvio.")
            return redirect(target_url)
        updated = 0
        for rem in qs.filter(fired=False):
            rem.fire_at = rem.fire_at + timedelta(days=days)
            rem.save(update_fields=["fire_at"])
            updated += 1
        log_action(request, "reminder_rimandati", "tasks", {
            "message": f"Rimandati {updated} promemoria kickoff di {days} giorni",
            "ids": ids,
            "days": days,
        })
        messages.success(request, f"{updated} promemoria rimandati di {days} giorni.")
        return redirect(target_url)

    if action == "fire_now":
        fired = 0
        skipped = 0
        for rem in qs.select_related("task", "task__project").filter(fired=False):
            task = rem.task
            if task is None:
                rem.fired = True
                rem.fired_at = timezone.now()
                rem.save(update_fields=["fired", "fired_at"])
                skipped += 1
                continue
            if task.status in {TaskStatus.DONE, TaskStatus.CANCELED}:
                rem.fired = True
                rem.fired_at = timezone.now()
                rem.save(update_fields=["fired", "fired_at"])
                skipped += 1
                continue
            project_label = f" [{task.project.name}]" if task.project_id and task.project else ""
            due_str = task.due_date.strftime("%d-%m-%Y") if task.due_date else "(senza data)"
            message_text = (
                f"Promemoria scadenza attivita kickoff: \"{task.title}\"{project_label} "
                f"in scadenza il {due_str}."
            )[:500]
            invia_notifica(
                int(rem.legacy_user_id or 0),
                "task",
                message_text,
                reverse("tasks:detail", args=[task.id]),
            )
            rem.fired = True
            rem.fired_at = timezone.now()
            rem.save(update_fields=["fired", "fired_at"])
            fired += 1
        log_action(request, "reminder_forzati", "tasks", {
            "message": f"Forzato invio di {fired} promemoria kickoff ({skipped} saltati)",
            "ids": ids,
        })
        messages.success(request, f"Inviati {fired} promemoria ({skipped} saltati).")
        return redirect(target_url)

    messages.error(request, "Azione non riconosciuta.")
    return redirect(target_url)


def _handle_tasks_agenda_templates_post(request):
    """POST tab modelli: CRUD dei modelli di ordine del giorno."""
    action = (request.POST.get("tpl_action") or "").strip()
    base_url = f"{reverse('tasks:impostazioni')}?tab=modelli"

    if action == "template_create":
        nome = (request.POST.get("nome") or "").strip()
        if not nome:
            messages.error(request, "Indica un nome per il modello.")
            return redirect(base_url)
        if MeetingAgendaTemplate.objects.filter(nome=nome[:120]).exists():
            messages.error(request, f"Esiste già un modello chiamato «{nome}».")
            return redirect(base_url)
        max_order = MeetingAgendaTemplate.objects.aggregate(m=Max("order_index")).get("m") or 0
        template = MeetingAgendaTemplate.objects.create(
            nome=nome[:120],
            descrizione=(request.POST.get("descrizione") or "").strip()[:255],
            items=_parse_agenda_template_items(request.POST.get("items_text") or ""),
            order_index=max_order + 10,
            created_by=request.user if request.user.is_authenticated else None,
        )
        log_action(request, "modello_odg_creato", "tasks", {
            "template_id": template.pk, "nome": template.nome,
        })
        messages.success(request, f"Modello «{template.nome}» creato.")
        return redirect(base_url)

    if action == "template_update":
        try:
            template = MeetingAgendaTemplate.objects.get(pk=int(request.POST.get("template_id") or 0))
        except (MeetingAgendaTemplate.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Modello non trovato.")
            return redirect(base_url)
        nome = (request.POST.get("nome") or "").strip()
        if not nome:
            messages.error(request, "Il nome del modello è obbligatorio.")
            return redirect(base_url)
        template.nome = nome[:120]
        template.descrizione = (request.POST.get("descrizione") or "").strip()[:255]
        template.items = _parse_agenda_template_items(request.POST.get("items_text") or "")
        template.is_active = bool(request.POST.get("is_active"))
        try:
            template.order_index = max(0, int(request.POST.get("order_index") or 0))
        except (TypeError, ValueError):
            pass
        template.save()
        log_action(request, "modello_odg_modificato", "tasks", {
            "template_id": template.pk, "nome": template.nome,
        })
        messages.success(request, f"Modello «{template.nome}» aggiornato.")
        return redirect(base_url)

    if action == "template_delete":
        try:
            template = MeetingAgendaTemplate.objects.get(pk=int(request.POST.get("template_id") or 0))
        except (MeetingAgendaTemplate.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Modello non trovato.")
            return redirect(base_url)
        nome = template.nome
        template.delete()
        log_action(request, "modello_odg_eliminato", "tasks", {"nome": nome})
        messages.success(request, f"Modello «{nome}» eliminato.")
        return redirect(base_url)

    messages.error(request, "Azione non valida.")
    return redirect(base_url)


def _handle_tasks_categories_post(request):
    """POST tab tipi: CRUD TaskCategory + TaskCategoryField."""
    action = (request.POST.get("cat_action") or "").strip()
    base_url = f"{reverse('tasks:impostazioni')}?tab=tipi"

    def _url_for(category=None):
        if category is not None:
            return f"{base_url}&cat={category.id}"
        return base_url

    def _unique_slug(base: str, exclude_pk: int | None = None) -> str:
        candidate = slugify(base) or "tipo"
        candidate = candidate[:120]
        n = 2
        root = candidate
        while TaskCategory.objects.exclude(pk=exclude_pk or 0).filter(slug=candidate).exists():
            candidate = f"{root}-{n}"[:120]
            n += 1
        return candidate

    valid_field_types = {value for value, _ in TaskCategoryFieldType.choices}
    valid_role_codes = {role.code for role in _task_role_definitions(include_inactive=False)}

    def _clean_category_role() -> str:
        raw_role = (request.POST.get("role_type") or "").strip()
        return raw_role if raw_role in valid_role_codes else ""

    if action == "category_create":
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Indica un nome per il tipo attivita.")
            return redirect(_url_for())
        description = (request.POST.get("description") or "").strip()
        icon = (request.POST.get("icon") or "").strip()
        max_order = TaskCategory.objects.aggregate(m=Max("order_index")).get("m") or 0
        category = TaskCategory.objects.create(
            name=name[:120],
            slug=_unique_slug(name),
            description=description[:255],
            icon=icon[:80],
            role_type=_clean_category_role(),
            order_index=max_order + 10,
            is_machine_work=bool(request.POST.get("is_machine_work")),
        )
        log_action(request, "tipo_creato", "tasks", {
            "message": f"Creato tipo attivita '{category.name}'",
            "category_id": category.id,
        })
        messages.success(request, f"Tipo '{category.name}' creato.")
        return redirect(_url_for(category))

    if action == "category_update":
        try:
            category = TaskCategory.objects.get(pk=int(request.POST.get("category_id") or 0))
        except (TaskCategory.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Tipo attivita non trovato.")
            return redirect(_url_for())
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Il nome del tipo e' obbligatorio.")
            return redirect(_url_for(category))
        category.name = name[:120]
        category.description = (request.POST.get("description") or "").strip()[:255]
        category.icon = (request.POST.get("icon") or "").strip()[:80]
        category.role_type = _clean_category_role()
        category.is_active = bool(request.POST.get("is_active"))
        category.is_machine_work = bool(request.POST.get("is_machine_work"))
        try:
            category.order_index = max(0, int(request.POST.get("order_index") or 0))
        except (TypeError, ValueError):
            pass
        category.save()
        log_action(request, "tipo_modificato", "tasks", {
            "message": f"Modificato tipo attivita '{category.name}'",
            "category_id": category.id,
        })
        messages.success(request, "Tipo aggiornato.")
        return redirect(_url_for(category))

    if action == "category_delete":
        try:
            category = TaskCategory.objects.get(pk=int(request.POST.get("category_id") or 0))
        except (TaskCategory.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Tipo attivita non trovato.")
            return redirect(_url_for())
        name = category.name
        in_use = Task.objects.filter(category_id=category.id).count()
        category.delete()
        log_action(request, "tipo_eliminato", "tasks", {
            "message": f"Eliminato tipo attivita '{name}' (attivita collegate: {in_use})",
        })
        messages.success(request, f"Tipo '{name}' eliminato ({in_use} attivita scollegate).")
        return redirect(_url_for())

    if action in {"field_create", "field_update", "field_delete"}:
        try:
            category = TaskCategory.objects.get(pk=int(request.POST.get("category_id") or 0))
        except (TaskCategory.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Tipo attivita non trovato.")
            return redirect(_url_for())

        if action == "field_delete":
            try:
                field = TaskCategoryField.objects.get(pk=int(request.POST.get("field_id") or 0), category=category)
            except (TaskCategoryField.DoesNotExist, TypeError, ValueError):
                messages.error(request, "Campo non trovato.")
                return redirect(_url_for(category))
            label = field.label
            field.delete()
            log_action(request, "tipo_campo_eliminato", "tasks", {
                "message": f"Eliminato campo '{label}' dal tipo '{category.name}'",
                "category_id": category.id,
            })
            messages.success(request, f"Campo '{label}' eliminato.")
            return redirect(_url_for(category))

        label = (request.POST.get("label") or "").strip()
        code = (request.POST.get("code") or "").strip()
        field_type = (request.POST.get("field_type") or "").strip()
        if field_type not in valid_field_types:
            messages.error(request, "Tipo di campo non valido.")
            return redirect(_url_for(category))
        if not label:
            messages.error(request, "La label del campo e' obbligatoria.")
            return redirect(_url_for(category))
        if not code:
            code = slugify(label)[:60] or "campo"
        else:
            code = slugify(code)[:60] or "campo"
        required = bool(request.POST.get("required"))
        help_text = (request.POST.get("help_text") or "").strip()[:255]
        placeholder = (request.POST.get("placeholder") or "").strip()[:120]
        depends_on_code = slugify(request.POST.get("depends_on_code") or "")[:60]
        depends_on_value = (request.POST.get("depends_on_value") or "").strip()[:255]
        try:
            order_index = max(0, int(request.POST.get("order_index") or 0))
        except (TypeError, ValueError):
            order_index = 0

        asset_type_filter = ",".join(
            [v.strip() for v in request.POST.getlist("asset_type_filter_multi") if v.strip()]
        )[:255]
        asset_category_filter_raw = request.POST.getlist("asset_category_filter_multi")
        asset_category_filter_ids: list[str] = []
        for v in asset_category_filter_raw:
            v = (v or "").strip()
            if not v:
                continue
            try:
                asset_category_filter_ids.append(str(int(v)))
            except (TypeError, ValueError):
                continue
        asset_category_filter = ",".join(asset_category_filter_ids)[:255]

        choices_raw = (request.POST.get("choices_raw") or "").strip()
        choices_json: list[dict[str, str]] = []
        if field_type in {TaskCategoryFieldType.SELECT, TaskCategoryFieldType.MULTISELECT}:
            for line in choices_raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                if "|" in line:
                    value, label_choice = line.split("|", 1)
                    value = value.strip()
                    label_choice = label_choice.strip() or value
                else:
                    value = line
                    label_choice = line
                if value:
                    choices_json.append({"value": value[:120], "label": label_choice[:180]})

        if action == "field_create":
            # unique code per category
            base_code = code
            n = 2
            while TaskCategoryField.objects.filter(category=category, code=code).exists():
                code = f"{base_code}-{n}"[:60]
                n += 1
            max_order = TaskCategoryField.objects.filter(category=category).aggregate(
                m=Max("order_index")
            ).get("m") or 0
            TaskCategoryField.objects.create(
                category=category,
                code=code,
                label=label[:180],
                field_type=field_type,
                required=required,
                order_index=order_index or (max_order + 10),
                help_text=help_text,
                placeholder=placeholder,
                choices_json=choices_json,
                depends_on_code=depends_on_code,
                depends_on_value=depends_on_value,
                asset_type_filter=asset_type_filter if field_type == TaskCategoryFieldType.ASSET else "",
                asset_category_filter=asset_category_filter if field_type == TaskCategoryFieldType.ASSET else "",
            )
            log_action(request, "tipo_campo_creato", "tasks", {
                "message": f"Aggiunto campo '{label}' al tipo '{category.name}'",
                "category_id": category.id,
            })
            messages.success(request, f"Campo '{label}' aggiunto.")
            return redirect(_url_for(category))

        # field_update
        try:
            field = TaskCategoryField.objects.get(pk=int(request.POST.get("field_id") or 0), category=category)
        except (TaskCategoryField.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Campo non trovato.")
            return redirect(_url_for(category))
        # permetti cambio code solo se non confligge
        if code != field.code:
            if TaskCategoryField.objects.filter(category=category, code=code).exclude(pk=field.pk).exists():
                messages.error(request, f"Codice '{code}' gia in uso.")
                return redirect(_url_for(category))
            field.code = code
        field.label = label[:180]
        field.field_type = field_type
        field.required = required
        field.help_text = help_text
        field.placeholder = placeholder
        field.depends_on_code = depends_on_code
        field.depends_on_value = depends_on_value
        field.choices_json = choices_json
        if field_type == TaskCategoryFieldType.ASSET:
            field.asset_type_filter = asset_type_filter
            field.asset_category_filter = asset_category_filter
        else:
            field.asset_type_filter = ""
            field.asset_category_filter = ""
        if order_index:
            field.order_index = order_index
        field.save()
        log_action(request, "tipo_campo_modificato", "tasks", {
            "message": f"Modificato campo '{label}' del tipo '{category.name}'",
            "category_id": category.id,
        })
        messages.success(request, f"Campo '{label}' aggiornato.")
        return redirect(_url_for(category))

    messages.error(request, "Azione non riconosciuta.")
    return redirect(base_url)


def _motivo_cancellazione(request) -> str:
    """Motivazione obbligatoria di una cancellazione, normalizzata.

    Cancellare un kickoff o un'attivita' dalle impostazioni e' irreversibile e
    porta via con se' tutto quello che ci sta appeso: il perche' deve restare
    scritto nell'audit, altrimenti fra sei mesi nessuno sa cosa e' sparito ne'
    per mano di chi. Stringa vuota = motivazione mancante.
    """
    return (request.POST.get("motivo") or "").strip()[:500]


@require_POST
@legacy_admin_or_acl_required("tasks", "impostazioni")
def impostazioni_kickoff_delete(request, project_id: int):
    """Elimina un kickoff dalla scheda Record, con motivazione obbligatoria."""
    record_url = f"{reverse('tasks:impostazioni')}?tab=record"
    project = get_object_or_404(Project, pk=project_id)
    motivo = _motivo_cancellazione(request)
    if not motivo:
        messages.error(request, "Serve la motivazione: il kickoff non e' stato eliminato.")
        return redirect(record_url)

    # I conteggi si leggono PRIMA della cancellazione: dopo il cascade non
    # resterebbe modo di dire quanto e' stato portato via.
    dettaglio = {
        "project_id": project.pk,
        "kickoff_number": project.kickoff_number,
        "name": project.name,
        "client_name": project.client_name,
        "tasks": Task.objects.filter(project=project).count(),
        "incontri": KickoffMeeting.objects.filter(project=project).count(),
        "motivo": motivo,
    }
    project.delete()
    log_action(request, "kickoff_project_delete", "tasks", dettaglio)
    messages.success(
        request,
        f"Kickoff «{dettaglio['name']}» eliminato con {dettaglio['tasks']} attivita' "
        f"e {dettaglio['incontri']} incontri collegati.",
    )
    return redirect(record_url)


@require_POST
@legacy_admin_or_acl_required("tasks", "impostazioni")
def impostazioni_task_delete(request, task_id: int):
    """Elimina un'attivita' dalla scheda Record, con motivazione obbligatoria."""
    record_url = f"{reverse('tasks:impostazioni')}?tab=record"
    task = get_object_or_404(Task.objects.select_related("project"), pk=task_id)
    motivo = _motivo_cancellazione(request)
    if not motivo:
        messages.error(request, "Serve la motivazione: l'attivita' non e' stata eliminata.")
        return redirect(record_url)

    dettaglio = {
        "task_id": task.pk,
        "title": task.title,
        "project_id": task.project_id,
        "project": getattr(task.project, "name", ""),
        "status": task.status,
        "motivo": motivo,
    }
    task.delete()
    log_action(request, "kickoff_task_delete", "tasks", dettaglio)
    messages.success(request, f"Attivita' «{dettaglio['title']}» eliminata.")
    return redirect(record_url)


@legacy_admin_or_acl_required("tasks", "impostazioni")
def impostazioni(request):
    """Pagina canonica impostazioni/admin del modulo Task."""
    cfg = TaskImpostazioni.get_singleton()
    config_url = f"{reverse('tasks:impostazioni')}?tab=config"

    if request.method == "POST":
        posted_tab = (request.POST.get("tab") or "").strip().lower()
        if posted_tab == "ruoli":
            return _handle_tasks_roles_post(request)
        if posted_tab == "accessi":
            return _handle_tasks_access_post(request)
        if posted_tab == "promemoria":
            return _handle_tasks_reminders_post(request)
        if posted_tab == "tipi":
            return _handle_tasks_categories_post(request)
        if posted_tab == "modelli":
            return _handle_tasks_agenda_templates_post(request)

        branding_response = handle_module_branding_post(
            request,
            module_key="tasks",
            redirect_to=config_url,
            audit_module="tasks",
            fallback_label="KICK-OFF",
        )
        if branding_response is not None:
            return branding_response
        cfg.responsabile_email = request.POST.get("responsabile_email", "").strip()
        cfg.notifiche_scadenza_attive = bool(request.POST.get("notifiche_scadenza_attive"))
        cfg.giorni_preavviso = _coerce_positive_int(request.POST.get("giorni_preavviso"), default=3)
        cfg.note_generali = request.POST.get("note_generali", "").strip()
        cfg.vrf_reminder_days = _coerce_positive_int(request.POST.get("vrf_reminder_days"), default=7)
        cfg.vrf_blocking_days = _coerce_positive_int(request.POST.get("vrf_blocking_days"), default=30)
        cfg.asset_conflict_check_enabled = bool(request.POST.get("asset_conflict_check_enabled"))
        cfg.asset_conflict_block = bool(request.POST.get("asset_conflict_block"))
        cfg.cc_predefinite_email = "\n".join(
            riga.strip()
            for riga in request.POST.get("cc_predefinite_email", "").splitlines()
            if riga.strip() and "@" in riga
        )
        cfg.save()
        cfg.cc_predefiniti_utenti.set(
            task_active_users_queryset().filter(pk__in=request.POST.getlist("cc_predefiniti_utenti"))
        )
        log_action(request, "modifica", "tasks", {"message": "Aggiornate impostazioni KICK-OFF"})
        messages.success(request, "Impostazioni salvate.")
        return redirect(config_url)

    tab = _normalize_tasks_settings_tab(request.GET.get("tab"), default="config")
    return render(
        request,
        "tasks/impostazioni.html",
        {
            **_tasks_shell_context(request, active="impostazioni"),
            **_build_tasks_settings_context(request, tab=tab),
            "cfg": cfg,
            **get_module_branding_context("tasks", fallback_label="KICK-OFF"),
        },
    )
