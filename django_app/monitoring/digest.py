"""Digest 'stato portale': riassunto sintetico (servizi, AI, automazioni, issue)
costruito una volta e reso sia su stdout (comando) sia via email (task schedulato).
Read-only, riusa le stesse fonti della pagina Stato sistema."""
from __future__ import annotations

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from .health import STATUS_FAIL, STATUS_WARN, run_readyz_checks
from .models import AutomationExecution, Issue
from .services import OPEN_ISSUE_STATUSES, detect_missed_jobs


def build_system_digest() -> dict:
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    open_filter = Q(status__in=OPEN_ISSUE_STATUSES)

    readyz = run_readyz_checks()
    services_bad = [c.name for c in readyz.checks if c.status in (STATUS_FAIL, STATUS_WARN)]
    severity = {
        # .order_by() azzera il Meta.ordering del modello: senza, su SQL Server il
        # GROUP BY implicito da values()/annotate() include last_seen_at nell'ORDER
        # BY e fallisce (8127). SQLite lo tollera, MSSQL no.
        row["severity"]: row["total"]
        for row in Issue.objects.filter(open_filter).values("severity").annotate(total=Count("id")).order_by()
    }
    ai_issues = list(
        Issue.objects.filter(open_filter, source=Issue.Source.SYSTEM_WATCHDOG,
                             current_url__startswith="check:ai_").values_list("title", flat=True)
    )
    job_failed_today = AutomationExecution.objects.filter(
        status=AutomationExecution.Status.FAILED, started_at__gte=today_start).count()
    job_missing = len(detect_missed_jobs(now=now, create_issues=False))
    crit_high = (severity.get(Issue.Severity.CRITICAL, 0) + severity.get(Issue.Severity.HIGH, 0))

    all_green = (
        readyz.status == "ok" and not ai_issues and job_failed_today == 0
        and job_missing == 0 and crit_high == 0
    )
    return {
        "generated_at": now,
        "readyz_status": readyz.status,
        "services_bad": services_bad,
        "ai_ok": not ai_issues,
        "ai_issues": ai_issues,
        "severity": severity,
        "open_total": Issue.objects.filter(open_filter).count(),
        "job_failed_today": job_failed_today,
        "job_missing": job_missing,
        "all_green": all_green,
    }


def render_system_digest(digest: dict) -> tuple[str, str]:
    env = getattr(settings, "MONITORING_ENVIRONMENT", "") or ""
    head = "tutto ok" if digest["all_green"] else "attenzioni presenti"
    subject = f"[Portale] Digest stato sistema — {head}" + (f" — {env}" if env else "")
    sev = digest["severity"]
    lines = [
        f"Stato portale al {timezone.localtime(digest['generated_at']):%d-%m-%Y %H:%M}",
        "",
        f"Servizi (readiness): {digest['readyz_status'].upper()}"
        + (f" — degradati: {', '.join(digest['services_bad'])}" if digest["services_bad"] else ""),
        f"Assistente AI: {'OPERATIVO' if digest['ai_ok'] else 'DEGRADATO'}"
        + ("" if digest["ai_ok"] else " — " + "; ".join(digest["ai_issues"])),
        f"Automazioni: job falliti oggi={digest['job_failed_today']}, non eseguiti nei tempi={digest['job_missing']}",
        "",
        "Issue aperte: "
        f"critiche={sev.get('critical', 0)}, alte={sev.get('high', 0)}, "
        f"medie={sev.get('medium', 0)}, basse={sev.get('low', 0)} "
        f"(totale {digest['open_total']})",
        "",
        "Dettaglio nella centrale di comando: pagina «Stato sistema» del monitoring.",
    ]
    return subject, "\n".join(lines)
