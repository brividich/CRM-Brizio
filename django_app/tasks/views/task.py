"""Viste delle attivita' (elenco, dettaglio, creazione, modifiche puntuali)."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from attrezzature.models import (
    Attrezzatura,
    AttrezzaturaNota,
    AttrezzaturaTask as GestioneAttrezzaturaTask,
    AttrezzaturaTaskTipo as GestioneAttrezzaturaTaskTipo,
)
from attrezzature.services import kickoff_integration as attrezzature_kickoff
from attrezzature.services import workflow as attrezzature_workflow

from ..forms import (
    SubTaskForm,
    SubTaskStatusForm,
    TaskAttachmentForm,
    TaskCommentForm,
    TaskDueDateForm,
    TaskFilterForm,
    TaskForm,
    TaskStartDateForm,
    TaskStatusForm,
    task_active_users_queryset,
)
from ..models import (
    Project,
    SubTask,
    Task,
    TaskAttachment,
    TaskCategory,
    TaskCategoryFieldType,
    TaskEventType,
    TaskImpostazioni,
    TaskStatus,
)
from ..access import (
    can_manage_project,
    can_manage_task,
    _can_update_task_due_date,
    _detail_queryset,
    has_task_permission,
    scoped_projects_queryset,
    scoped_tasks_queryset,
    task_permissions_required,
)
from ..services.asset_conflicts import (
    _asset_availability_report,
    _check_blocking_asset_conflicts,
    _check_machine_work_overlaps,
    _parse_iso_date,
)
from ..services.notify import (
    notify_user,
    _task_notify_users_queryset,
)
from ._extra_fields import (
    _build_asset_options_for_field,
    _persist_task_extra_data,
    _render_task_extra_data,
    _serialize_category_field,
)
from ._shared import (
    OPEN_STATUSES,
    _add_task_absence_warnings,
    _apply_default_ordering,
    _apply_subtask_rollup,
    _build_task_timeline_events,
    _log_event,
    _log_task_update_events,
    _sync_task_integrations,
    _task_snapshot,
    _tasks_shell_context,
    _vrf_status_detail,
)
from ._tooling import (
    _build_task_attrezzatura_context,
    _ensure_attrezzatura_task_link_for_kickoff_task,
    _handle_task_tooling_form_action,
    _task_attrezzatura_part_number,
)

logger = logging.getLogger(__name__)


@task_permissions_required("tasks_view")
def task_list(request):
    query_data = request.GET.copy()
    mine_raw = (query_data.get("mine") or "").strip().lower()
    mine_explicit_false = mine_raw in {"0", "false", "off", "no"}
    if mine_explicit_false:
        query_data.pop("mine", None)
    if not query_data and not mine_explicit_false:
        query_data["mine"] = "1"

    projects_qs = scoped_projects_queryset(request).order_by("name", "id")
    filter_form = TaskFilterForm(query_data or None, user=request.user, project_queryset=projects_qs)
    scoped_base_qs = scoped_tasks_queryset(request)
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

    tasks = _apply_default_ordering(tasks_qs)
    is_scope_admin = has_task_permission(request, "tasks_admin")
    can_create = has_task_permission(request, "tasks_create")
    can_edit = has_task_permission(request, "tasks_edit")
    can_comment = has_task_permission(request, "tasks_comment")

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

    # ── Readiness (prontezza avvio): singolo progetto, aggregato, badge riga backlog ──
    from tasks.readiness import (
        annotate_readiness_qs,
        compute_project_readiness,
        readiness_summary,
    )

    active_project_readiness = None
    if active_project:
        active_project_readiness = compute_project_readiness(active_project)

    readiness_summary_ctx = None
    if is_scope_admin:
        readiness_summary_ctx = readiness_summary(
            list(annotate_readiness_qs(scoped_projects_queryset(request)))
        )

    tasks = list(tasks)
    if not active_project:
        proj_ids = {t.project_id for t in tasks if getattr(t, "project_id", None)}
        rmap = {}
        if proj_ids:
            rmap = {
                p.id: compute_project_readiness(p)
                for p in annotate_readiness_qs(Project.objects.filter(id__in=proj_ids))
            }
        for t in tasks:
            t.project_readiness = rmap.get(getattr(t, "project_id", None))

    # Segnalazioni incontri (prossimi / da gestire): personali per default,
    # allargate a tutto lo scope per chi amministra il modulo.
    from tasks.meeting_alerts import build_meeting_alerts

    try:
        meeting_alerts = build_meeting_alerts(request, only_mine=not is_scope_admin)
    except Exception:
        # La banda e' accessoria: non deve far cadere la dashboard. Ma l'errore
        # va a log, altrimenti sparisce in silenzio come le sezioni di «da gestire».
        logger.exception("Segnalazioni incontri non calcolabili")
        meeting_alerts = None

    return render(
        request,
        "tasks/list.html",
        {
            **_tasks_shell_context(request, active="dashboard"),
            "page_title": "KICK-OFF",
            "meeting_alerts": meeting_alerts,
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
            "active_project_readiness": active_project_readiness,
            "readiness_summary": readiness_summary_ctx,
            "done_pct": done_pct,
        },
    )


@task_permissions_required("tasks_view")
def da_gestire(request):
    from tasks.da_gestire import build_kickoff_da_gestire

    is_admin = has_task_permission(request, "tasks_admin")
    scope = request.GET.get("scope") or ("portfolio" if is_admin else "mine")
    if scope not in ("portfolio", "mine"):
        scope = "portfolio" if is_admin else "mine"
    data = build_kickoff_da_gestire(request, scope)
    return render(
        request,
        "tasks/da_gestire.html",
        {
            **_tasks_shell_context(request, active="da_gestire"),
            "page_title": "Da gestire",
            "da_gestire_data": data,
            "scope": scope,
            "is_scope_admin": is_admin,
        },
    )


@task_permissions_required("tasks_view")
def task_detail(request, task_id: int):
    task = get_object_or_404(_detail_queryset(request), pk=task_id)
    can_manage = can_manage_task(request, task)
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
            "task_start_date_form": TaskStartDateForm(instance=task),
            "comment_form": comment_form,
            "subtask_form": SubTaskForm(user=request.user),
            "attachment_form": TaskAttachmentForm(task=task),
            "can_edit": can_manage,
            "can_manage_task": can_manage,
            "can_update_due_date": can_update_due_date,
            "can_comment": has_task_permission(request, "tasks_comment"),
            "task_status_choices": TaskStatus.choices,
            "subtask_status_choices": TaskStatus.choices,
            "task_extra_rows": _render_task_extra_data(task),
            "task_timeline_events": _build_task_timeline_events(task),
            "attrezzatura_embedded_context": _build_task_attrezzatura_context(task),
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def attrezzatura_action(request, task_id: int):
    task = get_object_or_404(_detail_queryset(request), pk=task_id)
    if not can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    part_number = _task_attrezzatura_part_number(task) or attrezzature_kickoff.normalize_part_number(
        request.POST.get("part_number", "")
    )
    if not part_number:
        messages.error(request, "P/N mancante: impossibile collegare Gestione Attrezzatura.")
        return redirect("tasks:detail", task_id=task.id)

    action = (request.POST.get("action") or "").strip()
    attrezzatura_id = request.POST.get("attrezzatura_id")
    attrezzatura = None
    if attrezzatura_id:
        attrezzatura = get_object_or_404(Attrezzatura, pk=attrezzatura_id)

    if action == "create_availability_task":
        linked, created = attrezzature_kickoff.get_or_create_attrezzatura_task_for_kickoff_activity(
            tipo=GestioneAttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
            part_number=part_number,
            attrezzatura=attrezzatura,
            titolo=f"Verificare disponibilita attrezzatura per {task.title}",
            descrizione=task.description,
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            user=request.user,
        )
        messages.success(request, "Task disponibilita creata." if created else f"Task disponibilita gia collegata: {linked.titolo}.")
    elif action == "create_new_tool_task":
        linked, created = attrezzature_kickoff.get_or_create_attrezzatura_task_for_kickoff_activity(
            tipo=GestioneAttrezzaturaTaskTipo.CREAZIONE_ATTREZZO,
            part_number=part_number,
            titolo=f"Creare nuovo attrezzo per P/N {part_number}",
            descrizione=task.description,
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            user=request.user,
        )
        messages.success(request, "Task creazione attrezzo creata." if created else f"Task creazione gia collegata: {linked.titolo}.")
    elif action == "create_draft_tool":
        tool = attrezzature_kickoff.create_draft_attrezzatura_from_kickoff(
            part_number=part_number,
            description=request.POST.get("description", "") or task.description,
            codice=request.POST.get("codice", ""),
            kickoff_ref=task.project_id,
            kickoff_activity_ref=task.id,
            user=request.user,
        )
        messages.success(request, f"Bozza attrezzatura creata per P/N {tool.part_number}.")
    elif action == "link_tool":
        if attrezzatura is None:
            messages.error(request, "Seleziona un'attrezzatura da collegare.")
        else:
            linked = _ensure_attrezzatura_task_link_for_kickoff_task(task, user=request.user)
            if linked is None:
                linked, _created = attrezzature_kickoff.get_or_create_attrezzatura_task_for_kickoff_activity(
                    tipo=GestioneAttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
                    part_number=part_number,
                    attrezzatura=attrezzatura,
                    titolo=f"Gestire attrezzatura per {task.title}",
                    kickoff_ref=task.project_id,
                    kickoff_activity_ref=task.id,
                    user=request.user,
                )
            attrezzature_kickoff.link_attrezzatura_to_kickoff_activity(
                attrezzatura,
                kickoff_ref=task.project_id,
                kickoff_activity_ref=task.id,
                task=linked,
            )
            messages.success(request, f"Attrezzatura {attrezzatura.codice or attrezzatura.pk} collegata.")
    elif action == "update_progress":
        if attrezzatura is None:
            messages.error(request, "Attrezzatura non trovata.")
        else:
            raw_percent = (request.POST.get("percentuale") or "").strip()
            try:
                percent = int(raw_percent) if raw_percent else None
            except ValueError:
                messages.error(request, "Percentuale avanzamento non valida.")
                return redirect("tasks:detail", task_id=task.id)
            stato = request.POST.get("stato") or None
            attrezzature_kickoff.update_attrezzatura_progress_from_kickoff(
                attrezzatura,
                percentuale=percent,
                stato=stato,
                user=request.user,
                note=request.POST.get("note", ""),
                kickoff_ref=task.project_id,
                kickoff_activity_ref=task.id,
            )
            messages.success(request, "Avanzamento attrezzatura aggiornato.")
    elif action == "mark_blocked":
        if attrezzatura is None:
            messages.error(request, "Attrezzatura non trovata.")
        else:
            reason = (request.POST.get("reason") or "").strip()
            if not reason:
                messages.error(request, "Indica il motivo del blocco.")
            else:
                attrezzature_workflow.mark_blocked(attrezzatura, user=request.user, reason=reason)
                attrezzature_kickoff.upsert_kickoff_link(
                    attrezzatura=attrezzatura,
                    kickoff_ref=task.project_id,
                    kickoff_activity_ref=task.id,
                    user=request.user,
                    notes=reason,
                )
                log_action(
                    request,
                    "tooling_blocked_from_kickoff",
                    "tasks",
                    {"task_id": task.id, "attrezzatura_id": attrezzatura.id, "reason": reason},
                )
                messages.success(request, "Attrezzatura bloccata.")
    elif action == "mark_to_create":
        if attrezzatura is None:
            messages.error(request, "Attrezzatura non trovata.")
        else:
            attrezzature_workflow.mark_to_create(attrezzatura, user=request.user, note=request.POST.get("note", ""))
            attrezzature_kickoff.upsert_kickoff_link(
                attrezzatura=attrezzatura,
                kickoff_ref=task.project_id,
                kickoff_activity_ref=task.id,
                user=request.user,
            )
            log_action(
                request,
                "tooling_to_create_from_kickoff",
                "tasks",
                {"task_id": task.id, "attrezzatura_id": attrezzatura.id},
            )
            messages.success(request, "Attrezzatura segnata da creare.")
    elif action == "set_availability":
        if attrezzatura is None:
            messages.error(request, "Attrezzatura non trovata.")
        else:
            attrezzature_workflow.set_availability_status(
                attrezzatura,
                request.POST.get("disponibilita_stato") or attrezzatura.disponibilita_stato,
                user=request.user,
                note=request.POST.get("note", ""),
            )
            attrezzature_kickoff.upsert_kickoff_link(
                attrezzatura=attrezzatura,
                kickoff_ref=task.project_id,
                kickoff_activity_ref=task.id,
                user=request.user,
            )
            messages.success(request, "Disponibilita attrezzatura aggiornata.")
    elif action == "add_note":
        if attrezzatura is None:
            messages.error(request, "Attrezzatura non trovata.")
        else:
            text = (request.POST.get("note") or "").strip()
            if text:
                AttrezzaturaNota.objects.create(
                    attrezzatura=attrezzatura,
                    testo=text,
                    origine="kickoff_activity",
                    created_by=request.user,
                )
                messages.success(request, "Nota attrezzatura aggiunta.")
            else:
                messages.error(request, "Scrivi una nota prima di salvarla.")
    elif action == "confirm_ready":
        if attrezzatura is None:
            messages.error(request, "Attrezzatura non trovata.")
        else:
            attrezzature_kickoff.confirm_attrezzatura_ready_from_kickoff(
                attrezzatura,
                user=request.user,
                note=request.POST.get("note", ""),
                kickoff_ref=task.project_id,
                kickoff_activity_ref=task.id,
            )
            messages.success(request, "Attrezzatura confermata pronta produzione.")
    elif action in {"complete_attrezzatura_task", "block_attrezzatura_task"}:
        gestione_task_id = request.POST.get("attrezzatura_task_id")
        task_qs = GestioneAttrezzaturaTask.objects.filter(
            Q(part_number__iexact=part_number)
            | Q(external_kickoff_activity_id=str(task.id))
            | Q(external_kickoff_id=str(task.project_id or ""))
        )
        gestione_task = get_object_or_404(task_qs, pk=gestione_task_id)
        if action == "complete_attrezzatura_task":
            attrezzature_kickoff.complete_attrezzatura_task_from_kickoff(
                gestione_task,
                user=request.user,
                note=request.POST.get("note", ""),
            )
            messages.success(request, "Task Gestione Attrezzatura completata.")
        else:
            attrezzature_kickoff.block_attrezzatura_task_from_kickoff(
                gestione_task,
                user=request.user,
                reason=request.POST.get("reason", ""),
            )
            messages.success(request, "Task Gestione Attrezzatura bloccata.")
    else:
        messages.error(request, "Azione Gestione Attrezzatura non riconosciuta.")
    return redirect("tasks:detail", task_id=task.id)


def _suggest_task_start_date(project) -> date:
    """Return the automatic start date for a new task in ``project``.

    Day after the last existing task's end date (due_date or next_step_due),
    or today if the project has no tasks yet.
    """
    today = timezone.localdate()
    if project is None:
        return today
    last_task = (
        Task.objects.filter(project=project)
        .order_by("-id")
        .first()
    )
    if last_task:
        last_end = last_task.due_date or last_task.next_step_due
        if last_end:
            return max(last_end + timedelta(days=1), today)
    return today


@task_permissions_required("tasks_view", api=True)
def project_info_json(request, project_id: int):
    """Restituisce info progetto + lista task (ordine creazione) in formato JSON, per l'AJAX del form."""
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
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
            "next_step_due": t["next_step_due"].strftime("%d-%m-%Y") if t["next_step_due"] else "",
            "due_date": t["due_date"].strftime("%d-%m-%Y") if t["due_date"] else "",
            "assignee": assignee,
        })
    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)
    return JsonResponse({
        "id": project.id,
        "name": project.name,
        "client_name": project.client_name or "",
        "part_number": project.part_number or "",
        "revisione": project.revisione or "",
        "versione": project.versione or "",
        "project_manager": project.team_display("project_managers"),
        "capo_commessa": project.team_display("capi_commessa"),
        "programmer": project.team_display("programmers"),
        "caporeparto": project.team_display("caporeparti"),
        "task_total": len(tasks_data),
        "vrf_status": vrf_detail["status"],
        "vrf_label": vrf_detail["label"],
        "vrf_upload_url": reverse("tasks:project_vrf_upload", kwargs={"project_id": project.id}),
        "vrf_compile_url": reverse("tasks:project_vrf_compile", kwargs={"project_id": project.id}),
        "tasks": tasks_data,
        "suggested_start_date": _suggest_task_start_date(project).isoformat(),
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
        projects_qs.prefetch_related(*Project.TEAM_ROLE_FIELDS),
        pk=project_id,
    )


@task_permissions_required("tasks_view", "tasks_create")
def task_create(request):
    projects_qs = scoped_projects_queryset(request).order_by("name", "id")
    locked_project = _task_create_locked_project(request, projects_qs)
    suggested_start_date = _suggest_task_start_date(locked_project)
    has_previous_task = (
        locked_project is not None
        and Task.objects.filter(project=locked_project).exists()
    )

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
            if task.project and not getattr(form, "new_project_created", False) and not can_manage_project(request, task.project):
                messages.error(
                    request,
                    "Non hai i permessi per aggiungere nuove attivita a questo kickoff.",
                )
                return redirect("tasks:project_gantt", project_id=task.project.id)

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

            block_msgs = _check_blocking_asset_conflicts(task, request.POST, exclude_task_id=None)
            if block_msgs:
                for m in block_msgs:
                    messages.error(request, m)
                form.add_error(
                    None,
                    "Impossibile salvare: conflitto bloccante sugli asset selezionati.",
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
                        "suggested_start_from_previous": has_previous_task,
                        "suggested_project_id": locked_project.id if locked_project is not None else None,
                        "locked_project": locked_project,
                        "locked_project_vrf_detail": _vrf_status_detail(locked_project, TaskImpostazioni.get_singleton()) if locked_project is not None else None,
                        "locked_project_task_total": Task.objects.filter(project=locked_project).count() if locked_project is not None else 0,
                        "task_extra_data_json": json.dumps(request.POST.dict()),
                    },
                )

            task.save()
            form.save_m2m()
            _persist_task_extra_data(task, request.POST)
            for mw_warn in _check_machine_work_overlaps(task, exclude_task_id=None):
                messages.warning(request, mw_warn)
            _ensure_attrezzatura_task_link_for_kickoff_task(task, user=request.user)
            _handle_task_tooling_form_action(request, task, form)
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
                messages.success(request, "Attivita creata correttamente.")
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

            # Applica preferenze reminder portale + integrazione Outlook
            task.reminder_portal_enabled = bool(form.cleaned_data.get("reminder_portal_enabled_field"))
            task.save(update_fields=["reminder_portal_enabled"])
            _sync_task_integrations(request, task, form, action="create")

            # Se è stato creato un nuovo progetto, redirect alla pagina upload VRF
            if getattr(form, "new_project_created", False) and task.project_id:
                next_url = reverse("tasks:detail", kwargs={"task_id": task.id})
                return redirect(
                    reverse("tasks:project_vrf_upload", kwargs={"project_id": task.project.id})
                    + f"?next={next_url}"
                )
            return redirect("tasks:detail", task_id=task.id)
    else:
        initial = {"next_step_due": suggested_start_date.isoformat()}
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
                "suggested_start_from_previous": has_previous_task,
                "suggested_project_id": locked_project.id if locked_project is not None else None,
                "locked_project": locked_project,
                "locked_project_vrf_detail": _vrf_status_detail(locked_project, TaskImpostazioni.get_singleton()) if locked_project is not None else None,
                "locked_project_task_total": Task.objects.filter(project=locked_project).count() if locked_project is not None else 0,
                "task_extra_data_json": json.dumps({}),
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
            "suggested_start_from_previous": has_previous_task,
            "suggested_project_id": locked_project.id if locked_project is not None else None,
            "locked_project": locked_project,
            "locked_project_vrf_detail": _vrf_status_detail(locked_project, TaskImpostazioni.get_singleton()) if locked_project is not None else None,
            "locked_project_task_total": Task.objects.filter(project=locked_project).count() if locked_project is not None else 0,
            "task_extra_data_json": json.dumps({}),
        },
    )


@task_permissions_required("tasks_view")
def task_edit(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request).prefetch_related("subscribers"), pk=task_id)
    if not can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
    projects_qs = scoped_projects_queryset(request).order_by("name", "id")
    before = _task_snapshot(task)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task, user=request.user, project_queryset=projects_qs)
        if form.is_valid():
            updated_task = form.save(commit=False)
            updated_task.project = form.resolve_project(created_by=request.user)
            if updated_task.project and updated_task.project_id != task.project_id and not can_manage_project(request, updated_task.project):
                messages.error(
                    request,
                    "Non hai i permessi per spostare l'attivita su questo kickoff.",
                )
                return redirect("tasks:edit", task_id=task.id)

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

            block_msgs = _check_blocking_asset_conflicts(updated_task, request.POST, exclude_task_id=task.id)
            if block_msgs:
                for m in block_msgs:
                    messages.error(request, m)
                form.add_error(
                    None,
                    "Impossibile salvare: conflitto bloccante sugli asset selezionati.",
                )
                return render(
                    request,
                    "tasks/form.html",
                    {
                        **_tasks_shell_context(request, active="edit", task=task),
                        "page_title": "Modifica attivita kickoff",
                        "form": form,
                        "task": task,
                        "mode": "edit",
                        "task_extra_data_json": json.dumps(request.POST.dict()),
                    },
                )

            updated_task.save()
            form.save_m2m()
            _persist_task_extra_data(updated_task, request.POST)
            for mw_warn in _check_machine_work_overlaps(updated_task, exclude_task_id=updated_task.pk):
                messages.warning(request, mw_warn)
            _ensure_attrezzatura_task_link_for_kickoff_task(updated_task, user=request.user)
            _handle_task_tooling_form_action(request, updated_task, form)
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
            updated_task.reminder_portal_enabled = bool(form.cleaned_data.get("reminder_portal_enabled_field"))
            updated_task.save(update_fields=["reminder_portal_enabled"])
            _sync_task_integrations(request, updated_task, form, action="edit")
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
            "task_extra_data_json": json.dumps(task.extra_data or {}),
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def update_due_date(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
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
        # Integrazione Carichi Macchina (non bloccante): riallinea la data della
        # pianificazione collegata alla nuova scadenza.
        try:
            from gestione_carichi_macchina.integrations import sync_kickoff_task_to_pianificazione
            sync_kickoff_task_to_pianificazione(task, user=request.user)
        except Exception as exc:
            logger.warning("Sync Carichi (update_due_date) fallita task=%s: %s", task.id, exc)
    else:
        messages.error(request, "Data prevista conclusione non valida.")

    return redirect("tasks:detail", task_id=task.id)


@require_POST
@task_permissions_required("tasks_view")
def update_start_date(request, task_id: int):
    """Corregge la data inizio di un'attivita' gia' creata.

    Stesso permesso della data fine: chi puo' spostare la conclusione puo'
    spostare la partenza. Senza questa scorciatoia l'unico modo era
    riattraversare il form completo, che ricalcola e rivalida tutto il resto.
    """
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
    if not _can_update_task_due_date(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )

    before = _task_snapshot(task)
    form = TaskStartDateForm(request.POST, instance=task)
    if form.is_valid():
        task = form.save()
        _log_task_update_events(task, request.user, before)
        messages.success(request, "Data inizio aggiornata.")
    else:
        for error in form.errors.get("next_step_due", ["Data inizio non valida."]):
            messages.error(request, error)

    return redirect("tasks:detail", task_id=task.id)


@require_POST
@task_permissions_required("tasks_view")
def change_status(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
    if not can_manage_task(request, task):
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
            # Integrazione Carichi Macchina (non bloccante): chiusura/annullamento
            # rimuove la pianificazione collegata, ripresa la ricrea.
            try:
                from gestione_carichi_macchina.integrations import sync_kickoff_task_to_pianificazione
                sync_kickoff_task_to_pianificazione(task, user=request.user)
            except Exception as exc:
                logger.warning("Sync Carichi (change_status) fallita task=%s: %s", task.id, exc)
    else:
        messages.error(request, "Stato non valido.")
    return redirect("tasks:detail", task_id=task_id)


@require_POST
@task_permissions_required("tasks_view", "tasks_comment")
def add_comment(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
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
            notify_user(
                comment.target_user,
                f"Nuovo commento su task '{task.title}'.",
                reverse("tasks:detail", kwargs={"task_id": task.id}),
            )
        messages.success(request, "Commento aggiunto.")
    else:
        messages.error(request, "Commento non valido.")
    return redirect("tasks:detail", task_id=task_id)


@require_POST
@task_permissions_required("tasks_view")
def add_subtask(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
    if not can_manage_task(request, task):
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
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
    if not can_manage_task(request, task):
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
def subtask_toggle(request, task_id: int, subtask_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
    if not can_manage_task(request, task):
        return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)
    subtask = get_object_or_404(SubTask.objects.filter(task=task), pk=subtask_id)
    old_status = subtask.status
    subtask.status = TaskStatus.TODO if subtask.status == TaskStatus.DONE else TaskStatus.DONE
    subtask.save(update_fields=["status"])
    if old_status != subtask.status:
        _log_event(
            task,
            request.user,
            TaskEventType.SUBTASK_STATUS_CHANGE,
            {"subtask_id": subtask.id, "from": old_status, "to": subtask.status},
        )
        _apply_subtask_rollup(task, request.user)
    task.refresh_from_db(fields=["status"])
    return JsonResponse(
        {
            "ok": True,
            "subtask_id": subtask.id,
            "status": subtask.status,
            "status_display": subtask.get_status_display(),
            "task_status": task.status,
            "task_status_display": task.get_status_display(),
        }
    )


@task_permissions_required("tasks_view")
def task_attachment_download(request, attachment_id: int):
    """Serve un allegato KICK-OFF/Task dallo storage privato (mai da /media pubblico).

    SEC: gli allegati contengono dati commerciali (P/N, riferimenti cliente). Un
    TaskAttachment può appartenere a un task e/o a un progetto: l'accesso è concesso
    solo se il task o il progetto rientra nello scope OWN/TEAM dell'utente. Il
    controllo precede l'accesso al file; out-of-scope → 404 (non rivela l'esistenza).
    Streaming come allegato, nome file sanificato, nosniff.
    """
    import mimetypes
    from pathlib import Path as _Path

    from django.http import FileResponse, Http404

    attachment = get_object_or_404(TaskAttachment, pk=attachment_id)
    in_scope = (
        (attachment.task_id and scoped_tasks_queryset(request).filter(pk=attachment.task_id).exists())
        or (attachment.project_id and scoped_projects_queryset(request).filter(pk=attachment.project_id).exists())
    )
    if not in_scope:
        raise Http404("Allegato non disponibile.")
    if not attachment.file or not attachment.file.name:
        raise Http404("Allegato non disponibile.")
    try:
        fh = attachment.file.open("rb")
    except Exception:
        raise Http404("File non trovato.")
    filename = attachment.original_name or _Path(attachment.file.name).name
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "").strip() or "allegato"
    content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    resp = FileResponse(fh, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@require_POST
@task_permissions_required("tasks_view")
def add_attachment(request, task_id: int):
    task = get_object_or_404(scoped_tasks_queryset(request), pk=task_id)
    if not can_manage_task(request, task):
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
            if not task.project_id or not can_manage_project(request, task.project):
                return render(
                    request,
                    "core/pages/forbidden.html",
                    {"page_title": "Accesso negato"},
                    status=403,
                )
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


@task_permissions_required("tasks_view", api=True)
def category_fields_json(request, category_id: int):
    """Espone la definizione dei campi di una categoria al form nuova attivita.

    Per i campi di tipo 'user' / 'asset' restituisce anche un piccolo dataset
    di opzioni (utenti attivi, asset base) cosi' il frontend puo' popolare
    la select senza una seconda chiamata.
    """
    try:
        category = TaskCategory.objects.prefetch_related("fields").get(pk=category_id, is_active=True)
    except TaskCategory.DoesNotExist:
        return JsonResponse({"ok": False, "reason": "not_found"}, status=404)

    raw_fields = list(category.fields.all().order_by("order_index", "id"))
    fields = [_serialize_category_field(f) for f in raw_fields]

    users_payload: list[dict] = []
    needs_users = any(f["field_type"] == TaskCategoryFieldType.USER for f in fields)

    # Popola le opzioni asset per-campo (ogni campo puo' avere filtri diversi).
    for raw, ser in zip(raw_fields, fields):
        if ser["field_type"] == TaskCategoryFieldType.ASSET:
            ser["choices"] = _build_asset_options_for_field(raw)

    if needs_users:
        users_payload = [
            {"value": u.id, "label": (u.get_full_name() or u.username)}
            for u in task_active_users_queryset()[:500]
        ]

    return JsonResponse({
        "ok": True,
        "category": {"id": category.id, "name": category.name, "slug": category.slug},
        "fields": fields,
        "users": users_payload,
        # retrocompat: il frontend accede a payload.assets; le choices asset
        # vivono ora per-campo in field.choices.
        "assets": [],
    })


@task_permissions_required("tasks_view", api=True)
def asset_availability_json(request, asset_id: int):
    """Ritorna il report di disponibilita per un asset nella finestra richiesta.

    Query string:
      start=YYYY-MM-DD (opzionale)
      end=YYYY-MM-DD (opzionale)
      exclude_task=<id> (opzionale, per l'edit di un task esistente)
    """
    try:
        from assets.models import Asset
        asset = Asset.objects.get(pk=asset_id)
    except Exception:
        return JsonResponse({"ok": False, "reason": "not_found"}, status=404)

    start = _parse_iso_date(request.GET.get("start") or "")
    end = _parse_iso_date(request.GET.get("end") or "")
    if start and end and end < start:
        start, end = end, start
    exclude_task_raw = request.GET.get("exclude_task") or ""
    exclude_task_id: int | None = None
    if exclude_task_raw:
        try:
            exclude_task_id = int(exclude_task_raw)
        except (TypeError, ValueError):
            exclude_task_id = None

    cfg = TaskImpostazioni.get_singleton()
    # SEC: passa gli id dei task visibili (scope OWN/TEAM); i conflitti su task fuori
    # scope mostreranno l'occupazione senza titolo/link.
    scope_task_ids = set(scoped_tasks_queryset(request).values_list("id", flat=True))
    report = _asset_availability_report(asset, start, end, exclude_task_id, scope_task_ids=scope_task_ids)
    report["ok"] = True
    report["check_enabled"] = bool(cfg.asset_conflict_check_enabled)
    report["block_on_conflict"] = bool(cfg.asset_conflict_block)
    return JsonResponse(report)
