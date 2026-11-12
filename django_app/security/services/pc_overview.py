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
    intune = _intune(name)
    cve_impacts = _cve_impacts(name)
    if backup is None and not assets and intune is None and not cve_impacts and not _in_inventario(name):
        return None
    hub_asset = (next((a.hub_asset for a in assets if a.hub_asset_id), None) or (backup or {}).get("asset")
                 or (intune.asset if intune else None))
    alerts = SecurityAlert.objects.filter(event__asset__in=assets, status__in=ACTIVE_ALERT_STATUSES).select_related("source")
    vulns = SecurityVulnerabilityFinding.objects.filter(asset__in=assets, status__in=ACTIVE_ALERT_STATUSES).select_related("source")
    signals = SecurityAssetSignal.objects.filter(asset__in=assets).exclude(kind=SecurityAssetSignal.KIND_BACKUP).select_related("source")
    events = SecurityEventRecord.objects.filter(asset__in=assets, suppressed=False).select_related("source")
    open_alerts = list(alerts.order_by("-created_at")[:10])
    # Le CVE già elencate dall'inventario non si ripetono tra quelle di Defender.
    gia_viste = {i.cve.cve_id.upper() for i in cve_impacts}
    open_vulns = [v for v in vulns.order_by("-cvss", "-last_seen_at")[:10 + len(gia_viste)] if (v.cve or "").upper() not in gia_viste][:10]
    uniche = cve_uniche(name).get(_norm(name), {"cves": 0, "kev": 0, "gravi": 0})
    endpoint = list(signals.order_by("-occurred_at")[:8])
    status = _overall(backup, open_alerts, open_vulns + [i for i in cve_impacts if i.grave])
    return {
        "name": (backup or {}).get("name") or (assets[0].hostname if assets else (intune.nome if intune else name)),
        "status": status,
        "hub_asset": hub_asset,
        "sources": sorted({a.source.name for a in assets if a.source_id} | ({"Intune"} if intune else set())),
        "ip": next((a.ip_address for a in assets if a.ip_address), ""),
        "asset_type": next((a.asset_type for a in assets if a.asset_type), ""),
        "backup": backup,
        "alerts": open_alerts,
        "alert_count": alerts.count(),
        "vulns": open_vulns,
        "vuln_count": vulns.count(),
        "cve_impacts": cve_impacts[:10],
        "cve_count": len(cve_impacts),
        # Il numero delle vulnerabilità del PC, uguale in scheda, pannello ed elenco Dispositivi.
        "cve_uniche": uniche["cves"],
        "cve_gravi": uniche["gravi"],
        "endpoint": [{"signal": s, "label": SIGNAL_LABELS.get(s.kind, s.kind)} for s in endpoint],
        "events": list(events.order_by("-occurred_at")[:8]),
        "days": days,
        "rete": _rete(name, hub_asset),
    }


def _norm(name):
    from security.services.pc_copertura import norm

    return norm(name)


def cve_uniche(name=None):
    """CVE uniche per PC: {nome normalizzato: {"cves", "kev", "gravi"}}. Unica definizione del numero.

    Una CVE conta una volta per PC anche se la segnalano sia l'inventario software
    (``SecurityCveImpact`` che colpisce) sia Microsoft Defender (vulnerabilità aperta sul
    dispositivo SOC con lo stesso nome). Grave = in CISA KEV o CVSS ≥ 9. Con ``name`` si
    calcola solo quel PC.
    """
    from security.models import SecurityCveImpact

    key = _norm(name) if name is not None else None
    if name is not None and not key:
        return {}
    impacts = SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS)
    findings = SecurityVulnerabilityFinding.objects.filter(status__in=ACTIVE_ALERT_STATUSES, asset__isnull=False).exclude(cve="")
    if key:
        impacts = impacts.filter(host__istartswith=key)
        findings = findings.filter(asset__hostname__istartswith=key)
    per_pc = {}  # host -> {cve: grave}
    kev_ids = set()
    for host, cve_id, kev, cvss in impacts.values_list("host", "cve__cve_id", "cve__kev", "cve__cvss").iterator():
        k = _norm(host)
        if k and (key is None or k == key):
            cve_id = (cve_id or "").upper()
            per_pc.setdefault(k, {})[cve_id] = per_pc.get(k, {}).get(cve_id, False) or bool(kev or (cvss or 0) >= 9)
            if kev:
                kev_ids.add(cve_id)
    da_defender = []
    for host, cve_id, cvss in findings.values_list("asset__hostname", "cve", "cvss").iterator():
        k = _norm(host)
        if k and (key is None or k == key):
            da_defender.append((k, (cve_id or "").upper(), cvss))
    # KEV delle CVE viste solo da Defender: dal catalogo CVE, una query.
    solo_defender = {c for _k, c, _s in da_defender} - kev_ids
    if solo_defender:
        from security.services.kev import kev_tra

        kev_ids |= {c.upper() for c in kev_tra(solo_defender)}
    for k, cve_id, cvss in da_defender:
        cves = per_pc.setdefault(k, {})
        cves[cve_id] = cves.get(cve_id, False) or cve_id in kev_ids or (cvss or 0) >= 9
    return {k: {"cves": len(cves), "kev": sum(1 for c in cves if c in kev_ids), "gravi": sum(1 for g in cves.values() if g)}
            for k, cves in per_pc.items()}


def _rete(name, hub_asset):
    """Indirizzi attivi dal DHCP/DNS di Windows (collegati all'asset o con lo stesso nome host) e porta dello switch."""
    try:
        from django.db.models import Q

        from assets.models import IndirizzoRete
        from assets.services.rete_windows import porta_switch
    except ImportError:  # pragma: no cover
        return []
    corto = (name or "").split(".")[0]
    filtro = Q(nome_dhcp__iexact=corto) | Q(nome_dhcp__istartswith=corto + ".") if corto else Q(pk__in=[])
    if hub_asset is not None:
        filtro |= Q(asset=hub_asset)
    righe = list(IndirizzoRete.objects.filter(filtro).filter(Q(nel_dhcp=True) | Q(nel_dns=True)).order_by("-nel_dhcp", "ip")[:3])
    for r in righe:
        r.switch = porta_switch(r.mac) if r.mac else None
    return righe


def _intune(name):
    from assets.models import DispositivoIntune
    from security.services.pc_copertura import norm

    key = norm(name)
    return next((d for d in DispositivoIntune.objects.filter(presente=True, nome__istartswith=key).select_related("asset") if norm(d.nome) == key), None) if key else None


def _in_inventario(name):
    from security.models import SoftwareInstallation
    from security.services.pc_copertura import norm

    key = norm(name)
    return bool(key) and any(norm(h) == key for h in SoftwareInstallation.objects.filter(still_detected=True, host__istartswith=key).values_list("host", flat=True)[:50])


def _cve_impacts(name):
    """CVE che colpiscono il PC secondo l'inventario software (stesso esito della pagina Vulnerabilità)."""
    from security.models import SecurityCveImpact
    from security.services.pc_copertura import norm

    key = norm(name)
    if not key:
        return []
    impacts = [
        i for i in SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS, host__istartswith=key).select_related("cve", "installation")
        if norm(i.host) == key
    ]
    seen, out = set(), []
    for i in sorted(impacts, key=lambda i: (not i.cve.kev, -(i.cve.cvss or 0), i.cve.cve_id)):
        if i.cve_id in seen:
            continue
        seen.add(i.cve_id)
        i.grave = bool(i.cve.kev or (i.cve.cvss or 0) >= 9)
        i.severity = "critical" if i.grave else "high"
        out.append(i)
    return out


def _overall(backup, alerts, vulns):
    """Verdetto in testa alla scheda: il problema più serio vince."""
    if any(a.severity == "critical" for a in alerts) or (backup and backup["last_status"] == "failed"):
        return ("critical", "Da gestire subito")
    if alerts or any(v.severity in ("critical", "high") for v in vulns) or (backup and backup["stale"]):
        return ("warning", "Da controllare")
    if backup is None:
        return ("muted", "Nessun backup registrato")
    return ("success", "In regola")
