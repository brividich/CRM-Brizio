import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from security.services.dedup import make_hash
from .base import BaseParser, ParsedRecord, ParsedReport
from .registry import parser_registry


STATUS_PATTERNS = (
    ("completed", ("completata", "completed")),
    ("failed", ("non riuscita", "failed", "errore")),
    ("warning", ("avviso", "warning")),
)


def parse_synology_active_backup_email(subject, body, sender=None, received_at=None):
    subject = subject or ""
    body = body or ""
    text = f"{subject}\n{body}"
    status = _parse_status(text)
    job_name, nas_name = _parse_job_and_nas(text)
    start_time = _parse_datetime(_match(r"ora\s+inizio\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}\s+[0-9]{1,2}:[0-9]{2})", body))
    end_time = _parse_datetime(_match(r"ora\s+fine\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{4}\s+[0-9]{1,2}:[0-9]{2})", body))
    duration_seconds = int((end_time - start_time).total_seconds()) if start_time and end_time else None
    transferred_size_gb = _parse_size_gb(_match(r"dimensioni\s+trasferite\s+([0-9]+(?:[.,][0-9]+)?)\s*(gb|mb|tb)", body))
    device_name = _match(r"dispositivo\s+([^\r\n]+)", body)

    normalized_hash = make_hash("synology", job_name, device_name, _iso(start_time), _iso(end_time), status)
    raw_body_hash = make_hash(subject, body)
    return {
        "source": "synology",
        "vendor": "synology",
        "job_name": job_name or "unknown",
        "nas_name": nas_name or "",
        "device_name": device_name or "",
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
        subject = getattr(item, "subject", "").lower()
        body = getattr(item, "body", "").lower()
        text = f"{subject}\n{body}"
        return (
            "active backup for business" in text
            or ("attività" in text and "backup" in text and "ora inizio" in text)
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
            payload={**payload, "protected_items": _parse_protected_items(item.body), "source_message_id": item.pk},
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
    match = re.search(
        r"(?:attivit[aà]\s+(?:di\s+)?backup|backup)\s+([A-Z0-9_.-]+)\s+su\s+([A-Z0-9_.-]+)\s+(?:completata|non riuscita|failed|completed|errore|avviso|warning)",
        text or "",
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), match.group(2).strip()
    job = _match(r"(?:job|task):\s*([^\r\n]+)", text) or _match(r"attivit[aà]\s+(?:di\s+)?backup\s+([^\s]+)", text)
    nas = _match(r"\bsu\s+([A-Z0-9_.-]+)", text)
    return job, nas


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = timezone.datetime.strptime(value.strip(), "%d/%m/%Y %H:%M")
    except ValueError:
        return None
    return timezone.make_aware(parsed, timezone.get_current_timezone()) if timezone.is_naive(parsed) else parsed


def _parse_size_gb(match):
    if not match:
        return None
    amount, unit = match
    try:
        value = Decimal(amount.replace(",", "."))
    except InvalidOperation:
        return None
    unit = unit.lower()
    if unit == "mb":
        value = value / Decimal("1024")
    elif unit == "tb":
        value = value * Decimal("1024")
    return float(value)


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
        metrics["backup_devices_backed_up"] = 1
    return metrics


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
