from django.db import IntegrityError, transaction
from django.utils import timezone

from security.models import SecurityAlertActionLog, SecurityRemediationTicket, Severity, Status
from security.services.dedup import make_hash
from security.services.notifications import notify_ticket_created


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
        try:
            with transaction.atomic():
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
        except IntegrityError:
            # Lost the race: a concurrent worker created the ticket between our lookup and
            # our INSERT. Adopt it and fall through to the update branch.
            ticket = _active_ticket_by_hash(source, ticket_hash)
            if ticket is None:
                raise
            created = False

    if created:
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
    if created:
        notify_ticket_created(ticket)
    return ticket, created


def _active_ticket_by_hash(source, dedup_hash):
    return (
        SecurityRemediationTicket.objects
        .filter(source=source, dedup_hash=dedup_hash, status__in=ACTIVE_TICKET_STATUSES)
        .order_by("-updated_at")
        .first()
    )


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
    """One live ticket per failing backup job, not one per night.

    This used to create a ticket unconditionally - the `dedup_hash` argument was stored
    but never checked - so a job failing every night produced a ticket every night. It
    now behaves like the vulnerability path: reuse the open ticket and count the
    recurrence.
    """
    existing = _active_ticket_by_hash(source, dedup_hash)
    if existing:
        existing.alert = alert or existing.alert
        existing.last_seen_at = timezone.now()
        existing.occurrence_count = int(existing.occurrence_count or 0) + 1
        existing.save(update_fields=["alert", "last_seen_at", "occurrence_count", "updated_at"])
        if evidence:
            existing.evidence.add(evidence)
        SecurityAlertActionLog.objects.create(
            alert=alert, ticket=existing, action="backup_ticket_recurrence",
            details={"job_name": job_name, "occurrence_count": existing.occurrence_count},
        )
        return existing

    try:
        with transaction.atomic():
            ticket = SecurityRemediationTicket.objects.create(
                source=source,
                alert=alert,
                title=f"Investigate backup issue: {job_name}",
                dedup_hash=dedup_hash,
            )
    except IntegrityError:
        ticket = _active_ticket_by_hash(source, dedup_hash)
        if ticket is None:
            raise
        if evidence:
            ticket.evidence.add(evidence)
        return ticket

    if evidence:
        ticket.evidence.add(evidence)
    SecurityAlertActionLog.objects.create(alert=alert, ticket=ticket, action="backup_ticket_created")
    notify_ticket_created(ticket)
    return ticket
