"""Utilita' per i report WatchGuard in PDF: il testo esce una cella per riga."""
import re
from datetime import datetime

from .common import parse_number

_FROM_TO = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")


def lines_of(text):
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def period_from_text(text):
    """Periodo dal «From ... To ...» del report (orario locale del firewall).

    Il periodo nel nome file e' in UTC (22:00 -> 21:59) e sposterebbe la data del report
    al giorno prima: il testo dice invece il giorno che il report descrive davvero.
    """
    lines = lines_of(text)
    found = {}
    for i, line in enumerate(lines[:60]):
        key = line.lower()
        if key in ("from", "to") and key not in found and i + 1 < len(lines):
            match = _FROM_TO.search(lines[i + 1])
            if match:
                found[key] = f"{match.group(1)} {match.group(2)}:00"
    start, end = found.get("from"), found.get("to")
    return start, end, (start or "")[:10] or None


def find_line(lines, label, start=0, exact=True):
    label = label.lower()
    for i in range(start, len(lines)):
        current = lines[i].lower()
        if (current == label) if exact else current.startswith(label):
            return i
    return -1


def value_after(lines, label, start=0, exact=True):
    """Riga che segue l'etichetta (i valori dei PDF sono sotto le etichette)."""
    i = find_line(lines, label, start, exact)
    return lines[i + 1] if 0 <= i < len(lines) - 1 else None


def leading_int(value):
    """«3,817 (100.0 %)» -> 3817; testo senza numero -> None."""
    match = re.match(r"\s*(\d[\d.,]*)", str(value or ""))
    if not match:
        return None
    return int(float(match.group(1).replace(",", "")))


def short_number(value):
    """«12.5K», «37.9M», «2.84K» -> numero."""
    return parse_number(value)


def section(lines, heading, stop_headings):
    """Righe dal titolo di sezione (riga esatta) al titolo successivo."""
    start = find_line(lines, heading)
    if start < 0:
        return []
    end = len(lines)
    for other in stop_headings:
        j = find_line(lines, other, start + 1)
        if j >= 0:
            end = min(end, j)
    return lines[start + 1:end]


def parse_us_datetime(value):
    """«9/29/2026 12:35 PM» o «Tuesday, September 29, 2026 | 10:00 AM»."""
    text = str(value or "").strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%A, %B %d, %Y | %I:%M %p"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
