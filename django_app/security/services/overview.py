"""Panoramica IT: tutto quello che arriva al Security Center, in una pagina che si legge in un minuto.

Ispirazione (Microsoft Defender «Home», Wazuh, WatchGuard Cloud): in alto UN elenco di cose da fare
ordinate per gravita' («Da guardare adesso»), sotto un riquadro per area con stato, pochi numeri e
quanto sono freschi i dati. Il dettaglio sta un clic piu' in la' (KPI, alert, accessi VPN, backup).
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from security.models import BackupJobRecord, SecurityAlert, SecurityReport, SecurityVulnerabilityFinding, Severity
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

LEVELS = {"critical": 0, "high": 1, "warning": 2, "info": 3}
LEVEL_LABELS = {"critical": "Critico", "high": "Alto", "warning": "Attenzione", "info": "Info"}

# Area -> (titolo, tipi di report che la alimentano, metriche chiave (nome, etichetta breve), pagina)
AREAS = [
    ("firewall", "Firewall", ("watchguard_dimension_executive_summary", "watchguard_executive_dashboard", "watchguard_zero_day_apt_summary",
                              "watchguard_sdwan_status", "watchguard_interface_summary"),
     (("watchguard_botnet_blocked_count", "botnet bloccate"), ("watchguard_ips_prevented_count", "intrusioni bloccate"),
      ("watchguard_malware_detected_count", "malware bloccati"))),
    ("endpoint", "Computer (Endpoint Security)", ("watchguard_epdr_executive_report", "watchguard_epdr_threat_alert"),
     (("watchguard_epdr_protected_endpoints", "protetti"), ("watchguard_epdr_unprotected_endpoints", "senza protezione"),
      ("watchguard_epdr_outdated_agents", "protezione non aggiornata"))),
    ("backup", "Backup", ("synology_active_backup", "veeam_backup_job"),
     (("backup_completed_count", "riusciti"), ("backup_failed_count", "falliti"), ("backup_transferred_total_gb", "GB salvati"))),
    ("vpn", "Accessi VPN", ("watchguard_firebox_authentication_allowed", "watchguard_firebox_authentication_denied"),
     (("vpn_access_allowed", "accessi"), ("vpn_access_denied", "negati"), ("vpn_unique_users", "utenti"))),
    ("vulns", "Vulnerabilità", ("defender_vulnerability_notification",),
     (("defender_vulnerability_critical_count", "critiche"), ("defender_exposed_devices_total", "dispositivi esposti"),
      ("defender_unique_cves", "CVE distinte"))),
]


AREA_OF_ITEM = {"Computer": "endpoint", "Backup": "backup", "Accessi VPN": "vpn", "Vulnerabilità": "vulns"}


def _item(level, area, title, detail="", url="", code=None):
    return {"level": level, "level_label": LEVEL_LABELS[level], "area": area, "title": title, "detail": detail, "url": url,
            "code": code or AREA_OF_ITEM.get(area)}


def _latest_metrics(report_types, max_age_days=10):
    report = SecurityReport.objects.filter(report_type__in=report_types, report_date__gte=timezone.localdate() - timedelta(days=max_age_days)) \
        .order_by("-report_date", "-created_at").first()
    if not report:
        return None, {}
    return report, {m.name: m.value for m in report.metrics.all()}


def attention_items(now=None):
    """Cose da guardare adesso, dalla piu' grave. Ogni voce ha un link al dettaglio."""
    now = now or timezone.now()
    items = []
    alerts = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, severity__in=[Severity.CRITICAL, Severity.HIGH]).select_related("source").order_by("-updated_at")
    for alert in alerts[:5]:
        items.append(_item("critical" if alert.severity == Severity.CRITICAL else "high", "Alert", alert.title,
                           f"aperto dal {alert.created_at:%d/%m %H:%M}", reverse("security:alert_detail", args=[alert.pk])))
    extra = alerts.count() - 5
    if extra > 0:
        items.append(_item("high", "Alert", f"Altri {extra} alert critici o alti aperti", "", reverse("security:alerts_list") + "?status=active"))

    # Conta la data del job, non quella di importazione: «Importa storico» porta dentro anche fallimenti vecchi.
    # Un solo punto per job (l'ultimo fallimento): tre notti fallite dello stesso job sono un problema, non tre.
    cutoff = now - timedelta(hours=48)
    failed, seen = [], set()
    for job in BackupJobRecord.objects.filter(status="failed").order_by("-started_at", "-created_at")[:50]:
        when = job.started_at or job.created_at
        if when >= cutoff and job.job_name not in seen:
            seen.add(job.job_name)
            failed.append(job)
    for job in failed[:3]:
        items.append(_item("high", "Backup", f"Backup fallito: {job.job_name}", f"{job.started_at:%d/%m %H:%M}" if job.started_at else "",
                           reverse("security:kpi_detail", args=["backup_failed_count"])))
    try:
        from security.services.backup_monitoring import missing_backup_candidates

        for missing in missing_backup_candidates()[:3]:
            items.append(_item("high", "Backup", f"Backup atteso non arrivato: {missing['job_name']}", "", reverse("security:admin_config_backups")))
    except Exception:  # noqa: BLE001 - un controllo che fallisce non blocca la panoramica
        pass

    _report, epdr = _latest_metrics(("watchguard_epdr_executive_report",))
    if epdr.get("watchguard_epdr_unprotected_endpoints"):
        items.append(_item("high", "Computer", f"{int(epdr['watchguard_epdr_unprotected_endpoints'])} computer senza protezione attiva",
                           "senza licenza o con protezione in errore", reverse("security:kpi_detail", args=["watchguard_epdr_unprotected_endpoints"])))
    if epdr.get("watchguard_epdr_unmanaged_computers"):
        items.append(_item("warning", "Computer", f"{int(epdr['watchguard_epdr_unmanaged_computers'])} computer in rete non gestiti",
                           "senza agente Endpoint Security", reverse("security:kpi_detail", args=["watchguard_epdr_unmanaged_computers"])))
    if epdr.get("watchguard_epdr_outdated_agents"):
        items.append(_item("warning", "Computer", f"{int(epdr['watchguard_epdr_outdated_agents'])} computer con protezione non aggiornata", "",
                           reverse("security:kpi_detail", args=["watchguard_epdr_outdated_agents"])))
    for name, label in (("watchguard_epdr_license_days_left", "Endpoint Security"),):
        days = epdr.get(name)
        if days is not None and days <= 60:
            items.append(_item("high" if days <= 15 else "warning", "Licenze", f"Licenza {label} in scadenza tra {int(days)} giorni", "", code="endpoint"))
    _report, firewall = _latest_metrics(("watchguard_dimension_executive_summary",))
    days = firewall.get("watchguard_license_days_left")
    if days is not None and days <= 60:
        items.append(_item("high" if days <= 15 else "warning", "Licenze", f"Licenza firewall in scadenza tra {int(days)} giorni", "", code="firewall"))

    try:
        from security.models import SecurityVpnAccess
        from security.services.vpn_history import vpn_findings

        week = SecurityVpnAccess.objects.filter(kind="vpn", login_at__gte=now - timedelta(days=7))
        for finding in vpn_findings(week):
            if finding["level"] == "high":
                items.append(_item("high", "Accessi VPN", finding["title"], finding["detail"], reverse("security:vpn_history") + "?" + finding["filter"]))
    except Exception:  # noqa: BLE001
        pass

    critical_cves = SecurityVulnerabilityFinding.objects.filter(severity=Severity.CRITICAL, last_seen_at__gte=now - timedelta(days=30)).count() \
        if hasattr(SecurityVulnerabilityFinding, "last_seen_at") else 0
    if critical_cves:
        items.append(_item("high", "Vulnerabilità", f"{critical_cves} vulnerabilità critiche negli ultimi 30 giorni", "", reverse("security:tickets_list")))

    try:
        from security.services.source_heartbeat import source_status_rows

        for row in source_status_rows():
            if row["state"] in ("high", "warning"):
                items.append(_item("warning", "Dati in arrivo", f"{row['name']}: {row['label'].lower()}",
                                   f"ultimo report {row['last_report_at']:%d/%m %H:%M}" if row["last_report_at"] else "nessun report ricevuto",
                                   reverse("security:admin_mailbox_sources_list")))
    except Exception:  # noqa: BLE001
        pass
    return sorted(items, key=lambda item: LEVELS[item["level"]])


def area_cards(items, days=7):
    """Un riquadro per area: stato (il peggiore dei suoi punti aperti), numeri chiave, freschezza dati."""
    from security.services.kpi_dashboard import kpi_overview

    tiles = {tile["name"]: tile for domain in kpi_overview(timezone.localdate(), days) for tile in domain["tiles"]}
    tiles.update(_live_tiles(days))
    worst = {}
    for item in items:
        code = item.get("code")
        if code and (code not in worst or LEVELS[item["level"]] < LEVELS[worst[code]]):
            worst[code] = item["level"]
    cards = []
    for code, title, report_types, metrics in AREAS:
        last = SecurityReport.objects.filter(report_type__in=report_types).order_by("-created_at").first()
        last_at = max([d for d in (last.created_at if last else None, _last_record_at(code)) if d], default=None)
        numbers = [{"name": name, "label": label, "tile": tiles.get(name)} for name, label in metrics]
        has_data = bool(last_at) or any(n["tile"] for n in numbers)
        state = worst.get(code) or ("ok" if has_data else "nodata")
        cards.append({
            "code": code, "title": title, "state": state,
            "state_label": {"ok": "In regola", "nodata": "Nessun dato"}.get(state, LEVEL_LABELS.get(state, state)),
            "numbers": numbers, "last_report": last_at,
            "stale": bool(last_at) and last_at < timezone.now() - timedelta(days=3),
        })
    return cards


def _live_tiles(days):
    """Numeri che non dipendono dai report: si contano direttamente dallo storico (accessi VPN)."""
    from security.models import SecurityVpnAccess

    week = SecurityVpnAccess.objects.filter(kind="vpn", login_at__gte=timezone.now() - timedelta(days=days))
    if not week.exists():
        return {}
    return {
        "vpn_access_allowed": {"value": week.filter(action="allowed").count()},
        "vpn_access_denied": {"value": week.filter(action="denied").count()},
        "vpn_unique_users": {"value": week.filter(action="allowed").order_by().values("username").distinct().count()},
    }


def _last_record_at(code):
    """Ultimo dato arrivato per le aree alimentate da righe proprie (backup, VPN) e non solo da report."""
    from security.models import SecurityVpnAccess

    if code == "backup":
        return BackupJobRecord.objects.order_by("-created_at").values_list("created_at", flat=True).first()
    if code == "vpn":
        return SecurityVpnAccess.objects.filter(kind="vpn").order_by("-created_at").values_list("created_at", flat=True).first()
    return None


def overall(items):
    if any(item["level"] == "critical" for item in items):
        return "critical", "Ci sono problemi critici da gestire subito"
    if any(item["level"] == "high" for item in items):
        return "high", "Alcuni punti richiedono attenzione oggi"
    if items:
        return "warning", "Tutto sotto controllo, con qualche punto da verificare"
    return "ok", "Nessun problema aperto"
