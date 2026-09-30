"""Mail WatchGuard Endpoint Security «Threats detected between ...»: un evento per computer coinvolto."""
import re

from .common import alert_candidate, base_result, finalize_result
from .pdf_helpers import parse_us_datetime

_SUMMARY = re.compile(r"(\d+)\s+([A-Z][A-Za-z ]+?)\s+ON\s+(\d+)\s+COMPUTERS?", re.I)
_COMPUTER = re.compile(r"Name:\s*(?P<name>[^\r\n]+?)\s*[\r\n]+\s*IP address:\s*(?P<ip>[^\r\n]*?)\s*[\r\n]+\s*Group:\s*(?P<group>[^\r\n]+)", re.I)
_PERIOD = re.compile(r"between\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)\s+and\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)", re.I)
# Categorie che indicano una minaccia vera; «devices blocked» e' il controllo dispositivi (es. chiavette USB).
_SERIOUS = ("malware", "ransomware", "virus", "exploit", "intrusion", "phishing", "threat")


def parse_watchguard_epdr_threat_mail(text, *, source_name=None, received_at=None):
    result = base_result("text", "watchguard_epdr_threat_alert", source_name, received_at)
    text = text or ""
    period = _PERIOD.search(text)
    if period:
        start, end = parse_us_datetime(period.group(1).upper()), parse_us_datetime(period.group(2).upper())
        result["period_start"] = start.strftime("%Y-%m-%d %H:%M:00") if start else None
        result["period_end"] = end.strftime("%Y-%m-%d %H:%M:00") if end else None
        result["report_date"] = (result["period_start"] or "")[:10] or None
    categories = [(int(n), label.strip().lower()) for n, label, _ in _SUMMARY.findall(text)]
    computers = [{"computer": m.group("name").strip(), "ip": m.group("ip").strip(), "group": m.group("group").strip()} for m in _COMPUTER.finditer(text)]
    result["records"] = [{"type": "epdr_threat_alert", "categories": categories, "computers": computers}]
    result["metrics"]["watchguard_epdr_threat_events"] = sum(count for count, _ in categories) or (1 if computers else 0)
    result["metrics"]["watchguard_epdr_affected_computers"] = len(computers)
    if not categories and not computers:
        result["parse_warnings"].append("Mail EPDR riconosciuta ma senza categoria di minaccia ne' computer coinvolti")
    label = ", ".join(f"{count} {name}" for count, name in categories) or "minacce"
    serious = any(word in label for word in _SERIOUS)
    for computer in computers or [{"computer": "", "ip": "", "group": ""}]:
        who = computer["computer"] or "computer non indicato"
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_epdr_threat_detected",
                "high" if serious else "warning",
                f"Endpoint Security: {label} su {who}",
                "Notifica WatchGuard Endpoint Security di minacce rilevate",
                computer=computer["computer"], ip=computer["ip"], group=computer["group"], categories=categories,
                period_start=result["period_start"],
            )
        )
    result["raw_summary"] = f"EPDR: {label} su {len(computers)} computer"
    return finalize_result(result, text)
