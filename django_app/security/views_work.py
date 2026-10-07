"""Impostazioni avvisi, «Il mio lavoro», ricerca unica e scheda PC del SOC."""
from urllib.parse import quote

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAsset,
    SecurityIncident,
    SecurityNotificationChannel,
    SecurityNotificationLog,
    SecurityRemediationTicket,
    SecurityVulnerabilityFinding,
)
from .permissions import can_view_security_center
from .services import soc_settings
from .services.configuration import can_manage_security_config
from .templatetags.security_i18n import ui_label


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


# --- Impostazioni ----------------------------------------------------------------------

def settings_page(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    can_edit = can_manage_security_config(request.user)
    errors = []
    if request.method == "POST":
        if not can_edit:
            return _denied(request)
        values, errors = soc_settings.parse_post(request.POST)
        if not errors:
            changed = soc_settings.save(values, request.user)
            messages.success(request, f"Impostazioni salvate ({changed} modific{'a' if changed == 1 else 'he'})." if changed else "Nessuna modifica.")
            return redirect("security:soc_settings")
    from .services import proactive_alerts

    preview = {"incidenti": None, "backup": None, "report": None}
    try:
        preview["incidenti"] = len(proactive_alerts.incident_items())
        preview["backup"] = len(proactive_alerts.backup_items())
        preview["report"] = _next_report_date()
    except Exception:  # noqa: BLE001 - l'anteprima non deve impedire di salvare le impostazioni
        pass
    events = [proactive_alerts.EVENT_INCIDENT, proactive_alerts.EVENT_BACKUP, proactive_alerts.EVENT_REPORT]
    return render(request, "security/soc_settings.html", {
        "sections": soc_settings.form_sections(),
        "channels": list(SecurityNotificationChannel.objects.order_by("name")),
        "can_edit": can_edit,
        "errors": errors,
        "preview": preview,
        "recent_logs": SecurityNotificationLog.objects.filter(event_kind__in=events).select_related("channel")[:12],
        "event_labels": {
            proactive_alerts.EVENT_INCIDENT: "Scadenza incidente",
            proactive_alerts.EVENT_BACKUP: "Backup PC",
            proactive_alerts.EVENT_REPORT: "Report periodico",
        },
    })


def _next_report_date():
    from datetime import timedelta

    today = timezone.localdate()
    if soc_settings.value("report.auto.frequenza") == "monthly":
        return (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


@require_POST
def settings_run_now(request):
    if not can_manage_security_config(request.user):
        return _denied(request)
    from .services.proactive_alerts import run_scheduled_notifications

    result = run_scheduled_notifications()
    sent = sum(v for v in result.values() if isinstance(v, int))
    errors = [f"{k}: {v}" for k, v in result.items() if not isinstance(v, int)]
    if errors:
        messages.error(request, "Controllo eseguito con errori: " + "; ".join(errors))
    else:
        messages.success(request, f"Controllo eseguito: {sent} avvis{'o' if sent == 1 else 'i'} inviat{'o' if sent == 1 else 'i'} (quelli già mandati non ripartono).")
    return redirect("security:soc_settings")


# --- Il mio lavoro ---------------------------------------------------------------------

def my_work(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.alert_lifecycle import ACTIVE_ALERT_STATUSES
    from .services.cases import ACTIVE_CASE_STATUSES
    from .services.incidents import ACTIVE_STATUSES, next_open_deadline

    user, now = request.user, timezone.now()
    incidents = list(SecurityIncident.objects.filter(owner=user, status__in=ACTIVE_STATUSES).order_by("detected_at"))
    for incident in incidents:
        incident.next_deadline = next_open_deadline(incident, now)
    incidents.sort(key=lambda i: (i.next_deadline is None, i.next_deadline["due_at"] if i.next_deadline else i.detected_at))
    tickets = list(SecurityRemediationTicket.objects.filter(assignee=user, status__in=ACTIVE_CASE_STATUSES).select_related("source").order_by("-updated_at")[:50])
    alerts = list(SecurityAlert.objects.filter(owner=user.get_username(), status__in=ACTIVE_ALERT_STATUSES).select_related("source").order_by("-updated_at")[:30])
    unassigned = {
        "tickets": SecurityRemediationTicket.objects.filter(assignee__isnull=True, status__in=ACTIVE_CASE_STATUSES).count(),
        "incidents": SecurityIncident.objects.filter(owner__isnull=True, status__in=ACTIVE_STATUSES).count(),
    }
    return render(request, "security/my_work.html", {
        "incidents": incidents, "tickets": tickets, "alerts": alerts, "unassigned": unassigned,
        "total": len(incidents) + len(tickets) + len(alerts),
    })


# --- Ricerca ---------------------------------------------------------------------------

SEARCH_LIMIT = 8


def search(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    query = request.GET.get("q", "").strip()[:100]
    groups = []
    if len(query) >= 2:
        groups = [
            ("Incidenti", [
                {"title": f"{i.code} · {i.title}", "meta": f"{i.get_status_display()} · rilevato {timezone.localtime(i.detected_at):%d/%m/%Y}", "url": f"/soc/incidenti/{i.pk}/"}
                for i in SecurityIncident.objects.filter(Q(code__icontains=query) | Q(title__icontains=query) | Q(csirt_reference__icontains=query)).order_by("-detected_at")[:SEARCH_LIMIT]
            ]),
            ("Ticket", [
                {"title": f"#{t.pk} · {t.title}", "meta": f"{ui_label(t.status)} · {t.source.name}", "url": f"/soc/tickets/{t.pk}/"}
                for t in SecurityRemediationTicket.objects.filter(Q(title__icontains=query) | Q(cve__icontains=query) | Q(affected_product__icontains=query)).select_related("source").order_by("-updated_at")[:SEARCH_LIMIT]
            ]),
            ("Alert", [
                {"title": a.title, "meta": f"{ui_label(a.severity)} · {ui_label(a.status)} · {timezone.localtime(a.created_at):%d/%m/%Y}", "url": f"/soc/alerts/{a.pk}/"}
                for a in SecurityAlert.objects.filter(title__icontains=query).order_by("-updated_at")[:SEARCH_LIMIT]
            ]),
            ("PC e server", [
                {"title": name, "meta": "scheda del dispositivo", "url": f"/soc/pc/?nome={quote(name)}"}
                for name in _device_names(query)
            ]),
            ("Vulnerabilità", [
                {"title": f"{f.cve} · {f.affected_product}", "meta": f"CVSS {f.cvss:.1f} · {f.exposed_devices} dispositivi".replace(".", ","), "url": f"/soc/tickets/?q={quote(f.cve)}"}
                for f in SecurityVulnerabilityFinding.objects.filter(Q(cve__icontains=query) | Q(affected_product__icontains=query)).order_by("-last_seen_at")[:SEARCH_LIMIT]
            ]),
        ]
        groups = [(label, rows) for label, rows in groups if rows]
    return render(request, "security/search.html", {"query": query, "groups": groups, "too_short": 0 < len(query) < 2})


def _device_names(query):
    """Nomi dei PC: dispositivi SOC e PC citati nei backup degli ultimi 90 giorni."""
    from datetime import timedelta

    from .services.backup_center import device_runs

    names = {h.casefold(): h for h in SecurityAsset.objects.filter(hostname__icontains=query).values_list("hostname", flat=True)[:50]}
    since = timezone.now() - timedelta(days=90)
    needle = query.casefold()
    for record in BackupJobRecord.objects.filter(created_at__gte=since).only("payload", "status", "job_name", "completed_at", "started_at", "created_at")[:3000]:
        for run in device_runs(record):
            if needle in run["device"].casefold():
                names.setdefault(run["device"].casefold(), run["device"])
        if len(names) >= SEARCH_LIMIT * 2:
            break
    return sorted(names.values(), key=str.casefold)[:SEARCH_LIMIT]


# --- Scheda PC -------------------------------------------------------------------------

def pc_detail(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.pc_overview import pc_overview

    name = request.GET.get("nome", "").strip()
    if not name:
        raise Http404("Dispositivo non indicato.")
    data = pc_overview(name)
    if data is None:
        raise Http404("Nessun dato SOC per questo dispositivo.")
    return render(request, "security/pc_detail.html", {"pc": data})
