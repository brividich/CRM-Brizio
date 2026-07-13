import re
from collections import Counter

from .common import alert_candidate, base_result, concentration_candidates, finalize_result, find_period, parse_number


def parse_watchguard_threatsync_summary(text, *, source_name=None, received_at=None):
    result = base_result("text", "watchguard_threatsync_summary", source_name, received_at)
    text = text or ""
    start, end, date = find_period(text, source_name)
    result["period_start"] = start
    result["period_end"] = end
    result["report_date"] = date
    severities = {name: _count_for(text, name) for name in ["low", "medium", "high", "critical"]}
    statuses = {name: _count_for(text, name) for name in ["open", "pending", "closed", "resolved"]}
    result["metrics"].update(
        {
            "watchguard_threatsync_total_count": _count_for(text, "total") or sum(severities.values()),
            "watchguard_threatsync_low_count": severities["low"],
            "watchguard_threatsync_medium_count": severities["medium"],
            "watchguard_threatsync_high_count": severities["high"],
            "watchguard_threatsync_critical_count": severities["critical"],
            "watchguard_threatsync_open_high_count": _paired_count(text, "high", ["open", "pending"]) or (severities["high"] if statuses["open"] or statuses["pending"] else 0),
            "watchguard_threatsync_open_critical_count": _paired_count(text, "critical", ["open", "pending"]) or (severities["critical"] if statuses["open"] or statuses["pending"] else 0),
        }
    )
    for severity, metric in [("high", "watchguard_threatsync_open_high_count"), ("critical", "watchguard_threatsync_open_critical_count")]:
        count = int(result["metrics"][metric])
        if count > 0:
            result["alerts_candidates"].append(
                alert_candidate(
                    "watchguard_threatsync_open_severe",
                    severity,
                    f"WatchGuard ThreatSync {severity} incidents open or pending",
                    "High/Critical ThreatSync incidents are not closed/resolved",
                    incident_severity=severity,
                    count=count,
                )
            )
    result["records"].append({"type": "threatsync_summary", "severities": severities, "statuses": statuses})
    return finalize_result(result, text)


def _count_for(text, label):
    match = re.search(rf"{re.escape(label)}\s*[:\-]?\s*(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)", text, flags=re.I)
    return parse_number(match.group(1)) if match else 0


def _paired_count(text, severity, statuses):
    total = 0
    for line in text.splitlines():
        lowered = line.lower()
        if severity in lowered and any(status in lowered for status in statuses):
            total += int(parse_number(line))
    return total
