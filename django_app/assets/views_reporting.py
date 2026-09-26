from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_or_acl_required
from core.audit import log_action
from .models import AssetReportRun, AssetReportSchedule
from .reporting_forms import AssetReportScheduleForm
from .services.reporting import configuration, create_run, display_snapshot, enqueue_run


def context(request, **kwargs):
    from .views import _assets_shell_context
    return {**_assets_shell_context(request), **kwargs}


@legacy_admin_or_acl_required("assets", "admin_assets")
def settings(request, pk=None):
    plan = get_object_or_404(AssetReportSchedule, pk=pk) if pk else None
    form = AssetReportScheduleForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Il lock protegge da una scadenza processata mentre si modifica il piano.
            if plan:
                AssetReportSchedule.objects.select_for_update().get(pk=plan.pk)
            saved = form.save(commit=False)
            if not saved.pk:
                saved.created_by = request.user
            saved.save()
        log_action(request, "report_schedule_save", "assets", oggetto=saved)
        messages.success(request, "Programmazione report salvata.")
        return redirect("assets:reporting_settings")
    return render(request, "assets/pages/reporting_settings.html", context(
        request, form=form, editing=plan, plans=AssetReportSchedule.objects.all(),
    ))


@legacy_admin_or_acl_required("assets", "admin_assets")
@require_POST
def run_now(request, pk):
    with transaction.atomic():
        plan = get_object_or_404(AssetReportSchedule.objects.select_for_update(), pk=pk)
        # Doppio click: riusa l'estrazione ancora in corso della stessa configurazione.
        config = configuration(plan)
        run = next((r for r in plan.runs.filter(status__in=["PENDING", "RUNNING"]).defer("snapshot", "pdf_content", "excel_content") if r.configuration == config), None)
        if run is None:
            run = create_run(plan, timezone.now(), request.user)
    try:
        enqueue_run(run.pk)
        messages.success(request, "Estrazione accodata. Il report sarà disponibile nell'archivio.")
    except Exception:
        messages.warning(request, "Estrazione salvata in coda; il servizio riproverà automaticamente.")
    log_action(request, "report_run_request", "assets", oggetto=run)
    return redirect("assets:reporting_settings")


@legacy_admin_or_acl_required("assets", "admin_assets")
@require_POST
def retry(request, pk):
    run = get_object_or_404(AssetReportRun, pk=pk)
    if run.status == "ERROR":
        AssetReportRun.objects.filter(pk=pk, status="ERROR").update(attempts=0, enqueued_at=None, status="PENDING")
        try:
            enqueue_run(pk)
        except Exception:
            messages.warning(request, "Richiesta salvata; worker non raggiungibile.")
        log_action(request, "report_run_retry", "assets", oggetto=run)
    return redirect("assets:reporting_settings")


@legacy_admin_or_acl_required("assets", "assets_reports")
def archive(request):
    runs = AssetReportRun.objects.select_related("schedule").defer("snapshot", "pdf_content", "excel_content")
    plan_id = request.GET.get("plan", "")
    if plan_id.isdigit():
        runs = runs.filter(schedule_id=int(plan_id))
    page = Paginator(runs, 25).get_page(request.GET.get("page"))
    return render(request, "assets/pages/reporting_archive.html", context(
        request, page=page, plans=AssetReportSchedule.objects.all(), selected_plan=plan_id,
    ))


@legacy_admin_or_acl_required("assets", "assets_reports")
def detail(request, pk):
    run = get_object_or_404(AssetReportRun.objects.defer("pdf_content", "excel_content"), pk=pk)
    data = display_snapshot(run.snapshot)
    trend = data.get("trend", [])
    maximum = max([row[key] for row in trend for key in ("assets", "in_use", "in_repair", "snmp_errors")] or [1]) or 1
    series = []
    for key, label, color in [("assets", "Asset", "#2563eb"), ("in_use", "In uso", "#16a34a"), ("in_repair", "In riparazione", "#d97706"), ("snmp_errors", "Errori SNMP", "#dc2626")]:
        points = " ".join(f"{30 + i * 640 / max(1, len(trend)-1):.1f},{180 - row[key] * 150 / maximum:.1f}" for i, row in enumerate(trend))
        series.append({"label": label, "color": color, "points": points})
    return render(request, "assets/pages/reporting_detail.html", context(request, run=run, data=data, series=series, trend=trend))


@legacy_admin_or_acl_required("assets", "assets_reports")
def download(request, pk, file_format):
    if file_format not in ("pdf", "xlsx"):
        raise Http404
    field = "pdf_content" if file_format == "pdf" else "excel_content"
    run = get_object_or_404(AssetReportRun.objects.only(field, "status"), pk=pk, status="DONE")
    content = getattr(run, field)
    if not content:
        raise Http404
    mime = "application/pdf" if file_format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response = HttpResponse(bytes(content), content_type=mime)
    response["Content-Disposition"] = f'attachment; filename="asset-report-{pk}.{file_format}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    log_action(request, "report_download", "assets", {"format": file_format}, oggetto=run)
    return response
