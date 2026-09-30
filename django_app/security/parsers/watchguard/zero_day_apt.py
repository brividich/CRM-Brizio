import re

from .common import alert_candidate, base_result, finalize_result, find_period, parse_number
from .pdf_helpers import period_from_text


def parse_watchguard_zero_day_apt_summary(text, *, source_name=None, received_at=None):
    result = base_result("text", "watchguard_zero_day_apt_summary", source_name, received_at)
    text = text or ""
    start, end, date = period_from_text(text)
    if not date:
        start, end, date = find_period(text, source_name)
    result["period_start"] = start
    result["period_end"] = end
    result["report_date"] = date
    if _axis_only(text):
        # PDF con il solo grafico: le cifre 0,1,2,3.. sono l'asse, non rilevamenti.
        hits = 0
        result["parse_warnings"].append("Grafico Zero-Day/APT senza rilevamenti (solo asse): 0 hit")
    else:
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


def _axis_only(text):
    """Vero se dopo ogni «Hits» ci sono solo i numeri 0,1,2,... dell'asse del grafico."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    seen = False
    for i, line in enumerate(lines):
        if line != "Hits":
            continue
        seen = True
        axis, j = [], i + 1
        while j < len(lines) and lines[j].isdigit():
            axis.append(int(lines[j]))
            j += 1
        if axis != list(range(len(axis))):
            return False
    return seen


def _extract_hits(text):
    if re.search(r"no\s+(?:content|apt|zero[- ]day|threats?).{0,30}(?:detected|found)", text, flags=re.I):
        return 0
    for pattern in [r"(?:hits?|detected|blocked|threats?)\s*[:\-]?\s*(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)", r"(\d+)\s+(?:hits?|detections?)"]:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return int(parse_number(match.group(1)))
    return 0
