"""Risoluzione automatica: quando l'anomalia rientra, l'alert che aveva generato si chiude.

Un alert nasce da un errore (backup fallito, sorgente silenziosa, CVE esposta). Se un
report *successivo* dimostra che il problema non c'è più, tenerlo aperto è solo rumore:
lo si chiude come «Risolto», con il motivo e il riferimento al report che lo prova.

Regole, una per tipo di segnale, tutte conservative (nel dubbio l'alert resta aperto):

- **backup_job**: un'esecuzione *completata* dello stesso job sullo stesso dispositivo,
  successiva all'ultimo fallimento, chiude gli alert di quel job.
- **vulnerability_finding**: lo stesso finding (stessa CVE, prodotto, organizzazione)
  riletto con 0 dispositivi esposti chiude l'alert. L'assenza dal report NON basta:
  un export parziale non è una prova di rientro.
- **source_silent**: la sorgente torna in regola (report e lettura nei tempi) e
  l'alert di silenzio si chiude.

Gli altri alert (picchi VPN, candidati WatchGuard, spoofing, dati illeggibili) non
hanno un segnale di rientro affidabile: restano a gestione manuale.

Un caso (ticket) i cui alert sono tutti chiusi e senza attività aperte si chiude a sua
volta; se ha attività ancora da fare resta aperto, con una voce in timeline.
"""
import logging

from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertActionLog, SecurityRemediationTicket, Status
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.configuration import get_setting

logger = logging.getLogger(__name__)

AUTO_ACTOR = "system"


def auto_resolve_enabled() -> bool:
    value = get_setting("SECURITY_AUTO_RESOLVE_ENABLED", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _norm(value):
    return str(value or "").strip().lower()


def resolve_alert(alert, reason, evidence_event=None):
    """Chiude ``alert`` come Risolto dal sistema e propaga ai casi collegati."""
    now = timezone.now()
    old_status = alert.status
    alert.status = Status.RESOLVED
    alert.status_reason = reason
    alert.closed_at = now
    alert.snoozed_until = None
    alert.save(update_fields=["status", "status_reason", "closed_at", "snoozed_until", "updated_at"])
    details = {"old_status": old_status, "new_status": Status.RESOLVED, "reason": reason, "actor": AUTO_ACTOR}
    if evidence_event is not None:
        details["evidence_event_id"] = evidence_event.pk
        details["evidence_occurred_at"] = evidence_event.occurred_at.isoformat() if evidence_event.occurred_at else None
    SecurityAlertActionLog.objects.create(alert=alert, action="auto_resolved", actor=AUTO_ACTOR, details=details)
    for case in _cases_of(alert):
        maybe_resolve_case(case)
    return alert


def _cases_of(alert):
    from security.services.cases import ACTIVE_CASE_STATUSES

    return (
        SecurityRemediationTicket.objects.filter(status__in=ACTIVE_CASE_STATUSES)
        .filter(pk__in=list(alert.tickets.values_list("pk", flat=True)) + list(alert.linked_remediation_tickets.values_list("pk", flat=True)))
        .distinct()
    )


def maybe_resolve_case(case):
    """Chiude il caso se tutti i suoi alert sono chiusi e non ha attività aperte."""
    from security.services.cases import ACTIVE_CASE_STATUSES, case_alerts

    if case.status not in ACTIVE_CASE_STATUSES:
        return False
    alerts = case_alerts(case)
    if not alerts or any(alert.status in ACTIVE_ALERT_STATUSES for alert in alerts):
        return False
    open_tasks = case.tasks.filter(done=False).count()
    if open_tasks:
        SecurityAlertActionLog.objects.create(
            ticket=case, action="case_alerts_all_resolved", actor=AUTO_ACTOR,
            details={"reason": "Tutti gli alert sono rientrati, ma restano attività da completare.", "open_tasks": open_tasks},
        )
        return False
    old_status = case.status
    case.status = Status.RESOLVED
    case.closed_at = timezone.now()
    case.resolution = case.resolution or "Risolto automaticamente: tutti gli alert collegati sono rientrati."
    case.save(update_fields=["status", "closed_at", "resolution", "updated_at"])
    SecurityAlertActionLog.objects.create(
        ticket=case, action="case_auto_resolved", actor=AUTO_ACTOR,
        details={"old_status": old_status, "new_status": Status.RESOLVED, "reason": case.resolution},
    )
    return True


def _active_alerts_for(source, event_type):
    return (
        SecurityAlert.objects.filter(source=source, status__in=ACTIVE_ALERT_STATUSES, event__event_type=event_type)
        .select_related("event")
    )


def resolve_backup_recovered(event):
    """Un backup completato chiude gli alert dei fallimenti precedenti dello stesso job."""
    if not auto_resolve_enabled():
        return 0
    payload = event.payload or {}
    job, device = _norm(payload.get("job_name")), _norm(payload.get("device_name"))
    if not job:
        return 0
    resolved = 0
    for alert in _active_alerts_for(event.source, "backup_job"):
        failure = alert.event
        failure_payload = failure.payload or {}
        if _norm(failure_payload.get("job_name")) != job or _norm(failure_payload.get("device_name")) != device:
            continue
        # Solo un'esecuzione riuscita DOPO il fallimento prova il rientro: i report
        # possono arrivare fuori ordine.
        if failure.occurred_at and event.occurred_at and event.occurred_at <= failure.occurred_at:
            continue
        when = timezone.localtime(event.occurred_at).strftime("%d/%m/%Y %H:%M") if event.occurred_at else "-"
        resolve_alert(alert, f"Backup «{payload.get('job_name')}» completato correttamente il {when}.", evidence_event=event)
        resolved += 1
    return resolved


def resolve_vulnerability_cleared(event):
    """Lo stesso finding riletto con 0 dispositivi esposti chiude l'alert della CVE."""
    if not auto_resolve_enabled():
        return 0
    payload = event.payload or {}
    if payload.get("cvss_unparsed") or payload.get("exposed_devices") in (None, ""):
        return 0
    try:
        exposed = int(payload.get("exposed_devices"))
    except (TypeError, ValueError):
        return 0
    if exposed > 0:
        return 0
    resolved = 0
    for alert in _active_alerts_for(event.source, "vulnerability_finding").filter(dedup_hash=event.dedup_hash):
        if alert.event and alert.event.occurred_at and event.occurred_at and event.occurred_at <= alert.event.occurred_at:
            continue
        resolve_alert(
            alert,
            f"{payload.get('cve') or 'CVE'} su {payload.get('affected_product') or 'prodotto'}: nessun dispositivo più esposto nel report successivo.",
            evidence_event=event,
        )
        resolved += 1
    return resolved


def resolve_source_back_online(security_source, mailbox_code):
    """La sorgente è tornata in regola: chiude i suoi alert di silenzio."""
    if not auto_resolve_enabled() or security_source is None:
        return 0
    resolved = 0
    for alert in _active_alerts_for(security_source, "source_silent"):
        if _norm((alert.event.payload or {}).get("source_code")) != _norm(mailbox_code):
            continue
        resolve_alert(alert, "La sorgente ha ripreso a inviare report nei tempi attesi.")
        resolved += 1
    return resolved
