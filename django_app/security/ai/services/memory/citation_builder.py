"""Internal citation helpers for AI memory context."""

from ....models import (
    AIKnowledgeDocument,
    SecurityAlert,
    SecurityEvidenceContainer,
    SecurityRemediationTicket,
    SecurityReport,
)


def build_reference(source_object_type: str, source_object_id: str | int | None, *, fallback_title: str = "") -> str:
    object_type = str(source_object_type or "").strip()
    object_id = str(source_object_id or "").strip()
    if not object_type or not object_id:
        return ""

    if object_type in {"AIKnowledgeDocument", "knowledge_document"}:
        document = AIKnowledgeDocument.objects.filter(id=_safe_int(object_id)).first()
        return f"KnowledgeDocument #{document.id} - {document.title}" if document else ""

    if object_type in {"SecurityAlert", "alert"}:
        alert = SecurityAlert.objects.filter(id=_safe_int(object_id)).first()
        return f"SecurityAlert #{alert.id} - {alert.title}" if alert else ""

    if object_type in {"SecurityReport", "report"}:
        report = SecurityReport.objects.filter(id=_safe_int(object_id)).first()
        return f"SecurityReport #{report.id} - {report.title}" if report else ""

    if object_type in {"SecurityRemediationTicket", "ticket"}:
        ticket = SecurityRemediationTicket.objects.filter(id=_safe_int(object_id)).first()
        return f"Ticket #{ticket.id} - {ticket.title}" if ticket else ""

    if object_type in {"SecurityEvidenceContainer", "evidence"}:
        evidence = SecurityEvidenceContainer.objects.filter(id=object_id[:80]).first()
        return f"Evidence Container #{evidence.id} - {evidence.title}" if evidence else ""

    if fallback_title:
        return f"{object_type} #{object_id} - {fallback_title}"
    return ""


def document_reference(document: AIKnowledgeDocument) -> str:
    return f"KnowledgeDocument #{document.id} - {document.title}"


def _safe_int(value: str) -> int | None:
    return int(value) if str(value).isdigit() else None
