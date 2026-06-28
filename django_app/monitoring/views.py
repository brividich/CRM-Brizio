from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_required
from core.audit import log_action

from .health import http_status_for, is_ip_allowed, run_readyz_checks
from .models import AutomationExecution, AutomationJob, Issue, UserProblemReport
from .services import OPEN_ISSUE_STATUSES, detect_missed_jobs, detect_stuck_jobs, register_user_problem_report


def healthz(request):
    """Liveness probe: 200 se Django sta processando richieste. Nessun check esterno."""
    if not is_ip_allowed(request):
        return JsonResponse({"status": "forbidden"}, status=403)
    return JsonResponse({"status": "ok"})


def readyz(request):
    """Readiness probe: aggregato dei check su DB/cache/Graph/LDAP/SMTP/queue."""
    if not is_ip_allowed(request):
        return JsonResponse({"status": "forbidden"}, status=403)
    report = run_readyz_checks()
    return JsonResponse(report.to_payload(), status=http_status_for(report))


@login_required
@require_POST
def report_problem(request):
    if not bool(getattr(settings, "MONITORING_ENABLED", True)):
        return JsonResponse({"ok": False, "error": "disabled"}, status=503)

    message = (request.POST.get("message") or "").strip()
    if not message:
        return JsonResponse({"ok": False, "error": "missing_message"}, status=400)

    current_url = (request.POST.get("current_url") or request.META.get("HTTP_REFERER") or request.path or "").strip()
    route_name = (request.POST.get("route_name") or "").strip()
    module_name = (request.POST.get("module_name") or "").strip()
    browser_info = (request.POST.get("browser_info") or request.META.get("HTTP_USER_AGENT") or "").strip()

    report = register_user_problem_report(
        user=request.user,
        current_url=current_url,
        route_name=route_name,
        module_name=module_name,
        message=message,
        browser_info=browser_info,
        extra_json={
            "client_timestamp": (request.POST.get("client_timestamp") or "").strip(),
            "submitted_from": "problem_report_modal",
        },
    )

    try:
        log_action(
            request,
            "monitoring_problem_report",
            "monitoring",
            {
                "report_id": report.pk,
                "issue_id": report.issue_id,
                "route_name": route_name,
                "module_name": module_name,
            },
        )
    except Exception:
        pass

    return JsonResponse(
        {
            "ok": True,
            "message": "Segnalazione inviata",
            "issue_code": report.issue.code if report.issue_id else "",
        }
    )


def _build_django_q_stats() -> dict:
    try:
        from django_q.models import Failure, Schedule, Success

        now = timezone.now()
        last_24h = now - timedelta(hours=24)
        return {
            "available": True,
            "success_24h": Success.objects.filter(started__gte=last_24h).count(),
            "failure_24h": Failure.objects.filter(started__gte=last_24h).count(),
            "schedules_count": Schedule.objects.filter(repeats__lt=0).count()
            + Schedule.objects.filter(repeats__gt=0).count(),
            "recent_failures": list(
                Failure.objects.filter(started__gte=last_24h)
                .order_by("-started")
                .values("name", "func", "started", "result")[:5]
            ),
        }
    except Exception:
        return {"available": False}


@legacy_admin_required
def admin_dashboard(request):
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    open_filter = Q(status__in=OPEN_ISSUE_STATUSES)
    missing_jobs = detect_missed_jobs(now=now, create_issues=False)

    context = {
        "open_issues_count": Issue.objects.filter(open_filter).count(),
        "critical_issues_count": Issue.objects.filter(open_filter, severity=Issue.Severity.CRITICAL).count(),
        "new_issues_24h_count": Issue.objects.filter(created_at__gte=last_24h).count(),
        "unassigned_open_issues_count": Issue.objects.filter(open_filter, assigned_to__isnull=True).count(),
        "job_failed_today_count": AutomationExecution.objects.filter(
            status=AutomationExecution.Status.FAILED,
            started_at__gte=today_start,
        ).count(),
        "job_missing_count": len(missing_jobs),
        "top_modules": list(
            Issue.objects.filter(open_filter)
            .exclude(module_name="")
            .values("module_name")
            .annotate(total=Count("id"), occurrences=Sum("occurrences_count"))
            .order_by("-occurrences", "-total", "module_name")[:6]
        ),
        "top_urls": list(
            Issue.objects.filter(open_filter)
            .exclude(current_url="")
            .values("current_url")
            .annotate(total=Count("id"), occurrences=Sum("occurrences_count"))
            .order_by("-occurrences", "-total", "current_url")[:6]
        ),
        "source_breakdown": list(
            Issue.objects.filter(last_seen_at__gte=last_24h)
            .values("source")
            .annotate(total=Count("id"))
            .order_by("-total", "source")
        ),
        "latest_manual_reports": UserProblemReport.objects.select_related("issue", "user").order_by("-created_at")[:8],
        "recent_open_issues": Issue.objects.select_related("assigned_to").filter(open_filter).order_by("-last_seen_at")[:10],
        "missing_jobs": missing_jobs[:8],
        "django_q_stats": _build_django_q_stats(),
    }
    return render(request, "monitoring/pages/dashboard.html", context)


@legacy_admin_required
def system_status(request):
    """Centrale di comando: stato a colpo d'occhio di Servizi (readyz), Assistente AI,
    Automazioni e Issue per severità. Lo stato AI è letto dalle Issue (lo scheduled
    task le apre/risolve sondando Ollama/TEI/RAG), quindi la pagina NON fa probe di
    rete verso la GPU."""
    from monitoring.health import run_readyz_checks

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    open_filter = Q(status__in=OPEN_ISSUE_STATUSES)

    readyz = run_readyz_checks()
    ai_issues = list(
        Issue.objects.filter(open_filter, source=Issue.Source.SYSTEM_WATCHDOG,
                             current_url__startswith="check:ai_")
        .order_by("severity", "-last_seen_at")
    )
    severity_counts = {
        row["severity"]: row["total"]
        for row in Issue.objects.filter(open_filter).values("severity").annotate(total=Count("id"))
    }
    missing_jobs = detect_missed_jobs(now=now, create_issues=False)

    context = {
        "generated_at": now,
        "readyz": readyz,
        "readyz_ok": readyz.status == "ok",
        "ai_issues": ai_issues,
        "ai_ok": not ai_issues,
        "severity_counts": severity_counts,
        "open_issues_count": Issue.objects.filter(open_filter).count(),
        "job_failed_today_count": AutomationExecution.objects.filter(
            status=AutomationExecution.Status.FAILED, started_at__gte=today_start).count(),
        "job_missing_count": len(missing_jobs),
        "quick_actions": [
            ("ai_verify", "🔎 Verifica AI"),
            ("ai_reindex", "🧠 Re-index SGI"),
            ("rag_quality", "📊 Valuta qualità RAG"),
            ("register_schedules", "📅 Registra schedule"),
        ],
    }
    return render(request, "monitoring/pages/system_status.html", context)


# Azioni rapide async (riusano i task django-q esistenti). Le operazioni lente
# (verifica AI ~rete, re-index ~minuti, eval qualità) si ACCODANO al cluster, non
# bloccano la request; l'esito si vede al refresh (badge/Issue).
_SYSTEM_ASYNC_ACTIONS = {
    "ai_verify": ("monitoring.tasks.run_ai_readiness_alert", {"include_services": True},
                  "Verifica AI avviata: ricarica tra poco per vedere l'esito."),
    "ai_reindex": ("ai_assistant.tasks.run_index_sgi_documents", {},
                   "Re-index del corpus SGI avviato (può richiedere minuti)."),
    "rag_quality": ("ai_assistant.tasks.run_rag_quality_alert", {},
                    "Valutazione qualità RAG avviata."),
}


@legacy_admin_required
@require_POST
def system_action(request):
    """Azioni rapide dalla centrale di comando (Ondata 2). Le azioni lente vengono
    accodate come task django-q (richiedono il cluster attivo); 'register_schedules'
    è rapida e sincrona. L'avvio/arresto del qcluster resta nel Server Dashboard
    (è il bootstrap su cui tutto il resto si appoggia)."""
    action = (request.POST.get("action") or "").strip()

    if action == "register_schedules":
        try:
            from django.core.management import call_command

            call_command("setup_q_schedules")
            log_action(request, "monitoring_register_schedules", "monitoring", {"action": action})
            messages.success(request, "Schedule django-q (ri)registrate.")
        except Exception as exc:
            messages.error(request, f"Registrazione schedule fallita: {exc}")
        return redirect("monitoring_admin:system_status")

    spec = _SYSTEM_ASYNC_ACTIONS.get(action)
    if not spec:
        messages.error(request, "Azione non riconosciuta.")
        return redirect("monitoring_admin:system_status")

    func_path, kwargs, ok_message = spec
    try:
        from django_q.tasks import async_task

        async_task(func_path, **kwargs)
        log_action(request, "monitoring_system_action", "monitoring",
                   {"action": action, "func": func_path})
        messages.success(request, ok_message)
    except Exception as exc:
        messages.error(request, f"Avvio azione non riuscito (cluster django-q attivo?): {exc}")
    return redirect("monitoring_admin:system_status")


@legacy_admin_required
def schedule_list(request):
    """Gestione schedule django-q dalla centrale (Ondata 3). Abilita/disabilita è
    DUREVOLE (monitoring.ScheduleControl, rispettato da setup_q_schedules anche dopo
    un redeploy); la cadenza resta definita nel codice (automazioni/schedules.py)."""
    from django_q.models import Schedule

    from automazioni.schedules import SCHEDULES

    from .models import ScheduleControl

    live = {s.name: s for s in Schedule.objects.all()}
    controls = {c.name: c.enabled for c in ScheduleControl.objects.all()}
    rows = []
    for spec in SCHEDULES:
        name = spec["name"]
        sch = live.get(name)
        rows.append({
            "name": name,
            "func": spec["func"],
            "cadence": (f"cron {spec['cron']}" if spec.get("schedule_type") == "C"
                        else f"ogni {spec.get('minutes')} min"),
            "enabled": controls.get(name, True),
            "registered": sch is not None,
            "next_run": getattr(sch, "next_run", None),
        })
    return render(request, "monitoring/pages/schedules.html", {"rows": rows})


@legacy_admin_required
@require_POST
def schedule_action(request):
    """Toggle (abilita/disabilita durevole) o 'esegui ora' di uno schedule."""
    from automazioni.schedules import delete_schedule, register_schedule, spec_by_name

    from .models import ScheduleControl

    name = (request.POST.get("name") or "").strip()
    action = (request.POST.get("action") or "").strip()
    spec = spec_by_name(name)
    if not spec:
        messages.error(request, "Schedule sconosciuto.")
        return redirect("monitoring_admin:schedule_list")

    if action == "toggle":
        control, _ = ScheduleControl.objects.get_or_create(name=name)
        control.enabled = not control.enabled
        control.updated_by = request.user if request.user.is_authenticated else None
        control.save()
        try:
            register_schedule(spec) if control.enabled else delete_schedule(name)
        except Exception as exc:
            messages.error(request, f"Applicazione non riuscita: {exc}")
            return redirect("monitoring_admin:schedule_list")
        log_action(request, "monitoring_schedule_toggle", "monitoring",
                   {"name": name, "enabled": control.enabled})
        messages.success(request, f"Schedule '{name}' {'abilitato' if control.enabled else 'disabilitato'}.")
    elif action == "run_now":
        try:
            from django_q.tasks import async_task

            async_task(spec["func"], **(spec.get("kwargs") or {}))
            log_action(request, "monitoring_schedule_run_now", "monitoring", {"name": name})
            messages.success(request, f"'{name}' avviato ora (accodato al cluster).")
        except Exception as exc:
            messages.error(request, f"Avvio non riuscito (cluster django-q attivo?): {exc}")
    else:
        messages.error(request, "Azione non riconosciuta.")
    return redirect("monitoring_admin:schedule_list")


@legacy_admin_required
def issue_list(request):
    qs = Issue.objects.select_related("assigned_to", "created_by_user").all().order_by("-last_seen_at", "-id")
    filters = {
        "status": (request.GET.get("status") or "").strip(),
        "severity": (request.GET.get("severity") or "").strip(),
        "source": (request.GET.get("source") or "").strip(),
        "category": (request.GET.get("category") or "").strip(),
        "module_name": (request.GET.get("module_name") or "").strip(),
        "date_from": (request.GET.get("date_from") or "").strip(),
        "date_to": (request.GET.get("date_to") or "").strip(),
        "open_only": (request.GET.get("open_only") or "").strip(),
    }

    if filters["status"]:
        qs = qs.filter(status=filters["status"])
    if filters["severity"]:
        qs = qs.filter(severity=filters["severity"])
    if filters["source"]:
        qs = qs.filter(source=filters["source"])
    if filters["category"]:
        qs = qs.filter(category=filters["category"])
    if filters["module_name"]:
        qs = qs.filter(module_name__icontains=filters["module_name"])
    if filters["date_from"]:
        qs = qs.filter(last_seen_at__date__gte=filters["date_from"])
    if filters["date_to"]:
        qs = qs.filter(last_seen_at__date__lte=filters["date_to"])
    if filters["open_only"] in {"1", "true", "on", "yes"}:
        qs = qs.filter(status__in=OPEN_ISSUE_STATUSES)

    page_obj = Paginator(qs, 50).get_page(request.GET.get("page"))
    context = {
        "page_obj": page_obj,
        "filters": filters,
        "status_choices": Issue.Status.choices,
        "severity_choices": Issue.Severity.choices,
        "source_choices": Issue.Source.choices,
        "category_choices": Issue.Category.choices,
    }
    return render(request, "monitoring/pages/issue_list.html", context)


@legacy_admin_required
def issue_detail(request, issue_id: int):
    issue = get_object_or_404(
        Issue.objects.select_related("assigned_to", "created_by_user"),
        pk=issue_id,
    )
    if request.method == "POST":
        _update_issue_from_post(request, issue)
        return redirect("monitoring_admin:issue_detail", issue_id=issue.pk)

    occurrences = list(issue.occurrences.select_related("user").order_by("-occurred_at", "-id")[:20])
    latest_occurrence = occurrences[0] if occurrences else None
    users_involved = list(
        issue.occurrences.exclude(username_snapshot="")
        .values("username_snapshot")
        .annotate(total=Count("id"))
        .order_by("-total", "username_snapshot")[:10]
    )
    related_reports = list(issue.user_problem_reports.select_related("user").order_by("-created_at", "-id")[:20])
    related_automation_executions = list(
        AutomationExecution.objects.select_related("job", "related_issue")
        .filter(Q(related_issue=issue) | Q(job__module_name=issue.module_name, status=AutomationExecution.Status.FAILED))
        .order_by("-started_at", "-id")[:20]
    )
    assignable_users = get_user_model().objects.filter(is_active=True).order_by("username")

    context = {
        "issue": issue,
        "occurrences": occurrences,
        "latest_occurrence": latest_occurrence,
        "users_involved": users_involved,
        "related_reports": related_reports,
        "related_automation_executions": related_automation_executions,
        "assignable_users": assignable_users,
        "status_choices": Issue.Status.choices,
    }
    return render(request, "monitoring/pages/issue_detail.html", context)


@legacy_admin_required
def automation_list(request):
    now = timezone.now()
    missing_jobs_map = {item["job"].pk: item for item in detect_missed_jobs(now=now, create_issues=False)}
    stuck_jobs_map = {item["job"].pk: item for item in detect_stuck_jobs(now=now, create_issues=False)}
    jobs = list(AutomationJob.objects.all().order_by("name", "code"))
    job_rows = [_build_job_row(job, missing_jobs_map=missing_jobs_map, stuck_jobs_map=stuck_jobs_map) for job in jobs]
    return render(request, "monitoring/pages/automations.html", {"job_rows": job_rows})


@legacy_admin_required
def automation_detail(request, job_id: int):
    now = timezone.now()
    job = get_object_or_404(AutomationJob, pk=job_id)
    executions = list(job.executions.select_related("related_issue").order_by("-started_at", "-id")[:30])
    job_row = _build_job_row(
        job,
        missing_jobs_map={item["job"].pk: item for item in detect_missed_jobs(now=now, create_issues=False)},
        stuck_jobs_map={item["job"].pk: item for item in detect_stuck_jobs(now=now, create_issues=False)},
        preloaded_executions=executions,
    )
    related_issues = Issue.objects.filter(
        Q(automation_executions__job=job) | Q(module_name=job.module_name, category=Issue.Category.AUTOMATION)
    ).distinct().order_by("-last_seen_at", "-id")[:20]

    return render(
        request,
        "monitoring/pages/automation_detail.html",
        {
            "job": job,
            "job_row": job_row,
            "executions": executions,
            "related_issues": related_issues,
        },
    )


def _update_issue_from_post(request, issue: Issue) -> None:
    desired_status = (request.POST.get("status") or "").strip()
    assigned_to_id = (request.POST.get("assigned_to") or "").strip()
    notes_internal = request.POST.get("notes_internal") or ""
    resolution_summary = request.POST.get("resolution_summary") or ""

    update_fields: list[str] = []
    valid_statuses = {choice[0] for choice in Issue.Status.choices}
    if desired_status in valid_statuses and desired_status != issue.status:
        issue.status = desired_status
        update_fields.append("status")

    if assigned_to_id:
        assigned_user = get_object_or_404(get_user_model(), pk=assigned_to_id)
    else:
        assigned_user = None

    if issue.assigned_to_id != getattr(assigned_user, "pk", None):
        issue.assigned_to = assigned_user
        update_fields.append("assigned_to")

    if issue.notes_internal != notes_internal:
        issue.notes_internal = notes_internal
        update_fields.append("notes_internal")
    if issue.resolution_summary != resolution_summary:
        issue.resolution_summary = resolution_summary
        update_fields.append("resolution_summary")

    if update_fields:
        issue.save(update_fields=update_fields + ["updated_at"])
        try:
            log_action(
                request,
                "monitoring_issue_update",
                "monitoring",
                {
                    "issue_id": issue.pk,
                    "issue_code": issue.code,
                    "updated_fields": update_fields,
                },
            )
        except Exception:
            pass
        messages.success(request, "Issue aggiornata.")
    else:
        messages.info(request, "Nessuna modifica da salvare.")


def _build_job_row(
    job: AutomationJob,
    *,
    missing_jobs_map: dict[int, dict[str, object]],
    stuck_jobs_map: dict[int, dict[str, object]],
    preloaded_executions: list[AutomationExecution] | None = None,
) -> dict[str, object]:
    executions = preloaded_executions if preloaded_executions is not None else list(
        job.executions.order_by("-started_at", "-id")[:10]
    )
    last_execution = executions[0] if executions else None
    consecutive_failures = 0
    for execution in executions:
        if execution.status != AutomationExecution.Status.FAILED:
            break
        consecutive_failures += 1

    next_expected_at = None
    if job.expected_max_interval_minutes:
        reference = last_execution.started_at if last_execution else job.created_at
        next_expected_at = reference + timedelta(minutes=int(job.expected_max_interval_minutes))

    return {
        "job": job,
        "last_execution": last_execution,
        "consecutive_failures": consecutive_failures,
        "missing_alert": missing_jobs_map.get(job.pk),
        "stuck_alert": stuck_jobs_map.get(job.pk),
        "next_expected_at": next_expected_at,
        "last_duration_seconds": getattr(last_execution, "duration_seconds", None),
    }
