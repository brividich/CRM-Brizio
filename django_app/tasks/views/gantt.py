"""Viste del Gantt di commessa e della baseline."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.contrib import messages
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from ..forms import (
    ProjectCommentForm,
    ProjectTaskGanttUpdateForm,
)
from ..models import (
    DependencyType,
    GanttBaseline,
    Project,
    ProjectComment,
    Task,
    TaskDependency,
    TaskImpostazioni,
    TaskPriority,
    TaskStatus,
)
from ..access import (
    _can_edit_project_schedule,
    can_manage_project,
    can_manage_task,
    has_task_permission,
    scoped_projects_queryset,
    task_permissions_required,
)
from ..services.absences import (
    _task_date_absence_conflicts,
)
from ..services.gantt import (
    _parse_gantt_options,
    _project_gantt_rows,
)
from ..services.notify import (
    _project_notify_users_queryset,
)
from ._shared import (
    OPEN_STATUSES,
    _add_task_absence_warnings,
    _log_task_update_events,
    _task_snapshot,
    _tasks_shell_context,
    _vrf_status_detail,
)

logger = logging.getLogger(__name__)


@task_permissions_required("tasks_view")
def project_gantt(request, project_id: int):
    project_qs = scoped_projects_queryset(request).prefetch_related(
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
                "project__similar_project",
            ).prefetch_related("subscribers", Project.team_prefetch("project__")).order_by("id"),
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
    can_comment = has_task_permission(request, "tasks_comment")
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
    for row in gantt_meta["rows"]:
        row["can_edit"] = can_manage_task(request, row["task"])
        if row["can_edit"]:
            task_update_forms[row["task"].id] = ProjectTaskGanttUpdateForm(
                instance=row["task"],
                prefix=f"task_{row['task'].id}",
            )
        row["update_form"] = task_update_forms.get(row["task"].id)

    can_edit_schedule = any(bool(row.get("can_edit")) for row in gantt_meta["rows"]) or can_manage_project(request, project)

    cfg = TaskImpostazioni.get_singleton()
    vrf_detail = _vrf_status_detail(project, cfg)

    # ── Baseline Gantt ──
    baseline = GanttBaseline.objects.filter(project=project).first()
    for row in gantt_meta["rows"]:
        row["baseline_delta"] = baseline.get_task_delta_days(row["task"]) if baseline else {"start": None, "end": None}

    # ── Dipendenze task ──
    task_ids = [t.id for t in tasks]
    deps = list(
        TaskDependency.objects.filter(
            predecessor_id__in=task_ids,
            successor_id__in=task_ids,
        ).select_related("predecessor", "successor")
    )
    task_id_to_wbs = {row["task"].id: row["wbs"] for row in gantt_meta["rows"]}
    deps_display = [
        {
            "pred_id": d.predecessor_id,
            "succ_id": d.successor_id,
            "pred_wbs": task_id_to_wbs.get(d.predecessor_id, "?"),
            "succ_wbs": task_id_to_wbs.get(d.successor_id, "?"),
            "type": d.dependency_type,
            "lag_days": d.lag_days,
            "dep_id": d.pk,
        }
        for d in deps
    ]

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
            "gantt_week_spans": gantt_meta["week_spans"],
            "gantt_today_index": gantt_meta["today_index"],
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
            "gantt_baseline": baseline,
            "gantt_deps": deps_display,
            "dependency_type_choices": DependencyType.choices,
            "can_add_project_task": has_task_permission(request, "tasks_create") and can_manage_project(request, project),
        },
    )


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_fix_baseline(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)
    tasks = list(project.tasks.all())
    snapshot = {}
    for task in tasks:
        snapshot[str(task.pk)] = {
            "start": task.next_step_due.isoformat() if task.next_step_due else None,
            "end":   task.due_date.isoformat()      if task.due_date      else None,
        }
    GanttBaseline.objects.update_or_create(
        project=project,
        defaults={"snapshot": snapshot, "fixed_by": request.user},
    )
    log_action(request, "gantt_baseline_fixed", "tasks", {"project_id": project.pk, "task_count": len(tasks)})
    messages.success(request, "Baseline Gantt fissata.")
    return_qs = request.POST.get("return_qs", "")
    base_url = reverse("tasks:project_gantt", kwargs={"project_id": project_id})
    return redirect(f"{base_url}?{return_qs}" if return_qs else base_url)


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_clear_baseline(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)
    GanttBaseline.objects.filter(project=project).delete()
    log_action(request, "gantt_baseline_cleared", "tasks", {"project_id": project.pk})
    messages.success(request, "Baseline Gantt rimossa.")
    return_qs = request.POST.get("return_qs", "")
    base_url = reverse("tasks:project_gantt", kwargs={"project_id": project_id})
    return redirect(f"{base_url}?{return_qs}" if return_qs else base_url)


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_add_dependency(request, project_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "error": "Accesso negato."}, status=403)
    pred_id  = request.POST.get("predecessor_id")
    succ_id  = request.POST.get("successor_id")
    dep_type = request.POST.get("dependency_type", DependencyType.FS)
    lag      = request.POST.get("lag_days", 0)
    if not pred_id or not succ_id:
        return JsonResponse({"ok": False, "error": "predecessor_id e successor_id obbligatori."}, status=400)
    if str(pred_id) == str(succ_id):
        return JsonResponse({"ok": False, "error": "Un task non può dipendere da se stesso."}, status=400)
    if dep_type not in dict(DependencyType.choices):
        dep_type = DependencyType.FS
    task_qs = Task.objects.filter(project=project)
    pred = get_object_or_404(task_qs, pk=pred_id)
    succ = get_object_or_404(task_qs, pk=succ_id)
    try:
        lag_int = int(lag)
    except (TypeError, ValueError):
        lag_int = 0
    dep, created = TaskDependency.objects.get_or_create(
        predecessor=pred,
        successor=succ,
        defaults={"dependency_type": dep_type, "lag_days": lag_int},
    )
    if not created:
        dep.dependency_type = dep_type
        dep.lag_days = lag_int
        dep.save(update_fields=["dependency_type", "lag_days"])
    log_action(request, "gantt_dependency_added", "tasks", {
        "project_id": project.pk,
        "predecessor_id": pred.pk,
        "successor_id": succ.pk,
        "type": dep_type,
        "lag_days": lag_int,
    })
    return JsonResponse({"ok": True, "dep_id": dep.pk, "created": created})


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_remove_dependency(request, project_id: int, dep_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    if not can_manage_project(request, project):
        return JsonResponse({"ok": False, "error": "Accesso negato."}, status=403)
    task_ids = list(project.tasks.values_list("id", flat=True))
    dep = get_object_or_404(
        TaskDependency,
        pk=dep_id,
        predecessor_id__in=task_ids,
        successor_id__in=task_ids,
    )
    dep.delete()
    log_action(request, "gantt_dependency_removed", "tasks", {"project_id": project.pk, "dep_id": dep_id})
    return JsonResponse({"ok": True})


@require_POST
@task_permissions_required("tasks_view")
def project_gantt_update_task(request, project_id: int, task_id: int):
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    task = get_object_or_404(Task.objects.filter(project=project), pk=task_id)
    if not can_manage_task(request, task):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato"},
            status=403,
        )
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
    project = get_object_or_404(scoped_projects_queryset(request), pk=project_id)
    task = get_object_or_404(Task.objects.filter(project=project), pk=task_id)
    if not can_manage_task(request, task):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    mode = str(request.POST.get("mode") or "shift").strip()
    if mode not in {"shift", "resize_start", "resize_end"}:
        return JsonResponse({"ok": False, "error": "invalid_mode"}, status=400)

    try:
        shift_days = int(str(request.POST.get("shift_days", "0")).strip())
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "invalid_shift"}, status=400)

    if shift_days == 0:
        return JsonResponse(
            {
                "ok": True,
                "task_id": task.id,
                "mode": mode,
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
    if mode in {"shift", "resize_start"} and predecessor:
        pred_end = predecessor.due_date or predecessor.next_step_due
        if pred_end:
            orig_start = task.next_step_due or task.due_date
            if orig_start:
                min_shift = (pred_end + timedelta(days=1) - orig_start).days
                shift_days = max(shift_days, min_shift)

    start_date = task.next_step_due or task.due_date
    end_date = task.due_date or task.next_step_due
    if mode == "resize_start" and start_date and end_date:
        shift_days = min(shift_days, (end_date - start_date).days)
    elif mode == "resize_end" and start_date and end_date:
        shift_days = max(shift_days, (start_date - end_date).days)

    before = _task_snapshot(task)

    if mode == "resize_start":
        if task.next_step_due:
            task.next_step_due = task.next_step_due + timedelta(days=shift_days)
        elif task.due_date:
            task.next_step_due = task.due_date + timedelta(days=shift_days)
    elif mode == "resize_end":
        if task.due_date:
            task.due_date = task.due_date + timedelta(days=shift_days)
        elif task.next_step_due:
            task.due_date = task.next_step_due + timedelta(days=shift_days)
    else:
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
    if cascade and mode in {"shift", "resize_end"}:
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
                f"{field_name}:{target_date.strftime('%d-%m-%Y')}:{label_text}"
            )

    return JsonResponse(
        {
            "ok": True,
            "task_id": task.id,
            "mode": mode,
            "shift_days": shift_days,
            "cascade_count": cascade_count,
            "next_step_due": task.next_step_due.isoformat() if task.next_step_due else None,
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "next_step_due_display": task.next_step_due.strftime("%d-%m-%Y") if task.next_step_due else "",
            "due_date_display": task.due_date.strftime("%d-%m-%Y") if task.due_date else "",
            "absence_conflicts": conflict_messages,
        }
    )
