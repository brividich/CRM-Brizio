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
from .models import Project, ProjectComment, SubTask, Task, TaskAttachment, TaskComment, TaskEvent, TaskEventType, TaskStatus

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

    stats_qs = scoped_base_qs.order_by()
    status_counter = {
        row["status"]: row["total"]
        for row in stats_qs.values("status").annotate(total=Count("id")).order_by()
    }
    dashboard_stats = {
        "total": stats_qs.count(),
        "todo": int(status_counter.get(TaskStatus.TODO, 0)),
        "in_progress": int(status_counter.get(TaskStatus.IN_PROGRESS, 0)),
        "done": int(status_counter.get(TaskStatus.DONE, 0)),
        "canceled": int(status_counter.get(TaskStatus.CANCELED, 0)),
        "overdue": stats_qs.filter(
            due_date__lt=timezone.localdate(),
            status__in=OPEN_STATUSES,
        ).count(),
    }

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
            "page_title": "Task",
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
            "can_gestione_admin": user_can_modulo_action(request, "tasks", "admin_tasks"),
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
    return JsonResponse({
        "id": project.id,
        "name": project.name,
        "client_name": project.client_name or "",
        "part_number": project.part_number or "",
        "project_manager": (pm.get_full_name() or pm.username) if pm else "",
        "capo_commessa": (cc.get_full_name() or cc.username) if cc else "",
        "programmer": (prog.get_full_name() or prog.username) if prog else "",
        "tasks": tasks_data,
    })


@task_permissions_required("tasks_view", "tasks_create")
def task_create(request):
    projects_qs = _scoped_projects_queryset(request).order_by("name", "id")
    if request.method == "POST":
        form = TaskForm(request.POST, user=request.user, project_queryset=projects_qs)
        if form.is_valid():
            task = form.save(commit=False)
            task.created_by = request.user
            task.project = form.resolve_project(created_by=request.user)
            task.save()
            form.save_m2m()
            if task.project_id:
                messages.success(request, f"Task creata nel progetto '{task.project.name}'.")
            else:
                messages.success(request, "Task singola creata correttamente.")
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
                messages.warning(request, "Task creata con scadenza gia oltre la data odierna.")
            _add_task_absence_warnings(request, task)
            return redirect("tasks:detail", task_id=task.id)
    else:
        # Se arrivo dal Gantt con ?project=X, pre-calcolo la data suggerita
        # come giorno successivo alla fine dell'ultima task del progetto.
        suggested_start_date = None
        suggested_project_id = None
        try:
            project_id_param = int(request.GET.get("project", ""))
            last_task = (
                Task.objects.filter(project_id=project_id_param)
                .order_by("-id")
                .first()
            )
            if last_task:
                last_end = last_task.due_date or last_task.next_step_due
                if last_end:
                    suggested_start_date = last_end + timedelta(days=1)
                    suggested_project_id = project_id_param
        except (ValueError, TypeError):
            pass

        initial = {}
        if suggested_start_date:
            initial["next_step_due"] = suggested_start_date
        if suggested_project_id:
            initial["project_choice"] = suggested_project_id
            initial["task_scope"] = "project"

        form = TaskForm(user=request.user, project_queryset=projects_qs, initial=initial)

        return render(
            request,
            "tasks/form.html",
            {
                "page_title": "Nuova task",
                "form": form,
                "mode": "create",
                "suggested_start_date": suggested_start_date,
                "suggested_project_id": suggested_project_id,
            },
        )

    return render(
        request,
        "tasks/form.html",
        {
            "page_title": "Nuova task",
            "form": form,
            "mode": "create",
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
            updated_task.save()
            form.save_m2m()
            _log_task_update_events(updated_task, request.user, before)
            messages.success(request, "Task aggiornata.")
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
            "page_title": "Modifica task",
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
    projects = projects_base_qs.annotate(
        task_total=Count("tasks", distinct=True),
        task_open=Count("tasks", filter=Q(tasks__status__in=OPEN_STATUSES), distinct=True),
        task_done=Count("tasks", filter=Q(tasks__status=TaskStatus.DONE), distinct=True),
    ).order_by("name", "id")
    return render(
        request,
        "tasks/projects.html",
        {
            "page_title": "Progetti Task",
            "projects": projects,
            "is_scope_admin": _has_task_permission(request, "tasks_admin"),
        },
    )


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

    task_update_forms = {}
    if can_edit_schedule:
        for task in tasks:
            task_update_forms[task.id] = ProjectTaskGanttUpdateForm(instance=task, prefix=f"task_{task.id}")
        for row in gantt_meta["rows"]:
            row["update_form"] = task_update_forms.get(row["task"].id)

    return render(
        request,
        "tasks/project_gantt.html",
        {
            "page_title": f"Gantt progetto - {project.name}",
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
        messages.error(request, "Aggiornamento Gantt non valido.")

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
                message_text=f"Nuovo commento nel progetto '{project.name}'.",
                action_url=reverse("tasks:project_gantt", kwargs={"project_id": project.id}),
            )
        messages.success(request, "Commento progetto aggiunto.")
    else:
        messages.error(request, "Commento progetto non valido.")
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
            "page_title": "Gestione Tasks",
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
