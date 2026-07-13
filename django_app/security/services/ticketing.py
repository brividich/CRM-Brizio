from django.utils import timezone

from security.models import SecurityAlertActionLog, SecurityRemediationTicket, Severity, Status
from security.services.dedup import make_hash


ACTIVE_TICKET_STATUSES = [Status.OPEN, Status.IN_PROGRESS, Status.NEW]
DEFENDER_SOURCE = "microsoft_defender"


def create_or_update_remediation_ticket_for_vulnerability_finding(source, alert, evidence, finding, dedup_hash=None):
    source_system = finding.get("source") or finding.get("source_system") or ""
    organization = finding.get("organization") or ""
    cve = (finding.get("cve") or "").upper()
    affected_product = finding.get("affected_product") or "Unknown product"
    cvss = float(finding.get("cvss") or 0)
    exposed_devices = int(finding.get("exposed_devices") or 0)
    severity = finding.get("severity") or Severity.CRITICAL
    ticket_hash = dedup_hash or make_hash(source_system or source.pk, organization, affected_product, cve)

    ticket = _find_existing_vulnerability_ticket(source, source_system, organization, affected_product, cve)
    created = ticket is None
    if created:
        cve_ids = [cve] if cve else []
        ticket = SecurityRemediationTicket.objects.create(
            source=source,
            alert=alert,
            cve=cve,
            cve_ids=cve_ids,
            affected_product=affected_product,
            organization=organization,
            source_system=source_system,
            title=_ticket_title(affected_product, cve_ids),
            severity=severity,
            max_cvss=cvss,
            max_exposed_devices=exposed_devices,
            first_seen_at=timezone.now(),
            last_seen_at=timezone.now(),
            occurrence_count=1,
            dedup_hash=ticket_hash,
        )
        action = "ticket_created"
    else:
        cve_ids = list(ticket.cve_ids or ([ticket.cve] if ticket.cve else []))
        if cve and cve not in cve_ids:
            cve_ids.append(cve)
        ticket.alert = alert
        ticket.cve = cve_ids[0] if cve_ids else cve
        ticket.cve_ids = sorted(cve_ids)
        ticket.affected_product = affected_product
        ticket.organization = organization or ticket.organization
        ticket.source_system = source_system or ticket.source_system
        ticket.title = _ticket_title(affected_product, ticket.cve_ids)
        ticket.severity = Severity.CRITICAL if Severity.CRITICAL in {ticket.severity, severity} else severity
        ticket.max_cvss = max(float(ticket.max_cvss or 0), cvss)
        ticket.max_exposed_devices = max(int(ticket.max_exposed_devices or 0), exposed_devices)
        ticket.last_seen_at = timezone.now()
        ticket.occurrence_count = int(ticket.occurrence_count or 0) + 1
        ticket.dedup_hash = ticket.dedup_hash or ticket_hash
        ticket.save(
            update_fields=[
                "alert",
                "cve",
                "cve_ids",
                "affected_product",
                "organization",
                "source_system",
                "title",
                "severity",
                "max_cvss",
                "max_exposed_devices",
                "last_seen_at",
                "occurrence_count",
                "dedup_hash",
                "updated_at",
            ]
        )
        action = "ticket_updated_existing_vulnerability"
    if alert:
        ticket.linked_alerts.add(alert)
    if evidence:
        ticket.evidence.add(evidence)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        ticket=ticket,
        action=action,
        details={
            "source": source_system,
            "organization": organization,
            "cve": cve,
            "cve_ids": ticket.cve_ids,
            "affected_product": affected_product,
            "cvss": cvss,
            "exposed_devices": exposed_devices,
            "evidence_id": str(evidence.id) if evidence else None,
        },
    )
    return ticket, created


def _find_existing_vulnerability_ticket(source, source_system, organization, affected_product, cve):
    queryset = SecurityRemediationTicket.objects.filter(
        source=source,
        affected_product=affected_product,
        status__in=ACTIVE_TICKET_STATUSES,
    )
    if organization:
        queryset = queryset.filter(organization=organization)
    if source_system:
        queryset = queryset.filter(source_system=source_system)
    if source_system == DEFENDER_SOURCE:
        ticket = queryset.order_by("-updated_at").first()
        if ticket:
            return ticket
    ticket = queryset.filter(cve=cve).order_by("-updated_at").first()
    if ticket:
        return ticket
    for ticket in queryset.order_by("-updated_at")[:100]:
        if cve and cve in (ticket.cve_ids or []):
            return ticket
    return None


def _ticket_title(affected_product, cve_ids):
    if len(cve_ids) > 1:
        return f"Remediate {len(cve_ids)} critical CVEs on {affected_product}"
    return f"Remediate {cve_ids[0] if cve_ids else 'critical CVE'} on {affected_product}"


def create_or_update_cve_ticket(source, alert, evidence, cve, affected_product, dedup_hash):
    return create_or_update_remediation_ticket_for_vulnerability_finding(
        source,
        alert,
        evidence,
        {
            "cve": cve,
            "affected_product": affected_product,
            "source": "",
            "cvss": 0,
            "exposed_devices": 0,
            "severity": alert.severity if alert else Severity.CRITICAL,
        },
        dedup_hash=dedup_hash,
    )


def create_backup_ticket(source, alert, evidence, job_name, dedup_hash):
    ticket = SecurityRemediationTicket.objects.create(
        source=source,
        alert=alert,
        title=f"Investigate backup issue: {job_name}",
        dedup_hash=dedup_hash,
    )
    if evidence:
        ticket.evidence.add(evidence)
    SecurityAlertActionLog.objects.create(alert=alert, ticket=ticket, action="backup_ticket_created")
    return ticket
