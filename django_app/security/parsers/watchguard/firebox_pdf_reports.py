"""Report Firebox in PDF che contengono soprattutto grafici: Executive Dashboard, Interface Summary, SD-WAN.

Nei PDF WatchGuard i grafici non hanno i valori nel testo (solo le etichette degli assi):
qui si estrae quello che c'e' davvero (periodo, dispositivo, interfacce/collegamenti, tabelle
«Top»), e si dichiara con un avviso cio' che NON e' leggibile, invece di produrre zeri finti.
"""
import re

from .common import base_result, find_period, finalize_result
from .pdf_helpers import find_line, lines_of, period_from_text

_TOP_SECTIONS = (
    "Top Domains",
    "Top URL Categories",
    "Top Applications",
    "Top Application Categories",
    "Top Blocked Applications",
    "Top Destinations",
    "Top Protocols",
    "Top Countries",
)
_IFACE = re.compile(r"^(?P<iface>[\w./-]+): (?P<name>.+?): Bytes Transferred", re.I)
_LINK = re.compile(r"^(?P<name>.+?) \((?P<iface>[\w./-]+)\): (?:Loss Rate|Latency|Jitter)", re.I)


def _base(report_type, text, source_name, received_at):
    result = base_result("pdf", report_type, source_name, received_at)
    start, end, day = period_from_text(text)
    if not day:
        start, end, day = find_period(text, source_name)
    result["period_start"], result["period_end"], result["report_date"] = start, end, day
    lines = lines_of(text)
    idx = find_line(lines, "Device(s)")
    if 0 <= idx < len(lines) - 1:
        result["firebox_name"] = lines[idx + 1].split("(")[0].strip(" -") or result["firebox_name"]
    return result, lines


def parse_watchguard_interface_summary_pdf(text, *, source_name=None, received_at=None):
    result, lines = _base("watchguard_interface_summary", text, source_name, received_at)
    interfaces = []
    for line in lines:
        match = _IFACE.match(line)
        if match and match.group("iface") not in {i["interface"] for i in interfaces}:
            interfaces.append({"interface": match.group("iface"), "name": match.group("name")})
    result["metrics"]["watchguard_interfaces_reported"] = len(interfaces)
    result["records"] = [{"interface": i["interface"], "name": i["name"], "packet_loss": None, "latency_ms": None, "jitter_ms": None, "dropped_packets": None} for i in interfaces]
    result["parse_warnings"].append("Il PDF contiene grafici del traffico per interfaccia senza valori numerici nel testo: riconosciute solo le interfacce")
    result["raw_summary"] = f"Interface Summary: {len(interfaces)} interfacce ({', '.join(i['name'] for i in interfaces[:6])})"
    return finalize_result(result, text)


def parse_watchguard_sdwan_status_pdf(text, *, source_name=None, received_at=None):
    result, lines = _base("watchguard_sdwan_status", text, source_name, received_at)
    links = []
    for line in lines:
        match = _LINK.match(line)
        if match and match.group("iface") not in {i["interface"] for i in links}:
            links.append({"interface": match.group("iface"), "name": match.group("name")})
    result["metrics"]["watchguard_sdwan_links_reported"] = len(links)
    result["records"] = [{"interface": i["interface"], "name": i["name"], "packet_loss": None, "latency_ms": None, "jitter_ms": None, "dropped_packets": None} for i in links]
    result["parse_warnings"].append("Il PDF SD-WAN contiene solo grafici (perdita, latenza, jitter) senza valori numerici nel testo: non e' possibile calcolare medie ne' alert")
    result["raw_summary"] = f"SD-WAN: {len(links)} collegamenti ({', '.join(i['name'] for i in links[:6])})"
    return finalize_result(result, text)


def parse_watchguard_executive_dashboard(text, *, source_name=None, received_at=None):
    result, lines = _base("watchguard_executive_dashboard", text, source_name, received_at)
    top_lists = {}
    for heading in _TOP_SECTIONS:
        rows = _top_rows(lines, heading)
        if rows:
            top_lists[heading] = rows[:5]
    blocked = top_lists.get("Top Blocked Applications", [])
    result["metrics"]["watchguard_dashboard_blocked_app_hits"] = sum(row.get("hits", 0) for row in blocked)
    result["metrics"]["watchguard_dashboard_sections"] = len(top_lists)
    result["records"] = [{"type": "dashboard_top_lists", "top": top_lists}]
    result["raw_summary"] = "Executive Dashboard: " + ", ".join(f"{name.replace('Top ', '')} ({len(rows)})" for name, rows in top_lists.items())
    if not top_lists:
        result["parse_warnings"].append("Nessuna tabella «Top» riconosciuta nel dashboard")
    # I Top Clients contengono utenti e IP interni: non vengono conservati.
    return finalize_result(result, text)


def _top_rows(lines, heading):
    """Righe «nome, byte, hit» della tabella che segue il titolo (dopo l'intestazione Name/Bytes/Hits)."""
    for i, line in enumerate(lines):
        if line != heading:
            continue
        window = lines[i:i + 60]
        try:
            head = window.index("Name")
        except ValueError:
            continue
        cols = []
        k = head
        while k < len(window) and window[k] in ("Name", "Bytes", "Hits") and len(cols) < 3:
            cols.append(window[k].lower())
            k += 1
        rows, body = [], window[k:]
        step = len(cols)
        for j in range(0, len(body) - step + 1, step):
            chunk = body[j:j + step]
            if any(" | Page " in cell for cell in chunk) or chunk[0] in _TOP_SECTIONS:
                break
            row = {"name": chunk[0]}
            for label, value in zip(cols[1:], chunk[1:]):
                row[label] = _to_int(value) if label == "hits" else value
            rows.append(row)
        if rows:
            return rows
    return []


def _to_int(value):
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else 0
