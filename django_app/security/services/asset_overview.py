"""Bounded, read-only SOC projection. Caller must enforce SOC permission."""
from django.db.models import Case, IntegerField, Value, When

from security.models import SecurityAlert, SecurityAssetSignal, Severity
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

BACKUP_SAMPLE_LIMIT = 200


def overview_for_hub_asset(asset):
    signals = SecurityAssetSignal.objects.filter(asset__hub_asset=asset).select_related("asset", "source")
    recent = list(signals.order_by("-occurred_at", "-id")[:10])
    backups = list(signals.filter(kind=SecurityAssetSignal.KIND_BACKUP).order_by("-occurred_at", "-id")[:BACKUP_SAMPLE_LIMIT + 1])
    sample_limited = len(backups) > BACKUP_SAMPLE_LIMIT
    groups = {}
    for signal in backups[:BACKUP_SAMPLE_LIMIT]:
        detail = signal.detail if isinstance(signal.detail, dict) else {}
        job = str(detail.get("job") or "Job non identificato")
        # Sources and device identities remain distinct, even if names coincide.
        # Missing job names must not silently merge unrelated backup runs.
        key = (signal.source_id, signal.asset_id, job, signal.pk if not detail.get("job") else None)
        row = groups.setdefault(key, {"job": job, "latest": signal, "success": None})
        if row["success"] is None and signal.status == "completed":
            row["success"] = signal
    alerts = SecurityAlert.objects.filter(
        event__asset__hub_asset=asset, status__in=ACTIVE_ALERT_STATUSES,
    )
    ordered_alerts = alerts.annotate(priority=Case(
        When(severity=Severity.CRITICAL, then=Value(0)),
        When(severity=Severity.HIGH, then=Value(1)),
        When(severity=Severity.MEDIUM, then=Value(2)),
        When(severity=Severity.WARNING, then=Value(3)),
        default=Value(4), output_field=IntegerField(),
    )).select_related("source").order_by("priority", "-created_at", "-id")
    return {
        "signals": recent,
        "last_signal": recent[0] if recent else None,
        "backup_rows": list(groups.values())[:12],
        "backup_attention_count": sum(row["latest"].status in ("failed", "warning") for row in groups.values()),
        "backup_sample_limited": sample_limited,
        "backup_jobs_limited": len(groups) > 12,
        "backup_sample_size": min(len(backups), BACKUP_SAMPLE_LIMIT),
        "open_alert_count": alerts.count(),
        "open_alerts": list(ordered_alerts[:5]),
    }
