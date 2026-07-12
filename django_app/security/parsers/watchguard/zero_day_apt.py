import re

from .common import alert_candidate, base_result, finalize_result, find_period, parse_number


def parse_watchguard_zero_day_apt_summary(text, *, source_name=None, received_at=None):
    result = base_result("text", "watchguard_zero_day_apt_summary", source_name, received_at)
    text = text or ""
    start, end, date = find_period(text, source_name)
    result["period_start"] = start
    result["period_end"] = end
    result["report_date"] = date
    hits = _extract_hits(text)
    result["metrics"]["watchguard_zero_day_apt_hits"] = hits
    result["records"].append({"type": "zero_day_apt_summary", "hits": hits})
    if hits > 0:
        severity = "critical" if re.search(r"\bcritical\b", text, flags=re.I) else "high"
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_zero_day_apt_hit",
                severity,
                "WatchGuard Zero-Day APT hit detected",
                "Zero-Day/APT report contains one or more hits",
                hits=hits,
                firebox_name=result["firebox_name"],
            )
        )
    return finalize_result(result, text)


def _extract_hits(text):
    if re.search(r"no\s+(?:content|apt|zero[- ]day|threats?).{0,30}(?:detected|found)", text, flags=re.I):
        return 0
    for pattern in [r"(?:hits?|detected|blocked|threats?)\s*[:\-]?\s*(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)", r"(\d+)\s+(?:hits?|detections?)"]:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return int(parse_number(match.group(1)))
    return 0
