"""Sezione Backup del SOC: panoramica con KPI, statistiche per PC e per job, log, scheda dispositivo."""
from django.http import Http404
from django.shortcuts import render

from .models import BackupJobRecord
from .permissions import can_view_security_center
from .services import backup_center as svc


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


def _days(request, default=30):
    value = request.GET.get("giorni", "")
    allowed = {days for days, _label in svc.PERIODS}
    return int(value) if value.isdigit() and int(value) in allowed else default


def backup_overview(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    days = _days(request)
    data = svc.overview(days)
    query = request.GET.get("q", "").strip()
    devices = data["devices"]
    if query:
        devices = [row for row in devices if query.casefold() in row["name"].casefold() or any(query.casefold() in j.casefold() for j in row["jobs"])]
    return render(request, "security/backup.html", {
        **data,
        "devices": devices,
        "devices_total": len(data["devices"]),
        "periods": svc.PERIODS,
        "query": query,
        "stale_days": svc.stale_days(),
    })


def backup_device(request):
    """Vecchio indirizzo della scheda backup del PC: ora tutto sta nella scheda PC unica."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from urllib.parse import urlencode

    from django.shortcuts import redirect
    from django.urls import reverse

    return redirect(reverse("security:pc_detail") + "?" + urlencode({"nome": request.GET.get("nome", "")}))


def backup_log(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    rows = svc.log_rows(request.GET)
    jobs = BackupJobRecord.objects.order_by().values_list("job_name", flat=True).distinct()
    return render(request, "security/backup_log.html", {
        "rows": rows,
        "jobs": sorted(set(jobs)),
        "filters": {k: request.GET.get(k, "") for k in ("esito", "job", "giorni", "q")},
        "status_choices": [(k, v) for k, v in svc.STATUS_LABELS.items() if k != "unknown"],
        "periods": svc.PERIODS,
    })
