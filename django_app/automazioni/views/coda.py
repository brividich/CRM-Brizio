"""Viste del modulo Automazioni — Coda eventi SQL, run log e invii pianificati.

Spacchettamento di ``automazioni/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from django.contrib import messages
from django.db.models import Count
from django.db import connection, transaction
from django.db.utils import OperationalError as DjangoOperationalError, ProgrammingError as DjangoProgrammingError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from admin_portale.decorators import legacy_admin_or_acl_required
from monitoring.models import AutomationJob, AutomationExecution
from monitoring.services import detect_missed_jobs, detect_stuck_jobs

from ..models import (
    AutomationActionLog,
    AutomationRule,
    AutomationRunLog,
    AutomationRunLogStatus,
)
from ..services import (
    count_queue_by_status,
    get_queue_event_detail,
    list_queue_events,
    delete_queue_event,
    process_single_queue_event_by_id,
    reset_queue_event_to_pending,
    stop_queue_event,
)
from ..source_registry import (
    get_registered_sources,
)



from . import _helpers  # noqa: E402


QUEUE_STATUS_CHOICES = ("pending", "processing", "done", "error")
QUEUE_OPERATION_CHOICES = ("insert", "update")
QUEUE_POLLER_JOB_CODE = "automazioni_process_queue"
QUEUE_POLLER_TASK_NAME = "Portale Hub Polling Mail"
QUEUE_POLLER_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "automation_queue.log"


def _run_powershell_json(script: str) -> dict[str, object]:
    if os.name != "nt":
        return {"ok": False, "error": "Task Scheduler disponibile solo su Windows."}
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return {"ok": False, "error": stderr or stdout or f"exit code {completed.returncode}"}
    if not stdout:
        return {"ok": False, "error": "Il comando non ha restituito output JSON."}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON non valido dal comando PowerShell: {exc}"}
    return {"ok": True, "data": data if isinstance(data, dict) else {}}


def _build_queue_poller_task_snapshot() -> dict[str, object]:
    snapshot = {
        "task_name": QUEUE_POLLER_TASK_NAME,
        "task_path": "\\",
        "task_exists": False,
        "task_state": "missing",
        "task_state_label": "Non registrato",
        "task_last_run_label": "-",
        "task_next_run_label": "-",
        "task_last_result_label": "-",
        "task_message": "Il task Windows locale non e registrato.",
    }
    escaped_name = QUEUE_POLLER_TASK_NAME.replace("'", "''")
    ps_query = f"""
$task = Get-ScheduledTask -TaskName '{escaped_name}' -ErrorAction SilentlyContinue
if ($null -eq $task) {{
  [pscustomobject]@{{
    exists = $false
    task_name = '{escaped_name}'
    task_path = '\\'
    state = 'missing'
    description = ''
    last_run_time = ''
    next_run_time = ''
    last_task_result = ''
  }} | ConvertTo-Json -Compress
  exit 0
}}
$info = Get-ScheduledTaskInfo -TaskName '{escaped_name}' -ErrorAction SilentlyContinue
[pscustomobject]@{{
  exists = $true
  task_name = [string]$task.TaskName
  task_path = [string]$task.TaskPath
  state = [string]$task.State
  description = [string]$task.Description
  last_run_time = $(if ($info -and $info.LastRunTime -gt [datetime]'1900-01-01') {{ $info.LastRunTime.ToString('o') }} else {{ '' }})
  next_run_time = $(if ($info -and $info.NextRunTime -gt [datetime]'1900-01-01') {{ $info.NextRunTime.ToString('o') }} else {{ '' }})
  last_task_result = $(if ($info) {{ [string]$info.LastTaskResult }} else {{ '' }})
}} | ConvertTo-Json -Compress
"""
    ps_result = _run_powershell_json(ps_query)
    if not ps_result.get("ok"):
        snapshot["task_state"] = "unknown"
        snapshot["task_state_label"] = "Stato non leggibile"
        snapshot["task_message"] = str(ps_result.get("error") or "Impossibile interrogare Task Scheduler.")
        return snapshot

    data = ps_result.get("data") or {}
    state_code = str(data.get("state") or "missing").strip().lower()
    state_labels = {
        "missing": "Non registrato",
        "ready": "Pronto",
        "running": "In esecuzione",
        "queued": "In coda",
        "disabled": "Disabilitato",
        "unknown": "Sconosciuto",
    }
    last_result = str(data.get("last_task_result") or "").strip()
    snapshot.update(
        {
            "task_name": str(data.get("task_name") or QUEUE_POLLER_TASK_NAME),
            "task_path": str(data.get("task_path") or "\\"),
            "task_exists": bool(data.get("exists")),
            "task_state": state_code,
            "task_state_label": state_labels.get(state_code, state_code.upper() or "Sconosciuto"),
            "task_last_run_label": _helpers._format_display_datetime(data.get("last_run_time")),
            "task_next_run_label": _helpers._format_display_datetime(data.get("next_run_time")),
            "task_last_result_label": "0 (ultimo avvio ok)" if last_result == "0" else (last_result or "-"),
        }
    )
    if snapshot["task_exists"]:
        snapshot["task_message"] = (
            "Task registrato localmente."
            if snapshot["task_state"] in {"ready", "running", "queued"}
            else "Task presente ma non in stato operativo."
        )
    return snapshot


def _build_queue_poller_log_snapshot() -> dict[str, object]:
    exists = QUEUE_POLLER_LOG_PATH.exists()
    size_label = "-"
    last_write_label = "-"
    if exists:
        stat = QUEUE_POLLER_LOG_PATH.stat()
        size_kb = stat.st_size / 1024 if stat.st_size else 0
        size_label = f"{size_kb:.1f} KB"
        last_write_label = _helpers._format_display_datetime(datetime.fromtimestamp(stat.st_mtime))
    return {
        "log_path": str(QUEUE_POLLER_LOG_PATH),
        "log_exists": exists,
        "log_size_label": size_label,
        "log_last_write_label": last_write_label,
    }


def _build_queue_poller_health_snapshot() -> dict[str, object]:
    now = timezone.now()
    task_snapshot = _build_queue_poller_task_snapshot()
    log_snapshot = _build_queue_poller_log_snapshot()
    job = AutomationJob.objects.filter(code=QUEUE_POLLER_JOB_CODE).first()
    executions = list(job.executions.order_by("-started_at", "-id")[:10]) if job else []
    last_execution = executions[0] if executions else None
    consecutive_failures = 0
    for execution in executions:
        if execution.status != AutomationExecution.Status.FAILED:
            break
        consecutive_failures += 1

    missing_alert = None
    stuck_alert = None
    next_expected_at_label = "-"
    if job is not None:
        missing_alert = {
            item["job"].pk: item for item in detect_missed_jobs(now=now, create_issues=False)
        }.get(job.pk)
        stuck_alert = {
            item["job"].pk: item for item in detect_stuck_jobs(now=now, create_issues=False)
        }.get(job.pk)
        if job.expected_max_interval_minutes:
            reference_time = last_execution.started_at if last_execution else job.created_at
            next_expected_at_label = _helpers._format_display_datetime(
                reference_time + timedelta(minutes=int(job.expected_max_interval_minutes))
            )

    summary_state = "healthy"
    summary_label = "Attivo"
    summary_message = "Task registrato e job monitorato nei tempi attesi."
    if not task_snapshot["task_exists"]:
        summary_state = "error"
        summary_label = "Task mancante"
        summary_message = (
            "Gli eventi possono restare pending perche il consumatore automatico non e registrato sul server."
        )
    elif task_snapshot["task_state"] == "disabled":
        summary_state = "error"
        summary_label = "Task disabilitato"
        summary_message = "Il task Windows esiste ma e disabilitato, quindi la queue non viene consumata."
    elif stuck_alert:
        summary_state = "error"
        summary_label = "Worker bloccato"
        summary_message = "L'ultima esecuzione risulta oltre la durata massima attesa."
    elif missing_alert:
        overdue_minutes = int(missing_alert.get("overdue_minutes") or 0)
        summary_state = "warning"
        summary_label = "In ritardo"
        summary_message = f"Il job non risulta eseguito nei tempi attesi ed e in ritardo di {overdue_minutes} minuti."
    elif last_execution is None:
        summary_state = "warning"
        summary_label = "Mai eseguito"
        summary_message = "Il task esiste ma non risultano ancora esecuzioni monitorate del queue processor."
    elif last_execution.status == AutomationExecution.Status.FAILED:
        summary_state = "warning"
        summary_label = "Ultimo run fallito"
        summary_message = "Il task parte, ma l'ultima esecuzione monitorata del queue processor e fallita."
    elif task_snapshot["task_state"] not in {"ready", "running", "queued"}:
        summary_state = "warning"
        summary_label = "Stato task anomalo"
        summary_message = "Il task esiste ma non risulta pronto o in esecuzione."

    return {
        **task_snapshot,
        **log_snapshot,
        "summary_state": summary_state,
        "summary_label": summary_label,
        "summary_message": summary_message,
        "display_timezone_label": timezone.get_current_timezone_name(),
        "job_exists": job is not None,
        "job_id": getattr(job, "pk", None),
        "job_code": QUEUE_POLLER_JOB_CODE,
        "job_name": getattr(job, "name", "Processo queue automazioni"),
        "job_last_execution_label": _helpers._format_display_datetime(getattr(last_execution, "started_at", None)),
        "job_status_label": getattr(last_execution, "get_status_display", lambda: "-")(),
        "job_status_code": str(getattr(last_execution, "status", "") or "").lower(),
        "job_trigger_type_label": getattr(last_execution, "get_trigger_type_display", lambda: "-")(),
        "job_message": str(getattr(last_execution, "message", "") or "").strip() or "-",
        "job_consecutive_failures": consecutive_failures,
        "job_next_expected_label": next_expected_at_label,
        "job_missing_alert": bool(missing_alert),
        "job_missing_detail": (
            f"In ritardo di {int(missing_alert.get('overdue_minutes') or 0)} minuti."
            if missing_alert else "-"
        ),
        "job_stuck_alert": bool(stuck_alert),
        "job_stuck_detail": (
            f"Oltre soglia di {int(stuck_alert.get('delay_seconds') or 0)} secondi."
            if stuck_alert else "-"
        ),
    }


def _queue_table_exists() -> bool:
    try:
        table_name = "automation_event_queue" if connection.vendor == "sqlite" else "dbo.automation_event_queue"
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM {table_name} WHERE 1=0;")
        return True
    except (DjangoProgrammingError, DjangoOperationalError):
        return False


@legacy_admin_or_acl_required("automazioni", "queue_list_page")
@require_GET
def queue_list_page(request):
    status = _helpers._get_filter_value(request, "status")
    source_code = _helpers._get_filter_value(request, "source_code")
    operation_type = _helpers._get_filter_value(request, "operation_type")
    poller_health = _build_queue_poller_health_snapshot()

    if not _queue_table_exists():
        context = {
            **_helpers._base_context(),
            "queue_table_missing": True,
            "poller_health": poller_health,
            "queue_events": [],
            "queue_counts": {},
            "filters": {"status": status, "source_code": source_code, "operation_type": operation_type},
            "queue_status_choices": QUEUE_STATUS_CHOICES,
            "queue_operation_choices": QUEUE_OPERATION_CHOICES,
            "source_choices": [],
        }
        return render(request, "automazioni/pages/queue_list.html", context)

    queue_events = list_queue_events(
        status=status or None,
        source_code=source_code or None,
        operation_type=operation_type or None,
        limit=200,
    )
    queue_ids = [int(event["id"]) for event in queue_events]
    run_log_counts = {
        row["queue_event_id"]: row["total"]
        for row in AutomationRunLog.objects.filter(queue_event_id__in=queue_ids)
        .order_by()
        .values("queue_event_id")
        .annotate(total=Count("id"))
    }
    for event in queue_events:
        event["run_log_count"] = int(run_log_counts.get(event["id"], 0))
        event["error_message_short"] = str(event.get("error_message") or "")[:180]
        event["can_reset"] = event.get("status") == "error"
        event["can_retry"] = event.get("status") in {"error", "pending"}
        event["can_stop"] = event.get("status") == "pending"
        event["can_delete"] = event.get("status") in {"pending", "error"} and event["run_log_count"] == 0

    context = {
        **_helpers._base_context(),
        "queue_table_missing": False,
        "poller_health": poller_health,
        "queue_events": queue_events,
        "queue_counts": count_queue_by_status(
            source_code=source_code or None,
            operation_type=operation_type or None,
        ),
        "filters": {
            "status": status,
            "source_code": source_code,
            "operation_type": operation_type,
        },
        "queue_status_choices": QUEUE_STATUS_CHOICES,
        "queue_operation_choices": QUEUE_OPERATION_CHOICES,
        "source_choices": [(source["code"], source["label"]) for source in get_registered_sources()],
    }
    return render(request, "automazioni/pages/queue_list.html", context)


@legacy_admin_or_acl_required("automazioni", "queue_detail_page")
@require_GET
def queue_detail_page(request, queue_id: int):
    queue_event = get_queue_event_detail(queue_id)
    if queue_event is None:
        raise Http404("Evento queue non trovato.")
    poller_health = _build_queue_poller_health_snapshot()

    run_logs = list(
        AutomationRunLog.objects.filter(queue_event_id=queue_id)
        .select_related("rule", "initiated_by")
        .prefetch_related("action_logs__action")
        .order_by("-started_at", "-id")
    )
    action_logs = list(
        AutomationActionLog.objects.filter(run_log__queue_event_id=queue_id)
        .select_related("action", "run_log", "run_log__rule")
        .order_by("created_at", "id")
    )

    queue_event["payload_pretty"] = _helpers._json_pretty(queue_event.get("payload_json"))
    queue_event["old_payload_pretty"] = _helpers._json_pretty(queue_event.get("old_payload_json"))
    queue_event["can_reset"] = queue_event.get("status") == "error"
    queue_event["can_retry"] = queue_event.get("status") in {"error", "pending"}
    queue_event["run_log_count"] = len(run_logs)
    queue_event["can_stop"] = queue_event.get("status") == "pending"
    queue_event["can_delete"] = queue_event.get("status") in {"pending", "error"} and not run_logs

    context = {
        **_helpers._base_context(),
        "poller_health": poller_health,
        "queue_event": queue_event,
        "run_logs": run_logs,
        "action_logs": action_logs,
    }
    return render(request, "automazioni/pages/queue_detail.html", context)


@legacy_admin_or_acl_required("automazioni", "queue_reset_view")
@require_POST
def queue_reset_view(request, queue_id: int):
    if reset_queue_event_to_pending(queue_id):
        messages.success(request, f"Evento queue {queue_id} riportato a pending.")
    else:
        messages.error(request, f"Reset non consentito per l'evento queue {queue_id}.")
    return redirect("admin_portale:automazioni_queue_detail", queue_id=queue_id)


@legacy_admin_or_acl_required("automazioni", "queue_retry_view")
@require_POST
def queue_retry_view(request, queue_id: int):
    result = process_single_queue_event_by_id(queue_id)
    if result["status"] == "done":
        messages.success(
            request,
            f"Retry completato per evento queue {queue_id}. Regole eseguite: {result['rule_runs']}.",
        )
    else:
        messages.error(request, f"Retry fallito per evento queue {queue_id}: {result['message']}")
    return redirect("admin_portale:automazioni_queue_detail", queue_id=queue_id)


@legacy_admin_or_acl_required("automazioni", "queue_stop_view")
@require_POST
def queue_stop_view(request, queue_id: int):
    if stop_queue_event(queue_id):
        _helpers.log_action(
            request,
            "queue_stop",
            "automazioni",
            {"queue_event_id": int(queue_id), "source": "queue_admin"},
        )
        messages.success(request, f"Evento queue {queue_id} stoppato manualmente.")
    else:
        messages.error(
            request,
            f"Stop non consentito per l'evento queue {queue_id}. Sono stoppabili solo eventi ancora pending.",
        )
    return redirect("admin_portale:automazioni_queue_detail", queue_id=queue_id)


@legacy_admin_or_acl_required("automazioni", "queue_delete_view")
@require_POST
def queue_delete_view(request, queue_id: int):
    if delete_queue_event(queue_id):
        _helpers.log_action(
            request,
            "queue_delete",
            "automazioni",
            {"queue_event_id": int(queue_id), "source": "queue_admin"},
        )
        messages.success(request, f"Evento queue {queue_id} eliminato.")
    else:
        messages.error(
            request,
            (
                f"Eliminazione non consentita per l'evento queue {queue_id}. "
                "Puoi eliminare solo eventi pending/error senza run log collegati."
            ),
        )
    return redirect("admin_portale:automazioni_queue_list")


@legacy_admin_or_acl_required("automazioni", "run_log_list_page")
@require_GET
def run_log_list_page(request):
    from datetime import timedelta
    from django.utils import timezone as _tz

    status = _helpers._get_filter_value(request, "status")
    source_code = _helpers._get_filter_value(request, "source_code")
    is_test = _helpers._get_filter_value(request, "is_test")
    rule_id = _helpers._get_filter_value(request, "rule")
    queue_event_id = _helpers._get_filter_value(request, "queue_event_id")
    recent = _helpers._get_filter_value(request, "recent")  # "24h" o vuoto

    queryset = AutomationRunLog.objects.select_related("rule", "initiated_by").order_by("-started_at", "-id")
    if status:
        queryset = queryset.filter(status=status)
    if source_code:
        queryset = queryset.filter(source_code=source_code)
    if is_test in {"true", "false"}:
        queryset = queryset.filter(is_test=is_test == "true")
    if rule_id:
        queryset = queryset.filter(rule_id=rule_id)
    if queue_event_id:
        queryset = queryset.filter(queue_event_id=queue_event_id)
    if recent == "24h":
        queryset = queryset.filter(started_at__gte=_tz.now() - timedelta(hours=24))

    run_logs = list(queryset[:200])
    # Max ms per la sparkbar (sui run mostrati). Evita divisioni per 0 sui chart.
    max_execution_ms = max((rl.execution_ms or 0 for rl in run_logs), default=0)

    # Conteggi rapidi per i chip (globali sulla queryset NON filtrata da status/is_test/recent,
    # così i chip mostrano "quanti ce ne sarebbero" anche quando un filtro è attivo).
    _global = AutomationRunLog.objects.all()
    if source_code:
        _global = _global.filter(source_code=source_code)
    if rule_id:
        _global = _global.filter(rule_id=rule_id)
    if queue_event_id:
        _global = _global.filter(queue_event_id=queue_event_id)
    chip_counts = {
        "errors": _global.filter(status__in=("failed", "error")).count(),
        "tests": _global.filter(is_test=True).count(),
        "recent_24h": _global.filter(started_at__gte=_tz.now() - timedelta(hours=24)).count(),
    }

    context = {
        **_helpers._base_context(),
        "run_logs": run_logs,
        "max_execution_ms": max_execution_ms,
        "chip_counts": chip_counts,
        "filters": {
            "status": status,
            "source_code": source_code,
            "is_test": is_test,
            "rule": rule_id,
            "queue_event_id": queue_event_id,
            "recent": recent,
        },
        "status_choices": AutomationRunLogStatus.values,
        "source_choices": _run_log_source_choices(),
        "rules": list(AutomationRule.objects.filter(run_logs__isnull=False).values("id", "name").distinct().order_by("name")),
    }
    return render(request, "automazioni/pages/run_log_list.html", context)


def _run_log_source_choices() -> list[tuple[str, str]]:
    """Opzioni del filtro 'Sorgente' del Run-log: sorgenti registrate + job di sistema.

    I job di sistema (task django-q tracciati con source_code 'system:<job>') non
    sono nel source registry; vengono aggiunti dinamicamente in base ai run effettivi
    cosi' restano filtrabili dalla UI.
    """
    choices = [(source["code"], source["label"]) for source in get_registered_sources()]
    known = {c[0] for c in choices}
    system_codes = (
        AutomationRunLog.objects.filter(source_code__startswith="system:")
        .values_list("source_code", flat=True)
        .distinct()
    )
    for code in sorted(set(system_codes)):
        if code in known:
            continue
        label = "Sistema: " + code.split(":", 1)[1].replace("_", " ")
        choices.append((code, label))
    return choices


@legacy_admin_or_acl_required("automazioni", "run_log_detail_page")
@require_GET
def run_log_detail_page(request, run_log_id: int):
    run_log = get_object_or_404(
        AutomationRunLog.objects.select_related("rule", "initiated_by").prefetch_related("action_logs__action"),
        pk=run_log_id,
    )
    queue_event = get_queue_event_detail(run_log.queue_event_id) if run_log.queue_event_id else None
    action_logs = list(run_log.action_logs.select_related("action").order_by("created_at", "id"))

    context = {
        **_helpers._base_context(),
        "run_log": run_log,
        "queue_event": queue_event,
        "action_logs": action_logs,
        "payload_pretty": _helpers._json_pretty(run_log.payload_json),
        "old_payload_pretty": _helpers._json_pretty(run_log.old_payload_json),
    }
    return render(request, "automazioni/pages/run_log_detail.html", context)


# ── Task pianificati (schedule django-q) — riflessi nell'area automazioni ──────

@legacy_admin_or_acl_required("automazioni", "pianificati_page")
@require_GET
def pianificati_page(request):
    """Elenco dei task pianificati (SCHEDULES) con stato on/off e prossima esecuzione.

    Riflette nell'area Automazioni i job periodici django-q che finora si vedevano
    solo dalla Centrale di comando. Abilita/disabilita è DUREVOLE (ScheduleControl,
    rispettato anche dopo un redeploy); la cadenza è definita nel codice.
    """
    from ..mail_config import is_configurable
    from ..schedules import SCHEDULES, schedule_rows

    rows = schedule_rows()
    for r in rows:
        r["configurable"] = is_configurable(r["name"])
    enabled_n = sum(1 for r in rows if r["enabled"])
    from ..flow_health import broker_health
    health = broker_health()
    context = {
        **_helpers._base_context(),
        "rows": rows,
        "health": health,
        "totale": len(SCHEDULES),
        "attivi": enabled_n,
        "disattivi": len(rows) - enabled_n,
    }
    return render(request, "automazioni/pages/pianificati.html", context)


@legacy_admin_or_acl_required("automazioni", "pianificati_action")
@require_POST
def pianificati_action(request):
    """Toggle on/off durevole o 'esegui ora' di un task pianificato."""
    from monitoring.models import ScheduleControl

    from ..schedules import delete_schedule, register_schedule, spec_by_name

    name = (request.POST.get("name") or "").strip()
    action = (request.POST.get("action") or "").strip()
    spec = spec_by_name(name)
    if not spec:
        messages.error(request, "Task pianificato sconosciuto.")
        return redirect("admin_portale:automazioni_pianificati")

    if action == "save_schedule":
        from ..flow_forms import ManagedScheduleForm
        from ..models import ManagedFlow
        from ..managed_flows import synchronize_schedule
        binding = get_object_or_404(ManagedFlow, code=name, kind="schedule")
        form = ManagedScheduleForm(request.POST, instance=binding)
        if form.is_valid():
            with transaction.atomic():
                binding = form.save()
                synchronize_schedule(binding)
            _helpers.log_action(request, "automazioni_schedule_config", "automazioni", {"name": name})
            messages.success(request, "Pianificazione salvata.")
        else:
            messages.error(request, "Pianificazione non valida: " + " ".join(str(e) for errors in form.errors.values() for e in errors))
        return redirect("admin_portale:automazioni_rule_designer", rule_id=binding.rule_id)
    if action == "toggle":
        control, _ = ScheduleControl.objects.get_or_create(name=name)
        control.enabled = not control.enabled
        if hasattr(control, "updated_by"):
            control.updated_by = request.user if request.user.is_authenticated else None
        control.save()
        try:
            register_schedule(spec) if control.enabled else delete_schedule(name)
        except Exception as exc:
            messages.error(request, f"Applicazione non riuscita: {exc}")
            return redirect("admin_portale:automazioni_pianificati")
        _helpers.log_action(request, "automazioni_schedule_toggle", "automazioni",
                   {"name": name, "enabled": control.enabled})
        messages.success(request, f"Task '{name}' {'attivato' if control.enabled else 'disattivato'}.")
    elif action == "run_now":
        try:
            from django_q.tasks import async_task

            from ..models import ManagedFlow
            binding = ManagedFlow.objects.filter(code=name, kind="schedule").first()
            if binding:
                async_task("automazioni.managed_flows.run_managed_flow", name)
            else:
                async_task(spec["func"], **(spec.get("kwargs") or {}))
            _helpers.log_action(request, "automazioni_schedule_run_now", "automazioni", {"name": name})
            messages.success(request, f"'{name}' avviato ora (accodato al cluster).")
        except Exception as exc:
            messages.error(request, f"Avvio non riuscito (cluster django-q attivo?): {exc}")
    else:
        messages.error(request, "Azione non riconosciuta.")
    return redirect("admin_portale:automazioni_pianificati")


@legacy_admin_or_acl_required("automazioni", "pianificati_mail_config_page")
@require_GET
def pianificati_mail_config_page(request, name):
    """Configura destinatari + cornice testuale (oggetto/intro/nota) di un task mail."""
    from ..mail_config import get_recipients_raw, get_text_overrides, is_configurable, task_meta
    from ..schedules import describe_cadence, schedule_descriptions, spec_by_name

    spec = spec_by_name(name)
    if not spec or not is_configurable(name):
        messages.error(request, "Questo task non è configurabile.")
        return redirect("admin_portale:automazioni_pianificati")

    txt = get_text_overrides(name)
    context = {
        **_helpers._base_context(),
        "name": name,
        "meta": task_meta(name),
        "cadence": describe_cadence(spec),
        "description": schedule_descriptions().get(name, ""),
        "recipients": get_recipients_raw(name),
        "subject": getattr(txt, "subject", ""),
        "intro": getattr(txt, "intro", ""),
        "footer": getattr(txt, "footer", ""),
    }
    return render(request, "automazioni/pages/pianificati_mail.html", context)


@legacy_admin_or_acl_required("automazioni", "pianificati_mail_config_save")
@require_POST
def pianificati_mail_config_save(request, name):
    """Salva destinatari (SiteConfig) + testo (ScheduledMailText) di un task mail."""
    from ..mail_config import is_configurable, set_recipients_raw, task_meta
    from ..models import ScheduledMailText
    from ..schedules import spec_by_name

    spec = spec_by_name(name)
    if not spec or not is_configurable(name):
        messages.error(request, "Questo task non è configurabile.")
        return redirect("admin_portale:automazioni_pianificati")

    if task_meta(name).get("config_key"):
        set_recipients_raw(name, request.POST.get("recipients") or "")

    subject = (request.POST.get("subject") or "").strip()
    intro = (request.POST.get("intro") or "").strip()
    footer = (request.POST.get("footer") or "").strip()
    if subject or intro or footer:
        obj, _ = ScheduledMailText.objects.get_or_create(task_name=name)
        obj.subject, obj.intro, obj.footer = subject, intro, footer
        obj.updated_by = request.user if request.user.is_authenticated else None
        obj.save()
    else:
        ScheduledMailText.objects.filter(task_name=name).delete()

    _helpers.log_action(request, "automazioni_mail_config_save", "automazioni", {"name": name})
    messages.success(request, f"Configurazione mail di '{name}' salvata.")
    return redirect("admin_portale:automazioni_pianificati_mail", name=name)


@legacy_admin_or_acl_required("automazioni", "pianificati_mail_test")
@require_POST
def pianificati_mail_test(request, name):
    """Invia all'admin corrente un'ANTEPRIMA della mail del flusso (dati di esempio).

    Usa la cornice reale (frame HUB + oggetto/intro/nota configurati) con righe di
    esempio: non interroga le scadenze reali e non tocca i destinatari veri.
    """
    from ..mail_config import apply_mail_overrides, is_configurable, task_meta
    from ..schedules import spec_by_name

    spec = spec_by_name(name)
    if not spec or not is_configurable(name):
        messages.error(request, "Questo task non è configurabile.")
        return redirect("admin_portale:automazioni_pianificati")

    destinatario = (getattr(request.user, "email", "") or "").strip()
    if not destinatario:
        messages.error(request, "Il tuo utente non ha un'email: impossibile inviare l'anteprima.")
        return redirect("admin_portale:automazioni_pianificati_mail", name=name)

    from core.email_utils import email_item_cards, send_hub_mail

    meta = task_meta(name)
    esempio = email_item_cards([
        {"title": "Dipendente #123", "subtitle": "Esempio di voce",
         "badge": ("In scadenza", "warning"), "note": "Scadenza 31-12-2026", "accent": "#f59e0b"},
        {"title": "Dipendente #456", "subtitle": "Esempio di voce",
         "badge": ("Scaduto", "danger"), "note": "Scaduto il 01-01-2026", "accent": "#dc2626"},
    ])
    subject = f"[ANTEPRIMA] {meta.get('label', name)}"
    body_text = ("Anteprima dell'email di questo flusso (dati di esempio).\n\n"
                 "Le voci reali sono generate automaticamente dalle scadenze al momento dell'invio.")
    subject, body_text, fragment, footer = apply_mail_overrides(
        name, subject=subject, body_text=body_text, fragment=esempio)
    try:
        send_hub_mail(
            subject, body_text, [destinatario],
            email_type="Anteprima", section_label=meta.get("label", name),
            body_html_fragment=fragment, footer_note=footer,
            preheader="Anteprima flusso mail", fail_silently=False,
        )
        _helpers.log_action(request, "automazioni_mail_test", "automazioni", {"name": name, "to": destinatario})
        messages.success(request, f"Anteprima inviata a {destinatario}.")
    except Exception as exc:
        messages.error(request, f"Invio anteprima non riuscito: {exc}")
    return redirect("admin_portale:automazioni_pianificati_mail", name=name)
