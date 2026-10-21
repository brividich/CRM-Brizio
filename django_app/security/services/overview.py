"""Panoramica IT: tutto quello che arriva al Security Center, in una pagina che si legge in un minuto.

Ispirazione (Microsoft Defender «Home», Wazuh, WatchGuard Cloud): in alto UN elenco di cose da fare
ordinate per gravita' («Da guardare adesso»), sotto un riquadro per area con stato, pochi numeri e
quanto sono freschi i dati. Il dettaglio sta un clic piu' in la' (KPI, alert, accessi VPN, backup).
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from security.models import BackupJobRecord, SecurityAlert, SecurityReport, Severity
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
     (("backup_completed_count", "esecuzioni riuscite"), ("backup_failed_count", "esecuzioni fallite"), ("backup_transferred_total_gb", "GB salvati"))),
    ("vpn", "Accessi VPN", ("watchguard_firebox_authentication_allowed", "watchguard_firebox_authentication_denied"),
     (("vpn_access_allowed", "accessi"), ("vpn_access_denied", "negati"), ("vpn_unique_users", "utenti"))),
    ("vulns", "Vulnerabilità", ("defender_vulnerability_notification",), ()),  # numeri dal catalogo: CVE sull'inventario
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
    # Notifiche NIS2/GDPR scadute o in scadenza: hanno un termine di legge, vengono prima di tutto.
    from security.services.incidents import urgent_incidents

    for row in urgent_incidents(now):
        incident, deadline = row["incident"], row["deadline"]
        overdue = deadline["state"] == "overdue"
        items.append(_item("critical" if overdue else "high", "Incidenti",
                           f"{incident.code}: {deadline['label']} {'scaduta' if overdue else 'in scadenza'}",
                           f"entro il {timezone.localtime(deadline['due_at']):%d/%m %H:%M} · {incident.title[:80]}",
                           reverse("security:incident_detail", args=[incident.pk])))
    alerts = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, severity__in=[Severity.CRITICAL, Severity.HIGH]).select_related("source").order_by("-updated_at")
    for alert in alerts[:5]:
        items.append(_item("critical" if alert.severity == Severity.CRITICAL else "high", "Alert", alert.title,
                           f"aperto dal {alert.created_at:%d/%m %H:%M}", reverse("security:alert_detail", args=[alert.pk])))
    extra = alerts.count() - 5
    if extra > 0:
        items.append(_item("high", "Alert", f"Altri {extra} alert critici o alti aperti", "",
                           reverse("security:alerts_list") + "?status=active&severity=critical&severity=high"))

    # Backup contati per PC, come il riquadro «PC con backup ko» e la pagina Backup (filtro «Solo backup ko»).
    from security.services import metriche

    ko = metriche.pc_backup_ko_rows()
    for row in ko[:3]:
        if row["last_status"] == "failed":
            detail = f"ultimo backup fallito il {timezone.localtime(row['last_at']):%d/%m %H:%M}"
        elif row["last_ok"]:
            detail = f"nessun backup riuscito da {row['days_since_ok']} giorni"
        else:
            detail = "nessun backup riuscito nel periodo"
        items.append(_item("high", "Backup", f"Backup ko: {row['name']}", detail, reverse("security:pc_detail") + "?nome=" + row["name"]))
    if len(ko) > 3:
        items.append(_item("high", "Backup", f"Altri {len(ko) - 3} PC con backup ko", "", reverse("security:backup") + "?giorni=7&stato=ko#pc"))
    # Job falliti che non nominano nessun PC (alcuni report danno solo il job): non entrano nel conteggio per PC,
    # quindi restano qui come job. Data del job, non dell'import; un punto per job (l'ultimo fallimento).
    from security.services.backup_center import device_runs

    cutoff = now - timedelta(hours=48)
    seen = set()
    for job in BackupJobRecord.objects.filter(status="failed").order_by("-started_at", "-created_at")[:50]:
        when = job.started_at or job.created_at
        if when < cutoff or job.job_name in seen or device_runs(job):
            continue
        seen.add(job.job_name)
        if len(seen) <= 3:
            items.append(_item("high", "Backup", f"Backup fallito: {job.job_name}", f"{job.started_at:%d/%m %H:%M} · il report non indica i PC" if job.started_at else "il report non indica i PC",
                               reverse("security:backup_log") + "?giorni=7"))
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

    cve = metriche.cve_sui_pc()
    if cve.extra["gravi"]:
        items.append(_item("high", "Vulnerabilità", f"{cve.extra['gravi']} CVE gravi colpiscono i nostri PC",
                           "sfruttate (CISA KEV) o con CVSS 9 o più, secondo l'inventario software", cve.url))
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
        numbers = [_number(name, label, tiles.get(name)) for name, label in metrics]
        if code == "vulns":
            numbers = _vuln_numbers()
        elif code == "backup":
            from security.services import metriche

            ko = metriche.pc_backup_ko()
            numbers = [{"name": "pc_backup_ko", "label": ko.label, "tile": {"value": ko.value}, "hint": "adesso", "url": ko.url, "raw": True}] + numbers
        if code == "vulns":
            from security.models import SoftwareInstallation

            last_at = SoftwareInstallation.objects.order_by("-last_seen_at").values_list("last_seen_at", flat=True).first() or last_at
        # Vulnerabilità e backup hanno numeri calcolati «adesso» (anche 0): conta solo se la fonte ha mandato dati.
        has_data = bool(last_at) or (code not in ("vulns", "backup") and any(n["tile"] for n in numbers))
        state = worst.get(code) or ("ok" if has_data else "nodata")
        cards.append({
            "code": code, "title": title, "state": state,
            "state_label": {"ok": "In regola", "nodata": "Nessun dato"}.get(state, LEVEL_LABELS.get(state, state)),
            "numbers": numbers, "last_report": last_at,
            "stale": bool(last_at) and last_at < timezone.now() - timedelta(days=3),
        })
    # Prima le aree con dati: quelle senza fonte collegata vanno in fondo, non in prima fila.
    cards.sort(key=lambda c: c["state"] == "nodata")
    return cards


def _number(name, label, tile):
    """Ogni numero dice se è l'ultimo valore letto o il totale del periodo: non si mescolano senza dirlo."""
    hint = ("ultimo report" if tile.get("last_value") else "totale 7 giorni") if tile else ""
    return {"name": name, "label": label, "tile": tile, "hint": hint, "url": reverse("security:kpi_detail", args=[name])}


def _vuln_numbers():
    """Vulnerabilità = CVE che colpiscono i nostri PC secondo l'inventario software (stesso dato della pagina Vulnerabilità)."""
    from security.services import metriche

    cve, pc, cop = metriche.cve_sui_pc(), metriche.pc_esposti(), metriche.copertura_cpe()
    return [
        {"name": "cve", "label": "CVE sui nostri PC", "tile": {"value": cve.value}, "hint": "adesso", "url": cve.url, "raw": True},
        {"name": "pc_esposti", "label": "PC con CVE", "tile": {"value": pc.value}, "hint": "adesso", "url": pc.url, "raw": True},
        {"name": "copertura_cpe", "label": f"software controllabili ({cop.extra['coperti']} su {cop.extra['totale']})",
         "tile": {"value": f"{cop.value}%"}, "hint": "collegati a un CPE o N/A", "url": cop.url, "raw": True},
    ]


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
