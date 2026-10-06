"""Eventi della timeline di vita che arrivano dal monitoraggio (SNMP) e dal SOC.

Come gli altri eventi automatici non sono righe di database: si ricalcolano a
ogni apertura della scheda dai dati gia' raccolti, rispettando i permessi dei
moduli. Niente ticket automatici: la timeline rende visibile il fatto, chi
gestisce l'asset decide cosa farne.
"""
from __future__ import annotations

from django.db import DatabaseError
from django.utils import timezone

from assets.services.it_coverage import SILENT_AFTER, can_view_snmp, can_view_soc

ALERT_SEVERITIES = ("critical", "high")
CRITICAL_CVSS = 9.0
MAX_EVENTS_PER_KIND = 5


def _snmp_events(asset, now) -> list[dict]:
    from contatori.models import DispositivoSNMP, Macchina

    rows = [
        (f"Dispositivo SNMP «{d.nome}»", d.host, d.snmp_stato, d.snmp_ultimo_controllo, d.snmp_ultimo_errore)
        for d in DispositivoSNMP.objects.filter(asset=asset, attivo=True)
    ] + [
        (f"MFC «{m.reparto}»", m.host or "", m.snmp_stato, m.snmp_ultimo_controllo, m.snmp_ultimo_errore)
        for m in Macchina.objects.filter(asset=asset, attiva=True)
    ]
    events = []
    for name, host, state, last, error in rows[:MAX_EVENTS_PER_KIND]:
        if state == "ERROR":
            title = f"{name}: non risponde al monitoraggio"
        elif last is not None and now - last > SILENT_AFTER:
            title = f"{name}: nessun controllo da {(now - last).days} giorni"
        else:
            continue
        events.append({
            "title": title,
            "tag": "MONITORAGGIO",
            "description": (error or "Ultimo controllo SNMP non riuscito.")[:200] if state == "ERROR" else "Il dato mostrato in scheda può essere vecchio.",
            "date": last or now,
            "meta": host or "Centrale SNMP",
            "color": "amber",
        })
    return events


def _soc_events(asset) -> list[dict]:
    from security.models import SecurityAlert, SecurityVulnerabilityFinding
    from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

    events = []
    alerts = (SecurityAlert.objects.filter(event__asset__hub_asset=asset, status__in=ACTIVE_ALERT_STATUSES,
                                           severity__in=ALERT_SEVERITIES)
              .select_related("source").order_by("-created_at")[:MAX_EVENTS_PER_KIND])
    for alert in alerts:
        events.append({
            "title": f"Alert SOC: {alert.title}",
            "tag": "SICUREZZA",
            "description": "Alert aperto con gravità elevata. Dettagli e gestione nel Security Center.",
            "date": alert.created_at,
            "meta": alert.source.name if alert.source_id else "SOC",
            "color": "amber",
        })
    vulns = (SecurityVulnerabilityFinding.objects.filter(asset__hub_asset=asset, status__in=ACTIVE_ALERT_STATUSES,
                                                         cvss__gte=CRITICAL_CVSS)
             .order_by("-cvss", "-first_seen_at")[:MAX_EVENTS_PER_KIND])
    for vuln in vulns:
        events.append({
            "title": f"Vulnerabilità critica {vuln.cve}",
            "tag": "SICUREZZA",
            "description": f"{vuln.affected_product} · CVSS {vuln.cvss:.1f}",
            "date": vuln.first_seen_at,
            "meta": "Vulnerability management",
            "color": "amber",
        })
    return events


def monitoring_timeline_events(request, asset) -> list[dict]:
    now = timezone.now()
    events: list[dict] = []
    try:
        if can_view_snmp(request):
            events += _snmp_events(asset, now)
    except DatabaseError:
        pass
    try:
        if can_view_soc(request):
            events += _soc_events(asset)
    except DatabaseError:
        pass
    return events
