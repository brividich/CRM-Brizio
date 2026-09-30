import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from security.services.dedup import make_hash
from .base import BaseParser, ParsedRecord, ParsedReport
from .registry import parser_registry

# Ordine = precedenza: «non è stata completata» contiene «completata» e «completata con avvisi»
# e' un avviso, non un successo. Prima il peggiore.
STATUS_PATTERNS = (
    ("failed", ("non riuscita", "non è stata completata", "non e' stata completata", "non completata", "fallita", "failed", "errore", "error")),
    ("warning", ("parzialmente", "avviso", "avvisi", "warning", "partial")),
    ("completed", ("completata", "completed", "success", "riuscita")),
)

_DT = r"(\d{1,2}[/.]\d{1,2}[/.]\d{4}\s+\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2})"
_START = re.compile(r"(?:ora\s+d['`]?\s*(?:i\s+)?inizio|ora\s+inizio|start\s+time|inizio)\s*[:：]?\s*" + _DT, re.I)
_END = re.compile(r"(?:ora\s+d[i'`]?\s*fine|ora\s+fine|end\s+time|fine)\s*[:：]?\s*" + _DT, re.I)
_SIZE = re.compile(r"(?:dimensioni?\s+trasferit[ae]|transferred\s+size|dati\s+trasferiti)\s*[:：]?\s*([0-9][0-9.,]*)\s*(kb|mb|gb|tb)", re.I)
_DEVICES = re.compile(r"(?:elenco\s+dispositivi|dispositivi|dispositivo|device\s+list|devices?)\s*[:：]\s*([^\r\n]+)", re.I)


def _normalize(text):
    """Apostrofi tipografici (d’inizio) e spazi non separabili: le mail Synology li usano."""
    return (text or "").replace("’", "'").replace("‘", "'").replace(" ", " ")


def parse_synology_active_backup_email(subject, body, sender=None, received_at=None):
    subject = _normalize(subject)
    body = _normalize(body)
    text = f"{subject}\n{body}"
    status = _parse_status(text)
    job_name, nas_name = _parse_job_and_nas(text)
    start_time = _parse_datetime(_first_group(_START, body))
    end_time = _parse_datetime(_first_group(_END, body))
    duration_seconds = int((end_time - start_time).total_seconds()) if start_time and end_time and end_time >= start_time else None
    size = _SIZE.search(body)
    transferred_size_gb = _parse_size_gb(size.groups()) if size else None
    devices = _parse_devices(body)
    device_name = ", ".join(devices)

    normalized_hash = make_hash("synology", job_name, device_name, _iso(start_time), _iso(end_time), status)
    raw_body_hash = make_hash(subject, body)
    return {
        "source": "synology",
        "vendor": "synology",
        "job_name": job_name or "unknown",
        "nas_name": nas_name or "",
        "device_name": device_name,
        "devices": devices,
        "status": status,
        "start_time": _iso(start_time),
        "end_time": _iso(end_time),
        "duration_seconds": duration_seconds,
        "transferred_size_gb": transferred_size_gb,
        "subject": subject,
        "sender": sender or "",
        "received_at": _iso(received_at),
        "dedup_hash": normalized_hash,
        "raw_body_hash": raw_body_hash,
    }


class SynologyActiveBackupEmailParser(BaseParser):
    name = "synology_active_backup_email_parser"

    def can_parse(self, item) -> bool:
        subject = _normalize(getattr(item, "subject", "")).lower()
        body = _normalize(getattr(item, "body", "")).lower()
        text = f"{subject}\n{body}"
        return (
            "active backup for business" in text
            or ("attività" in text and "backup" in text and ("ora d'inizio" in text or "ora inizio" in text or "ora di inizio" in text))
            or ("synology" in text and "backup" in text)
        )

    def parse(self, item) -> ParsedReport:
        payload = parse_synology_active_backup_email(
            item.subject,
            item.body,
            sender=getattr(item, "sender", None),
            received_at=getattr(item, "received_at", None),
        )
        metrics = _metrics_for_payload(payload)
        record = ParsedRecord(
            record_type="backup_job",
            payload={**payload, "protected_items": len(payload["devices"]) or _parse_protected_items(item.body), "source_message_id": getattr(item, "pk", None)},
            metrics=metrics,
        )
        return ParsedReport(
            report_type="synology_active_backup",
            title=item.subject,
            parser_name=self.name,
            records=[record],
            metrics=metrics,
            payload=payload,
        )


def _parse_status(text):
    normalized = (text or "").lower()
    for status, tokens in STATUS_PATTERNS:
        if any(token in normalized for token in tokens):
            return status
    return "unknown"


def _parse_job_and_nas(text):
    match = re.search(r"backup\s+([A-Za-z0-9_.-]+)\s+su\s+([A-Za-z0-9_.-]+)", text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.search(r"(?:backup\s+)?(?:task|job)\s+([A-Za-z0-9_.-]+)\s+on\s+([A-Za-z0-9_.-]+)", text or "", re.IGNORECASE)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    job = _match(r"(?:job|task):\s*([^\r\n]+)", text) or _match(r"attivit[aà]\s+(?:di\s+)?backup\s+([^\s]+)", text)
    nas = _match(r"\bsu\s+([A-Z0-9_.-]+)", text)
    return job, nas


def _parse_datetime(value):
    if not value:
        return None
    value = value.strip().replace("T", " ")
    for fmt in ("%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            parsed = timezone.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed
    return None


def _decimal(amount):
    """«522.6», «522,6», «1.234,5», «1,234.5» -> Decimal."""
    text = amount.strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    return Decimal(text)


def _parse_size_gb(groups):
    amount, unit = groups
    try:
        value = _decimal(amount)
    except InvalidOperation:
        return None
    unit = unit.lower()
    if unit == "kb":
        value = value / Decimal("1048576")
    elif unit == "mb":
        value = value / Decimal("1024")
    elif unit == "tb":
        value = value * Decimal("1024")
    return float(value)


def _parse_devices(body):
    match = _DEVICES.search(body or "")
    if not match:
        return []
    return [name.strip() for name in re.split(r"[,;]", match.group(1)) if name.strip()]


def _parse_protected_items(body):
    value = _match(r"Protected items?:\s*(\d+)", body)
    return int(value) if value else 0


def _metrics_for_payload(payload):
    status = payload["status"]
    metrics = {
        "backup_completed_count": 1 if status == "completed" else 0,
        "backup_failed_count": 1 if status == "failed" else 0,
        "backup_warning_count": 1 if status == "warning" else 0,
    }
    if payload.get("transferred_size_gb") is not None:
        metrics["backup_transferred_total_gb"] = payload["transferred_size_gb"]
    if payload.get("duration_seconds") is not None:
        metrics["backup_duration_seconds"] = payload["duration_seconds"]
    if payload.get("device_name"):
        metrics["backup_devices_backed_up"] = len(payload.get("devices") or [1])
    return metrics


def _first_group(pattern, text):
    match = pattern.search(text or "")
    return match.group(1) if match else None


def _match(pattern, text):
    match = re.search(pattern, text or "", re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    if len(match.groups()) > 1:
        return match.groups()
    return match.group(1).strip()


def _iso(value):
    return value.isoformat() if value else None


parser_registry.register(SynologyActiveBackupEmailParser())
