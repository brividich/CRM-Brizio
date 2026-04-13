from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.db import DatabaseError, connections
from django.db.models import Count, F, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_required
from core.acl import user_can_modulo_action
from core.audit import log_action
from core.legacy_cache import get_cached_perm_map
from core.legacy_utils import get_legacy_user
from core.legacy_utils import is_legacy_admin
from core.legacy_utils import legacy_table_columns
from core.models import AuditLog, Notifica
from core.module_branding import get_module_branding_context, handle_module_branding_post

from .forms import (
    ProjectCommentForm,
    ProjectTaskGanttUpdateForm,
    SubTaskForm,
    SubTaskStatusForm,
    TaskAttachmentForm,
    TaskCommentForm,
    TaskDueDateForm,
    TaskFilterForm,
    TaskForm,
    TaskStatusForm,
)
from .models import (
    Project,
    ProjectComment,
    SubTask,
    Task,
    TaskAttachment,
    TaskComment,
    TaskEvent,
    TaskEventType,
    TaskImpostazioni,
    TaskPriority,
    TaskStatus,
    VRFDocStatus,
)

TASK_MODULE_CODE = "tasks"
OPEN_STATUSES = {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
KEY_EDIT_FIELDS = ("title", "priority", "due_date", "next_step_text", "next_step_due", "tags", "project_id")
User = get_user_model()

MONTH_LABELS_IT = {
    1: "Gennaio",
    2: "Febbraio",
    3: "Marzo",
    4: "Aprile",
    5: "Maggio",
    6: "Giugno",
    7: "Luglio",
    8: "Agosto",
    9: "Settembre",
    10: "Ottobre",
    11: "Novembre",
    12: "Dicembre",
}

GANTT_WINDOW_OPTIONS = (
    (31, "1 mese"),
    (62, "2 mesi"),
    (93, "3 mesi"),
    (124, "4 mesi"),
    (0, "Auto"),
)
GANTT_CELL_OPTIONS = (
    ("s", "Compatta"),
    ("m", "Standard"),
    ("l", "Ampia"),
)
GANTT_NAME_WIDTH_OPTIONS = (
    (280, "Compatta"),
    (360, "Media"),
    (460, "Ampia"),
)
TASK_SETTINGS_TABS = ("config", "riepilogo", "record", "log")


def _normalize_tasks_settings_tab(raw_tab: str | None, *, default: str = "config") -> str:
    tab = str(raw_tab or "").strip().lower()
    if tab in TASK_SETTINGS_TABS:
        return tab
    return default


def _coerce_positive_int(value, *, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        parsed = default
    return max(minimum, parsed)


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

        projects_qs = Project.objects.select_related("project_manager").order_by("-updated_at")
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

    return context


def _parse_vrf_excel(file_obj) -> dict:
    """Estrae i campi identificativi da MOD.073 VRF Rev.10 (Sheet 'VRF').
    Celle fisse: B3=P/N, I3=Descrizione, P3=Esp, O2=Preventivo n°, P2=Versione n°, B4=Cliente.
    Restituisce dict con chiavi stringa, mai None.
    """
    import io
    import openpyxl

    def _s(val):
        return str(val or "").strip()

    result = {
        "part_number": "",
        "vrf_description": "",
        "vrf_esp": "",
        "vrf_quote_number": "",
        "versione": "",
        "client_name": "",
    }
    try:
        data = file_obj.read() if hasattr(file_obj, "read") else file_obj
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        # Preferenza sheet "VRF", altrimenti primo sheet
        ws = wb["VRF"] if "VRF" in wb.sheetnames else wb.active
        # Leggi le 4 righe di intestazione (1-indexed)
        rows = {}
        for r in ws.iter_rows(min_row=1, max_row=4, values_only=True):
            pass  # warming
        # iter_rows con read_only non supporta accesso per cella — rileggiamo
        wb.close()
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        ws = wb["VRF"] if "VRF" in wb.sheetnames else wb.active
        result["vrf_quote_number"] = _s(ws.cell(row=2, column=15).value)  # O2
        result["versione"]         = _s(ws.cell(row=2, column=16).value)  # P2
        result["part_number"]      = _s(ws.cell(row=3, column=2).value)   # B3
        result["vrf_description"]  = _s(ws.cell(row=3, column=9).value)   # I3
        result["vrf_esp"]          = _s(ws.cell(row=3, column=16).value)  # P3
        result["client_name"]      = _s(ws.cell(row=4, column=2).value)   # B4
        wb.close()
    except Exception:
        pass
    return result


def _vrf_status_detail(project, cfg: "TaskImpostazioni") -> dict:
    """Calcola lo stato del documento VRF per un kickoff.

    Restituisce dict con:
      status: 'ok' | 'na' | 'pending' | 'warning' | 'blocked'
      label: str (messaggio utente)
      is_blocked: bool
      days_pending: int | None
      show_upload_cta: bool
    """
    from django.utils import timezone as tz

    vrf_status = project.vrf_status

    if vrf_status == VRFDocStatus.UPLOADED:
        return {
            "status": "ok",
            "label": "Documento VRF caricato.",
            "is_blocked": False,
            "days_pending": None,
            "show_upload_cta": False,
        }

    if vrf_status == VRFDocStatus.NOT_REQUIRED:
        return {
            "status": "na",
            "label": "Documento VRF non richiesto per questo kickoff.",
            "is_blocked": False,
            "days_pending": None,
            "show_upload_cta": False,
        }

    # PENDING
    today = tz.localdate()
    created_date = project.created_at.date() if project.created_at else today
    days = (today - created_date).days

    if days >= cfg.vrf_blocking_days:
        return {
            "status": "blocked",
            "label": (
                f"Kickoff BLOCCATO: documento VRF non caricato da {days} giorni "
                f"(soglia blocco: {cfg.vrf_blocking_days} giorni). "
                "Non e possibile aggiungere o modificare attivita kickoff finche il documento non viene caricato."
            ),
            "is_blocked": True,
            "days_pending": days,
            "show_upload_cta": True,
        }

    if days >= cfg.vrf_reminder_days:
        return {
            "status": "warning",
            "label": (
                f"Attenzione: documento VRF non ancora caricato ({days} giorni dalla creazione del kickoff). "
                f"Il kickoff sara bloccato dopo {cfg.vrf_blocking_days} giorni."
            ),
            "is_blocked": False,
            "days_pending": days,
            "show_upload_cta": True,
        }

    return {
        "status": "pending",
        "label": f"Documento VRF non ancora caricato ({days} giorni dalla creazione del kickoff).",
        "is_blocked": False,
        "days_pending": days,
        "show_upload_cta": True,
    }


def _copy_project_vrf_file(project: Project, *, clear_part_number: bool = False) -> tuple[bytes | None, str]:
    if not project.vrf_file:
        return None, ""

    import io
    from pathlib import Path

    project.vrf_file.open("rb")
    try:
        file_bytes = project.vrf_file.read()
    finally:
        project.vrf_file.close()

    filename = project.vrf_original_name or Path(project.vrf_file.name).name

    if clear_part_number:
        import openpyxl

        workbook = openpyxl.load_workbook(io.BytesIO(file_bytes))
        try:
            worksheet = workbook["VRF"] if "VRF" in workbook.sheetnames else workbook.active
            worksheet["B3"] = ""
            output = io.BytesIO()
            workbook.save(output)
            file_bytes = output.getvalue()
        finally:
            workbook.close()

    return file_bytes, filename


def _duplicate_kickoff(source_project: Project, *, created_by, clear_part_number: bool = False) -> Project:
    from django.core.files.base import ContentFile

    kickoff = Project.objects.create(
        name="",
        description=source_project.description,
        client_name=source_project.client_name,
        project_manager=source_project.project_manager,
        capo_commessa=source_project.capo_commessa,
        programmer=source_project.programmer,
        control_method=source_project.control_method,
        part_number="" if clear_part_number else source_project.part_number,
        revisione=source_project.revisione,
        versione=source_project.versione,
        vrf_status=source_project.vrf_status,
        vrf_original_name=source_project.vrf_original_name,
        vrf_uploaded_at=source_project.vrf_uploaded_at,
        vrf_quote_number=source_project.vrf_quote_number,
        vrf_description=source_project.vrf_description,
        vrf_esp=source_project.vrf_esp,
        similar_project=source_project.similar_project,
        similar_work_note=source_project.similar_work_note,
        created_by=created_by,
    )

    file_bytes, filename = _copy_project_vrf_file(source_project, clear_part_number=clear_part_number)
    if file_bytes is not None:
        kickoff.vrf_file.save(filename, ContentFile(file_bytes), save=False)
        kickoff.vrf_original_name = filename
        kickoff.save(update_fields=["vrf_file", "vrf_original_name", "updated_at"])

    return kickoff


def _request_legacy_user(request):
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is None:
        legacy_user = get_legacy_user(request.user)
        request.legacy_user = legacy_user
    return legacy_user


def _check_task_action_for_legacy(legacy_user, action_code: str) -> bool:
    """ACL action check locale app tasks (riuso cache permessi + override per-utente)."""
    if not legacy_user:
        return False
    if is_legacy_admin(legacy_user):
        return True

    role_id = getattr(legacy_user, "ruolo_id", None)
    if not role_id:
        return False

    action_norm = str(action_code or "").strip()
    if not action_norm:
        return False

    try:
        from core.models import UserPermissionOverride

        override = UserPermissionOverride.objects.filter(
            legacy_user_id=int(legacy_user.id),
            modulo__iexact=TASK_MODULE_CODE,
            azione__iexact=action_norm,
        ).first()
        if override is not None and override.can_view is not None:
            return bool(override.can_view)
    except Exception:
        pass

    perm_map = get_cached_perm_map(int(role_id))
    return bool(perm_map.get((TASK_MODULE_CODE, action_norm.lower()), False))


def _has_task_permission(request, action_code: str) -> bool:
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


def task_permissions_required(*action_codes: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            for action_code in action_codes:
                if not _has_task_permission(request, action_code):
                    return render(
                        request,
                        "core/pages/forbidden.html",
                        {"page_title": "Accesso negato"},
                        status=403,
                    )
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def _scoped_tasks_queryset(request):
    qs = Task.objects.select_related(
        "created_by",
        "assigned_to",
        "project",
        "project__project_manager",
        "project__capo_commessa",
        "project__programmer",
        "project__similar_project",
    )
    if _has_task_permission(request, "tasks_admin"):
        return qs
    user = request.user
    return qs.filter(Q(created_by=user) | Q(assigned_to=user) | Q(subscribers=user)).distinct()


def _scoped_projects_queryset(request):
    qs = Project.objects.select_related(
        "created_by",
        "project_manager",
        "capo_commessa",
        "programmer",
        "similar_project",
    )
    if _has_task_permission(request, "tasks_admin"):
        return qs
    user = request.user
    return qs.filter(
        Q(created_by=user)
        | Q(tasks__created_by=user)
        | Q(tasks__assigned_to=user)
        | Q(tasks__subscribers=user)
    ).distinct()


def _detail_queryset(request):
    return _scoped_tasks_queryset(request).prefetch_related(
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


def _apply_default_ordering(qs):
    return qs.order_by(
        F("next_step_due").asc(nulls_last=True),
        F("due_date").asc(nulls_last=True),
        "-updated_at",
    )


def _tasks_shell_context(request, *, active: str, task: Task | None = None, project: Project | None = None) -> dict:
    current_project = project
    if current_project is None and task is not None and getattr(task, "project_id", None):
        current_project = task.project
    return {
        "tasks_shell_active": active,
        "tasks_shell_task": task,
        "tasks_shell_project": current_project,
        "tasks_shell_can_create": _has_task_permission(request, "tasks_create"),
        "tasks_shell_can_admin": user_can_modulo_action(request, "tasks", "admin_tasks"),
        "tasks_shell_is_scope_admin": _has_task_permission(request, "tasks_admin"),
    }


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _log_event(task: Task, actor, event_type: str, payload: dict | None = None) -> None:
    TaskEvent.objects.create(
        task=task,
        actor=actor,
        type=event_type,
        payload=payload or {},
    )


def _task_snapshot(task: Task) -> dict:
    return {
        "status": task.status,
        "assigned_to_id": task.assigned_to_id,
        "title": task.title,
        "priority": task.priority,
        "due_date": task.due_date,
        "next_step_text": task.next_step_text,
        "next_step_due": task.next_step_due,
        "tags": task.tags,
        "project_id": task.project_id,
    }


def _task_notify_users_queryset(task: Task):
    user_ids: set[int] = {task.created_by_id}
    if task.assigned_to_id:
        user_ids.add(task.assigned_to_id)
    user_ids.update(task.subscribers.values_list("id", flat=True))
    user_ids.discard(None)
    return User.objects.filter(id__in=user_ids).order_by("first_name", "last_name", "username")


def _project_notify_users_queryset(project: Project):
    task_rows = project.tasks.values_list("created_by_id", "assigned_to_id")
    user_ids: set[int] = {project.created_by_id}
    for created_by_id, assigned_to_id in task_rows:
        if created_by_id:
            user_ids.add(created_by_id)
        if assigned_to_id:
            user_ids.add(assigned_to_id)
    user_ids.update(project.tasks.values_list("subscribers__id", flat=True))
    user_ids.discard(None)
    return User.objects.filter(id__in=user_ids).order_by("first_name", "last_name", "username")


def _legacy_user_id_for_user(user) -> int | None:
    profile = getattr(user, "profile", None)
    if profile and getattr(profile, "legacy_user_id", None):
        try:
            return int(profile.legacy_user_id)
        except Exception:
            return None
    return None


def _notify_user(target_user, *, message_text: str, action_url: str = "") -> None:
    target_legacy_user_id = _legacy_user_id_for_user(target_user)
    if not target_legacy_user_id:
        return
    Notifica.objects.create(
        legacy_user_id=target_legacy_user_id,
        tipo="generico",
        messaggio=str(message_text or "")[:500],
        url_azione=str(action_url or "")[:255],
    )


def _legacy_fetch_all_dict(sql: str, params: list | tuple | None = None) -> list[dict]:
    with connections["default"].cursor() as cursor:
        cursor.execute(sql, params or [])
        columns = [str(col[0]) for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _absence_status_label(row: dict) -> str:
    raw_status = row.get("moderation_status")
    try:
        parsed = int(raw_status)
    except (TypeError, ValueError):
        parsed = None
    status_map = {
        0: "Approvato",
        1: "Rifiutato",
        2: "In attesa",
        3: "Bozza",
        4: "Programmato",
    }
    if parsed is not None:
        return status_map.get(parsed, "In attesa")
    consenso = str(row.get("consenso") or "").strip()
    if consenso:
        return consenso
    return "In attesa"


def _load_user_absences(user, *, date_start: date, date_end: date) -> list[dict]:
    if not user or date_end < date_start:
        return []

    columns = legacy_table_columns("assenze")
    if not columns:
        legacy_table_columns.cache_clear()
        columns = legacy_table_columns("assenze")
    if not columns or "data_inizio" not in columns or "data_fine" not in columns:
        return []

    full_name = str(user.get_full_name() or user.get_username() or "").strip()
    email = str(getattr(user, "email", "") or "").strip()

    identity_clauses: list[str] = []
    identity_params: list = []
    if "copia_nome" in columns and full_name:
        identity_clauses.append("UPPER(COALESCE(copia_nome,'')) = UPPER(%s)")
        identity_params.append(full_name)
    if "email_esterna" in columns and email:
        identity_clauses.append("UPPER(COALESCE(email_esterna,'')) = UPPER(%s)")
        identity_params.append(email)
    if not identity_clauses:
        return []

    range_start = datetime.combine(date_start, datetime.min.time())
    range_end = datetime.combine(date_end, datetime.max.time())

    status_clause = ""
    status_params: list = []
    if "moderation_status" in columns:
        status_clause = "AND COALESCE(moderation_status, 2) != %s"
        status_params.append(1)
    elif "consenso" in columns:
        status_clause = "AND UPPER(COALESCE(consenso,'')) NOT LIKE UPPER(%s)"
        status_params.append("%rifiut%")

    tipo_select = "tipo_assenza" if "tipo_assenza" in columns else "'' AS tipo_assenza"
    consenso_select = "consenso" if "consenso" in columns else "'' AS consenso"
    moderation_select = "moderation_status" if "moderation_status" in columns else "NULL AS moderation_status"

    sql = f"""
        SELECT
            id,
            data_inizio,
            data_fine,
            {tipo_select},
            {consenso_select},
            {moderation_select}
        FROM assenze
        WHERE ({' OR '.join(identity_clauses)})
          AND data_inizio IS NOT NULL
          AND data_fine IS NOT NULL
          AND data_fine >= %s
          AND data_inizio <= %s
          {status_clause}
        ORDER BY data_inizio ASC, id ASC
    """

    try:
        rows = _legacy_fetch_all_dict(sql, [*identity_params, range_start, range_end, *status_params])
    except DatabaseError:
        return []
    except Exception:
        return []

    normalized: list[dict] = []
    for row in rows:
        start_date = _coerce_date(row.get("data_inizio"))
        end_date = _coerce_date(row.get("data_fine"))
        if not start_date or not end_date:
            continue
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        normalized.append(
            {
                "id": row.get("id"),
                "start_date": start_date,
                "end_date": end_date,
                "tipo": str(row.get("tipo_assenza") or "Assenza").strip() or "Assenza",
                "status": _absence_status_label(row),
            }
        )
    return normalized


def _task_date_absence_conflicts(task: Task) -> dict[str, list[dict]]:
    if not task.assigned_to_id:
        return {}

    target_dates: dict[str, date] = {}
    if task.due_date:
        target_dates["due_date"] = task.due_date
    if task.next_step_due:
        target_dates["next_step_due"] = task.next_step_due
    if not target_dates:
        return {}

    date_start = min(target_dates.values())
    date_end = max(target_dates.values())
    absences = _load_user_absences(task.assigned_to, date_start=date_start, date_end=date_end)
    if not absences:
        return {}

    conflicts: dict[str, list[dict]] = {}
    for field_name, target_date in target_dates.items():
        field_conflicts = [row for row in absences if row["start_date"] <= target_date <= row["end_date"]]
        if field_conflicts:
            conflicts[field_name] = field_conflicts
    return conflicts


def _add_task_absence_warnings(request, task: Task) -> None:
    conflicts = _task_date_absence_conflicts(task)
    if not conflicts or not task.assigned_to_id:
        return

    assignee_name = task.assigned_to.get_full_name() or task.assigned_to.get_username()
    field_labels = {
        "due_date": "data prevista conclusione",
        "next_step_due": "data obiettivo prossima azione",
    }
    for field_name in ("next_step_due", "due_date"):
        if field_name not in conflicts:
            continue
        target_date = getattr(task, field_name, None)
        if not target_date:
            continue
        unique_labels: list[str] = []
        for entry in conflicts[field_name]:
            label = f"{entry['tipo']} ({entry['status']})"
            if label not in unique_labels:
                unique_labels.append(label)
        label_text = ", ".join(unique_labels[:2])
        if len(unique_labels) > 2:
            label_text += ", ..."
        messages.warning(
            request,
            (
                f"Conflitto assenze: {field_labels[field_name]} del {target_date.strftime('%d/%m/%Y')} "
                f"coincide con assenza di {assignee_name} ({label_text})."
            ),
        )


def _build_task_absence_day_map(tasks: list[Task], *, timeline_start: date, timeline_end: date) -> dict[int, dict[date, list[dict]]]:
    if timeline_end < timeline_start:
        return {}

    user_absence_cache: dict[int, list[dict]] = {}
    for task in tasks:
        if not task.assigned_to_id or task.assigned_to_id in user_absence_cache:
            continue
        user_absence_cache[task.assigned_to_id] = _load_user_absences(
            task.assigned_to,
            date_start=timeline_start,
            date_end=timeline_end,
        )

    per_task_day_map: dict[int, dict[date, list[dict]]] = {}
    for task in tasks:
        task_day_map: dict[date, list[dict]] = {}
        for absence in user_absence_cache.get(task.assigned_to_id, []):
            start_date = max(absence["start_date"], timeline_start)
            end_date = min(absence["end_date"], timeline_end)
            if end_date < start_date:
                continue
            current = start_date
            while current <= end_date:
                task_day_map.setdefault(current, []).append(absence)
                current += timedelta(days=1)
        per_task_day_map[task.id] = task_day_map
    return per_task_day_map


def _query_bool(query_data, key: str, *, default: bool = True) -> bool:
    raw = query_data.get(key)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "off", "no", ""}


def _parse_gantt_options(request):
    query_data = request.GET

    valid_windows = {row[0] for row in GANTT_WINDOW_OPTIONS}
    valid_cells = {row[0] for row in GANTT_CELL_OPTIONS}
    valid_name_widths = {row[0] for row in GANTT_NAME_WIDTH_OPTIONS}

    try:
        window_days = int(query_data.get("window_days", 31))
    except (TypeError, ValueError):
        window_days = 31
    if window_days not in valid_windows:
        window_days = 31

    cell_size = str(query_data.get("cell_size", "m") or "m").strip().lower()
    if cell_size not in valid_cells:
        cell_size = "m"

    try:
        name_width = int(query_data.get("name_width", 360))
    except (TypeError, ValueError):
        name_width = 360
    if name_width not in valid_name_widths:
        name_width = 360

    day_cell_px_map = {"s": 22, "m": 30, "l": 38}

    return {
        "window_days": window_days,
        "cell_size": cell_size,
        "name_width": name_width,
        "show_wbs": _query_bool(query_data, "show_wbs", default=True),
        "show_duration": _query_bool(query_data, "show_duration", default=True),
        "show_start": _query_bool(query_data, "show_start", default=True),
        "show_end": _query_bool(query_data, "show_end", default=True),
        "day_cell_px": day_cell_px_map[cell_size],
        "window_choices": GANTT_WINDOW_OPTIONS,
        "cell_choices": GANTT_CELL_OPTIONS,
        "name_width_choices": GANTT_NAME_WIDTH_OPTIONS,
        "return_qs": query_data.urlencode(),
    }


def _easter_date(year: int) -> date:
    """Calcola la domenica di Pasqua (algoritmo gregoriano anonimo)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _italian_holidays(year: int) -> set[date]:
    """Restituisce le festività nazionali italiane fisse + Pasqua/Lunedì dell'Angelo."""
    easter = _easter_date(year)
    return {
        date(year, 1, 1),   # Capodanno
        date(year, 1, 6),   # Epifania
        easter,              # Pasqua
        easter + timedelta(days=1),  # Lunedì dell'Angelo
        date(year, 4, 25),  # Liberazione
        date(year, 5, 1),   # Festa del lavoro
        date(year, 6, 2),   # Repubblica
        date(year, 8, 15),  # Ferragosto
        date(year, 11, 1),  # Ognissanti
        date(year, 12, 8),  # Immacolata Concezione
        date(year, 12, 25), # Natale
        date(year, 12, 26), # Santo Stefano
    }


def _build_holidays_set(start: date, end: date) -> set[date]:
    """Costruisce l'insieme di tutte le festività nell'arco temporale dato."""
    holidays: set[date] = set()
    for year in range(start.year, end.year + 1):
        holidays |= _italian_holidays(year)
    return holidays


def _is_non_working_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() >= 5 or d in holidays


def _count_working_days(start: date, end: date, holidays: set[date]) -> int:
    return sum(1 for i in range((end - start).days + 1) if not _is_non_working_day(start + timedelta(days=i), holidays))


def _project_gantt_rows(tasks: list[Task], *, min_window_days: int = 31) -> dict:
    today = timezone.localdate()
    timeline_points: list[date] = [today]
    base_rows: list[dict] = []

    for index, task in enumerate(tasks, start=1):
        start = task.next_step_due or task.created_at.date()
        end = task.due_date or task.next_step_due or start
        active_start = min(start, end)
        active_end = max(start, end)
        invalid_range = bool(task.next_step_due and task.due_date and task.due_date <= task.next_step_due)

        timeline_points.extend([active_start, active_end])
        base_rows.append(
            {
                "task": task,
                "wbs": str(index),
                "start": start,
                "end": end,
                "active_start": active_start,
                "active_end": active_end,
                "invalid_range": invalid_range,
                "duration_days": max(1, (active_end - active_start).days + 1),
            }
        )

    if base_rows:
        timeline_start = min(timeline_points) - timedelta(days=1)
        timeline_end = max(timeline_points) + timedelta(days=1)
    else:
        timeline_start = today - timedelta(days=3)
        timeline_end = today + timedelta(days=10)

    if min_window_days and min_window_days > 0:
        current_days = max(1, (timeline_end - timeline_start).days + 1)
        if current_days < min_window_days:
            extra_days = min_window_days - current_days
            left_extra = extra_days // 2
            right_extra = extra_days - left_extra
            timeline_start -= timedelta(days=left_extra)
            timeline_end += timedelta(days=right_extra)

    total_days = max(1, (timeline_end - timeline_start).days + 1)
    days = [timeline_start + timedelta(days=offset) for offset in range(total_days)]
    holidays = _build_holidays_set(timeline_start, timeline_end)
    day_columns = [
        {
            "date": day_value,
            "is_weekend": day_value.weekday() >= 5,
            "is_holiday": day_value in holidays and day_value.weekday() < 5,
            "is_today": day_value == today,
        }
        for day_value in days
    ]

    month_spans = []
    if days:
        current_month = (days[0].year, days[0].month)
        span_start = 0
        for index, day_value in enumerate(days):
            key = (day_value.year, day_value.month)
            if key != current_month:
                month_spans.append(
                    {
                        "label": f"{MONTH_LABELS_IT.get(current_month[1], current_month[1])} {current_month[0]}",
                        "span": index - span_start,
                    }
                )
                current_month = key
                span_start = index
        month_spans.append(
            {
                "label": f"{MONTH_LABELS_IT.get(current_month[1], current_month[1])} {current_month[0]}",
                "span": len(days) - span_start,
            }
        )

    task_absence_days = _build_task_absence_day_map(tasks, timeline_start=timeline_start, timeline_end=timeline_end)

    rows: list[dict] = []
    for row in base_rows:
        start_index = max(0, (row["active_start"] - timeline_start).days)
        end_index = min(len(days) - 1, (row["active_end"] - timeline_start).days)
        row_absence_days = task_absence_days.get(row["task"].id, {})
        conflict_dates: list[date] = [
            day_value
            for day_value in sorted(row_absence_days.keys())
            if row["active_start"] <= day_value <= row["active_end"]
        ]
        cells = []
        for day_index, day_value in enumerate(days):
            classes = []
            marker = ""
            title = ""
            is_wknd = day_value.weekday() >= 5
            is_hol = day_value in holidays and not is_wknd
            if is_wknd:
                classes.append("is-weekend")
            if is_hol:
                classes.append("is-holiday")
            if day_value == today:
                classes.append("is-today")
            if start_index <= day_index <= end_index:
                classes.append("is-active")
                classes.append(f"status-{row['task'].status.lower()}")
                if row["invalid_range"]:
                    classes.append("is-invalid-range")
            absence_entries = row_absence_days.get(day_value, [])
            if absence_entries and start_index <= day_index <= end_index:
                classes.append("is-absence")
                marker = "X"
                labels = [f"{entry['tipo']} ({entry['status']})" for entry in absence_entries]
                title = "; ".join(dict.fromkeys(labels))
            cells.append(
                {
                    "classes": " ".join(classes),
                    "marker": marker,
                    "title": title,
                }
            )
        row["cells"] = cells
        row["start_index"] = start_index
        row["end_index"] = end_index
        row["absence_days"] = len(conflict_dates)
        row["absence_dates"] = conflict_dates[:6]
        row["has_absence_conflicts"] = bool(conflict_dates)
        row["duration_working_days"] = _count_working_days(row["active_start"], row["active_end"], holidays)
        rows.append(row)

    # Predecessore implicito (WBS order): ogni task conosce l'end_index del task precedente
    # per consentire il vincolo "task N non può iniziare prima della fine di task N-1" nel Gantt.
    for i, row in enumerate(rows):
        row["prev_end_index"] = rows[i - 1]["end_index"] if i > 0 else -1

    return {
        "rows": rows,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "today": today,
        "days": day_columns,
        "month_spans": month_spans,
    }


def _can_edit_project_schedule(request, project: Project) -> bool:
    if _has_task_permission(request, "tasks_admin"):
        return True
    if project.created_by_id == request.user.id:
        return True
    if not _has_task_permission(request, "tasks_edit"):
        return False
    return project.tasks.filter(assigned_to=request.user).exists()


def _is_project_lead_for_task(user, task: Task) -> bool:
    return bool(task.project_id and task.project and task.project.created_by_id == getattr(user, "id", None))


def _can_manage_task(request, task: Task) -> bool:
    if _has_task_permission(request, "tasks_admin"):
        return True
    if _is_project_lead_for_task(request.user, task):
        return True
    return _has_task_permission(request, "tasks_edit")


def _can_update_task_due_date(request, task: Task) -> bool:
    if _has_task_permission(request, "tasks_admin"):
        return True
    if _can_manage_task(request, task):
        return True
    return bool(task.assigned_to_id and task.assigned_to_id == request.user.id)


def _compute_rollup_status(task: Task) -> str | None:
    subtask_statuses = list(task.subtasks.values_list("status", flat=True))
    if not subtask_statuses:
        return None
    if all(status == TaskStatus.DONE for status in subtask_statuses):
        return TaskStatus.DONE
    if all(status == TaskStatus.CANCELED for status in subtask_statuses):
        return TaskStatus.CANCELED
    if any(status == TaskStatus.IN_PROGRESS for status in subtask_statuses):
        return TaskStatus.IN_PROGRESS
    has_done = any(status == TaskStatus.DONE for status in subtask_statuses)
    has_todo = any(status == TaskStatus.TODO for status in subtask_statuses)
    if has_done and has_todo:
        return TaskStatus.IN_PROGRESS
    return TaskStatus.TODO


def _apply_subtask_rollup(task: Task, actor) -> None:
    next_status = _compute_rollup_status(task)
    if not next_status or next_status == task.status:
        return
    old_status = task.status
    task.status = next_status
    task.save(update_fields=["status", "updated_at"])
    _log_event(
        task,
        actor,
        TaskEventType.STATUS_CHANGE,
        {"from": old_status, "to": next_status, "source": "subtask_rollup"},
    )


def _log_task_update_events(task: Task, actor, before: dict) -> None:
    if before.get("status") != task.status:
        _log_event(
            task,
            actor,
            TaskEventType.STATUS_CHANGE,
            {"from": before.get("status"), "to": task.status},
        )

    if before.get("assigned_to_id") != task.assigned_to_id:
        _log_event(
            task,
            actor,
            TaskEventType.ASSIGNMENT_CHANGE,
            {"from_user_id": before.get("assigned_to_id"), "to_user_id": task.assigned_to_id},
        )

    key_changes = {}
    for field_name in KEY_EDIT_FIELDS:
        old_value = before.get(field_name)
        new_value = getattr(task, field_name)
        if old_value != new_value:
            key_changes[field_name] = {
                "from": _json_safe(old_value),
                "to": _json_safe(new_value),
            }
    if key_changes:
        _log_event(
            task,
            actor,
            TaskEventType.EDIT,
            {"changes": key_changes},
        )


@task_permissions_required("tasks_view")
def task_list(request):
    query_data = request.GET.copy()
    mine_raw = (query_data.get("mine") or "").strip().lower()
    mine_explicit_false = mine_raw in {"0", "false", "off", "no"}
    if mine_explicit_false:
        query_data.pop("mine", None)
    if not query_data and not mine_explicit_false:
        query_data["mine"] = "1"

    projects_qs = _scoped_projects_queryset(request).order_by("name", "id")
    filter_form = TaskFilterForm(query_data or None, user=request.user, project_queryset=projects_qs)
    scoped_base_qs = _scoped_tasks_queryset(request)
    tasks_qs = scoped_base_qs.prefetch_related("subscribers")

    if filter_form.is_valid():
        data = filter_form.cleaned_data
        mine_enabled = bool(data.get("mine")) and not mine_explicit_false
        if mine_enabled:
            user = request.user
            tasks_qs = tasks_qs.filter(Q(created_by=user) | Q(assigned_to=user) | Q(subscribers=user)).distinct()
        if data.get("status"):
            tasks_qs = tasks_qs.filter(status=data["status"])
        if data.get("priority"):
            tasks_qs = tasks_qs.filter(priority=data["priority"])
        if data.get("overdue"):
            tasks_qs = tasks_qs.filter(due_date__lt=timezone.localdate(), status__in=OPEN_STATUSES)
        if data.get("due_from"):
            tasks_qs = tasks_qs.filter(due_date__gte=data["due_from"])
        if data.get("due_to"):
            tasks_qs = tasks_qs.filter(due_date__lte=data["due_to"])
        if data.get("assigned_to"):
            tasks_qs = tasks_qs.filter(assigned_to=data["assigned_to"])
        if data.get("project"):
            tasks_qs = tasks_qs.filter(project=data["project"])
        if data.get("tag"):
            tasks_qs = tasks_qs.filter(tags__icontains=data["tag"].strip())
        if data.get("unassigned"):
            tasks_qs = tasks_qs.filter(assigned_to__isnull=True)
        if data.get("without_due_date"):
            tasks_qs = tasks_qs.filter(due_date__isnull=True)
        if data.get("without_project"):
            tasks_qs = tasks_qs.filter(project__isnull=True)

    tasks = _apply_default_ordering(tasks_qs)
    is_scope_admin = _has_task_permission(request, "tasks_admin")
    can_create = _has_task_permission(request, "tasks_create")
    can_edit = _has_task_permission(request, "tasks_edit")
    can_comment = _has_task_permission(request, "tasks_comment")

    active_project = filter_form.cleaned_data.get("project") if filter_form.is_valid() else None

    # Stats source: project-scoped when filtering by project, global otherwise
    stats_qs = tasks_qs.order_by() if active_project else scoped_base_qs.order_by()
    status_counter = {
        row["status"]: row["total"]
        for row in stats_qs.values("status").annotate(total=Count("id")).order_by()
    }
    total_count = stats_qs.count()
    done_count = int(status_counter.get(TaskStatus.DONE, 0))
    dashboard_stats = {
        "total": total_count,
        "todo": int(status_counter.get(TaskStatus.TODO, 0)),
        "in_progress": int(status_counter.get(TaskStatus.IN_PROGRESS, 0)),
        "done": done_count,
        "canceled": int(status_counter.get(TaskStatus.CANCELED, 0)),
        "overdue": stats_qs.filter(
            due_date__lt=timezone.localdate(),
            status__in=OPEN_STATUSES,
        ).count(),
    }
    done_pct = round(done_count / max(total_count, 1) * 100)

    admin_console = None
    admin_project_summary = []
    if is_scope_admin:
        today = timezone.localdate()
        now = timezone.now()
        admin_console = {
            "unassigned": stats_qs.filter(assigned_to__isnull=True).count(),
            "without_due_date": stats_qs.filter(due_date__isnull=True).count(),
            "without_project": stats_qs.filter(project__isnull=True).count(),
            "due_next_7d": stats_qs.filter(
                status__in=OPEN_STATUSES,
                due_date__gte=today,
                due_date__lte=today + timedelta(days=7),
            ).count(),
            "stale_in_progress": stats_qs.filter(
                status=TaskStatus.IN_PROGRESS,
                updated_at__lt=now - timedelta(days=7),
            ).count(),
        }
        admin_project_summary = list(
            Project.objects.filter(tasks__in=stats_qs)
            .order_by()
            .values("id", "name")
            .annotate(
                task_total=Count("tasks", distinct=True),
                open_total=Count("tasks", filter=Q(tasks__status__in=OPEN_STATUSES), distinct=True),
            )
            .order_by("-open_total", "name")[:6]
        )

    return render(
        request,
        "tasks/list.html",
        {
            **_tasks_shell_context(request, active="dashboard"),
            "page_title": "KICK-OFF",
            "tasks": tasks,
            "filter_form": filter_form,
            "can_create": can_create,
            "can_edit": can_edit,
            "can_comment": can_comment,
            "is_scope_admin": is_scope_admin,
            "dashboard_stats": dashboard_stats,
            "mine_explicit_false": mine_explicit_false,
            "showing_mine_default": (not is_scope_admin) or (not mine_explicit_false),
            "admin_console": admin_console,
            "admin_project_summary": admin_project_summary,
            "active_project": active_project,
            "done_pct": done_pct,
        },
    )


@task_permissions_required("tasks_view")
def task_detail(request, task_id: int):
    task = get_object_or_404(_detail_queryset(request), pk=task_id)
    can_manage = _can_manage_task(request, task)
    can_update_due_date = _can_update_task_due_date(request, task)
    comment_form = TaskCommentForm(
        user=request.user,
        notify_user_queryset=_task_notify_users_queryset(task),
    )

    return render(
        request,
        "tasks/detail.html",
        {
            **_tasks_shell_context(request, active="detail", task=task),
            "page_title": task.title,
            "task": task,
            "task_status_form": TaskStatusForm(instance=task),
            "task_due_date_form": TaskDueDateForm(instance=task),
            "comment_form": comment_form,
            "subtask_form": SubTaskForm(user=request.user),
            "attachment_form": TaskAttachmentForm(task=task),
            "can_edit": can_manage,
            "can_manage_task": can_manage,
            "can_update_due_date": can_update_due_date,
            "can_comment": _has_task_permission(request, "tasks_comment"),
            "task_status_choices": TaskStatus.choices,
            "subtask_status_choices": TaskStatus.choices,
        },
    )


@task_permissions_required("tasks_view")
def project_info_json(request, project_id: int):
    """Restituisce info progetto + lista task (ordine creazione) in formato JSON, per l'AJAX del form."""
    project = get_object_or_404(_scoped_projects_queryset(request).select_related(
        "project_manager", "capo_commessa", "programmer"
    ), pk=project_id)
    raw_tasks = list(
        Task.objects.filter(project=project)
        .order_by("id")
        .values("id", "title", "status", "next_step_due", "due_date",
                "assigned_to__first_name", "assigned_to__last_name", "assigned_to__username")
    )
    tasks_data = []
    for i, t in enumerate(raw_tasks, start=1):
        fn = t["assigned_to__first_name"] or ""
        ln = t["assigned_to__last_name"] or ""
        assignee = f"{fn} {ln}".strip() or t["assigned_to__username"] or ""
        tasks_data.append({
            "wbs": i,
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "next_step_due": t["next_step_due"].strftime("%d/%m/%Y") if t["next_step_due"] else "",
            "due_date": t["due_date"].strftime("%d/%m/%Y") if t["due_date"] else "",
            "assignee": assignee,
        })
    pm = project.project_manager
    cc = project.capo_commessa
    prog = project.programmer
    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)
    return JsonResponse({
        "id": project.id,
        "name": project.name,
        "client_name": project.client_name or "",
        "part_number": project.part_number or "",
        "revisione": project.revisione or "",
        "versione": project.versione or "",
        "project_manager": (pm.get_full_name() or pm.username) if pm else "",
        "capo_commessa": (cc.get_full_name() or cc.username) if cc else "",
        "programmer": (prog.get_full_name() or prog.username) if prog else "",
        "task_total": len(tasks_data),
        "vrf_status": vrf_detail["status"],
        "vrf_label": vrf_detail["label"],
        "vrf_upload_url": reverse("tasks:project_vrf_upload", kwargs={"project_id": project.id}),
        "tasks": tasks_data,
    })


def _task_create_locked_project(request, projects_qs):
    project_param = (request.GET.get("project") or "").strip()
    if not project_param:
        return None
    try:
        project_id = int(project_param)
    except (TypeError, ValueError):
        return None
    return get_object_or_404(
        projects_qs.select_related("project_manager", "capo_commessa", "programmer"),
        pk=project_id,
    )


@task_permissions_required("tasks_view", "tasks_create")
def task_create(request):
    projects_qs = _scoped_projects_queryset(request).order_by("name", "id")
    locked_project = _task_create_locked_project(request, projects_qs)
    suggested_start_date = None
    if locked_project is not None:
        last_task = (
            Task.objects.filter(project=locked_project)
            .order_by("-id")
            .first()
        )
        if last_task:
            last_end = last_task.due_date or last_task.next_step_due
            if last_end:
                suggested_start_date = last_end + timedelta(days=1)

    if request.method == "POST":
        form = TaskForm(
            request.POST,
            user=request.user,
            project_queryset=projects_qs,
            locked_project=locked_project,
        )
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.project = form.resolve_project(created_by=request.user)

            # Blocking guard: se il progetto esistente è bloccato per VRF mancante, blocca il salvataggio
            if task.project and not getattr(form, "new_project_created", False):
                cfg = TaskImpostazioni.get_singleton()
                vrf_detail = _vrf_status_detail(task.project, cfg)
                if vrf_detail["is_blocked"]:
                    messages.error(
                        request,
                        f"Kickoff bloccato: carica il documento VRF prima di procedere. "
                        f"({vrf_detail['days_pending']} giorni senza documento VRF)",
                    )
                    return redirect(
                        reverse("tasks:project_vrf_upload", kwargs={"project_id": task.project.id})
                        + f"?next={reverse('tasks:create')}"
                    )

            task.save()
            form.save_m2m()
            if form.reused_existing_project is not None and task.project_id:
                if form.reused_existing_project_fields:
                    messages.info(
                        request,
                        (
                            f"Kickoff esistente riutilizzato per P/N {task.project.part_number or '-'}: "
                            "anagrafica kickoff aggiornata con i dati inseriti."
                        ),
                    )
                else:
                    messages.info(
                        request,
                        (
                            f"Kickoff esistente riutilizzato per P/N {task.project.part_number or '-'}: "
                            "l'attivita kickoff e stata agganciata senza creare duplicati."
                        ),
                    )
            if task.project_id:
                messages.success(request, f"Attivita kickoff creata nel kickoff '{task.project.name}'.")
            else:
                messages.success(request, "Attivita singola creata correttamente.")
            if form.assignment_conflicts and task.assigned_to_id:
                assignee_name = task.assigned_to.get_full_name() or task.assigned_to.get_username()
                messages.warning(
                    request,
                    (
                        f"Impegni sovrapposti: {assignee_name} ha gia {len(form.assignment_conflicts)} task attive "
                        f"nello stesso periodo ({form.assignment_conflict_summary(limit=3)})."
                    ),
                )
            if form.auto_raised_priority:
                messages.warning(request, "Priorita aggiornata automaticamente a High per conflitto impegni.")
            if task.is_overdue:
                messages.warning(request, "Attivita kickoff creata con scadenza gia oltre la data odierna.")
            _add_task_absence_warnings(request, task)

            # Se è stato creato un nuovo progetto, redirect alla pagina upload VRF
            if getattr(form, "new_project_created", False) and task.project_id:
                next_url = reverse("tasks:detail", kwargs={"task_id": task.id})
                return redirect(
                    reverse("tasks:project_vrf_upload", kwargs={"project_id": task.project.id})
                    + f"?next={next_url}"
                )
            return redirect("tasks:detail", task_id=task.id)
    else:
        initial = {}
        if suggested_start_date:
            initial["next_step_due"] = suggested_start_date
        if locked_project is not None:
            initial["project_choice"] = locked_project.id
            initial["task_scope"] = "project"
            initial["project_link_mode"] = TaskForm.PROJECT_LINK_EXISTING

        form = TaskForm(
            user=request.user,
            project_queryset=projects_qs,
            initial=initial,
            locked_project=locked_project,
        )

        return render(
            request,
            "tasks/form.html",
            {
                **_tasks_shell_context(request, active="create"),
                "page_title": "Nuova attivita kickoff",
                "form": form,
                "mode": "create",
                "suggested_start_date": suggested_start_date,
                "suggested_project_id": locked_project.id if locked_project is not None else None,
                "locked_project": locked_project,
                "locked_project_vrf_detail": _vrf_status_detail(locked_project, TaskImpostazioni.get_singleton()) if locked_project is not None else None,
                "locked_project_task_total": Task.objects.filter(project=locked_project).count() if locked_project is not None else 0,
            },
        )

    return render(
        request,
        "tasks/form.html",
        {
            **_tasks_shell_context(request, active="create"),
            "page_title": "Nuova attivita kickoff",
            "form": form,
            "mode": "create",
            "suggested_start_date": suggested_start_date,
            "suggested_project_id": locked_project.id if locked_project is not None else None,
            "locked_project": locked_project,
            "locked_project_vrf_detail": _vrf_status_detail(locked_project, TaskImpostazioni.get_singleton()) if locked_project is not None else None,
            "locked_project_task_total": Task.objects.filter(project=locked_project).count() if locked_project is not None else 0,
        },
    )


@task_permissions_required("tasks_view")
def task_edit(request, task_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request).prefetch_related("subscribers"), pk=task_id)
    if not _can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    projects_qs = _scoped_projects_queryset(request).order_by("name", "id")
    before = _task_snapshot(task)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task, user=request.user, project_queryset=projects_qs)
        if form.is_valid():
            updated_task = form.save(commit=False)
            updated_task.project = form.resolve_project(created_by=request.user)

            # Blocking guard: progetto bloccato per VRF mancante
            if updated_task.project and not getattr(form, "new_project_created", False):
                cfg = TaskImpostazioni.get_singleton()
                vrf_detail = _vrf_status_detail(updated_task.project, cfg)
                if vrf_detail["is_blocked"]:
                    messages.error(
                        request,
                        "Kickoff bloccato: carica il documento VRF prima di modificare questa attivita kickoff.",
                    )
                    return redirect(
                        reverse("tasks:project_vrf_upload", kwargs={"project_id": updated_task.project.id})
                        + f"?next={reverse('tasks:edit', kwargs={'task_id': task.id})}"
                    )

            updated_task.save()
            form.save_m2m()
            _log_task_update_events(updated_task, request.user, before)
            if form.reused_existing_project is not None and updated_task.project_id:
                messages.info(
                    request,
                    (
                        f"Attivita kickoff riallineata al kickoff esistente '{updated_task.project.name}' "
                        f"(P/N {updated_task.project.part_number or '-'})."
                    ),
                )
            messages.success(request, "Attivita kickoff aggiornata.")
            if form.assignment_conflicts and updated_task.assigned_to_id:
                assignee_name = updated_task.assigned_to.get_full_name() or updated_task.assigned_to.get_username()
                messages.warning(
                    request,
                    (
                        f"Impegni sovrapposti: {assignee_name} ha gia {len(form.assignment_conflicts)} task attive "
                        f"nello stesso periodo ({form.assignment_conflict_summary(limit=3)})."
                    ),
                )
            if form.auto_raised_priority:
                messages.warning(request, "Priorita aggiornata automaticamente a High per conflitto impegni.")
            if updated_task.is_overdue:
                messages.warning(request, "Task in stato overdue.")
            _add_task_absence_warnings(request, updated_task)
            return redirect("tasks:detail", task_id=updated_task.id)
    else:
        form = TaskForm(instance=task, user=request.user, project_queryset=projects_qs)

    return render(
        request,
        "tasks/form.html",
        {
            **_tasks_shell_context(request, active="edit", task=task),
            "page_title": "Modifica attivita kickoff",
            "form": form,
            "task": task,
            "mode": "edit",
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def update_due_date(request, task_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request), pk=task_id)
    if not _can_update_task_due_date(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )

    before = _task_snapshot(task)
    form = TaskDueDateForm(request.POST, instance=task)
    if form.is_valid():
        task = form.save()
        _log_task_update_events(task, request.user, before)
        messages.success(request, "Data prevista conclusione aggiornata.")
        if task.is_overdue:
            messages.warning(request, "Task in stato overdue.")
        _add_task_absence_warnings(request, task)
    else:
        messages.error(request, "Data prevista conclusione non valida.")

    return redirect("tasks:detail", task_id=task.id)


@require_POST
@task_permissions_required("tasks_view")
def change_status(request, task_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request), pk=task_id)
    if not _can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    old_status = task.status
    form = TaskStatusForm(request.POST, instance=task)
    if form.is_valid():
        task = form.save()
        if old_status != task.status:
            _log_event(
                task,
                request.user,
                TaskEventType.STATUS_CHANGE,
                {"from": old_status, "to": task.status},
            )
            messages.success(request, "Stato task aggiornato.")
    else:
        messages.error(request, "Stato non valido.")
    return redirect("tasks:detail", task_id=task_id)


@require_POST
@task_permissions_required("tasks_view", "tasks_comment")
def add_comment(request, task_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request), pk=task_id)
    notify_users_qs = _task_notify_users_queryset(task)
    form = TaskCommentForm(request.POST, user=request.user, notify_user_queryset=notify_users_qs)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.task = task
        comment.author = request.user
        comment.save()
        _log_event(
            task,
            request.user,
            TaskEventType.COMMENT_ADDED,
            {
                "comment_id": comment.id,
                "target_user_id": comment.target_user_id,
            },
        )
        if comment.target_user_id and comment.target_user_id != request.user.id:
            _notify_user(
                comment.target_user,
                message_text=f"Nuovo commento su task '{task.title}'.",
                action_url=reverse("tasks:detail", kwargs={"task_id": task.id}),
            )
        messages.success(request, "Commento aggiunto.")
    else:
        messages.error(request, "Commento non valido.")
    return redirect("tasks:detail", task_id=task_id)


@require_POST
@task_permissions_required("tasks_view")
def add_subtask(request, task_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request), pk=task_id)
    if not _can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    form = SubTaskForm(request.POST, user=request.user)
    if form.is_valid():
        subtask = form.save(commit=False)
        subtask.task = task
        subtask.save()
        _log_event(
            task,
            request.user,
            TaskEventType.SUBTASK_ADDED,
            {
                "subtask_id": subtask.id,
                "title": subtask.title,
                "status": subtask.status,
            },
        )
        _apply_subtask_rollup(task, request.user)
        messages.success(request, "Subtask aggiunta.")
    else:
        messages.error(request, "Subtask non valida.")
    return redirect("tasks:detail", task_id=task_id)


@require_POST
@task_permissions_required("tasks_view")
def edit_subtask_status(request, task_id: int, subtask_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request), pk=task_id)
    if not _can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    subtask = get_object_or_404(SubTask.objects.filter(task=task), pk=subtask_id)
    old_status = subtask.status

    form = SubTaskStatusForm(request.POST, instance=subtask)
    if form.is_valid():
        subtask = form.save()
        if old_status != subtask.status:
            _log_event(
                task,
                request.user,
                TaskEventType.SUBTASK_STATUS_CHANGE,
                {
                    "subtask_id": subtask.id,
                    "from": old_status,
                    "to": subtask.status,
                },
            )
            _apply_subtask_rollup(task, request.user)
            messages.success(request, "Stato subtask aggiornato.")
    else:
        messages.error(request, "Stato subtask non valido.")
    return redirect("tasks:detail", task_id=task_id)


@require_POST
@task_permissions_required("tasks_view")
def add_attachment(request, task_id: int):
    task = get_object_or_404(_scoped_tasks_queryset(request), pk=task_id)
    if not _can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    form = TaskAttachmentForm(request.POST, request.FILES, task=task)

    if form.is_valid():
        attachment = form.save(commit=False)
        attachment.uploaded_by = request.user
        attachment.original_name = getattr(form.cleaned_data.get("file"), "name", "") or ""

        attach_to = form.cleaned_data.get("attach_to") or TaskAttachmentForm.TARGET_TASK
        if attach_to == TaskAttachmentForm.TARGET_PROJECT:
            attachment.project = task.project
            attachment.task = None
            target = "project"
        else:
            attachment.task = task
            attachment.project = None
            target = "task"

        attachment.save()
        _log_event(
            task,
            request.user,
            TaskEventType.ATTACHMENT_ADDED,
            {
                "attachment_id": attachment.id,
                "target": target,
                "task_id": attachment.task_id,
                "project_id": attachment.project_id,
                "file_name": attachment.original_name,
            },
        )
        messages.success(request, "Allegato caricato.")
    else:
        messages.error(request, "Upload allegato non valido.")

    return redirect("tasks:detail", task_id=task.id)


@task_permissions_required("tasks_view")
def project_list(request):
    projects_base_qs = _scoped_projects_queryset(request).order_by()
    projects = list(
        projects_base_qs.annotate(
            task_total=Count("tasks", distinct=True),
            task_open=Count("tasks", filter=Q(tasks__status__in=OPEN_STATUSES), distinct=True),
            task_done=Count("tasks", filter=Q(tasks__status=TaskStatus.DONE), distinct=True),
        ).order_by("name", "id")
    )
    cfg = TaskImpostazioni.get_singleton()
    for p in projects:
        p.vrf_detail = _vrf_status_detail(p, cfg)
    return render(
        request,
        "tasks/projects.html",
        {
            **_tasks_shell_context(request, active="projects"),
            "page_title": "Portfolio kickoff",
            "projects": projects,
            "is_scope_admin": _has_task_permission(request, "tasks_admin"),
        },
    )


@require_POST
@task_permissions_required("tasks_view", "tasks_create")
def copy_project_with_vrf(request, project_id: int):
    source_project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    kickoff = _duplicate_kickoff(source_project, created_by=request.user, clear_part_number=False)
    log_action(
        request,
        "copy_kickoff_vrf",
        "tasks",
        {
            "message": f"Copiato kickoff #{source_project.id} in kickoff #{kickoff.id} con duplicazione VRF.",
            "source_project_id": source_project.id,
            "copied_project_id": kickoff.id,
        },
    )
    messages.success(request, f"Kickoff duplicato correttamente: {kickoff.name}.")
    return redirect("tasks:project_gantt", project_id=kickoff.id)


@require_POST
@task_permissions_required("tasks_view", "tasks_create")
def copy_project_with_vrf_without_pn(request, project_id: int):
    source_project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    kickoff = _duplicate_kickoff(source_project, created_by=request.user, clear_part_number=True)
    log_action(
        request,
        "copy_kickoff_vrf_without_pn",
        "tasks",
        {
            "message": (
                f"Copiato kickoff #{source_project.id} in kickoff #{kickoff.id} "
                "svuotando il P/N e la cella B3 del file VRF."
            ),
            "source_project_id": source_project.id,
            "copied_project_id": kickoff.id,
            "without_part_number": True,
        },
    )
    messages.success(request, f"Kickoff duplicato senza P/N: {kickoff.name}.")
    return redirect("tasks:project_gantt", project_id=kickoff.id)


@task_permissions_required("tasks_view")
def project_gantt(request, project_id: int):
    project_qs = _scoped_projects_queryset(request).prefetch_related(
        Prefetch(
            "tasks",
            # Nel Gantt le task sono ordinate per ordine di creazione (id asc)
            # così WBS 1 = prima task creata, WBS 2 = seconda, ecc.
            # Questo mantiene la sequenza logica definita dall'utente
            # indipendentemente dalle date (che possono essere in disordine durante la pianificazione).
            queryset=Task.objects.select_related(
                "created_by",
                "assigned_to",
                "project",
                "project__project_manager",
                "project__capo_commessa",
                "project__programmer",
                "project__similar_project",
            ).prefetch_related("subscribers").order_by("id"),
        ),
        Prefetch(
            "comments",
            queryset=ProjectComment.objects.select_related("author", "target_user").order_by("-created_at", "-id"),
        ),
    )
    project = get_object_or_404(project_qs, pk=project_id)
    # Forziamo ordinamento lato Python (SQL Server può ignorare ORDER BY nei prefetch)
    tasks = sorted(project.tasks.all(), key=lambda t: t.id)
    can_edit_schedule = _can_edit_project_schedule(request, project)
    can_comment = _has_task_permission(request, "tasks_comment")
    gantt_options = _parse_gantt_options(request)
    gantt_meta = _project_gantt_rows(tasks, min_window_days=gantt_options["window_days"])
    comment_form = ProjectCommentForm(
        user=request.user,
        notify_user_queryset=_project_notify_users_queryset(project),
    )
    today = timezone.localdate()
    total_tasks = len(tasks)
    done_total = sum(1 for task in tasks if task.status == TaskStatus.DONE)
    open_total = sum(1 for task in tasks if task.status in OPEN_STATUSES)
    in_progress_total = sum(1 for task in tasks if task.status == TaskStatus.IN_PROGRESS)
    overdue_total = sum(1 for task in tasks if task.is_overdue)
    due_next_7d_total = sum(
        1
        for task in tasks
        if task.status in OPEN_STATUSES
        and task.due_date
        and today <= task.due_date <= today + timedelta(days=7)
    )
    unassigned_total = sum(1 for task in tasks if not task.assigned_to_id)
    high_priority_open_total = sum(
        1 for task in tasks if task.status in OPEN_STATUSES and task.priority == TaskPriority.HIGH
    )
    invalid_range_total = sum(1 for row in gantt_meta["rows"] if row.get("invalid_range"))
    absence_conflict_total = sum(1 for row in gantt_meta["rows"] if row.get("has_absence_conflicts"))
    progress_percent = int(round((done_total / total_tasks) * 100)) if total_tasks else 0
    project_summary = {
        "total_tasks": total_tasks,
        "open_tasks": open_total,
        "in_progress_tasks": in_progress_total,
        "done_tasks": done_total,
        "overdue_tasks": overdue_total,
        "due_next_7d_tasks": due_next_7d_total,
        "unassigned_tasks": unassigned_total,
        "high_priority_open_tasks": high_priority_open_total,
        "invalid_range_tasks": invalid_range_total,
        "absence_conflict_tasks": absence_conflict_total,
        "progress_percent": progress_percent,
        "planned_start": gantt_meta["timeline_start"],
        "planned_end": gantt_meta["timeline_end"],
    }

    task_update_forms = {}
    if can_edit_schedule:
        for task in tasks:
            task_update_forms[task.id] = ProjectTaskGanttUpdateForm(instance=task, prefix=f"task_{task.id}")
        for row in gantt_meta["rows"]:
            row["update_form"] = task_update_forms.get(row["task"].id)

    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)

    return render(
        request,
        "tasks/project_gantt.html",
        {
            **_tasks_shell_context(request, active="gantt", project=project),
            "page_title": f"Gantt kickoff - {project.name}",
            "project": project,
            "tasks": tasks,
            "gantt_rows": gantt_meta["rows"],
            "gantt_timeline_start": gantt_meta["timeline_start"],
            "gantt_timeline_end": gantt_meta["timeline_end"],
            "gantt_today": gantt_meta["today"],
            "gantt_days": gantt_meta["days"],
            "gantt_month_spans": gantt_meta["month_spans"],
            "can_edit_schedule": can_edit_schedule,
            "can_comment": can_comment,
            "task_update_forms": task_update_forms,
            "project_comment_form": comment_form,
            "project_summary": project_summary,
            "gantt_option_window_days": gantt_options["window_days"],
            "gantt_option_cell_size": gantt_options["cell_size"],
            "gantt_option_name_width": gantt_options["name_width"],
            "gantt_show_wbs": gantt_options["show_wbs"],
            "gantt_show_duration": gantt_options["show_duration"],
            "gantt_show_start": gantt_options["show_start"],
            "gantt_show_end": gantt_options["show_end"],
            "gantt_day_cell_px": gantt_options["day_cell_px"],
            "gantt_window_choices": gantt_options["window_choices"],
            "gantt_cell_choices": gantt_options["cell_choices"],
            "gantt_name_width_choices": gantt_options["name_width_choices"],
            "gantt_return_qs": gantt_options["return_qs"],
            "vrf_detail": vrf_detail,
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_update_task(request, project_id: int, task_id: int):
    project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    if not _can_edit_project_schedule(request, project):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )

    task = get_object_or_404(Task.objects.filter(project=project), pk=task_id)
    before = _task_snapshot(task)
    form = ProjectTaskGanttUpdateForm(request.POST, instance=task, prefix=f"task_{task.id}")
    if form.is_valid():
        task = form.save()
        _log_task_update_events(task, request.user, before)
        messages.success(request, f"Gantt aggiornato per task '{task.title}'.")
        _add_task_absence_warnings(request, task)
    else:
        errors = "; ".join(
            f"{form.fields[f].label or f}: {', '.join(errs)}"
            for f, errs in form.errors.items()
            if f != "__all__"
        )
        non_field = "; ".join(form.non_field_errors())
        detail = errors or non_field or "dati non validi"
        messages.error(request, f"Aggiornamento non salvato — {detail}")

    return_qs = str(request.POST.get("return_qs") or "").strip()
    target_url = reverse("tasks:project_gantt", kwargs={"project_id": project.id})
    if return_qs:
        target_url = f"{target_url}?{return_qs}"
    return redirect(target_url)


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_shift_task(request, project_id: int, task_id: int):
    project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    if not _can_edit_project_schedule(request, project):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    task = get_object_or_404(Task.objects.filter(project=project), pk=task_id)

    try:
        shift_days = int(str(request.POST.get("shift_days", "0")).strip())
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_shift"}, status=400)

    if shift_days == 0:
        return JsonResponse(
            {
                "ok": True,
                "task_id": task.id,
                "shift_days": 0,
                "next_step_due": task.next_step_due.isoformat() if task.next_step_due else None,
                "due_date": task.due_date.isoformat() if task.due_date else None,
            }
        )

    # limite operativo anti-errori da drag involontario
    shift_days = max(-365, min(365, shift_days))

    # Vincolo predecessore implicito (WBS order): il task non può iniziare prima della fine
    # del task precedente. Il clamp garantisce la coerenza anche se il frontend è bypassato.
    predecessor = Task.objects.filter(project=project, id__lt=task.id).order_by("-id").first()
    if predecessor:
        pred_end = predecessor.due_date or predecessor.next_step_due
        if pred_end:
            orig_start = task.next_step_due or task.due_date
            if orig_start:
                min_shift = (pred_end + timedelta(days=1) - orig_start).days
                shift_days = max(shift_days, min_shift)

    # Salva la data originale di start PRIMA dello spostamento (per il cascade)
    original_active_start = task.next_step_due or task.due_date

    before = _task_snapshot(task)

    if task.next_step_due:
        task.next_step_due = task.next_step_due + timedelta(days=shift_days)
    if task.due_date:
        task.due_date = task.due_date + timedelta(days=shift_days)
    task.save(update_fields=["next_step_due", "due_date", "updated_at"])
    _log_task_update_events(task, request.user, before)

    # Cascade sequenziale: rispetta l'ordine WBS (creazione) e garantisce che
    # ogni task inizi DOPO la fine della precedente nella sequenza.
    cascade = str(request.POST.get("cascade", "1")).strip() != "0"
    cascade_count = 0
    if cascade:
        # Tutte le task del progetto in ordine WBS (id asc = ordine di creazione)
        all_project_tasks = list(Task.objects.filter(project=project).order_by("id"))

        # Sostituisce la task appena salvata con la versione aggiornata in memoria
        for i, t in enumerate(all_project_tasks):
            if t.id == task.id:
                all_project_tasks[i] = task
                dragged_idx = i
                break
        else:
            dragged_idx = -1

        if dragged_idx >= 0:
            for i in range(dragged_idx + 1, len(all_project_tasks)):
                ft = all_project_tasks[i]
                prev = all_project_tasks[i - 1]

                # Data di fine della task precedente
                prev_end = prev.due_date or prev.next_step_due
                if not prev_end:
                    continue

                # Data di inizio della task corrente
                ft_start = ft.next_step_due or ft.due_date
                if not ft_start:
                    continue

                if ft_start <= prev_end:
                    # La task corrente inizia prima o nello stesso giorno in cui finisce la precedente:
                    # la spostiamo al giorno successivo alla fine della precedente,
                    # mantenendo la durata originale.
                    new_start = prev_end + timedelta(days=1)
                    task_delta = (new_start - ft_start).days
                    if ft.next_step_due:
                        ft.next_step_due = ft.next_step_due + timedelta(days=task_delta)
                    if ft.due_date:
                        ft.due_date = ft.due_date + timedelta(days=task_delta)
                    ft.save(update_fields=["next_step_due", "due_date", "updated_at"])
                    cascade_count += 1

    conflict_messages: list[str] = []
    conflicts = _task_date_absence_conflicts(task)
    if conflicts:
        for field_name in ("next_step_due", "due_date"):
            if field_name not in conflicts:
                continue
            target_date = getattr(task, field_name)
            if not target_date:
                continue
            labels = [f"{entry['tipo']} ({entry['status']})" for entry in conflicts[field_name]]
            label_text = ", ".join(dict.fromkeys(labels))
            conflict_messages.append(
                f"{field_name}:{target_date.strftime('%d/%m/%Y')}:{label_text}"
            )

    return JsonResponse(
        {
            "ok": True,
            "task_id": task.id,
            "shift_days": shift_days,
            "cascade_count": cascade_count,
            "next_step_due": task.next_step_due.isoformat() if task.next_step_due else None,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "next_step_due_display": task.next_step_due.strftime("%d/%m/%Y") if task.next_step_due else "",
            "due_date_display": task.due_date.strftime("%d/%m/%Y") if task.due_date else "",
            "absence_conflicts": conflict_messages,
        }
    )


@require_POST
@task_permissions_required("tasks_view", "tasks_comment")
def add_project_comment(request, project_id: int):
    project = get_object_or_404(_scoped_projects_queryset(request), pk=project_id)
    notify_users_qs = _project_notify_users_queryset(project)
    form = ProjectCommentForm(request.POST, user=request.user, notify_user_queryset=notify_users_qs)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.project = project
        comment.author = request.user
        comment.save()
        if comment.target_user_id and comment.target_user_id != request.user.id:
            _notify_user(
                comment.target_user,
                message_text=f"Nuovo commento nel kickoff '{project.name}'.",
                action_url=reverse("tasks:project_gantt", kwargs={"project_id": project.id}),
            )
        messages.success(request, "Commento kickoff aggiunto.")
    else:
        messages.error(request, "Commento kickoff non valido.")
    return_qs = str(request.POST.get("return_qs") or "").strip()
    target_url = reverse("tasks:project_gantt", kwargs={"project_id": project.id})
    if return_qs:
        target_url = f"{target_url}?{return_qs}"
    return redirect(target_url)


@legacy_admin_required
def gestione_admin(request):
    """Pagina di gestione interna Tasks — accesso solo admin."""
    from django.core.paginator import Paginator

    today = timezone.localdate()
    tab = request.GET.get("tab", "riepilogo")

    # --- Statistiche ---
    total_tasks = Task.objects.count()
    total_projects = Project.objects.count()
    _tasks_by_status_raw = dict(Task.objects.values_list("status").annotate(n=Count("id")).order_by())
    tasks_by_status = [(val, lbl, _tasks_by_status_raw.get(val, 0)) for val, lbl in TaskStatus.choices]
    tasks_overdue = Task.objects.filter(
        due_date__lt=today,
        status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS],
    ).count()
    top_assignees = list(
        Task.objects.filter(assigned_to__isnull=False)
        .values("assigned_to__username")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    )
    todo_count = _tasks_by_status_raw.get(TaskStatus.TODO, 0)
    in_progress_count = _tasks_by_status_raw.get(TaskStatus.IN_PROGRESS, 0)
    done_count = _tasks_by_status_raw.get(TaskStatus.DONE, 0)

    # --- Record ---
    q_task = request.GET.get("q_task", "").strip()
    q_proj = request.GET.get("q_proj", "").strip()
    filter_status = request.GET.get("filter_status", "").strip()

    tasks_qs = Task.objects.select_related("project", "assigned_to").order_by("-updated_at")
    if q_task:
        tasks_qs = tasks_qs.filter(Q(title__icontains=q_task))
    if filter_status:
        tasks_qs = tasks_qs.filter(status=filter_status)
    tasks_page = Paginator(tasks_qs, 50).get_page(request.GET.get("task_page"))

    projects_qs = Project.objects.select_related("project_manager").order_by("-updated_at")
    if q_proj:
        projects_qs = projects_qs.filter(Q(name__icontains=q_proj) | Q(client_name__icontains=q_proj))
    projects_page = Paginator(projects_qs, 50).get_page(request.GET.get("proj_page"))

    # --- Log ---
    audit_entries = AuditLog.objects.filter(modulo="tasks").order_by("-created_at")[:100]

    return render(
        request,
        "tasks/gestione_admin.html",
        {
            **_tasks_shell_context(request, active="admin"),
            "page_title": "Gestione KICK-OFF",
            "tab": tab,
            # stats
            "total_tasks": total_tasks,
            "total_projects": total_projects,
            "tasks_by_status": tasks_by_status,
            "tasks_overdue": tasks_overdue,
            "top_assignees": top_assignees,
            "task_status_choices": TaskStatus.choices,
            "todo_count": todo_count,
            "in_progress_count": in_progress_count,
            "done_count": done_count,
            # records
            "tasks_page": tasks_page,
            "projects_page": projects_page,
            "q_task": q_task,
            "q_proj": q_proj,
            "filter_status": filter_status,
            # log
            "audit_entries": audit_entries,
        },
    )


@legacy_admin_required
def impostazioni(request):
    """Impostazioni globali del modulo Task."""
    cfg = TaskImpostazioni.get_singleton()

    if request.method == "POST":
        branding_response = handle_module_branding_post(
            request,
            module_key="tasks",
            redirect_to="tasks:impostazioni",
            audit_module="tasks",
            fallback_label="KICK-OFF",
        )
        if branding_response is not None:
            return branding_response
        cfg.responsabile_email = request.POST.get("responsabile_email", "").strip()
        cfg.notifiche_scadenza_attive = bool(request.POST.get("notifiche_scadenza_attive"))
        cfg.giorni_preavviso = max(1, int(request.POST.get("giorni_preavviso") or 3))
        cfg.note_generali = request.POST.get("note_generali", "").strip()
        cfg.vrf_reminder_days = max(1, int(request.POST.get("vrf_reminder_days") or 7))
        cfg.vrf_blocking_days = max(1, int(request.POST.get("vrf_blocking_days") or 30))
        cfg.save()
        log_action(request, "modifica", "tasks", {"message": "Aggiornate impostazioni KICK-OFF"})
        messages.success(request, "Impostazioni salvate.")
        return redirect("tasks:impostazioni")

    return render(request, "tasks/impostazioni.html", {
        "cfg": cfg,
        "tasks_shell_active": "impostazioni",
        "tasks_shell_can_admin": True,
        **get_module_branding_context("tasks", fallback_label="KICK-OFF"),
    })


@legacy_admin_required
def gestione_admin(request):
    """Compat legacy: la vecchia gestione admin confluisce nelle impostazioni."""
    params = request.GET.copy()
    params["tab"] = _normalize_tasks_settings_tab(params.get("tab"), default="riepilogo")
    target_url = reverse("tasks:impostazioni")
    query_string = params.urlencode()
    if query_string:
        target_url = f"{target_url}?{query_string}"
    return redirect(target_url)


@legacy_admin_required
def impostazioni(request):
    """Pagina canonica impostazioni/admin del modulo Task."""
    cfg = TaskImpostazioni.get_singleton()
    config_url = f"{reverse('tasks:impostazioni')}?tab=config"

    if request.method == "POST":
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
        cfg.save()
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


# ---------------------------------------------------------------------------
# VRF Document upload / management
# ---------------------------------------------------------------------------

@task_permissions_required("tasks_view")
def project_vrf_upload(request, project_id: int):
    """Upload documento VRF per un progetto: GET mostra form, POST gestisce upload/confirm/later/not_required."""
    project_qs = _scoped_projects_queryset(request)
    project = get_object_or_404(project_qs, pk=project_id)
    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)

    next_url = request.GET.get("next") or request.POST.get("next") or reverse(
        "tasks:project_gantt", kwargs={"project_id": project_id}
    )

    # Sanitize next_url to only allow relative paths
    if next_url and not next_url.startswith("/"):
        next_url = reverse("tasks:project_gantt", kwargs={"project_id": project_id})

    session_key = f"tasks_vrf_preview_{project_id}"

    if request.method == "GET":
        request.session.pop(session_key, None)
        return render(request, "tasks/project_vrf_upload.html", {
            **_tasks_shell_context(request, active="projects", project=project),
            "page_title": f"Documento VRF - {project.name}",
            "project": project,
            "vrf_detail": vrf_detail,
            "preview": None,
            "next_url": next_url,
        })

    action = request.POST.get("action", "")

    # --- action: upload → parse e mostra preview ---
    if action == "upload":
        uploaded = request.FILES.get("vrf_file")
        if not uploaded:
            messages.error(request, "Nessun file selezionato.")
            return redirect(request.get_full_path())

        ext = uploaded.name.rsplit(".", 1)[-1].lower() if "." in uploaded.name else ""
        if ext not in {"xlsx", "xls"}:
            messages.error(request, "Formato non valido. Carica un file .xlsx o .xls.")
            return redirect(request.get_full_path())

        try:
            file_bytes = uploaded.read()
            extracted = _parse_vrf_excel(file_bytes)
        except Exception:
            messages.error(request, "Impossibile leggere il file Excel. Verifica che sia un MOD.073 valido.")
            return redirect(request.get_full_path())

        request.session[session_key] = {
            "filename": uploaded.name,
            "file_bytes_b64": __import__("base64").b64encode(file_bytes).decode(),
            "extracted": extracted,
        }

        return render(request, "tasks/project_vrf_upload.html", {
            **_tasks_shell_context(request, active="projects", project=project),
            "page_title": f"Documento VRF - {project.name}",
            "project": project,
            "vrf_detail": vrf_detail,
            "preview": extracted,
            "filename": uploaded.name,
            "next_url": next_url,
        })

    # --- action: confirm → salva file e aggiorna progetto ---
    if action == "confirm":
        session_data = request.session.pop(session_key, None)
        if not session_data:
            messages.error(request, "Sessione scaduta. Ricarica il file.")
            return redirect(request.get_full_path())

        import base64, io
        from django.core.files.base import ContentFile
        from django.utils import timezone as tz

        extracted = session_data["extracted"]
        filename = session_data["filename"]
        file_bytes = base64.b64decode(session_data["file_bytes_b64"])

        project.vrf_file.save(filename, ContentFile(file_bytes), save=False)
        project.vrf_original_name = filename
        project.vrf_uploaded_at = tz.now()
        project.vrf_status = VRFDocStatus.UPLOADED

        if extracted.get("client_name"):
            project.client_name = extracted["client_name"]
        if extracted.get("part_number"):
            project.part_number = extracted["part_number"]
        if extracted.get("versione"):
            project.versione = extracted["versione"]
        if extracted.get("vrf_quote_number"):
            project.vrf_quote_number = extracted["vrf_quote_number"]
        if extracted.get("vrf_description"):
            project.vrf_description = extracted["vrf_description"]
        if extracted.get("vrf_esp"):
            project.vrf_esp = extracted["vrf_esp"]

        project.save()
        log_action(
            request,
            "upload_vrf",
            "tasks",
            {
                "message": f"Caricato documento VRF '{filename}' per kickoff #{project.id} — {project.name}",
                "project_id": project.id,
                "filename": filename,
            },
        )
        messages.success(request, f"Documento VRF caricato correttamente. Dati del kickoff aggiornati da '{filename}'.")
        return redirect(next_url)

    # --- action: discard → torna al form upload ---
    if action == "discard":
        request.session.pop(session_key, None)
        return redirect(request.get_full_path())

    # --- action: later → resta PENDING ---
    if action == "later":
        request.session.pop(session_key, None)
        log_action(
            request,
            "vrf_remind_skipped",
            "tasks",
            {
                "message": f"VRF rimandato per kickoff #{project.id} — {project.name}",
                "project_id": project.id,
            },
        )
        messages.info(request, "Documento VRF rimandato. Ricordati di caricarlo al piu presto.")
        return redirect(next_url)

    # --- action: not_required ---
    if action == "not_required":
        request.session.pop(session_key, None)
        project.vrf_status = VRFDocStatus.NOT_REQUIRED
        project.save(update_fields=["vrf_status"])
        log_action(
            request,
            "vrf_not_required",
            "tasks",
            {
                "message": f"VRF marcato come 'non richiesto' per kickoff #{project.id} — {project.name}",
                "project_id": project.id,
            },
        )
        messages.success(request, "Kickoff marcato come 'VRF non richiesto'.")
        return redirect(next_url)

    return redirect(request.get_full_path())


# ---------------------------------------------------------------------------
# Excel import / template download
# ---------------------------------------------------------------------------

_IMPORT_COLUMNS = [
    "Kickoff / Riferimento",
    "Cliente",
    "P/N",
    "Revisione",
    "Versione",
    "PM (username)",
    "Titolo attivita",
    "Descrizione attivita",
    "Stato",       # TODO / IN_PROGRESS / DONE / CANCELED
    "Priorita",    # LOW / MEDIUM / HIGH
    "Assegnato a (username)",
    "Data inizio (YYYY-MM-DD)",
    "Data fine (YYYY-MM-DD)",
    "Tag",
]


@task_permissions_required("tasks_create")
def download_excel_template(request):
    """Genera e scarica il template .xlsx per l'import attivita kickoff."""
    import io
    import openpyxl
    from django.http import HttpResponse

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Kickoff Import"

    # Header row
    for col_idx, col_name in enumerate(_IMPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = openpyxl.styles.Font(bold=True)

    # Example row
    example = [
        "Rif. kickoff Alfa",
        "Cliente SRL",
        "PN-001",
        "A",
        "1.0",
        "",
        "Titolo attivita di esempio",
        "Descrizione operativa",
        "TODO",
        "MEDIUM",
        "",
        "",
        "",
        "",
    ]
    for col_idx, val in enumerate(example, start=1):
        ws.cell(row=2, column=col_idx, value=val)

    # Istruzioni foglio
    ws_info = wb.create_sheet("Istruzioni")
    ws_info["A1"] = "Istruzioni import attivita kickoff"
    ws_info["A1"].font = openpyxl.styles.Font(bold=True, size=13)
    instructions = [
        ("Kickoff / Riferimento", "Riferimento libero per raggruppare piu righe nello stesso kickoff quando il P/N non e disponibile."),
        ("Cliente", "Ragione sociale cliente (testo libero)."),
        ("P/N", "Part Number (testo libero)."),
        ("Revisione", "Revisione del P/N (testo libero, es. A, B, 01)."),
        ("Versione", "Versione del P/N (testo libero, es. 1.0, 2.3)."),
        ("PM (username)", "Username del project manager. Deve esistere nel sistema."),
        ("Titolo attivita", "Titolo dell'attivita kickoff (obbligatorio)."),
        ("Descrizione attivita", "Descrizione operativa (opzionale)."),
        ("Stato", "TODO / IN_PROGRESS / DONE / CANCELED. Default: TODO."),
        ("Priorita", "LOW / MEDIUM / HIGH. Default: MEDIUM."),
        ("Assegnato a (username)", "Username dell'operatore. Deve esistere nel sistema."),
        ("Data inizio (YYYY-MM-DD)", "Data inizio (next_step_due). Formato: 2025-03-15."),
        ("Data fine (YYYY-MM-DD)", "Data fine prevista (due_date). Formato: 2025-04-30."),
        ("Tag", "Etichette separate da virgola."),
    ]
    ws_info["A3"] = "Campo"
    ws_info["B3"] = "Descrizione"
    ws_info["A3"].font = openpyxl.styles.Font(bold=True)
    ws_info["B3"].font = openpyxl.styles.Font(bold=True)
    for row_idx, (field, desc) in enumerate(instructions, start=4):
        ws_info.cell(row=row_idx, column=1, value=field)
        ws_info.cell(row=row_idx, column=2, value=desc)
    ws_info.column_dimensions["A"].width = 28
    ws_info.column_dimensions["B"].width = 80

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="template_import_kickoff.xlsx"'
    return response


@task_permissions_required("tasks_create")
def import_excel(request):
    """Upload + anteprima + commit import attivita kickoff da Excel."""
    import io
    import openpyxl
    from django.db import transaction

    if request.method == "GET":
        return render(request, "tasks/import.html", {
            **_tasks_shell_context(request, active="import"),
            "page_title": "Import attivita kickoff da Excel",
            "columns": _IMPORT_COLUMNS,
        })

    # --- STEP 1: upload file e anteprima ---
    if "file" in request.FILES and "confirm" not in request.POST:
        uploaded = request.FILES["file"]
        try:
            wb = openpyxl.load_workbook(io.BytesIO(uploaded.read()), read_only=True, data_only=True)
        except Exception:
            messages.error(request, "File non valido. Carica un file .xlsx corretto.")
            return redirect("tasks:import_excel")

        ws = wb.active
        rows_raw = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()

        preview_rows = []
        errors = []
        for row_idx, row in enumerate(rows_raw, start=2):
            if not any(row):
                continue
            def _cell(n):
                try:
                    return str(row[n] or "").strip()
                except IndexError:
                    return ""

            kickoff_reference = _cell(0)
            part_number = _cell(2)
            revisione = _cell(3) if part_number else ""
            versione = _cell(4) if part_number else ""
            titolo = _cell(6)
            if not titolo:
                errors.append(f"Riga {row_idx}: campo Titolo attivita vuoto — riga ignorata.")
                continue

            stato_raw = _cell(8).upper() or "TODO"
            if stato_raw not in {s.value for s in TaskStatus}:
                stato_raw = "TODO"
            priorita_raw = _cell(9).upper() or "MEDIUM"
            if priorita_raw not in {p.value for p in TaskPriority}:
                priorita_raw = "MEDIUM"

            preview_rows.append({
                "progetto": kickoff_reference,
                "cliente": _cell(1),
                "part_number": part_number,
                "revisione": revisione,
                "versione": versione,
                "pm_username": _cell(5),
                "titolo": titolo,
                "descrizione": _cell(7),
                "stato": stato_raw,
                "priorita": priorita_raw,
                "assegnato_username": _cell(10),
                "data_inizio": _cell(11),
                "data_fine": _cell(12),
                "tag": _cell(13),
            })

        request.session["tasks_import_preview"] = preview_rows
        return render(request, "tasks/import.html", {
            **_tasks_shell_context(request, active="import"),
            "page_title": "Import attivita kickoff da Excel",
            "columns": _IMPORT_COLUMNS,
            "preview_rows": preview_rows,
            "errors": errors,
            "filename": uploaded.name,
        })

    # --- STEP 2: commit ---
    if "confirm" in request.POST:
        preview_rows = request.session.pop("tasks_import_preview", [])
        if not preview_rows:
            messages.error(request, "Sessione scaduta o nessun dato da importare. Ricarica il file.")
            return redirect("tasks:import_excel")

        created_projects = 0
        updated_projects = 0
        created_tasks = 0
        updated_project_ids: set[int] = set()
        cached_projects_by_identity: dict[tuple[str, str, str], Project] = {}
        cached_projects_by_reference: dict[str, Project] = {}

        try:
            with transaction.atomic():
                for row in preview_rows:
                    # Risolvi PM
                    pm_user = None
                    if row["pm_username"]:
                        pm_user = User.objects.filter(username__iexact=row["pm_username"]).first()

                    proj_defaults = {
                        "client_name": row["cliente"],
                        "project_manager": pm_user,
                    }
                    part_number = (row["part_number"] or "").strip()
                    revisione = (row["revisione"] or "").strip()
                    versione = (row["versione"] or "").strip()
                    kickoff_reference = (row["progetto"] or "").strip()

                    project = None
                    project_was_created = False
                    if part_number:
                        identity_key = (
                            part_number.lower(),
                            revisione.lower(),
                            versione.lower(),
                        )
                        project = cached_projects_by_identity.get(identity_key)
                        if project is None:
                            project = (
                                Project.objects.filter(
                                    part_number__iexact=part_number,
                                    revisione__iexact=revisione,
                                    versione__iexact=versione,
                                )
                                .order_by("id")
                                .first()
                            )
                            if project is None:
                                project = Project.objects.create(
                                    name="",
                                    client_name=row["cliente"],
                                    project_manager=pm_user,
                                    part_number=part_number,
                                    revisione=revisione,
                                    versione=versione,
                                    created_by=request.user,
                                )
                                project_was_created = True
                                created_projects += 1
                            cached_projects_by_identity[identity_key] = project
                    elif kickoff_reference:
                        reference_key = kickoff_reference.lower()
                        project = cached_projects_by_reference.get(reference_key)
                        if project is None:
                            project = Project.objects.create(
                                name="",
                                client_name=row["cliente"],
                                project_manager=pm_user,
                                created_by=request.user,
                            )
                            project_was_created = True
                            cached_projects_by_reference[reference_key] = project
                            created_projects += 1
                    else:
                        project = Project.objects.create(
                            name="",
                            client_name=row["cliente"],
                            project_manager=pm_user,
                            created_by=request.user,
                        )
                        project_was_created = True
                        created_projects += 1

                    updated_fields = []
                    for field_name, value in proj_defaults.items():
                        if getattr(project, field_name) != value:
                            setattr(project, field_name, value)
                            updated_fields.append(field_name)
                    if updated_fields:
                        project.save(update_fields=updated_fields + ["updated_at"])
                    if project.id not in updated_project_ids and updated_fields and not project_was_created:
                        updated_project_ids.add(project.id)
                        updated_projects += 1

                    # Risolvi assegnatario
                    assigned = None
                    if row["assegnato_username"]:
                        assigned = User.objects.filter(username__iexact=row["assegnato_username"]).first()

                    # Date
                    data_inizio = _coerce_date(row["data_inizio"])
                    data_fine = _coerce_date(row["data_fine"])
                    # Sanity: data_fine deve essere > data_inizio
                    if data_inizio and data_fine and data_fine <= data_inizio:
                        data_fine = None

                    Task.objects.create(
                        title=row["titolo"],
                        description=row["descrizione"],
                        status=row["stato"],
                        priority=row["priorita"],
                        project=project,
                        assigned_to=assigned,
                        next_step_due=data_inizio,
                        due_date=data_fine,
                        tags=row["tag"],
                        created_by=request.user,
                    )
                    created_tasks += 1

        except Exception as exc:
            messages.error(request, f"Errore durante l'import: {exc}")
            return redirect("tasks:import_excel")

        log_action(
            request,
            "import_excel",
            "tasks",
            {
                "message": (
                    f"Import Excel: {created_tasks} attivita kickoff create, "
                    f"{created_projects} kickoff nuovi, {updated_projects} kickoff aggiornati."
                ),
                "created_tasks": created_tasks,
                "created_projects": created_projects,
                "updated_projects": updated_projects,
            },
        )
        messages.success(
            request,
            (
                f"Import completato: {created_tasks} attivita kickoff create "
                f"({created_projects} kickoff nuovi, {updated_projects} aggiornati)."
            ),
        )
        return redirect("tasks:list")

    return redirect("tasks:import_excel")
