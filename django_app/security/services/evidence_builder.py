from security.models import SecurityEvidenceContainer, SecurityEvidenceItem


def build_evidence_container(source, title, alert=None, event=None, report=None, decision_trace=None):
    container = SecurityEvidenceContainer.objects.create(
        source=source,
        alert=alert,
        title=title,
        decision_trace=decision_trace or {},
    )
    if event:
        SecurityEvidenceItem.objects.create(
            container=container,
            event=event,
            report=report or event.report,
            item_type="event",
            content={"payload": event.payload, "decision_trace": event.decision_trace},
        )
    elif report:
        SecurityEvidenceItem.objects.create(
            container=container,
            report=report,
            item_type="report",
            content={"parsed_payload": report.parsed_payload},
        )
    return container
