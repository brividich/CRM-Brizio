"""Postura di sicurezza e trend della dashboard SOC, calcolati dai dati reali.

Prima la dashboard mostrava punteggi e grafici scritti a mano nel template: una console
di sicurezza che resta «verde» qualunque cosa succeda e' peggio di nessuna console.
Qui ogni indice e' ricavato dai record, con una formula semplice e dichiarata (il
``detail`` finisce nel tooltip), e vale ``None`` («n.d.») quando mancano i dati invece
di inventare un numero rassicurante.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityEventRecord,
    SecurityMailboxMessage,
    SecurityReport,
    SecuritySourceFile,
    SecurityVulnerabilityFinding,
    Severity,
    Status,
)

WINDOW_DAYS = 7

# Alert "in lavorazione": posticipati/silenziati sono una scelta consapevole dell'operatore
# e non abbassano la postura.
PENALIZED_ALERT_STATUSES = [Status.NEW, Status.OPEN, Status.ACKNOWLEDGED, Status.IN_PROGRESS]
OPEN_FINDING_STATUSES = PENALIZED_ALERT_STATUSES

ALERT_PENALTY = {
    Severity.CRITICAL: 30,
    Severity.HIGH: 15,
    Severity.WARNING: 8,
    Severity.MEDIUM: 5,
    Severity.LOW: 2,
}
FINDING_PENALTY = {Severity.CRITICAL: 25, Severity.HIGH: 10, Severity.MEDIUM: 3}
SILENT_SOURCE_PENALTY = 20

SEVERITY_LABELS = {
    Severity.CRITICAL: "critici",
    Severity.HIGH: "alti",
    Severity.WARNING: "attenzione",
    Severity.MEDIUM: "medi",
    Severity.LOW: "bassi",
}


def _clamp(value):
    return max(0, min(100, int(round(value))))


def _grade(score):
    if score is None:
        return "n.d.", "muted"
    if score >= 90:
        return "Ottimo", "success"
    if score >= 75:
        return "Buono", "success"
    if score >= 50:
        return "Attenzione", "warning"
    return "Critico", "danger"


def _indicator(key, label, score, detail):
    grade, tone = _grade(score)
    return {"key": key, "label": label, "score": score, "grade": grade, "tone": tone, "detail": detail}


def _severity_breakdown(counts, penalties):
    parts = [f"{counts[sev]} {SEVERITY_LABELS[sev]}" for sev in penalties if counts.get(sev)]
    return ", ".join(parts)


def alert_indicator():
    rows = (
        SecurityAlert.objects.filter(status__in=PENALIZED_ALERT_STATUSES)
        .order_by()
        .values("severity")
        .annotate(n=Count("id"))
    )
    counts = {row["severity"]: row["n"] for row in rows}
    penalty = sum(ALERT_PENALTY.get(sev, 0) * n for sev, n in counts.items())
    total = sum(counts.values())
    if total:
        detail = f"{total} alert da gestire ({_severity_breakdown(counts, ALERT_PENALTY) or 'solo info'})."
    else:
        detail = "Nessun alert da gestire."
    detail += " 100 meno: critico 30, alto 15, attenzione 8, medio 5, basso 2."
    return _indicator("alerts", "Alert", _clamp(100 - penalty), detail)


def vulnerability_indicator(now):
    findings = SecurityVulnerabilityFinding.objects.filter(status__in=OPEN_FINDING_STATUSES, exposed_devices__gt=0)
    has_data = (
        SecurityVulnerabilityFinding.objects.exists()
        or SecurityReport.objects.filter(
            parser_name__icontains="defender", created_at__gte=now - timedelta(days=30)
        ).exists()
    )
    if not has_data:
        return _indicator("vulnerabilities", "Vulnerabilità", None, "Nessun report vulnerabilità negli ultimi 30 giorni.")
    rows = findings.order_by().values("severity").annotate(n=Count("id"))
    counts = {row["severity"]: row["n"] for row in rows}
    penalty = sum(FINDING_PENALTY.get(sev, 0) * n for sev, n in counts.items())
    breakdown = _severity_breakdown(counts, FINDING_PENALTY)
    detail = f"CVE aperte con dispositivi esposti: {breakdown}." if breakdown else "Nessuna CVE rilevante aperta con dispositivi esposti."
    detail += " 100 meno: critica 25, alta 10, media 3."
    return _indicator("vulnerabilities", "Vulnerabilità", _clamp(100 - penalty), detail)


def backup_indicator(now):
    since = now - timedelta(days=WINDOW_DAYS)
    agg = BackupJobRecord.objects.filter(created_at__gte=since).aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        warning=Count("id", filter=Q(status="warning")),
        failed=Count("id", filter=Q(status="failed")),
    )
    if not agg["total"]:
        return _indicator("backup", "Backup", None, f"Nessun job di backup negli ultimi {WINDOW_DAYS} giorni.")
    score = 100 * (agg["completed"] + 0.5 * agg["warning"]) / agg["total"]
    detail = (
        f"Ultimi {WINDOW_DAYS} giorni: {agg['completed']} completati, {agg['warning']} con avvisi, "
        f"{agg['failed']} falliti su {agg['total']} job (avvisi contano metà)."
    )
    return _indicator("backup", "Backup", _clamp(score), detail)


def ingestion_indicator(now):
    since = now - timedelta(days=WINDOW_DAYS)
    parsed = failed = 0
    for model, date_field in ((SecurityMailboxMessage, "received_at"), (SecuritySourceFile, "uploaded_at")):
        agg = model.objects.filter(**{f"{date_field}__gte": since}).aggregate(
            parsed=Count("id", filter=Q(parse_status=ParseStatus.PARSED)),
            failed=Count("id", filter=Q(parse_status=ParseStatus.FAILED)),
        )
        parsed += agg["parsed"]
        failed += agg["failed"]
    silent = SecurityAlert.objects.filter(
        status__in=PENALIZED_ALERT_STATUSES, event__event_type="source_silent"
    ).count()
    if not (parsed + failed) and not silent:
        return _indicator("ingestion", "Ingestione", None, f"Nessun report ricevuto negli ultimi {WINDOW_DAYS} giorni.")
    base = 100 * parsed / (parsed + failed) if (parsed + failed) else 100
    detail = f"Ultimi {WINDOW_DAYS} giorni: {parsed} report letti, {failed} in errore"
    detail += f"; {silent} sorgenti silenziose (-{SILENT_SOURCE_PENALTY} ciascuna)." if silent else "; nessuna sorgente silenziosa."
    return _indicator("ingestion", "Ingestione", _clamp(base - SILENT_SOURCE_PENALTY * silent), detail)


def build_posture(now=None):
    now = now or timezone.now()
    return [alert_indicator(), vulnerability_indicator(now), backup_indicator(now), ingestion_indicator(now)]


# --- Trend ---------------------------------------------------------------------------

TREND_WIDTH = 640
TREND_HEIGHT = 180
TREND_PAD_X = 28
TREND_PAD_Y = 16

TREND_SERIES = (
    ("events", "Eventi", "var(--primary-mid, #1f4e79)"),
    ("alerts", "Alert creati", "var(--warning, #d4a017)"),
    ("critical", "Alert critici", "var(--danger, #dc2626)"),
)


def build_trend(days=WINDOW_DAYS, today=None):
    """Conteggi giornalieri reali + coordinate SVG pronte per il template."""
    today = today or timezone.localdate()
    dates = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    start = dates[0]

    def per_day(qs, field):
        rows = qs.filter(**{f"{field}__date__gte": start}).order_by().values(f"{field}__date").annotate(n=Count("id"))
        return {row[f"{field}__date"]: row["n"] for row in rows}

    raw = {
        "events": per_day(SecurityEventRecord.objects.filter(suppressed=False), "occurred_at"),
        "alerts": per_day(SecurityAlert.objects.all(), "created_at"),
        "critical": per_day(SecurityAlert.objects.filter(severity=Severity.CRITICAL), "created_at"),
    }
    values = {key: [raw[key].get(day, 0) for day in dates] for key in raw}
    peak = max([1] + [v for series in values.values() for v in series])

    inner_w = TREND_WIDTH - 2 * TREND_PAD_X
    inner_h = TREND_HEIGHT - 2 * TREND_PAD_Y
    step = inner_w / max(1, days - 1)

    def xy(index, value):
        return round(TREND_PAD_X + index * step, 1), round(TREND_PAD_Y + inner_h * (1 - value / peak), 1)

    series = []
    for key, label, color in TREND_SERIES:
        points = [xy(i, v) for i, v in enumerate(values[key])]
        series.append(
            {
                "key": key,
                "label": label,
                "color": color,
                "total": sum(values[key]),
                "points": " ".join(f"{x},{y}" for x, y in points),
                "dots": [{"x": x, "y": y, "value": v, "day": dates[i]} for i, ((x, y), v) in enumerate(zip(points, values[key]))],
            }
        )
    return {
        "width": TREND_WIDTH,
        "height": TREND_HEIGHT,
        "baseline": TREND_HEIGHT - TREND_PAD_Y,
        "top": TREND_PAD_Y,
        "peak": peak,
        "days": [{"date": day, "x": round(TREND_PAD_X + i * step, 1)} for i, day in enumerate(dates)],
        "series": series,
        "is_empty": all(s["total"] == 0 for s in series),
    }
