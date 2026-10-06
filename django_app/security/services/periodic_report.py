"""Report periodico del Security Center (settimana, mese, intervallo libero).

Un solo dizionario alimenta sia la pagina sia il PDF: quello che si vede è quello che si
scarica. Solo numeri e titoli: niente corpi di mail, niente nomi utente VPN (il report va
alla direzione e agli audit, non serve sapere chi si è collegato).
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityIncident,
    SecurityMailboxMessage,
    SecurityRemediationTicket,
    SecurityReport,
    SecuritySourceFile,
    SecurityVpnAccess,
    SecurityVulnerabilityFinding,
    Severity,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.posture import OPEN_FINDING_STATUSES

SEVERITY_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.WARNING, Severity.MEDIUM, Severity.LOW, Severity.INFO]
SEVERITY_LABELS = {
    Severity.CRITICAL: "Critica",
    Severity.HIGH: "Alta",
    Severity.WARNING: "Attenzione",
    Severity.MEDIUM: "Media",
    Severity.LOW: "Bassa",
    Severity.INFO: "Info",
}
ACTIVE_TICKET_STATUSES = ["new", "open", "in_progress"]
CLOSED_TICKET_STATUSES = ["resolved", "closed", "false_positive"]
MAX_PERIOD_DAYS = 366

PRESETS = [
    ("last_week", "Settimana scorsa"),
    ("last_month", "Mese scorso"),
    ("last_30", "Ultimi 30 giorni"),
    ("this_month", "Mese corrente"),
    ("custom", "Intervallo libero"),
]


def resolve_period(preset="last_week", start=None, end=None, today=None):
    """``(inizio, fine, etichetta)`` con date incluse. Intervalli invertiti o oltre un anno
    vengono corretti invece di dare errore."""
    today = today or timezone.localdate()
    if preset == "custom" and start and end:
        if start > end:
            start, end = end, start
        if (end - start).days > MAX_PERIOD_DAYS:
            start = end - timedelta(days=MAX_PERIOD_DAYS)
        return start, end, f"dal {start:%d/%m/%Y} al {end:%d/%m/%Y}"
    if preset == "last_month":
        first_this = today.replace(day=1)
        end = first_this - timedelta(days=1)
        start = end.replace(day=1)
        return start, end, f"{_MONTHS[end.month - 1]} {end.year}"
    if preset == "this_month":
        start = today.replace(day=1)
        return start, today, f"{_MONTHS[today.month - 1]} {today.year} (fino a oggi)"
    if preset == "last_30":
        return today - timedelta(days=29), today, "ultimi 30 giorni"
    # Settimana scorsa: da lunedì a domenica.
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(days=7)
    end = start + timedelta(days=6)
    return start, end, f"settimana dal {start:%d/%m} al {end:%d/%m/%Y}"


_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"]


def _bounds(start: date, end: date):
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz),
    )


def _by_severity(queryset):
    rows = queryset.order_by().values("severity").annotate(n=Count("id"))
    counts = {row["severity"]: row["n"] for row in rows}
    return [
        {"key": sev, "label": SEVERITY_LABELS[sev], "count": counts.get(sev, 0)}
        for sev in SEVERITY_ORDER
        if counts.get(sev)
    ]


def _hours(delta):
    return round(delta.total_seconds() / 3600, 1)


def _alerts_section(since, until):
    created = SecurityAlert.objects.filter(created_at__gte=since, created_at__lt=until)
    closed = SecurityAlert.objects.filter(closed_at__gte=since, closed_at__lt=until).exclude(closed_at=None)
    durations = [alert.closed_at - alert.created_at for alert in closed.only("created_at", "closed_at") if alert.closed_at >= alert.created_at]
    top = (
        created.order_by().values("title").annotate(n=Count("id")).order_by("-n", "title")[:10]
    )
    return {
        "created": created.count(),
        "closed": closed.count(),
        "open_now": SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES).count(),
        "by_severity": _by_severity(created),
        "mean_hours_to_close": _hours(sum(durations, timedelta()) / len(durations)) if durations else None,
        "top_titles": [{"title": row["title"], "count": row["n"]} for row in top],
    }


def _backup_section(since, until):
    jobs = BackupJobRecord.objects.filter(
        Q(completed_at__gte=since, completed_at__lt=until)
        | Q(completed_at__isnull=True, created_at__gte=since, created_at__lt=until)
    )
    counts = Counter(jobs.values_list("status", flat=True))
    total = sum(counts.values())
    failed = [
        {
            "job": job.job_name,
            "device": (job.payload or {}).get("device_name", ""),
            "status": job.status,
            "when": job.completed_at or job.started_at or job.created_at,
        }
        for job in jobs.filter(status__in=["failed", "warning"]).order_by("-completed_at", "-created_at")[:15]
    ]
    return {
        "total": total,
        "completed": counts.get("completed", 0),
        "warning": counts.get("warning", 0),
        "failed": counts.get("failed", 0),
        "success_rate": round(100 * counts.get("completed", 0) / total, 1) if total else None,
        "problems": failed,
    }


def _vulnerability_section(since, until):
    open_findings = SecurityVulnerabilityFinding.objects.filter(status__in=OPEN_FINDING_STATUSES, exposed_devices__gt=0)
    new_findings = SecurityVulnerabilityFinding.objects.filter(first_seen_at__gte=since, first_seen_at__lt=until)
    top = open_findings.filter(severity__in=[Severity.CRITICAL, Severity.HIGH]).order_by("-cvss", "-exposed_devices")[:10]
    return {
        "open_now": open_findings.count(),
        "open_by_severity": _by_severity(open_findings),
        "new_in_period": new_findings.count(),
        "top": [
            {"cve": f.cve, "product": f.affected_product, "cvss": f.cvss, "devices": f.exposed_devices, "severity": f.severity}
            for f in top
        ],
    }


def _vpn_section(since, until):
    accesses = SecurityVpnAccess.objects.filter(login_at__gte=since, login_at__lt=until).filter(Q(kind="vpn") | Q(kind=""))
    agg = accesses.aggregate(
        allowed=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_ALLOWED)),
        denied=Count("id", filter=Q(action=SecurityVpnAccess.ACTION_DENIED)),
    )
    users = accesses.filter(action=SecurityVpnAccess.ACTION_ALLOWED).exclude(username="").values("username").distinct().count()
    return {"allowed": agg["allowed"], "denied": agg["denied"], "distinct_users": users}


def _tickets_section(since, until):
    return {
        "opened": SecurityRemediationTicket.objects.filter(created_at__gte=since, created_at__lt=until).count(),
        "closed": SecurityRemediationTicket.objects.filter(closed_at__gte=since, closed_at__lt=until).count(),
        "open_now": SecurityRemediationTicket.objects.filter(status__in=ACTIVE_TICKET_STATUSES).count(),
    }


def _incidents_section(since, until, now):
    from security.services.incidents import deadlines

    rows = []
    for incident in SecurityIncident.objects.filter(detected_at__gte=since, detected_at__lt=until).order_by("detected_at"):
        items = deadlines(incident, now)
        rows.append({
            "code": incident.code,
            "title": incident.title,
            "status": incident.get_status_display(),
            "detected_at": incident.detected_at,
            "significant": incident.is_significant,
            "personal_data": incident.personal_data_breach,
            "late": sum(1 for d in items if d["state"] in {"late", "overdue"}),
        })
    return {
        "total": len(rows),
        "significant": sum(1 for r in rows if r["significant"]),
        "personal_data": sum(1 for r in rows if r["personal_data"]),
        "rows": rows,
    }


def _ingestion_section(since, until):
    reports = SecurityReport.objects.filter(created_at__gte=since, created_at__lt=until)
    by_source = reports.order_by().values("source__name").annotate(n=Count("id")).order_by("-n")
    failed = (
        SecurityMailboxMessage.objects.filter(received_at__gte=since, received_at__lt=until, parse_status=ParseStatus.FAILED).count()
        + SecuritySourceFile.objects.filter(uploaded_at__gte=since, uploaded_at__lt=until, parse_status=ParseStatus.FAILED).count()
    )
    return {
        "reports": reports.count(),
        "failed": failed,
        "by_source": [{"source": row["source__name"], "count": row["n"]} for row in by_source[:12]],
    }


def build_report(start: date, end: date, label: str = "", now=None):
    from security.services.posture import build_posture

    now = now or timezone.now()
    since, until = _bounds(start, end)
    return {
        "start": start,
        "end": end,
        "label": label or f"dal {start:%d/%m/%Y} al {end:%d/%m/%Y}",
        "generated_at": now,
        "days": (end - start).days + 1,
        "posture": build_posture(now),
        "alerts": _alerts_section(since, until),
        "backup": _backup_section(since, until),
        "vulnerabilities": _vulnerability_section(since, until),
        "vpn": _vpn_section(since, until),
        "tickets": _tickets_section(since, until),
        "incidents": _incidents_section(since, until, now),
        "ingestion": _ingestion_section(since, until),
    }


def parse_date(value):
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None

