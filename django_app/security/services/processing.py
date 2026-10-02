"""«Stato elaborazione»: cosa fa da solo il Security Center, quando l'ha fatto l'ultima volta, cosa e' fermo.

La vecchia pagina Pipeline mostrava quattro pulsanti («Esegui parser», «Valuta regole»...) senza dire
che tutto questo gira gia' da solo ogni 15 minuti (schedule `security_cycle`): non si capiva a cosa
servisse. Qui la stessa catena e' descritta per passi, con lo stato reale di ciascuno.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from security.models import (
    ParseStatus, SecurityAlert, SecurityEventRecord, SecurityKpiSnapshot, SecurityMailboxIngestionRun, SecurityMailboxMessage,
    SecurityMailboxSource, SecurityReport, SecuritySourceFile,
)

CYCLE_NAME = "security_cycle"
CYCLE_MINUTES = 15


def _schedule():
    """Lo schedule django-q del ciclo, se registrato (None se assente o django-q non disponibile)."""
    try:
        from django_q.models import Schedule

        return Schedule.objects.filter(name=CYCLE_NAME).first()
    except Exception:  # noqa: BLE001 - pagina di stato: mai un errore per questo
        return None


def processing_status(now=None, window_days=7):
    now = now or timezone.now()
    day_ago = now - timedelta(hours=24)
    since = now - timedelta(days=window_days)
    schedule = _schedule()
    last_run = SecurityMailboxIngestionRun.objects.exclude(finished_at=None).order_by("-finished_at").select_related("source").first()
    mailboxes = SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual").count()

    counts = {"pending": 0, "failed": 0, "skipped": 0, "parsed_24h": 0}
    for model, date_field in ((SecurityMailboxMessage, "received_at"), (SecuritySourceFile, "uploaded_at")):
        agg = model.objects.aggregate(
            pending=Count("id", filter=Q(parse_status=ParseStatus.PENDING)),
            failed=Count("id", filter=Q(parse_status=ParseStatus.FAILED, **{f"{date_field}__gte": since})),
            skipped=Count("id", filter=Q(parse_status=ParseStatus.SKIPPED, **{f"{date_field}__gte": since})),
        )
        for key in ("pending", "failed", "skipped"):
            counts[key] += agg[key] or 0
    reports_24h = SecurityReport.objects.filter(created_at__gte=day_ago).count()
    last_report = SecurityReport.objects.order_by("-created_at").first()
    events_24h = SecurityEventRecord.objects.filter(created_at__gte=day_ago).count()
    unevaluated = SecurityEventRecord.objects.filter(decision_trace={}).count()
    alerts_24h = SecurityAlert.objects.filter(created_at__gte=day_ago).count()
    last_kpi = SecurityKpiSnapshot.objects.order_by("-created_at").first()

    def tone(ok, warn=False):
        return "ok" if ok else ("warning" if warn else "high")

    stale = last_run is None or last_run.finished_at < now - timedelta(minutes=CYCLE_MINUTES * 3)
    steps = [
        {
            "n": 1, "title": "Lettura delle caselle", "what": f"Legge le mail nuove delle caselle attive ({mailboxes}) e ne salva testo e allegati, ZIP compresi.",
            "when": last_run.finished_at if last_run else None,
            "detail": (f"{last_run.source.name}: {last_run.imported_messages_count} nuove, {last_run.duplicate_messages_count} già presenti" if last_run else "Mai eseguita"),
            "tone": tone(bool(last_run) and not stale and last_run.status != "failed", warn=bool(last_run) and last_run.status != "failed"),
            "problem": ("Lettura fallita: " + last_run.error_message[:160]) if last_run and last_run.status == "failed" else (
                "Nessuna lettura negli ultimi 45 minuti: lo schedule automatico potrebbe essere fermo." if stale else ""),
        },
        {
            "n": 2, "title": "Riconoscimento dei report", "what": "Ogni mail o allegato passa dai parser (WatchGuard, Synology, Veeam, Defender): quelli riconosciuti diventano report con metriche.",
            "when": last_report.created_at if last_report else None,
            "detail": f"{reports_24h} report nelle ultime 24 ore · {counts['pending']} in coda · {counts['skipped']} non pertinenti ({window_days} gg)",
            "tone": tone(not counts["failed"], warn=counts["failed"] < 5),
            "problem": f"{counts['failed']} elementi in errore negli ultimi {window_days} giorni (vedi sotto)." if counts["failed"] else "",
        },
        {
            "n": 3, "title": "Regole e alert", "what": "Le regole confrontano gli eventi con le soglie: se scattano nasce un alert (deduplicato) ed eventualmente un ticket.",
            "when": None,
            "detail": f"{events_24h} eventi e {alerts_24h} alert nelle ultime 24 ore",
            "tone": tone(not unevaluated, warn=True),
            "problem": f"{unevaluated} eventi non ancora valutati: verranno valutati al prossimo ciclo." if unevaluated else "",
        },
        {
            "n": 4, "title": "KPI", "what": "Calcola gli indicatori del giorno (backup, VPN, firewall, endpoint) mostrati nella pagina KPI.",
            "when": last_kpi.created_at if last_kpi else None,
            "detail": f"ultimo giorno calcolato: {last_kpi.snapshot_date:%d/%m/%Y}" if last_kpi else "Mai calcolati",
            "tone": tone(bool(last_kpi), warn=True),
            "problem": "",
        },
    ]
    failed_items = _failed_items(since)
    return {
        "steps": steps,
        "schedule": {"registered": schedule is not None, "next_run": getattr(schedule, "next_run", None), "minutes": CYCLE_MINUTES},
        "failed_items": failed_items,
        "recent_reports": list(SecurityReport.objects.select_related("source").order_by("-created_at")[:12]),
        "window_days": window_days,
        "counts": counts,
    }


def _failed_items(since, limit=15):
    rows = []
    for message in SecurityMailboxMessage.objects.filter(parse_status=ParseStatus.FAILED, received_at__gte=since).order_by("-received_at")[:limit]:
        rows.append({"kind": "Mail", "when": message.received_at, "name": message.subject, "parser": (message.raw_payload or {}).get("parser_name", ""),
                     "error": (message.raw_payload or {}).get("parser_error", "") or "Errore nella pipeline"})
    for item in SecuritySourceFile.objects.filter(parse_status=ParseStatus.FAILED, uploaded_at__gte=since).order_by("-uploaded_at")[:limit]:
        rows.append({"kind": "Allegato", "when": item.uploaded_at, "name": item.original_name, "parser": (item.raw_payload or {}).get("parser_name", ""),
                     "error": (item.raw_payload or {}).get("parser_error", "") or "Errore nella pipeline"})
    return sorted(rows, key=lambda r: r["when"], reverse=True)[:limit]
