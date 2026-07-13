import re

from .common import alert_candidate, base_result, finalize_result, find_period, parse_number
from .config import BOTNET_BLOCKED_WARN_THRESHOLD


def parse_watchguard_dimension_executive_summary(text, *, source_name=None, received_at=None):
    result = base_result("text", "watchguard_dimension_executive_summary", source_name, received_at)
    text = text or ""
    start, end, date = find_period(text, source_name)
    result["period_start"] = start
    result["period_end"] = end
    result["report_date"] = date
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
    result["records"].append({"type": "dimension_summary", "firebox_name": result["firebox_name"], "metrics": result["metrics"]})
    return finalize_result(result, text)


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
