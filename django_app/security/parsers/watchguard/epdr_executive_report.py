import re

from .common import alert_candidate, base_result, finalize_result, find_period, parse_number


def parse_watchguard_epdr_executive_report(text, *, source_name=None, received_at=None):
    result = base_result("text", "watchguard_epdr_executive_report", source_name, received_at)
    text = text or ""
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
