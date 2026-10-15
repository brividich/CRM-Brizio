"""Mail di esito di Veeam Backup & Replication («[Success] Backup ... (4 objects)»).

Il corpo ha un riepilogo (stato, orari, dimensioni, durata) e una tabella per macchina
virtuale, separati da tabulazioni. Un job = un record di backup; le macchine restano nel
payload perche' contarle come job gonfierebbe i KPI di completati/falliti.
"""
import re
from datetime import timedelta

from django.utils import timezone

from security.services.dedup import make_hash
from .base import BaseParser, Lettura, ParsedRecord, ParsedReport
from .registry import parser_registry
from .synology_active_backup_email_parser import _parse_size_gb

_SUBJECT_STATUS = re.compile(r"^\s*\[(success|warning|failed|error)\]", re.I)
_STATUS_MAP = {"success": "completed", "warning": "warning", "failed": "failed", "error": "failed"}
_STATUS_LABELS = {"completed": "Riuscito", "warning": "Con avvisi", "failed": "Non riuscito"}
_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_LONG_DATE = re.compile(r"(\d{1,2})\s+([A-Za-zàèéìòù]+)\s+(\d{4})|([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
_SIZE_FIELD = r"{}\s+([0-9][0-9.,]*\s*[KMGT]B)"
_TIME = r"(\d{1,2}:\d{2}:\d{2})"


class VeeamBackupEmailParser(BaseParser):
    name = "veeam_backup_email_parser"

    def can_parse(self, item) -> bool:
        subject = str(getattr(item, "subject", "") or "")
        body = str(getattr(item, "body", "") or "")
        low = body.lower()
        if "veeam backup" in low:
            return True
        return bool(_SUBJECT_STATUS.match(subject)) and "backup job:" in low

    def perche_riconosce(self, item):
        subject = str(getattr(item, "subject", "") or "")
        low = str(getattr(item, "body", "") or "").lower()
        reasons = []
        if "veeam backup" in low:
            reasons.append("Il testo cita «Veeam Backup»")
        tag = _SUBJECT_STATUS.match(subject)
        if tag:
            reasons.append(f"Oggetto con l'esito tra parentesi quadre («[{tag.group(1)}]»)")
        if "backup job:" in low:
            reasons.append("Ha la riga «Backup job:»")
        return reasons

    def parse(self, item) -> ParsedReport:
        payload = parse_veeam_email(item.subject, item.body, getattr(item, "sender", None), getattr(item, "received_at", None))
        metrics = _metrics(payload)
        record = ParsedRecord(
            record_type="backup_job",
            payload={**payload, "source_message_id": getattr(item, "pk", None)},
            metrics=metrics,
        )
        return ParsedReport(
            report_type="veeam_backup_job",
            title=item.subject,
            parser_name=self.name,
            records=[record],
            metrics=metrics,
            payload=payload,
        )


def parse_veeam_email(subject, body, sender=None, received_at=None):
    subject, body = subject or "", body or ""
    job = _search(r"job:\s*(.+)", body) or re.sub(r"^\s*\[[^\]]+\]\s*|\s*\(\d+\s+objects?\)\s*$", "", subject, flags=re.I).strip()
    tag = _SUBJECT_STATUS.match(subject)
    status = _STATUS_MAP[tag.group(1).lower()] if tag else _status_from_body(body)
    processed = re.search(r"(\d+)\s+of\s+(\d+)\s+(?:VMs?|objects?|machines?|computers?)\s+processed", body, re.I)
    day = _long_date(body)
    day_from_mail = False
    if day is None and received_at is not None:
        # Senza la data in testo gli orari andavano persi: si usa il giorno di ricezione.
        day, day_from_mail = timezone.localtime(received_at).date() if timezone.is_aware(received_at) else received_at.date(), True
    start_time = _at(day, _search(r"Start time\s+" + _TIME, body))
    end_time = _at(day, _search(r"End time\s+" + _TIME, body))
    if start_time and end_time and end_time < start_time:
        end_time += timedelta(days=1)  # il job e' passato oltre la mezzanotte
    duration = _search(r"Duration\s+(\d+:\d{2}:\d{2})", body)
    counts = {label.lower(): int(value) for label, value in re.findall(r"^\s*(Success|Warning|Error)\s+(\d+)\b", body, re.M | re.I)}
    objects = _objects(body)
    transferred = _size(r"Transferred", body)
    raw_body_hash = make_hash(subject, body)
    if start_time or end_time:
        dedup = make_hash("veeam", job, _iso(start_time), _iso(end_time), status)
    else:
        # Job+stato da soli sono uguali ogni giorno: il secondo «[Success]» veniva scartato
        # come duplicato e il job sembrava fermo al primo esito.
        dedup = make_hash("veeam", job, status, _iso(received_at), raw_body_hash)

    lettura = Lettura("Esito job Veeam Backup & Replication")
    lettura.campo("Esito", _STATUS_LABELS.get(status, ""), obbligatorio=True)
    lettura.campo("Nome del job", job, obbligatorio=True)
    lettura.campo("Inizio", _iso(start_time))
    lettura.campo("Fine", _iso(end_time))
    lettura.campo("Macchine", [row["name"] for row in objects])
    lettura.campo("Dati trasferiti (GB)", round(transferred, 3) if transferred is not None else None)
    if day_from_mail and (start_time or end_time):
        lettura.avviso("Data del job non trovata nel testo: usata la data di ricezione della mail")
    if not (start_time or end_time):
        lettura.avviso("Orari di inizio e fine non trovati: per distinguere i giorni si usa la data di ricezione della mail")
    if status == "unknown":
        lettura.avviso("Esito non riconosciuto (né «[Success]/[Warning]/[Failed]» nell'oggetto né nel testo): il job non conta come riuscito")
    if processed and objects and int(processed.group(2)) != len(objects):
        lettura.avviso(f"La mail dichiara {processed.group(2)} macchine ma la tabella ne elenca {len(objects)}")
    return {
        "source": "veeam",
        "vendor": "veeam",
        "job_name": job or "unknown",
        "status": status,
        "start_time": _iso(start_time),
        "end_time": _iso(end_time),
        "duration_seconds": _seconds(duration) if duration else (int((end_time - start_time).total_seconds()) if start_time and end_time else None),
        "transferred_size_gb": transferred,
        "total_size_gb": _size(r"Total size", body),
        "backup_size_gb": _size(r"Backup size", body),
        "data_read_gb": _size(r"Data read", body),
        "objects_processed": int(processed.group(1)) if processed else len(objects),
        "objects_total": int(processed.group(2)) if processed else len(objects),
        "objects_ok": counts.get("success"),
        "objects_warning": counts.get("warning"),
        "objects_error": counts.get("error"),
        "objects": objects,
        "protected_items": int(processed.group(1)) if processed else len(objects),
        "device_name": "",
        "subject": subject,
        "sender": sender or "",
        "received_at": _iso(received_at),
        "dedup_hash": dedup,
        "raw_body_hash": raw_body_hash,
        "parse_warnings": list(lettura.avvisi),
        "lettura": lettura.as_dict(),
    }


def _status_from_body(body):
    for line in body.splitlines()[:8]:
        word = line.strip().lower()
        if word in _STATUS_MAP:
            return _STATUS_MAP[word]
    return "unknown"


def _search(pattern, text):
    match = re.search(pattern, text or "", re.I | re.M)
    return match.group(1).strip() if match else None


def _long_date(body):
    for match in _LONG_DATE.finditer(body):
        if match.group(1):
            day, month, year = int(match.group(1)), _MONTHS.get(match.group(2).lower()), int(match.group(3))
        else:
            day, month, year = int(match.group(5)), _MONTHS.get(match.group(4).lower()), int(match.group(6))
        if month:
            return timezone.datetime(year, month, day).date()
    return None


def _at(day, clock):
    if not day or not clock:
        return None
    hour, minute, second = (int(part) for part in clock.split(":"))
    naive = timezone.datetime(day.year, day.month, day.day, hour, minute, second)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _seconds(value):
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _size(label, body):
    match = re.search(_SIZE_FIELD.format(label), body, re.I)
    if not match:
        return None
    amount, unit = re.match(r"([0-9][0-9.,]*)\s*([KMGT]B)", match.group(1), re.I).groups()
    return _parse_size_gb((amount, unit))


def _objects(body):
    """Righe della tabella «Name Status Start time End time Size Read Transferred Duration»."""
    rows = []
    for line in body.splitlines():
        cells = [cell.strip() for cell in line.split("\t")]
        if len(cells) >= 8 and cells[1].lower() in ("success", "warning", "failed", "error"):
            rows.append({
                "name": cells[0], "status": _STATUS_MAP[cells[1].lower()], "start": cells[2], "end": cells[3],
                "size": cells[4], "read": cells[5], "transferred": cells[6], "duration": cells[7],
                "details": cells[8] if len(cells) > 8 else "",
            })
    return rows


def _metrics(payload):
    status = payload["status"]
    metrics = {
        "backup_completed_count": 1 if status == "completed" else 0,
        "backup_failed_count": 1 if status == "failed" else 0,
        "backup_warning_count": 1 if status == "warning" else 0,
        "backup_objects_processed": payload.get("objects_processed") or 0,
    }
    if payload.get("transferred_size_gb") is not None:
        metrics["backup_transferred_total_gb"] = payload["transferred_size_gb"]
    if payload.get("duration_seconds") is not None:
        metrics["backup_duration_seconds"] = payload["duration_seconds"]
    if payload.get("backup_size_gb") is not None:
        metrics["backup_size_total_gb"] = payload["backup_size_gb"]
    return metrics


def _iso(value):
    return value.isoformat() if value else None


parser_registry.register(VeeamBackupEmailParser())
