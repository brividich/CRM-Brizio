"""Riconoscimento del tipo di report WatchGuard.

Prima si cercavano parole sparse nel testo: un PDF «Executive Dashboard» che elenca
«Zero-Day Malware» tra i suoi capitoli finiva nel parser Zero-Day, mentre Executive
Summary, Interface Summary e il report EPDR non venivano riconosciuti perche' il testo
non contiene «watchguard». Ora si guarda il TITOLO del documento (prima riga), poi
l'intestazione del CSV, poi il nome file.
"""
import re

AUTH_ALLOWED = "auth_allowed"
AUTH_DENIED = "auth_denied"
EXECUTIVE_SUMMARY = "executive_summary"
EXECUTIVE_DASHBOARD = "executive_dashboard"
INTERFACE_SUMMARY = "interface_summary"
SDWAN = "sdwan"
ZERO_DAY = "zero_day"
EPDR_REPORT = "epdr_report"
EPDR_THREAT_MAIL = "epdr_threat_mail"
THREATSYNC_LIST = "threatsync_list"
THREATSYNC_SUMMARY = "threatsync_summary"
DIMENSION = "dimension_summary"

_VENDOR_WORDS = re.compile(r"\b(watchguard|firebox|threatsync|epdr|dimension)\b", re.I)


def _first_lines(text, count=3):
    lines = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if line:
            lines.append(line.lower())
            if len(lines) == count:
                break
    return lines


def detect_report(source_name="", text="", subject=""):
    """Tipo di report, o None se non sembra un report WatchGuard."""
    name = str(source_name or "").lower()
    subject = str(subject or "").lower()
    text = str(text or "")
    lines = _first_lines(text)
    first = lines[0] if lines else ""
    head = text[:3000].lower()

    # CSV delle autenticazioni: se il nome file dice Denied/Allowed vale quello, altrimenti
    # l'intestazione (Denied ha la colonna `reason`).
    if "authentication" in name and ("denied" in name or "allowed" in name):
        return AUTH_DENIED if "denied" in name else AUTH_ALLOWED
    if first.startswith("user,") and "ip" in first and "login" in first:
        return AUTH_DENIED if "reason" in first else AUTH_ALLOWED
    if "authentication" in name:
        return None

    # Mail EPDR «Threats detected between ...»
    if "threats detected between" in subject or ("threats detected between" in head and "affected computer" in head):
        return EPDR_THREAT_MAIL

    # PDF/testo: titolo del documento.
    titles = " | ".join(lines[:2])
    if first.startswith("executive summary") or "executive_summary" in name or "executive summary" in name:
        return EXECUTIVE_SUMMARY
    if first.startswith("executive dashboard") or "executive_dashboard" in name or "executive dashboard" in name:
        return EXECUTIVE_DASHBOARD
    if first.startswith("interface summary") or "interface summary" in name or "interface_summary" in name:
        return INTERFACE_SUMMARY
    if first.startswith("sd-wan") or "sd-wan" in name or "sdwan" in name:
        return SDWAN
    if first.startswith("zero-day") or "zero_day" in name or "zero-day" in name:
        return ZERO_DAY
    if "executive report" in titles and ("license status" in head or "network security status" in head):
        return EPDR_REPORT
    if "threatsync" in name or "threatsync" in subject or "threatsync" in first:
        first_data_line = str(text or "").splitlines()[0] if str(text or "").strip() else ""
        return THREATSYNC_LIST if "," in first_data_line else THREATSYNC_SUMMARY
    if "epdr" in name or "epdr" in subject:
        return EPDR_REPORT
    if re.search(r"\bdimension\b", name + " " + subject) or "botnet detection" in head:
        return DIMENSION
    return None


def looks_like_watchguard(item_parts, text=""):
    """Vero se il mittente/oggetto/nome file citano WatchGuard (mai il corpo generico)."""
    return bool(_VENDOR_WORDS.search(" ".join(str(part or "") for part in item_parts)))
