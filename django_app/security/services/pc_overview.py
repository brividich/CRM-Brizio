"""Scheda unica di un PC o server: tutto quello che il SOC sa di quel nome host.

Fonti: backup (``backup_center``), dispositivi SOC con lo stesso nome host
(``SecurityAsset``: segnali endpoint, vulnerabilità, eventi, alert) e l'asset HUB
collegato. Il nome è l'unica chiave comune ai fornitori: il confronto ignora maiuscole.
Sola lettura, a numero di query limitato.
"""
from __future__ import annotations

from security.models import (
    SecurityAlert,
    SecurityAsset,
    SecurityAssetSignal,
    SecurityEventRecord,
    SecurityVulnerabilityFinding,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

SIGNAL_LABELS = {
    SecurityAssetSignal.KIND_BACKUP: "Backup",
    SecurityAssetSignal.KIND_DETECTIONS: "Rilevamenti endpoint",
    SecurityAssetSignal.KIND_THREAT: "Minaccia endpoint",
}


def pc_overview(name, days=90):
    from security.services.backup_center import device_detail

    backup = device_detail(name, days)
    assets = list(SecurityAsset.objects.filter(hostname__iexact=name).select_related("source", "hub_asset"))
    if backup is None and not assets:
        return None
    hub_asset = next((a.hub_asset for a in assets if a.hub_asset_id), None) or (backup or {}).get("asset")
    alerts = SecurityAlert.objects.filter(event__asset__in=assets, status__in=ACTIVE_ALERT_STATUSES).select_related("source")
    vulns = SecurityVulnerabilityFinding.objects.filter(asset__in=assets, status__in=ACTIVE_ALERT_STATUSES).select_related("source")
    signals = SecurityAssetSignal.objects.filter(asset__in=assets).exclude(kind=SecurityAssetSignal.KIND_BACKUP).select_related("source")
    events = SecurityEventRecord.objects.filter(asset__in=assets, suppressed=False).select_related("source")
    open_alerts = list(alerts.order_by("-created_at")[:10])
    open_vulns = list(vulns.order_by("-cvss", "-last_seen_at")[:10])
    endpoint = list(signals.order_by("-occurred_at")[:8])
    status = _overall(backup, open_alerts, open_vulns)
    return {
        "name": (backup or {}).get("name") or assets[0].hostname,
        "status": status,
        "hub_asset": hub_asset,
        "sources": sorted({a.source.name for a in assets if a.source_id}),
        "ip": next((a.ip_address for a in assets if a.ip_address), ""),
        "asset_type": next((a.asset_type for a in assets if a.asset_type), ""),
        "backup": backup,
        "alerts": open_alerts,
        "alert_count": alerts.count(),
        "vulns": open_vulns,
        "vuln_count": vulns.count(),
        "endpoint": [{"signal": s, "label": SIGNAL_LABELS.get(s.kind, s.kind)} for s in endpoint],
        "events": list(events.order_by("-occurred_at")[:8]),
        "days": days,
    }


def _overall(backup, alerts, vulns):
    """Verdetto in testa alla scheda: il problema più serio vince."""
    if any(a.severity == "critical" for a in alerts) or (backup and backup["last_status"] == "failed"):
        return ("critical", "Da gestire subito")
    if alerts or any(v.severity in ("critical", "high") for v in vulns) or (backup and backup["stale"]):
        return ("warning", "Da controllare")
    if backup is None:
        return ("muted", "Nessun backup registrato")
    return ("success", "In regola")
