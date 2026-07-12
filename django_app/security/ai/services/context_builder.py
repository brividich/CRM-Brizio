"""Context builder for AI chat - constructs secure messages with application context"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from django.contrib.auth.models import User
from django.utils import timezone

from ..services.redaction import redact_ai_context, redact_text
from ...models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityEvidenceContainer,
    SecurityEvidenceItem,
    SecurityRemediationTicket,
    SecurityReport,
    SecurityVulnerabilityFinding,
    SecurityEventRecord,
    SecuritySourceFile,
    SecurityMailboxMessage,
)
from ...permissions import can_view_security_center

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 10
MAX_CONTENT_LENGTH = 4000

# Rich report context limits
MAX_REPORT_CONTEXT_CHARS = 30000
MAX_PARSED_PAYLOAD_CHARS = 8000
MAX_MAIL_BODY_CHARS = 8000
MAX_PIPELINE_RESULT_CHARS = 4000
MAX_MAIL_RAW_PAYLOAD_CHARS = 4000
MAX_EVENT_PAYLOAD_CHARS = 4000
MAX_EVENT_DECISION_TRACE_CHARS = 3000
MAX_SOURCE_FILE_CONTENT_CHARS = 8000
MAX_SOURCE_FILE_RAW_PAYLOAD_CHARS = 4000
MAX_EVIDENCE_ITEM_CHARS = 3000

CONTEXT_DIR = Path(__file__).parent.parent / "context"
ALLOWED_OBJECT_TYPES = {"dashboard", "alert", "report", "ticket", "evidence"}
SAFE_UNAVAILABLE_CONTEXT = {"error": "requested object not found or unavailable"}


def safe_json_dumps(value: Any, indent: Optional[int] = None) -> str:
    """Safely serialize value to JSON string, handling non-serializable types"""
    try:
        return json.dumps(value, default=str, ensure_ascii=False, indent=indent)
    except Exception as e:
        logger.warning(f"Failed to serialize value to JSON: {e}")
        return str(value)


def value_char_len(value: Any) -> int:
    """Calculate character length of a value"""
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (dict, list)):
        return len(safe_json_dumps(value))
    return len(str(value))


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max characters, adding ellipsis if truncated"""
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def redact_and_truncate(value: Any, max_chars: int) -> Any:
    """Redact and truncate a value for safe AI context"""
    if value is None:
        return None

    # Redact first
    if isinstance(value, dict):
        redacted = redact_ai_context(value)
    elif isinstance(value, list):
        redacted = redact_ai_context(value)
    elif isinstance(value, str):
        redacted = redact_text(value)
    else:
        redacted = value

    # Then truncate if text
    if isinstance(redacted, str):
        if isinstance(value, str) and len(value) > max_chars and len(redacted) <= max_chars:
            return truncate_text(redacted + "...", max_chars)
        return truncate_text(redacted, max_chars)

    # For dict/list, check total length and truncate if needed
    if isinstance(redacted, (dict, list)):
        json_str = safe_json_dumps(redacted)
        if len(json_str) > max_chars:
            # Truncate the JSON string and try to parse back
            truncated_json = truncate_text(json_str, max_chars)
            try:
                return json.loads(truncated_json)
            except json.JSONDecodeError:
                # If parsing fails, return truncated string
                return truncated_json

    return redacted


def add_context_warning(context: Dict[str, Any], message: str) -> None:
    """Add a warning message to context warnings list"""
    if "warnings" not in context:
        context["warnings"] = []
    if message not in context["warnings"]:
        context["warnings"].append(message)


def section_ref(source_model: str, source_id: Any, section_id: str) -> str:
    """Generate a section reference string"""
    return f"{source_model}:{source_id}:{section_id}"


def load_context_file(filename: str) -> str:
    """Load markdown context file"""
    try:
        path = CONTEXT_DIR / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    except Exception as e:
        logger.warning(f"Failed to load context file {filename}: {e}")
        return ""


def sanitize_chat_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Sanitize chat history - only accept user/assistant, max 10 messages, max 4000 chars"""
    if not isinstance(history, list):
        return []

    sanitized = []
    for msg in history[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        content = msg.get("content", "")

        if role not in ("user", "assistant"):
            continue

        if not isinstance(content, str) or not content.strip():
            continue

        content = content[:MAX_CONTENT_LENGTH]
        sanitized.append({"role": role, "content": content})

    return sanitized


def get_alert_context(alert_id: int) -> Dict[str, Any]:
    """Get context for SecurityAlert"""
    try:
        alert = SecurityAlert.objects.select_related("source", "event").prefetch_related(
            "evidence_containers__items", "tickets", "action_logs"
        ).get(id=alert_id)

        context = {
            "type": "alert",
            "id": alert.id,
            "title": alert.title,
            "severity": alert.severity,
            "status": alert.status,
            "source": alert.source.name if alert.source else None,
            "source_type": alert.source.source_type if alert.source else None,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
            "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
            "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
            "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
            "snoozed_until": alert.snoozed_until.isoformat() if alert.snoozed_until else None,
            "status_reason": alert.status_reason,
            "owner": alert.owner,
            "dedup_hash": alert.dedup_hash,
            "decision_trace": alert.decision_trace,
        }

        if alert.event:
            context["event"] = {
                "event_type": alert.event.event_type,
                "severity": alert.event.severity,
                "payload": alert.event.payload,
                "occurred_at": alert.event.occurred_at.isoformat() if alert.event.occurred_at else None,
                "created_at": alert.event.created_at.isoformat() if alert.event.created_at else None,
            }

        evidence_containers = []
        for container in alert.evidence_containers.all()[:5]:
            container_data = {
                "id": str(container.id),
                "title": container.title,
                "status": container.status,
                "created_at": container.created_at.isoformat() if container.created_at else None,
            }
            items = []
            for item in container.items.all()[:10]:
                items.append(
                    {
                        "item_type": item.item_type,
                        "content": item.content,
                    }
                )
            container_data["items"] = items
            evidence_containers.append(container_data)
        context["evidence_containers"] = evidence_containers

        tickets = []
        for ticket in alert.tickets.all()[:5]:
            tickets.append(
                {
                    "id": ticket.id,
                    "title": ticket.title,
                    "status": ticket.status,
                    "severity": ticket.severity,
                    "cve": ticket.cve,
                    "cve_ids": ticket.cve_ids,
                    "affected_product": ticket.affected_product,
                    "max_cvss": ticket.max_cvss,
                    "max_exposed_devices": ticket.max_exposed_devices,
                    "occurrence_count": ticket.occurrence_count,
                }
            )
        context["tickets"] = tickets

        action_logs = []
        for log in alert.action_logs.all()[:10]:
            action_logs.append(
                {
                    "action": log.action,
                    "actor": log.actor,
                    "details": log.details,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
            )
        context["action_logs"] = action_logs

        return context
    except SecurityAlert.DoesNotExist:
        logger.warning(f"Alert {alert_id} not found")
        return {"error": "requested object not found or unavailable"}
    except Exception as e:
        logger.exception(f"Error getting alert context: {e}")
        return {"error": "error retrieving alert context"}


def get_report_context(report_id: int) -> Dict[str, Any]:
    """Get rich context for SecurityReport"""
    try:
        report = SecurityReport.objects.select_related(
            "source", "mailbox_message", "source_file"
        ).prefetch_related("metrics").get(id=report_id)

        context = {
            "context_available": True,
            "context_type": "report",
            "object_id": str(report_id),
            "type": "report",
            "id": report.id,
            "summary": {
                "title": report.title,
                "report_type": report.report_type,
                "report_date": report.report_date.isoformat() if report.report_date else None,
                "parser_name": report.parser_name,
                "parse_status": report.parse_status,
                "created_at": report.created_at.isoformat() if report.created_at else None,
            },
            "source": {
                "id": report.source.id if report.source else None,
                "name": report.source.name if report.source else None,
                "vendor": report.source.vendor if report.source else None,
                "source_type": report.source.source_type if report.source else None,
            },
            "main_object": {
                "report": {
                    "id": report.id,
                    "title": report.title,
                    "report_type": report.report_type,
                    "report_date": report.report_date.isoformat() if report.report_date else None,
                    "parser_name": report.parser_name,
                    "parse_status": report.parse_status,
                    "created_at": report.created_at.isoformat() if report.created_at else None,
                },
                "parsed_payload": redact_and_truncate(report.parsed_payload, MAX_PARSED_PAYLOAD_CHARS),
                "metrics": [],
            },
            "raw_extracts": {
                "mailbox_message": {
                    "available": False,
                    "id": None,
                    "subject": None,
                    "sender": None,
                    "received_at": None,
                    "parse_status": None,
                    "body_available": False,
                    "body_preview": None,
                    "pipeline_result_available": False,
                    "pipeline_result": None,
                    "raw_payload": None,
                    "references": [],
                },
                "source_file": {
                    "available": False,
                    "id": None,
                    "original_name": None,
                    "file_type": None,
                    "parse_status": None,
                    "uploaded_at": None,
                    "content_available": False,
                    "content_preview": None,
                    "raw_payload": None,
                    "references": [],
                },
            },
            "related": {
                "events": [],
                "vulnerabilities": [],
                "evidence_items": [],
                "linked_alerts": [],
            },
            "context_quality": {
                "score": 0,
                "level": "empty",
                "has_parsed_payload": False,
                "has_mail_body": False,
                "has_pipeline_result": False,
                "has_events": False,
                "has_event_payload": False,
                "has_metrics": False,
                "has_vulnerabilities": False,
                "has_evidence_items": False,
                "has_source_file_text": False,
                "missing_sections": [],
            },
            "limits": {
                "truncated": False,
                "max_context_chars": MAX_REPORT_CONTEXT_CHARS,
                "included_sections": [],
            },
            "warnings": [],
        }

        # Backward compatibility: maintain flat keys
        context["title"] = report.title
        context["report_type"] = report.report_type
        context["report_date"] = report.report_date.isoformat() if report.report_date else None
        context["parser_name"] = report.parser_name
        context["parse_status"] = report.parse_status
        context["source"] = report.source.name if report.source else None
        context["source_type"] = report.source.source_type if report.source else None

        # Include parsed_payload
        if report.parsed_payload:
            context["context_quality"]["has_parsed_payload"] = True
            context["context_quality"]["score"] += 20
            context["limits"]["included_sections"].append("parsed_payload")
        else:
            context["context_quality"]["missing_sections"].append("parsed_payload")

        # Include metrics (max 50)
        metrics = []
        for metric in report.metrics.all()[:50]:
            metrics.append(
                {
                    "name": metric.name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "labels": metric.labels,
                    "references": [section_ref("SecurityReport", report.id, f"metric:{metric.name}")],
                }
            )
        context["main_object"]["metrics"] = metrics
        context["metrics"] = metrics  # Backward compatibility

        if metrics:
            context["context_quality"]["has_metrics"] = True
            context["context_quality"]["score"] += 10
            context["limits"]["included_sections"].append("metrics")
        else:
            context["context_quality"]["missing_sections"].append("metrics")

        # Include mailbox_message if present
        if report.mailbox_message:
            mailbox = report.mailbox_message
            context["raw_extracts"]["mailbox_message"]["available"] = True
            context["raw_extracts"]["mailbox_message"]["id"] = mailbox.id
            context["raw_extracts"]["mailbox_message"]["subject"] = mailbox.subject
            context["raw_extracts"]["mailbox_message"]["sender"] = redact_text(mailbox.sender) if mailbox.sender else None
            context["raw_extracts"]["mailbox_message"]["received_at"] = mailbox.received_at.isoformat() if mailbox.received_at else None
            context["raw_extracts"]["mailbox_message"]["parse_status"] = mailbox.parse_status
            context["raw_extracts"]["mailbox_message"]["references"] = [
                section_ref("SecurityMailboxMessage", mailbox.id, "message")
            ]

            # Body preview
            if mailbox.body:
                context["raw_extracts"]["mailbox_message"]["body_available"] = True
                context["raw_extracts"]["mailbox_message"]["body_preview"] = redact_and_truncate(
                    mailbox.body, MAX_MAIL_BODY_CHARS
                )
                context["context_quality"]["has_mail_body"] = True
                context["context_quality"]["score"] += 15
                context["limits"]["included_sections"].append("mailbox_body")
            else:
                add_context_warning(context, "mailbox_message.body is empty or unavailable")
                context["context_quality"]["missing_sections"].append("mailbox_body")

            # Pipeline result
            if mailbox.pipeline_result:
                context["raw_extracts"]["mailbox_message"]["pipeline_result_available"] = True
                context["raw_extracts"]["mailbox_message"]["pipeline_result"] = redact_and_truncate(
                    mailbox.pipeline_result, MAX_PIPELINE_RESULT_CHARS
                )
                context["context_quality"]["has_pipeline_result"] = True
                context["context_quality"]["score"] += 10
                context["limits"]["included_sections"].append("pipeline_result")
            else:
                add_context_warning(context, "mailbox_message.pipeline_result is empty or unavailable")
                context["context_quality"]["missing_sections"].append("pipeline_result")

            # Raw payload
            if mailbox.raw_payload:
                context["raw_extracts"]["mailbox_message"]["raw_payload"] = redact_and_truncate(
                    mailbox.raw_payload, MAX_MAIL_RAW_PAYLOAD_CHARS
                )
                context["limits"]["included_sections"].append("mailbox_raw_payload")
        else:
            context["context_quality"]["missing_sections"].append("mailbox_message")

        # Include source_file if present
        if report.source_file:
            source_file = report.source_file
            context["raw_extracts"]["source_file"]["available"] = True
            context["raw_extracts"]["source_file"]["id"] = source_file.id
            context["raw_extracts"]["source_file"]["original_name"] = source_file.original_name
            context["raw_extracts"]["source_file"]["file_type"] = source_file.file_type
            context["raw_extracts"]["source_file"]["parse_status"] = source_file.parse_status
            context["raw_extracts"]["source_file"]["uploaded_at"] = source_file.uploaded_at.isoformat() if source_file.uploaded_at else None
            context["raw_extracts"]["source_file"]["references"] = [
                section_ref("SecuritySourceFile", source_file.id, "file")
            ]

            # Content preview
            if source_file.content:
                context["raw_extracts"]["source_file"]["content_available"] = True
                context["raw_extracts"]["source_file"]["content_preview"] = redact_and_truncate(
                    source_file.content, MAX_SOURCE_FILE_CONTENT_CHARS
                )
                context["context_quality"]["has_source_file_text"] = True
                context["context_quality"]["score"] += 10
                context["limits"]["included_sections"].append("source_file_content")
            else:
                context["context_quality"]["missing_sections"].append("source_file_content")

            # Raw payload
            if source_file.raw_payload:
                context["raw_extracts"]["source_file"]["raw_payload"] = redact_and_truncate(
                    source_file.raw_payload, MAX_SOURCE_FILE_RAW_PAYLOAD_CHARS
                )
                context["limits"]["included_sections"].append("source_file_raw_payload")
        else:
            context["context_quality"]["missing_sections"].append("source_file")

        # Include events (max 30)
        events = (
            SecurityEventRecord.objects.select_related("source", "asset")
            .filter(report=report)
            .order_by("-occurred_at")[:30]
        )
        event_list = []
        has_event_payload = False
        for event in events:
            event_data = {
                "id": event.id,
                "event_type": event.event_type,
                "severity": event.severity,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "suppressed": event.suppressed,
                "asset": event.asset.hostname if event.asset else None,
                "payload": redact_and_truncate(event.payload, MAX_EVENT_PAYLOAD_CHARS),
                "decision_trace": redact_and_truncate(event.decision_trace, MAX_EVENT_DECISION_TRACE_CHARS),
                "references": [section_ref("SecurityEventRecord", event.id, "event")],
            }
            event_list.append(event_data)
            if event.payload:
                has_event_payload = True
        context["related"]["events"] = event_list

        if event_list:
            context["context_quality"]["has_events"] = True
            context["context_quality"]["score"] += 15
            context["limits"]["included_sections"].append("events")
        else:
            context["context_quality"]["missing_sections"].append("events")

        if has_event_payload:
            context["context_quality"]["has_event_payload"] = True
            context["context_quality"]["score"] += 10
        else:
            context["context_quality"]["missing_sections"].append("event_payload")

        # Include vulnerabilities (max 50)
        vulnerabilities = (
            SecurityVulnerabilityFinding.objects.select_related("asset")
            .filter(report=report)
            .order_by("-last_seen_at")[:50]
        )
        vuln_list = []
        for vuln in vulnerabilities:
            vuln_list.append(
                {
                    "cve": vuln.cve,
                    "severity": vuln.severity,
                    "status": vuln.status,
                    "cvss": vuln.cvss,
                    "asset": vuln.asset.hostname if vuln.asset else None,
                    "affected_product": vuln.affected_product,
                    "exposed_devices": vuln.exposed_devices,
                    "payload": redact_and_truncate(vuln.payload, MAX_EVIDENCE_ITEM_CHARS),
                    "first_seen_at": vuln.first_seen_at.isoformat() if vuln.first_seen_at else None,
                    "last_seen_at": vuln.last_seen_at.isoformat() if vuln.last_seen_at else None,
                    "references": [section_ref("SecurityVulnerabilityFinding", vuln.id, "vulnerability")],
                }
            )
        context["related"]["vulnerabilities"] = vuln_list
        context["vulnerabilities"] = vuln_list  # Backward compatibility

        if vuln_list:
            context["context_quality"]["has_vulnerabilities"] = True
            context["context_quality"]["score"] += 10
            context["limits"]["included_sections"].append("vulnerabilities")
        else:
            context["context_quality"]["missing_sections"].append("vulnerabilities")

        # Include evidence items (max 30)
        evidence_items = (
            SecurityEvidenceItem.objects.select_related("container", "event")
            .filter(report=report)[:30]
        )
        evidence_list = []
        for item in evidence_items:
            evidence_list.append(
                {
                    "item_type": item.item_type,
                    "content": redact_and_truncate(item.content, MAX_EVIDENCE_ITEM_CHARS),
                    "container": {
                        "id": str(item.container.id) if item.container else None,
                        "title": item.container.title if item.container else None,
                        "status": item.container.status if item.container else None,
                    } if item.container else None,
                    "event": {
                        "id": item.event.id if item.event else None,
                        "event_type": item.event.event_type if item.event else None,
                    } if item.event else None,
                    "references": [section_ref("SecurityEvidenceItem", item.id, "evidence")],
                }
            )
        context["related"]["evidence_items"] = evidence_list

        if evidence_list:
            context["context_quality"]["has_evidence_items"] = True
            context["context_quality"]["score"] += 10
            context["limits"]["included_sections"].append("evidence_items")
        else:
            context["context_quality"]["missing_sections"].append("evidence_items")

        # Include linked alerts (max 30)
        linked_alerts = (
            SecurityAlert.objects.select_related("source", "event")
            .filter(event__report=report)
            .order_by("-created_at")[:30]
        )
        alert_list = []
        for alert in linked_alerts:
            alert_list.append(
                {
                    "id": alert.id,
                    "title": alert.title,
                    "severity": alert.severity,
                    "status": alert.status,
                    "created_at": alert.created_at.isoformat() if alert.created_at else None,
                    "event_id": alert.event.id if alert.event else None,
                    "decision_trace": redact_and_truncate(alert.decision_trace, MAX_EVENT_DECISION_TRACE_CHARS),
                    "references": [section_ref("SecurityAlert", alert.id, "alert")],
                }
            )
        context["related"]["linked_alerts"] = alert_list

        if alert_list:
            context["limits"]["included_sections"].append("linked_alerts")

        # Calculate context quality level
        score = context["context_quality"]["score"]
        if score == 0:
            context["context_quality"]["level"] = "empty"
        elif score <= 25:
            context["context_quality"]["level"] = "poor"
        elif score <= 55:
            context["context_quality"]["level"] = "partial"
        elif score <= 80:
            context["context_quality"]["level"] = "good"
        else:
            context["context_quality"]["level"] = "complete"

        # Check if truncated
        total_chars = value_char_len(context)
        if total_chars > MAX_REPORT_CONTEXT_CHARS:
            context["limits"]["truncated"] = True
            add_context_warning(
                context,
                f"Context truncated to {MAX_REPORT_CONTEXT_CHARS} characters (was {total_chars})"
            )

        return context
    except SecurityReport.DoesNotExist:
        logger.warning(f"Report {report_id} not found")
        return {"error": "requested object not found or unavailable"}
    except Exception as e:
        logger.exception(f"Error getting report context: {e}")
        return {"error": "error retrieving report context"}


def get_ticket_context(ticket_id: int) -> Dict[str, Any]:
    """Get context for SecurityRemediationTicket"""
    try:
        ticket = SecurityRemediationTicket.objects.select_related("source", "alert").prefetch_related(
            "evidence", "linked_alerts"
        ).get(id=ticket_id)

        context = {
            "type": "ticket",
            "id": ticket.id,
            "title": ticket.title,
            "status": ticket.status,
            "severity": ticket.severity,
            "cve": ticket.cve,
            "cve_ids": ticket.cve_ids,
            "affected_product": ticket.affected_product,
            "organization": ticket.organization,
            "source_system": ticket.source_system,
            "max_cvss": ticket.max_cvss,
            "max_exposed_devices": ticket.max_exposed_devices,
            "first_seen_at": ticket.first_seen_at.isoformat() if ticket.first_seen_at else None,
            "last_seen_at": ticket.last_seen_at.isoformat() if ticket.last_seen_at else None,
            "occurrence_count": ticket.occurrence_count,
            "dedup_hash": ticket.dedup_hash,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
            "source": ticket.source.name if ticket.source else None,
            "source_type": ticket.source.source_type if ticket.source else None,
        }

        evidence_count = ticket.evidence.count()
        linked_alerts_count = ticket.linked_alerts.count()
        context["evidence_count"] = evidence_count
        context["linked_alerts_count"] = linked_alerts_count

        linked_alerts = []
        for alert in ticket.linked_alerts.all()[:5]:
            linked_alerts.append(
                {
                    "id": alert.id,
                    "title": alert.title,
                    "severity": alert.severity,
                    "status": alert.status,
                }
            )
        context["linked_alerts"] = linked_alerts

        return context
    except SecurityRemediationTicket.DoesNotExist:
        logger.warning(f"Ticket {ticket_id} not found")
        return {"error": "requested object not found or unavailable"}
    except Exception as e:
        logger.exception(f"Error getting ticket context: {e}")
        return {"error": "error retrieving ticket context"}


def get_evidence_context(evidence_id: str) -> Dict[str, Any]:
    """Get context for SecurityEvidenceContainer"""
    try:
        container = SecurityEvidenceContainer.objects.select_related("source", "alert").prefetch_related("items").get(
            id=evidence_id
        )

        context = {
            "type": "evidence",
            "id": str(container.id),
            "title": container.title,
            "status": container.status,
            "created_at": container.created_at.isoformat() if container.created_at else None,
            "source": container.source.name if container.source else None,
            "source_type": container.source.source_type if container.source else None,
            "decision_trace": container.decision_trace,
        }

        if container.alert:
            context["alert"] = {
                "id": container.alert.id,
                "title": container.alert.title,
                "severity": container.alert.severity,
                "status": container.alert.status,
            }

        items = []
        for item in container.items.all()[:20]:
            items.append(
                {
                    "item_type": item.item_type,
                    "content": item.content,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
            )
        context["items"] = items

        return context
    except SecurityEvidenceContainer.DoesNotExist:
        logger.warning(f"Evidence container {evidence_id} not found")
        return {"error": "requested object not found or unavailable"}
    except Exception as e:
        logger.exception(f"Error getting evidence context: {e}")
        return {"error": "error retrieving evidence context"}


def get_dashboard_context() -> Dict[str, Any]:
    """Get synthetic dashboard overview context"""
    try:
        from django.db.models import Count, Q

        now = timezone.now()

        open_alerts = SecurityAlert.objects.filter(status="new").count()
        critical_alerts = SecurityAlert.objects.filter(severity="critical", status="new").count()
        high_alerts = SecurityAlert.objects.filter(severity="high", status="new").count()
        medium_alerts = SecurityAlert.objects.filter(severity="medium", status="new").count()
        low_alerts = SecurityAlert.objects.filter(severity="low", status="new").count()

        open_tickets = SecurityRemediationTicket.objects.filter(status="open").count()
        cve_tickets = SecurityRemediationTicket.objects.filter(status="open").exclude(cve="").count()

        recent_alerts = (
            SecurityAlert.objects.select_related("source")
            .filter(created_at__gte=now - timezone.timedelta(days=7))
            .order_by("-created_at")[:5]
        )
        recent_reports = (
            SecurityReport.objects.select_related("source")
            .filter(created_at__gte=now - timezone.timedelta(days=7))
            .order_by("-created_at")[:5]
        )

        context = {
            "type": "dashboard",
            "generated_at": now.isoformat(),
            "alerts": {
                "open": open_alerts,
                "critical": critical_alerts,
                "high": high_alerts,
                "medium": medium_alerts,
                "low": low_alerts,
            },
            "tickets": {
                "open": open_tickets,
                "cve": cve_tickets,
                "non_cve": open_tickets - cve_tickets,
            },
            "recent_alerts": [
                {
                    "id": alert.id,
                    "title": alert.title,
                    "severity": alert.severity,
                    "status": alert.status,
                    "source": alert.source.name if alert.source else None,
                    "created_at": alert.created_at.isoformat() if alert.created_at else None,
                }
                for alert in recent_alerts
            ],
            "recent_reports": [
                {
                    "id": report.id,
                    "title": report.title,
                    "report_type": report.report_type,
                    "report_date": report.report_date.isoformat() if report.report_date else None,
                    "parser_name": report.parser_name,
                    "parse_status": report.parse_status,
                    "source": report.source.name if report.source else None,
                }
                for report in recent_reports
            ],
        }

        return context
    except Exception as e:
        logger.exception(f"Error getting dashboard context: {e}")
        return {"error": "error retrieving dashboard context"}


def _can_access_context(user: User, object_type: str) -> bool:
    if object_type == "dashboard":
        return can_view_security_center(user)
    if object_type == "alert":
        return user.has_perm("security.view_securityalert") or user.is_staff
    if object_type == "report":
        return user.has_perm("security.view_securityreport") or user.is_staff
    if object_type == "ticket":
        return (
            user.has_perm("security.view_securityremediationticket")
            or user.is_staff
            or user.has_perm("security.manage_security_configuration")
        )
    if object_type == "evidence":
        return (
            user.has_perm("security.view_securityevidencecontainer")
            or user.is_staff
            or user.has_perm("security.manage_security_configuration")
        )
    return False


def _parse_numeric_object_id(object_id: Any) -> Optional[int]:
    try:
        if isinstance(object_id, str) and not object_id.strip().isdigit():
            return None
        parsed = int(object_id)
    except (ValueError, TypeError):
        return None
    return parsed if parsed > 0 else None


def get_runtime_context(user: User, runtime_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Get runtime context based on object_type and object_id"""
    if not isinstance(runtime_context, dict) or not runtime_context:
        return None

    object_type = runtime_context.get("object_type")
    object_id = runtime_context.get("object_id")

    if object_type not in ALLOWED_OBJECT_TYPES:
        logger.warning("Unknown or disallowed AI context object_type")
        return SAFE_UNAVAILABLE_CONTEXT

    if not _can_access_context(user, object_type):
        logger.warning("User is not authorized for requested AI context", extra={"object_type": object_type})
        return SAFE_UNAVAILABLE_CONTEXT

    if object_type == "dashboard":
        return get_dashboard_context()

    if not object_id:
        return SAFE_UNAVAILABLE_CONTEXT

    if object_type in {"alert", "report", "ticket"}:
        parsed_id = _parse_numeric_object_id(object_id)
        if parsed_id is None:
            logger.warning("Invalid AI context object_id", extra={"object_type": object_type})
            return SAFE_UNAVAILABLE_CONTEXT
        if object_type == "alert":
            return get_alert_context(parsed_id)
        if object_type == "report":
            return get_report_context(parsed_id)
        return get_ticket_context(parsed_id)

    if object_type == "evidence":
        return get_evidence_context(str(object_id)[:80])

    return SAFE_UNAVAILABLE_CONTEXT


def build_ai_messages(
    user: User,
    user_message: str,
    history: Optional[List[Dict[str, str]]] = None,
    runtime_context: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Build AI messages with application context

    Args:
        user: Django user instance
        user_message: Current user message
        history: Chat history from client
        runtime_context: Optional context with object_type and object_id

    Returns:
        List of messages for AI completion
    """
    messages = []

    assistant_profile = load_context_file("assistant_profile.md")
    domain_knowledge = load_context_file("domain_knowledge.md")
    safety_policy = load_context_file("safety_policy.md")
    response_formats = load_context_file("response_formats.md")

    system_content = ""

    if assistant_profile:
        system_content += f"\n{assistant_profile}\n"

    if domain_knowledge:
        system_content += f"\n{domain_knowledge}\n"

    if safety_policy:
        system_content += f"\n{safety_policy}\n"

    if response_formats:
        system_content += f"\n{response_formats}\n"

    if system_content:
        messages.append({"role": "system", "content": system_content.strip()})

    user_context = {
        "username": user.username,
        "is_staff": user.is_staff,
        "permissions": list(user.get_all_permissions())[:10],
    }

    messages.append({"role": "system", "content": f"User context: {user_context}"})

    sanitized_history = sanitize_chat_history(history or [])
    messages.extend(sanitized_history)

    if runtime_context:
        context_data = get_runtime_context(user, runtime_context)
        if context_data:
            redacted_context = redact_ai_context(context_data)

            # For reports, use structured context message
            object_type = runtime_context.get("object_type")
            if object_type == "report" and context_data.get("context_available"):
                context_message = (
                    "Security Center report context package follows. "
                    "Use only this context and the user's question. "
                    "If a section is missing, say it clearly and do not invent details. "
                    "Cite internal section_id references when useful.\n\n"
                    f"{safe_json_dumps(redacted_context, indent=2)}"
                )
                messages.append({"role": "system", "content": context_message})
            else:
                # Use legacy format for other object types
                messages.append({"role": "system", "content": f"Context: {redacted_context}"})

    from .memory.ai_memory_context_builder import build_ai_memory_context

    memory_context = build_ai_memory_context(
        question=user_message,
        context_type=(runtime_context or {}).get("object_type") if isinstance(runtime_context, dict) else None,
        context_object_id=(runtime_context or {}).get("object_id") if isinstance(runtime_context, dict) else None,
        user=user,
    )
    messages.append({"role": "system", "content": memory_context["prompt_context_text"]})

    messages.append({"role": "user", "content": user_message})

    return messages
