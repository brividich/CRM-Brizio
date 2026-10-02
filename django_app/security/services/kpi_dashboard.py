"""KPI del Security Center per area, con andamento e dettaglio.

La pagina mostrava una tabella statica per «sorgente» (cioe' il nome della casella mail: un
unico gruppo con 40 righe) e un solo giorno alla volta. Qui ogni metrica diventa un riquadro
con il valore del periodo, il confronto col periodo precedente e l'andamento giornaliero.

Valori giornalieri: le metriche dei report, senza doppi conteggi (vedi `report_daily_values`);
le istantanee KPI (`SecurityKpiSnapshot`) per i giorni senza report e per le metriche calcolate
dallo storico (accessi VPN), che lì sono la fonte esatta.
"""
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Sum
from django.db.models.fields.json import KT

from security.models import BackupJobRecord, SecurityEventRecord, SecurityKpiSnapshot, SecurityReportMetric

# Ordine delle aree in pagina: (codice, titolo, prefissi del nome metrica)
DOMAINS = [
    ("backup", "Backup", ("backup_",)),
    ("vpn", "Accessi VPN", ("vpn_", "watchguard_sslvpn_", "watchguard_auth_", "watchguard_firewall_auth")),
    ("endpoint", "Endpoint Security", ("watchguard_epdr_", "watchguard_pup_")),
    ("firewall", "Firewall", ("watchguard_",)),
    ("vulns", "Vulnerabilità", ("defender_", "vulnerability_")),
    ("events", "Eventi e segnalazioni", ()),
]
DOMAIN_TITLES = {code: title for code, title, _ in DOMAINS}

# Metriche che sono uno «stato» (si guarda l'ultimo valore), non un conteggio da sommare:
# «12 computer senza protezione» lunedi' e ancora 12 martedi' sono 12 computer, non 24.
_LAST_VALUE_MARKERS = ("_endpoints", "_licenses_", "_days_left", "_unique_", "_avg_", "_max_", "_size_total", "_protected", "_outdated",
                       "_computers_", "_risk_", "_no_license", "_protection_errors", "_unmanaged", "_reported", "_sections", "_up_to_date",
                       "_open_", "_pending_", "_expiring", "_sdwan_", "_concentration")
_LAST_VALUE_NAMES = {
    "watchguard_epdr_affected_computers", "watchguard_epdr_blocked_devices", "watchguard_epdr_critical_risk",
    "watchguard_epdr_malware_critical_asset", "watchguard_threatsync_open_severe", "defender_exposed_devices_total",
    "defender_critical_exposed_devices_total",
}
# Tecniche: utili al debug, non a chi guarda i KPI.
_HIDDEN = {"watchguard_report_summary", "top_users", "top_source_ips"}
# Calcolate dallo storico accessi (utenti unici, durate): l'istantanea e' esatta, i report no.
_SNAPSHOT_FIRST_PREFIXES = ("vpn_",)


def domain_for(name):
    if name.startswith("watchguard_malware_detected"):
        return "firewall"
    for code, _title, prefixes in DOMAINS:
        if prefixes and name.startswith(prefixes):
            return code
    return "events"


def is_last_value(name):
    return name in _LAST_VALUE_NAMES or any(marker in name for marker in _LAST_VALUE_MARKERS)


def _as_date(value, default):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return default


def report_daily_values(start, end, name=None, used=None):
    """{name: {date: valore}} dalle metriche dei report, senza doppi conteggi.

    Prima si sommava tutto quello che arrivava nello stesso giorno: lo stesso report letto due
    volte (casella e storico, mail duplicata) raddoppiava il numero, e un report settimanale
    che arriva ogni giorno contava la stessa settimana sette volte. Ora, per sorgente e tipo di report:
    - un solo report per giorno (il piu' recente);
    - i conteggi di report che coprono un periodo si sommano solo se i periodi non si sovrappongono
      (si tiene il piu' recente);
    - gli stati (computer senza protezione, licenze...) valgono per il giorno, mai sommati nel tempo.
    """
    metrics = SecurityReportMetric.objects.filter(report__report_date__range=(start, end))
    if name:
        metrics = metrics.filter(name=name)
    rows = list(metrics.order_by().values_list(
        "name", "value", "report_id", "report__source_id", "report__report_type", "report__report_date", "report__created_at"))
    report_ids = {row[2] for row in rows}
    periods = {}
    if report_ids:
        from security.models import SecurityReport

        ids = list(report_ids)
        for i in range(0, len(ids), 500):
            for rid, p_start, p_end, day in SecurityReport.objects.filter(id__in=ids[i:i + 500]).values_list(
                    "id", KT("parsed_payload__period_start"), KT("parsed_payload__period_end"), "report_date"):
                p_end = _as_date(p_end, day)
                periods[rid] = (min(_as_date(p_start, p_end), p_end), p_end)
    groups = defaultdict(list)
    for metric, value, rid, source_id, report_type, day, created in rows:
        groups[(metric, source_id, report_type)].append((day, created, rid, value))
    values = defaultdict(lambda: defaultdict(float))
    for (metric, _source, _type), items in groups.items():
        items.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        state = is_last_value(metric)
        seen, covered_from = set(), None
        for day, _created, rid, value in items:
            if day in seen:
                continue  # stesso report (o rilettura) nello stesso giorno: vale il piu' recente
            p_start, p_end = periods.get(rid, (day, day))
            if not state and covered_from is not None and p_end >= covered_from:
                continue  # periodo gia' contato da un report piu' recente
            seen.add(day)
            if used is not None:
                used.add(rid)
            covered_from = p_start if covered_from is None else min(covered_from, p_start)
            values[metric][day] += value
    return {metric: dict(by_day) for metric, by_day in values.items()}


def _daily_values(start, end, name=None):
    """{name: {date: valore}}: report deduplicati prima, istantanee per i giorni scoperti (e per le VPN)."""
    values = defaultdict(dict)
    for metric, by_day in report_daily_values(start, end, name=name).items():
        values[metric].update(by_day)
    snapshots = SecurityKpiSnapshot.objects.filter(snapshot_date__range=(start, end))
    if name:
        snapshots = snapshots.filter(name=name)
    for row in snapshots.order_by().values("name", "snapshot_date").annotate(total=Sum("value")):
        if row["name"].startswith(_SNAPSHOT_FIRST_PREFIXES):
            values[row["name"]][row["snapshot_date"]] = row["total"]
        else:
            values[row["name"]].setdefault(row["snapshot_date"], row["total"])
    return values


def _summarize(series, last_value):
    present = [v for v in series if v is not None]
    if not present:
        return None
    return present[-1] if last_value else sum(present)


def _sparkline(series, width=120, height=32):
    points = [(i, v) for i, v in enumerate(series) if v is not None]
    if len(points) < 2:
        return ""
    low, high = min(v for _, v in points), max(v for _, v in points)
    span = (high - low) or 1
    step = width / max(len(series) - 1, 1)
    return " ".join(f"{i * step:.1f},{height - 3 - (v - low) / span * (height - 6):.1f}" for i, v in points)


def kpi_overview(end, days):
    """Riquadri per area: valore del periodo, variazione sul periodo precedente, andamento."""
    start = end - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    values = _daily_values(prev_start, end)
    dates = [start + timedelta(days=i) for i in range(days)]
    prev_dates = [prev_start + timedelta(days=i) for i in range(days)]
    domains = defaultdict(list)
    for name, by_day in values.items():
        if name in _HIDDEN:
            continue
        last = is_last_value(name)
        series = [by_day.get(d, None if last else 0) for d in dates]
        if not any(v for v in series if v is not None) and not any(by_day.get(d) for d in prev_dates):
            continue
        current = _summarize(series, last)
        previous = _summarize([by_day.get(d) for d in prev_dates], last)
        delta = None if current is None or previous is None else current - previous
        domains[domain_for(name)].append({
            "name": name, "value": current, "previous": previous, "delta": delta, "last_value": last,
            "spark": _sparkline(series), "days_with_data": sum(1 for v in series if v),
        })
    result = []
    for code, title, _ in DOMAINS:
        tiles = sorted(domains.get(code, []), key=lambda t: t["name"])
        if tiles:
            result.append({"code": code, "title": title, "tiles": tiles})
    return result


def kpi_detail(name, end, days):
    """Andamento giornaliero di una metrica + da dove arriva il numero."""
    start = end - timedelta(days=days - 1)
    used = set()
    report_daily_values(start, end, name=name, used=used)
    by_day = _daily_values(start, end, name=name).get(name, {})
    last = is_last_value(name)
    dates = [start + timedelta(days=i) for i in range(days)]
    series = [by_day.get(d) for d in dates]
    peak = max([v for v in series if v is not None] or [0]) or 1
    width, height, top, left = 760, 180, 10, 36
    slot = (width - left) / days
    bar = max(min(slot - 2, 28), 2)  # 2px di distacco tra le barre
    baseline = top + height
    bars = []
    for i, (day, value) in enumerate(zip(dates, series)):
        h = 0 if not value else max(height * value / peak, 2)
        bars.append({
            "date": day, "value": value, "x": round(left + i * slot + (slot - bar) / 2, 1), "w": round(bar, 1),
            "y": round(baseline - h, 1), "h": round(h, 1), "label_x": round(left + i * slot + slot / 2, 1),
            "show_label": i % max(days // 8, 1) == 0,
        })
    reports = list(
        SecurityReportMetric.objects.filter(name=name, report__report_date__range=(start, end))
        .select_related("report", "report__source").order_by("-report__report_date", "-id")[:60]
    )
    for metric in reports:
        metric.counted = metric.report_id in used
    backups = list(BackupJobRecord.objects.filter(created_at__date__range=(start, end)).order_by("-started_at", "-id")[:60]) if name.startswith("backup_") else []
    events = list(SecurityEventRecord.objects.filter(event_type=name, occurred_at__date__range=(start, end)).order_by("-occurred_at")[:60]) if not reports else []
    return {
        "name": name, "domain": DOMAIN_TITLES[domain_for(name)], "last_value": last,
        "value": _summarize(series, last), "chart": {"bars": bars, "peak": peak, "width": width, "height": height + top + 24,
                                                       "baseline": baseline, "top": top, "left": left},
        "rows": [{"date": d, "value": v} for d, v in zip(dates, series)][::-1],
        "reports": reports, "backups": backups, "events": events,
    }
