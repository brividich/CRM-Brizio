"""Dai report ai dispositivi: estrae «chi» e registra cosa dice il report su di lui.

Ogni report cita dispositivi (il computer di un backup Synology, le macchine virtuali di un job
Veeam, i computer con rilevamenti di Endpoint Security). Qui diventano `SecurityAsset` con i
loro `SecurityAssetSignal`. Il collegamento all'asset del registro HUB NON e' automatico: si
propone per nome identico e lo conferma una persona (vedi ``suggest_hub_asset`` / ``link``).
"""
import ipaddress
import logging
import re

from django.utils import timezone

from security.models import SecurityAsset, SecurityAssetSignal
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

_PAREN = re.compile(r"\(([^()]+)\)\s*$")
# Senza \b: nei nomi Veeam l'IP segue un trattino basso («_2_10.0.0.6»), che e' un carattere di parola.
_IP = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def device_identity(raw):
    """Nome host (e IP se c'e') da etichette come «_2_10.0.0.6 (QLIKSENSE-SRV)» o «PCLOGSYS»."""
    text = str(raw or "").strip()
    match = _PAREN.search(text)
    if match:
        name = match.group(1).strip()
        found = _IP.search(text[:match.start()])
        return name[:255], (found.group(0) if found else "")
    return text[:255], (text if _IP.fullmatch(text) else "")


def _valid_ip(value):
    try:
        return str(ipaddress.ip_address(str(value).strip())) if value else None
    except ValueError:
        return None


def get_or_create_asset(source, hostname, ip="", asset_type=""):
    hostname = str(hostname or "").strip()
    if not hostname:
        return None
    asset = SecurityAsset.objects.filter(hostname__iexact=hostname).order_by("id").first()
    if asset:
        if not asset.ip_address and _valid_ip(ip):
            asset.ip_address = _valid_ip(ip)
            asset.save(update_fields=["ip_address", "updated_at"])
        return asset
    return SecurityAsset.objects.create(source=source, hostname=hostname[:255], ip_address=_valid_ip(ip), asset_type=asset_type[:80])


def add_signal(asset, *, kind, status, title, occurred_at, detail, source, report, key):
    digest = make_hash(kind, key)
    if SecurityAssetSignal.objects.filter(asset=asset, dedup_hash=digest).exists():
        return False
    SecurityAssetSignal.objects.create(
        asset=asset, source=source, report=report, kind=kind, status=status[:24], title=title[:255],
        detail=detail, occurred_at=occurred_at or timezone.now(), dedup_hash=digest,
    )
    return True


def _when(value):
    if not value:
        return None
    try:
        parsed = timezone.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed


def record_asset_signals(source, report, parsed):
    """Registra i segnali per dispositivo di un report appena letto. Mai un'eccezione verso il chiamante."""
    created = 0
    try:
        for record in parsed.records:
            if record.record_type == "backup_job":
                created += _from_backup(source, report, record.payload)
        for entry in (parsed.payload or {}).get("records", []) or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "epdr_executive_report":
                created += _from_epdr_report(source, report, entry, parsed.payload)
            elif entry.get("type") == "epdr_threat_alert":
                created += _from_epdr_threat(source, report, entry, parsed.payload)
    except Exception:  # noqa: BLE001 - un segnale mancato non deve far fallire la lettura del report
        logger.exception("Segnali asset non registrati per il report %s", getattr(report, "pk", "?"))
    return created


def _from_backup(source, report, payload):
    job = payload.get("job_name") or "backup"
    occurred = _when(payload.get("end_time")) or _when(payload.get("start_time"))
    created = 0
    if payload.get("vendor") == "veeam":
        targets = [(item.get("name"), item.get("status") or payload.get("status"), {"duration": item.get("duration"), "transferred": item.get("transferred"), "size": item.get("size")}) for item in payload.get("objects") or []]
        asset_type = "vm"
    else:
        targets = [(name, payload.get("status"), {"duration_seconds": payload.get("duration_seconds"), "transferred_gb": payload.get("transferred_size_gb"), "nas": payload.get("nas_name")}) for name in payload.get("devices") or []]
        asset_type = "computer"
    for raw_name, status, extra in targets:
        hostname, ip = device_identity(raw_name)
        asset = get_or_create_asset(source, hostname, ip, asset_type)
        if asset and add_signal(
            asset, kind=SecurityAssetSignal.KIND_BACKUP, status=status or "unknown", title=f"Backup «{job}»",
            occurred_at=occurred, detail={"job": job, **{k: v for k, v in extra.items() if v not in (None, "")}},
            source=source, report=report, key=f"{job}:{payload.get('start_time')}:{hostname.lower()}",
        ):
            created += 1
    return created


def _from_epdr_report(source, report, entry, payload):
    created = 0
    occurred = _when(payload.get("period_end")) or _when(payload.get("period_start"))
    for row in entry.get("top_computers") or []:
        asset = get_or_create_asset(source, row.get("computer"), "", "computer")
        detections = row.get("detections") or 0
        if asset and detections and add_signal(
            asset, kind=SecurityAssetSignal.KIND_DETECTIONS, status="warning", title=f"{detections} rilevamenti Endpoint Security",
            occurred_at=occurred, detail={"detections": detections, "group": row.get("group", "")},
            source=source, report=report, key=f"{payload.get('report_date')}:{str(row.get('computer')).lower()}",
        ):
            created += 1
    return created


def _from_epdr_threat(source, report, entry, payload):
    created = 0
    label = ", ".join(f"{count} {name}" for count, name in entry.get("categories") or []) or "minaccia"
    occurred = _when(payload.get("period_start"))
    for row in entry.get("computers") or []:
        asset = get_or_create_asset(source, row.get("computer"), row.get("ip"), "computer")
        if asset and add_signal(
            asset, kind=SecurityAssetSignal.KIND_THREAT, status="warning", title=f"Endpoint Security: {label}",
            occurred_at=occurred, detail={"group": row.get("group", ""), "ip": row.get("ip", "")},
            source=source, report=report, key=f"{payload.get('period_start')}:{label}:{str(row.get('computer')).lower()}",
        ):
            created += 1
    return created


# ---- collegamento all'asset del registro HUB (conferma manuale) ---------------------------------

def suggest_hub_asset(security_asset):
    """``(asset_hub, motivo)``: propone SOLO il nome identico (senza maiuscole) e univoco."""
    from assets.models import Asset

    matches = list(Asset.objects.filter(name__iexact=security_asset.hostname.strip())[:3])
    if len(matches) == 1:
        return matches[0], "nome identico"
    if len(matches) > 1:
        return None, "piu' asset con lo stesso nome"
    return None, "nessun asset con questo nome"


def link(security_asset, hub_asset, *, actor=None, request=None):
    from security.services.configuration import audit_config_change

    old = security_asset.hub_asset
    security_asset.hub_asset = hub_asset
    security_asset.save(update_fields=["hub_asset", "updated_at"])
    audit_config_change(actor, "asset_link" if hub_asset else "asset_unlink", security_asset, "hub_asset",
                        getattr(old, "asset_tag", "") if old else "", getattr(hub_asset, "asset_tag", "") if hub_asset else "", request=request)


def signals_for_hub_asset(hub_asset, limit=10):
    """Segnali dei dispositivi collegati a un asset HUB, piu' recenti in alto + ultimo backup."""
    qs = SecurityAssetSignal.objects.filter(asset__hub_asset=hub_asset).select_related("asset")
    last_backup = qs.filter(kind=SecurityAssetSignal.KIND_BACKUP).order_by("-occurred_at").first()
    return {"signals": list(qs.order_by("-occurred_at")[:limit]), "last_backup": last_backup, "total": qs.count()}
