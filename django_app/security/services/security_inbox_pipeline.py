"""
Shared Security Inbox processing pipeline.
Processes mailbox messages, source files, and text payloads through parser/rule/KPI/alert/evidence pipeline.
"""
import logging
from typing import Optional, Dict, Any

from django.utils import timezone

from security.models import (
    SecurityMailboxMessage,
    SecuritySourceFile,
    SecurityReport,
    SecurityAlert,
    SecurityEvidenceContainer,
    SecurityRemediationTicket,
    SecurityReportMetric,
    SecurityEventRecord,
    ParseStatus,
    SourceType,
)
from security.services.parser_engine import _match_enabled_parser, run_pending_parsers
from security.services.rule_engine import evaluate_security_rules

logger = logging.getLogger(__name__)

_SECRET_LIKE_KEYS = frozenset({"password", "secret", "token", "api_key", "credential", "auth", "key"})


def summarize_pipeline_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a compact, safe summary of a pipeline result dict. No raw content."""
    if not result:
        return {"status": "unknown"}
    errors = result.get("errors") or []
    warnings = result.get("warnings") or []
    short_error = ""
    if errors:
        raw = str(errors[0])
        for k in _SECRET_LIKE_KEYS:
            if k in raw.lower():
                raw = "[redacted]"
                break
        short_error = raw[:200]
    return {
        "status": result.get("status", "unknown"),
        "parser_detected": bool(result.get("parser_matched")),
        "parser_name": str(result.get("parser_name") or ""),
        "metrics_count": int(result.get("metrics_created") or 0),
        "findings_count": int(result.get("events_created") or 0),
        "alerts_count": int(result.get("alerts_created") or 0),
        "evidence_created": int(result.get("evidence_created") or 0),
        "ticket_created": int(result.get("tickets_changed") or 0),
        "warnings_count": len(warnings),
        "errors_count": len(errors),
        "short_error": short_error,
    }


def process_mailbox_message(message: SecurityMailboxMessage, *, source=None, run=None, dry_run=False) -> Dict[str, Any]:
    """Process imported mailbox message through parser/rule pipeline."""
    if message.parse_status not in (ParseStatus.PENDING, ParseStatus.FAILED):
        logger.debug(f"Message {message.id} already processed with status {message.parse_status}")
        return {"status": "already_processed", "processed": False}

    if dry_run:
        return {"status": "dry_run", "processed": False}

    result = _process_inbox_item(message)

    message.parse_status = ParseStatus.PARSED if result["status"] == "success" else ParseStatus.FAILED
    message.pipeline_result = {k: v for k, v in result.items() if k not in ("errors", "warnings")}
    message.save(update_fields=["parse_status", "pipeline_result"])

    return result


def process_source_file(source_file: SecuritySourceFile, *, message=None, source=None, run=None, dry_run=False) -> Dict[str, Any]:
    """Process imported source file through parser/rule pipeline."""
    if source_file.parse_status not in (ParseStatus.PENDING, ParseStatus.FAILED):
        logger.debug(f"File {source_file.id} already processed with status {source_file.parse_status}")
        return {"status": "already_processed", "processed": False}

    if dry_run:
        return {"status": "dry_run", "processed": False}

    result = _process_inbox_item(source_file)

    source_file.parse_status = ParseStatus.PARSED if result["status"] == "success" else ParseStatus.FAILED
    source_file.save(update_fields=["parse_status"])

    return result


def process_text_payload(text: str, *, subject: str = "", sender: str = "", source=None, dry_run=False) -> Dict[str, Any]:
    """Process a raw text payload by creating a transient SecurityMailboxMessage and running the pipeline."""
    if dry_run:
        return {"status": "dry_run", "processed": False}

    if not text and not subject:
        return {"status": "skipped", "processed": False, "warnings": ["Empty payload"], "errors": []}

    from security.services.ingestion import get_or_create_source
    if source is None:
        source = get_or_create_source("Manual Inbox", "", SourceType.EMAIL)

    message = SecurityMailboxMessage.objects.create(
        source=source,
        subject=subject or "Text payload",
        body=text,
        sender=sender,
        raw_payload={"payload_mode": "text"},
    )
    return process_mailbox_message(message, dry_run=False)


def process_security_input(item, *, source=None, run=None, dry_run=False) -> Dict[str, Any]:
    """Dispatch to the correct pipeline function based on item type."""
    if isinstance(item, SecuritySourceFile):
        return process_source_file(item, source=source, run=run, dry_run=dry_run)
    if isinstance(item, SecurityMailboxMessage):
        return process_mailbox_message(item, source=source, run=run, dry_run=dry_run)
    return {"status": "error", "processed": False, "errors": [f"Unknown item type: {type(item).__name__}"], "warnings": []}


def _process_inbox_item(item) -> Dict[str, Any]:
    """Core processing logic for inbox items (messages or files)."""
    result = {
        "status": "success",
        "parser_matched": False,
        "parser_name": "",
        "reports_parsed": 0,
        "metrics_created": 0,
        "events_created": 0,
        "alerts_created": 0,
        "evidence_created": 0,
        "tickets_changed": 0,
        "warnings": [],
        "errors": [],
    }

    parser = _match_enabled_parser(item)
    if parser:
        result["parser_matched"] = True
        result["parser_name"] = parser.name
    else:
        result["status"] = "skipped"
        result["warnings"].append("No parser matched this item")
        return result

    before = _pipeline_counts()

    try:
        parsed_count = run_pending_parsers()
        item.refresh_from_db()
        after_parse = _pipeline_counts()

        evaluated = evaluate_security_rules()
        after_rules = _pipeline_counts()

        linked_reports = _reports_for_item(item)
        if linked_reports:
            report = linked_reports[0]
            result["parser_name"] = report.parser_name
            result["warnings"].extend((report.parsed_payload or {}).get("parse_warnings", [])[:5])

        result["reports_parsed"] = len(linked_reports) or parsed_count
        result["metrics_created"] = max(after_parse["metrics"] - before["metrics"], 0)
        result["events_created"] = max(after_parse["events"] - before["events"], 0)
        result["alerts_created"] = max(after_rules["alerts"] - before["alerts"], 0)
        result["evidence_created"] = max(after_rules["evidence"] - before["evidence"], 0)
        result["tickets_changed"] = max(after_rules["tickets"] - before["tickets"], 0)

        if getattr(item, "parse_status", "") == ParseStatus.FAILED:
            result["status"] = "error"
            error = (getattr(item, "raw_payload", {}) or {}).get("parser_error")
            if error:
                result["errors"].append(error)
        elif getattr(item, "parse_status", "") == ParseStatus.SKIPPED:
            result["status"] = "skipped"

    except Exception as exc:
        logger.exception(f"Pipeline processing failed for item {item.id}: {exc}")
        result["status"] = "error"
        result["errors"].append(str(exc))

    return result


def _pipeline_counts():
    """Get current pipeline entity counts."""
    return {
        "reports": SecurityReport.objects.count(),
        "metrics": SecurityReportMetric.objects.count(),
        "events": SecurityEventRecord.objects.count(),
        "alerts": SecurityAlert.objects.count(),
        "evidence": SecurityEvidenceContainer.objects.count(),
        "tickets": SecurityRemediationTicket.objects.count(),
    }


def _reports_for_item(item):
    """Get reports linked to an inbox item."""
    reports = SecurityReport.objects.select_related("source").order_by("-created_at")
    if isinstance(item, SecuritySourceFile):
        return list(reports.filter(source_file=item)[:5])
    return list(reports.filter(mailbox_message=item)[:5])
