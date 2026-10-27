"""Sezione Backup del SOC: panoramica con KPI, statistiche per PC e per job, log, scheda dispositivo."""
from django.shortcuts import get_object_or_404, render

from .models import BackupJobRecord
from .permissions import can_view_security_center
from .services import backup_center as svc
from .services import veeam_api


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
    solo_ko = request.GET.get("stato") == "ko"
    if solo_ko:
        devices = [row for row in devices if row["stale"] or row["last_status"] == svc.FAIL]
    if query:
        devices = [row for row in devices if query.casefold() in row["name"].casefold() or any(query.casefold() in j.casefold() for j in row["jobs"])]
    return render(request, "security/backup.html", {
        **data,
        "devices": devices,
        "devices_total": len(data["devices"]),
        "periods": svc.PERIODS,
        "query": query,
        "solo_ko": solo_ko,
        "stale_days": svc.stale_days(),
        "veeam": veeam_api.panel(),
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


def backup_ripristini(request):
    """Prove di ripristino (ISO 27001 8.13): registro, nuova prova, stato della cadenza."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from django.contrib import messages
    from django.shortcuts import redirect

    from core.audit import log_action

    from .forms import BackupRestoreTestForm
    from .models import BackupRestoreTest
    from .services import ripristini

    if request.method == "POST":
        form = BackupRestoreTestForm(request.POST, request.FILES)
        if form.is_valid():
            prova = ripristini.registra(request.user, **form.cleaned_data)
            log_action(request, "prova_ripristino", "security", {"sistema": prova.sistema, "esito": prova.esito}, oggetto=prova)
            if prova.esito == BackupRestoreTest.ESITO_KO:
                messages.warning(request, "Prova di ripristino registrata come fallita: è stato aperto un alert del SOC.")
            else:
                messages.success(request, "Prova di ripristino registrata.")
            return redirect("security:backup_ripristini")
    else:
        form = BackupRestoreTestForm(initial={"eseguito_da": request.user.get_full_name() or request.user.username})
    return render(request, "security/backup_ripristini.html", {
        "form": form,
        "stato": ripristini.stato(),
        "prove": BackupRestoreTest.objects.select_related("alert")[:200],
    })


def backup_ripristino_allegato(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    from django.http import FileResponse, Http404

    from .models import BackupRestoreTest

    prova = get_object_or_404(BackupRestoreTest, pk=pk)
    if not prova.allegato:
        raise Http404
    return FileResponse(prova.allegato.open("rb"), as_attachment=True, filename=prova.allegato.name.rsplit("/", 1)[-1])
