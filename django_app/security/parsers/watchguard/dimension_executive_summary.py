import re
from datetime import date

from .common import alert_candidate, base_result, finalize_result, find_period, parse_number
from .config import BOTNET_BLOCKED_WARN_THRESHOLD, LICENSE_EXPIRY_WARN_DAYS
from .pdf_helpers import find_line, lines_of, period_from_text, short_number

# Servizi nell'ordine in cui compaiono nel report Firebox «Executive Summary».
_SERVICE_HEADINGS = (
    "Gateway AntiVirus",
    "IntelligentAV",
    "Advanced Malware",
    "Zero-Day Malware",
    "Intrusion Prevention Service",
    "Reputation Enabled Defense",
    "Botnet Detection",
)
_STAT_LABELS = ("scanned", "detected and blocked", "detected", "prevented", "blocked")
_NUMBER = re.compile(r"^\d[\d.,]*\s*[KMBkmb]?$")


def parse_watchguard_dimension_executive_summary(text, *, source_name=None, received_at=None):
    """Executive Summary del Firebox (PDF) o, in mancanza del layout reale, il vecchio formato a riga."""
    text = text or ""
    lines = lines_of(text)
    if find_line(lines, "Malware Attacks") >= 0 and find_line(lines, "Network Attacks") >= 0:
        return _parse_pdf_layout(text, lines, source_name, received_at)
    return _parse_legacy(text, source_name, received_at)


def _parse_pdf_layout(text, lines, source_name, received_at):
    result = base_result("pdf", "watchguard_dimension_executive_summary", source_name, received_at)
    start, end, day = period_from_text(text)
    if not day:
        start, end, day = find_period(text, source_name)
    result["period_start"], result["period_end"], result["report_date"] = start, end, day
    result["firebox_name"] = _device_name(lines) or result["firebox_name"]

    services = {}
    for heading in _SERVICE_HEADINGS:
        idx = find_line(lines, heading)
        if idx >= 0:
            services[heading] = _stats_after(lines, idx)

    malware_total = _total_scanned(lines, "Malware Attacks")
    attacks_total = _total_scanned(lines, "Network Attacks")
    av = [services.get(name, {}) for name in _SERVICE_HEADINGS[:4]]
    ips = services.get("Intrusion Prevention Service", {})
    botnet = services.get("Botnet Detection", {})
    reputation = services.get("Reputation Enabled Defense", {})
    botnet_hits = botnet.get("detected and blocked", botnet.get("detected", 0.0))
    detected = sum(stat.get("detected and blocked", 0.0) + stat.get("detected", 0.0) for stat in av)

    metrics = result["metrics"]
    metrics.update(
        {
            "watchguard_malware_scanned_count": malware_total,
            "watchguard_malware_detected_count": detected,
            "watchguard_gav_scanned_count": services.get("Gateway AntiVirus", {}).get("scanned", 0.0),
            "watchguard_apt_scanned_count": services.get("Zero-Day Malware", {}).get("scanned", 0.0),
            "watchguard_network_attacks_scanned_count": attacks_total,
            "watchguard_ips_scanned_count": ips.get("scanned", 0.0),
            "watchguard_ips_detected_count": ips.get("detected", 0.0),
            "watchguard_ips_prevented_count": ips.get("prevented", 0.0),
            "watchguard_reputation_blocked_count": reputation.get("detected and blocked", 0.0),
            "watchguard_botnet_scanned_count": botnet.get("scanned", 0.0),
            "watchguard_botnet_detected_count": botnet_hits,
            "watchguard_botnet_blocked_count": botnet_hits,
        }
    )
    days_left = _license_days_left(text, day)
    if days_left is not None:
        metrics["watchguard_license_days_left"] = days_left
        if days_left <= LICENSE_EXPIRY_WARN_DAYS:
            result["alerts_candidates"].append(
                alert_candidate(
                    "watchguard_license_expiring",
                    "high" if days_left <= 15 else "warning",
                    f"Licenza WatchGuard in scadenza tra {days_left} giorni",
                    "La licenza del firewall sta per scadere: senza rinnovo si perdono le protezioni",
                    days_left=days_left,
                    firebox_name=result["firebox_name"],
                )
            )
    if detected > 0:
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_malware_blocked",
                "warning",
                f"Il firewall ha bloccato {int(detected)} malware",
                "Gateway AntiVirus / IntelligentAV / Advanced Malware hanno rilevato e bloccato file",
                count=detected,
                firebox_name=result["firebox_name"],
            )
        )
    _add_botnet_alert(result, botnet_hits)
    result["records"].append({"type": "firebox_executive_summary", "firebox_name": result["firebox_name"], "metrics": dict(metrics)})
    return finalize_result(result, text)


def _parse_legacy(text, source_name, received_at):
    result = base_result("text", "watchguard_dimension_executive_summary", source_name, received_at)
    start, end, day = find_period(text, source_name)
    result["period_start"], result["period_end"], result["report_date"] = start, end, day
    result["firebox_name"] = _extract_firebox(text) or result["firebox_name"]
    result["metrics"].update(
        {
            "watchguard_malware_scanned_count": _line_metric(text, "Malware Attacks", "scanned"),
            "watchguard_malware_detected_count": _line_metric(text, "Malware Attacks", "detected") or _line_metric(text, "Malware Attacks", "blocked"),
            "watchguard_network_attacks_scanned_count": _line_metric(text, "Network Attacks", "scanned"),
            "watchguard_ips_scanned_count": _line_metric(text, "IPS", "scanned"),
            "watchguard_ips_detected_count": _line_metric(text, "IPS", "detected"),
            "watchguard_ips_prevented_count": _line_metric(text, "IPS", "prevented"),
            "watchguard_botnet_scanned_count": _line_metric(text, "Botnet Detection", "scanned"),
            "watchguard_botnet_detected_count": _line_metric(text, "Botnet Detection", "detected"),
            "watchguard_botnet_blocked_count": _line_metric(text, "Botnet Detection", "blocked"),
        }
    )
    botnet_count = max(result["metrics"]["watchguard_botnet_detected_count"], result["metrics"]["watchguard_botnet_blocked_count"])
    _add_botnet_alert(result, botnet_count)
    result["records"].append({"type": "dimension_summary", "firebox_name": result["firebox_name"], "metrics": result["metrics"]})
    return finalize_result(result, text)


def _add_botnet_alert(result, botnet_count):
    if botnet_count >= BOTNET_BLOCKED_WARN_THRESHOLD:
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_botnet_blocked_aggregate",
                "warning",
                "Significant WatchGuard Botnet Detection activity",
                "Detected/blocked botnet volume is above the configured aggregate threshold",
                count=botnet_count,
                threshold=BOTNET_BLOCKED_WARN_THRESHOLD,
                firebox_name=result["firebox_name"],
            )
        )


def _stats_after(lines, idx):
    """«12.1K / Scanned / 0 / Detected and Blocked»: il valore sta SOPRA l'etichetta."""
    stats = {}
    i = idx + 1
    limit = min(len(lines) - 1, idx + 12)
    while i < limit:
        if _NUMBER.match(lines[i]) and lines[i + 1].lower() in _STAT_LABELS:
            stats[lines[i + 1].lower()] = short_number(lines[i])
            i += 2
            continue
        if lines[i] in _SERVICE_HEADINGS or lines[i].endswith("Attacks"):
            break
        i += 1
    return stats


def _total_scanned(lines, heading):
    idx = find_line(lines, heading)
    if idx < 0:
        return 0.0
    for line in lines[idx + 1:idx + 6]:
        match = re.match(r"total scanned\s+(\d[\d.,]*\s*[KMBkmb]?)", line, flags=re.I)
        if match:
            return short_number(match.group(1))
    return 0.0


def _device_name(lines):
    idx = find_line(lines, "Device(s)")
    if idx < 0 or idx + 1 >= len(lines):
        return None
    name = lines[idx + 1].split("(")[0].strip(" -")
    return name or None


def _license_days_left(text, report_day):
    match = re.search(r"Expires on\s+(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        expiry = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        today = date.fromisoformat(report_day) if report_day else date.today()
    except ValueError:
        return None
    return (expiry - today).days


def _extract_firebox(text):
    match = re.search(r"(?:firebox|device)\s*[:\-]\s*([A-Za-z0-9_.-]+)", text, flags=re.I)
    return match.group(1) if match else None


def _line_metric(text, label, metric_word):
    for line in text.splitlines():
        if label.lower() in line.lower() and metric_word.lower() in line.lower():
            match = re.search(rf"(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)\s+{re.escape(metric_word)}", line, flags=re.I)
            if match:
                return parse_number(match.group(1))
    return 0.0
