import re

from .common import alert_candidate, base_result, finalize_result, find_period, parse_number
from .config import LICENSE_EXPIRY_WARN_DAYS
from .pdf_helpers import find_line, leading_int, lines_of, parse_us_datetime, section, value_after

_HEADINGS = (
    "LICENSE STATUS",
    "NETWORK SECURITY STATUS",
    "DETECTIONS",
    "RISKS",
    "WEB ACCESS",
    "PATCH MANAGEMENT STATUS",
)


def parse_watchguard_epdr_executive_report(text, *, source_name=None, received_at=None):
    """Executive Report di WatchGuard Endpoint Security (PDF) o, in mancanza, il vecchio formato a riga."""
    text = text or ""
    lines = lines_of(text)
    if find_line(lines, "LICENSE STATUS") >= 0 and find_line(lines, "NETWORK SECURITY STATUS") >= 0:
        return _parse_pdf_layout(text, lines, source_name, received_at)
    return _parse_legacy(text, source_name, received_at)


def _parse_pdf_layout(text, lines, source_name, received_at):
    result = base_result("pdf", "watchguard_epdr_executive_report", source_name, received_at)
    start, end = _period(lines)
    result["period_start"], result["period_end"] = start, end
    result["report_date"] = (end or start or "")[:10] or None

    licenses = section(lines, "LICENSE STATUS", _HEADINGS[1:])
    status = section(lines, "NETWORK SECURITY STATUS", _HEADINGS[2:])
    detections = section(lines, "DETECTIONS", _HEADINGS[3:])
    risk_zone = lines[find_line(lines, "DETECTIONS"):]

    contracted = leading_int(value_after(licenses, "Contracted licenses:")) or 0
    used = leading_int(value_after(licenses, "Used licenses:")) or 0
    expires = parse_us_datetime((value_after(licenses, "Expiration date:") or "") + " 12:00 AM")
    enabled = leading_int(value_after(status, "Enabled")) or 0
    no_license = leading_int(value_after(status, "No license")) or 0
    with_errors = leading_int(value_after(status, "Protection with errors")) or 0
    joined = "\n".join(lines)

    def pair(pattern):
        match = re.search(pattern, joined, flags=re.I | re.S)
        return (int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))) if match else (0, 0)

    online, offline = _labelled(joined, r"Last 30 days\s+(\d[\d,]*)"), _labelled(joined, r"More than 30 days ago\s+(\d[\d,]*)")
    prot_ok, prot_old = pair(r"UP-TO-DATE PROTECTION:\s*Updated\s+(\d[\d,]*).*?Outdated\s+(\d[\d,]*)")
    know_ok, know_old = pair(r"UP-TO-DATE KNOWLEDGE:\s*Updated\s+(\d[\d,]*).*?Outdated\s+(\d[\d,]*)")
    unmanaged = _labelled(joined, r"(\d[\d,]*)\s+computers have been discovered", group_first=True)
    pups = leading_int(value_after(detections, "PUPs")) or 0
    exploits = leading_int(value_after(detections, "Exploits")) or 0
    malware = leading_int(value_after(detections, "Malware")) or 0
    threats = {
        "phishing": _labelled(joined, r"Phishing:\s*(\d[\d,]*)"),
        "blocked_devices": _labelled(joined, r"Blocked devices:\s*(\d[\d,]*)"),
        "intrusion_attempts": _labelled(joined, r"Intrusion attempts blocked:\s*(\d[\d,]*)"),
        "dangerous_actions": _labelled(joined, r"Dangerous actions blocked:\s*(\d[\d,]*)"),
        "malware_urls": _labelled(joined, r"Malware URLs:\s*(\d[\d,]*)"),
    }
    risk = {name: _risk_count(joined, label) for name, label in (("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("none", "No risk"))}
    detected_risks = _detected_risks(lines)
    top_computers = _top_computers(lines)

    metrics = result["metrics"]
    metrics.update(
        {
            "watchguard_epdr_licenses_contracted": contracted,
            "watchguard_epdr_licenses_used": used,
            "watchguard_epdr_protected_endpoints": enabled,
            "watchguard_epdr_no_license": no_license,
            "watchguard_epdr_protection_errors": with_errors,
            "watchguard_epdr_unprotected_endpoints": no_license + with_errors,
            "watchguard_epdr_computers_online": online,
            "watchguard_epdr_computers_offline_30d": offline,
            "watchguard_epdr_outdated_agents": prot_old,
            "watchguard_epdr_up_to_date_protection": prot_ok,
            "watchguard_epdr_outdated_knowledge": know_old,
            "watchguard_epdr_unmanaged_computers": unmanaged,
            "watchguard_malware_detected_count": malware,
            "watchguard_pup_detected_count": pups,
            "watchguard_epdr_exploit_count": exploits,
            "watchguard_epdr_blocked_devices": threats["blocked_devices"],
            "watchguard_epdr_malware_urls": threats["malware_urls"],
            "watchguard_epdr_risk_critical": risk["critical"],
            "watchguard_epdr_risk_high": risk["high"],
            "watchguard_epdr_risk_medium": risk["medium"],
            "watchguard_epdr_risk_none": risk["none"],
        }
    )
    if expires:
        report_day = _report_day(result["report_date"])
        days_left = (expires.date() - report_day).days if report_day else None
        if days_left is not None:
            metrics["watchguard_epdr_license_days_left"] = days_left
            if days_left <= LICENSE_EXPIRY_WARN_DAYS:
                result["alerts_candidates"].append(
                    alert_candidate("watchguard_epdr_license_expiring", "high" if days_left <= 15 else "warning",
                                    f"Licenza WatchGuard Endpoint in scadenza tra {days_left} giorni",
                                    "Senza rinnovo gli endpoint perdono la protezione", days_left=days_left)
                )
    if no_license + with_errors > 0:
        result["alerts_candidates"].append(
            alert_candidate("watchguard_epdr_unprotected_endpoints", "high" if no_license + with_errors >= 10 else "warning",
                            f"{no_license + with_errors} computer senza protezione attiva",
                            f"{no_license} senza licenza, {with_errors} con protezione in errore",
                            count=no_license + with_errors, no_license=no_license, with_errors=with_errors)
        )
    if unmanaged > 0:
        result["alerts_candidates"].append(
            alert_candidate("watchguard_epdr_unmanaged_computers", "warning", f"{unmanaged} computer in rete non gestiti da Endpoint Security",
                            "Computer scoperti in rete senza agente installato", count=unmanaged)
        )
    if malware + exploits > 0:
        result["alerts_candidates"].append(
            alert_candidate("watchguard_epdr_malware_detected", "high", f"Endpoint Security ha rilevato {malware} malware e {exploits} exploit",
                            "Rilevamenti nel periodo del report", malware=malware, exploits=exploits, computers=top_computers[:5])
        )
    if risk["critical"] > 0:
        result["alerts_candidates"].append(
            alert_candidate("watchguard_epdr_critical_risk", "warning", f"{risk['critical']} computer a rischio critico",
                            "Rischio aziendale calcolato da Endpoint Security", count=risk["critical"], risks=detected_risks[:6])
        )
    result["records"].append({"type": "epdr_executive_report", "metrics": dict(metrics), "detected_risks": detected_risks, "top_computers": top_computers})
    return finalize_result(result, text)


def _report_day(value):
    from datetime import date

    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _period(lines):
    raw = value_after(lines, "Created on:") or ""
    parts = [part.strip() for part in raw.split(" - ")]
    start = parse_us_datetime(parts[0]) if parts else None
    end = parse_us_datetime(parts[1]) if len(parts) > 1 else None
    fmt = lambda dt: dt.strftime("%Y-%m-%d %H:%M:00") if dt else None  # noqa: E731
    return fmt(start), fmt(end)


def _labelled(text, pattern, group_first=False):
    match = re.search(pattern, text, flags=re.I)
    return int(match.group(1).replace(",", "")) if match else 0


def _risk_count(text, label):
    match = re.search(rf"^{re.escape(label)}\s*\n\s*(\d[\d,]*)\s*\(", text, flags=re.M)
    return int(match.group(1).replace(",", "")) if match else 0


def _detected_risks(lines):
    """Tabella «DETECTED RISKS»: rischio, n. computer, livello."""
    idx = find_line(lines, "DETECTED RISKS:")
    end = find_line(lines, "TOP 10 COMPUTERS AT RISK:", idx + 1) if idx >= 0 else -1
    if idx < 0 or end < 0:
        return []
    body = [line for line in lines[idx + 1:end] if line not in ("Risk", "Computers", "Risk level") and not line.startswith("Executive Report")]
    rows = []
    for i in range(0, len(body) - 2, 3):
        count = leading_int(body[i + 1])
        if count is not None:
            rows.append({"risk": body[i], "computers": count, "level": body[i + 2]})
    return rows


def _top_computers(lines):
    idx = find_line(lines, "TOP 10 COMPUTERS WITH MOST DETECTIONS:")
    if idx < 0:
        return []
    rows, body = [], []
    for line in lines[idx + 1:idx + 60]:
        if line.startswith("Executive Report") or line.upper().startswith("MALWARE ACTIVITY"):
            break
        body.append(line)
    body = [line for line in body if line not in ("Computer", "Group", "Detections", "First detection", "Last detection")]
    for i in range(0, len(body) - 4, 5):
        count = leading_int(body[i + 2])
        if count is not None:
            rows.append({"computer": body[i], "group": body[i + 1], "detections": count})
    return rows


def _parse_legacy(text, source_name, received_at):
    result = base_result("text", "watchguard_epdr_executive_report", source_name, received_at)
    start, end, date = find_period(text, source_name)
    result["period_start"] = start
    result["period_end"] = end
    result["report_date"] = date
    metrics = {
        "watchguard_epdr_protected_endpoints": _metric(text, "protected endpoints"),
        "watchguard_epdr_unprotected_endpoints": _metric(text, "unprotected endpoints"),
        "watchguard_epdr_outdated_agents": _metric(text, "outdated agents") or _metric(text, "outdated signatures"),
        "watchguard_malware_detected_count": _metric(text, "malware detected"),
        "watchguard_pup_detected_count": _metric(text, "pup detected"),
        "watchguard_epdr_blocked_quarantined": _metric(text, "blocked") + _metric(text, "quarantined"),
        "watchguard_epdr_pending_actions": _metric(text, "pending actions"),
    }
    result["metrics"].update(metrics)
    if metrics["watchguard_epdr_unprotected_endpoints"] > 0:
        severity = "high" if metrics["watchguard_epdr_unprotected_endpoints"] >= 10 else "warning"
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_epdr_unprotected_endpoints",
                severity,
                "WatchGuard EPDR has unprotected endpoints",
                "One or more endpoints are not protected",
                count=metrics["watchguard_epdr_unprotected_endpoints"],
            )
        )
    if metrics["watchguard_epdr_pending_actions"] > 0 and re.search(r"(high|critical).{0,40}pending|pending.{0,40}(high|critical)", text, flags=re.I):
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_epdr_pending_severe",
                "high",
                "WatchGuard EPDR has pending high/critical actions",
                "Pending security actions include high or critical severity",
                count=metrics["watchguard_epdr_pending_actions"],
            )
        )
    if (metrics["watchguard_malware_detected_count"] or metrics["watchguard_pup_detected_count"]) and re.search(r"critical asset|server|domain controller", text, flags=re.I):
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_epdr_malware_critical_asset",
                "high",
                "WatchGuard EPDR malware/PUP on critical asset",
                "Detection references a critical asset",
                malware_count=metrics["watchguard_malware_detected_count"],
                pup_count=metrics["watchguard_pup_detected_count"],
            )
        )
    result["records"].append({"type": "epdr_executive_summary", "metrics": metrics})
    return finalize_result(result, text)


def _metric(text, label):
    patterns = [
        rf"{re.escape(label)}\s*[:\-]?\s*(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)",
        rf"(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)\s+{re.escape(label)}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return parse_number(match.group(1))
    return 0.0
