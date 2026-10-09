"""Casi SOC: il ticket è un alert "complesso" su cui si lavora.

L'alert resta il segnale automatico; il caso raccoglie uno o più alert e porta
responsabile, stato di lavorazione, note, attività e una timeline unica. I ticket
automatici (CVE, backup) sono casi come gli altri: gestibili allo stesso modo.

Ogni passaggio scrive in ``SecurityAlertActionLog`` (ticket=caso): la timeline del
caso e l'audit sono la stessa cosa.
"""
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from security.models import (
    SecurityAlertActionLog,
    SecurityCaseNote,
    SecurityCaseTask,
    SecurityRemediationTicket,
    Severity,
    Status,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES, acknowledge_alert, close_alert, mark_false_positive
from security.services.dedup import make_hash

ACTIVE_CASE_STATUSES = [Status.NEW, Status.OPEN, Status.IN_PROGRESS]
CLOSED_CASE_STATUSES = [Status.RESOLVED, Status.CLOSED, Status.FALSE_POSITIVE]
CASE_STATUSES = ACTIVE_CASE_STATUSES + CLOSED_CASE_STATUSES

_SEVERITY_ORDER = [s for s, _ in Severity.choices]


class CaseConflict(Exception):
    """Il caso non può tornare attivo: ne esiste già uno attivo per lo stesso problema."""


def actor_name(user):
    return getattr(user, "username", "") or "ui"


def case_alerts(case):
    """Alert collegati al caso: i ``linked_alerts`` più l'alert principale (i ticket backup
    storici avevano solo quest'ultimo)."""
    alerts = {alert.pk: alert for alert in case.linked_alerts.all()}
    if case.alert_id and case.alert_id not in alerts:
        alerts[case.alert_id] = case.alert
    return sorted(alerts.values(), key=lambda alert: alert.created_at, reverse=True)


def _max_severity(alerts):
    severities = [alert.severity for alert in alerts if alert.severity in _SEVERITY_ORDER]
    if not severities:
        return Severity.WARNING
    return max(severities, key=_SEVERITY_ORDER.index)


def _log(case, action, actor, alert=None, **details):
    return SecurityAlertActionLog.objects.create(alert=alert, ticket=case, action=action, actor=actor, details=details)


def open_case_from_alerts(alerts, *, user, title="", description="", assignee=None):
    """Apre un caso a mano da uno o più alert. Gli alert nuovi passano a «preso in carico»."""
    alerts = list(alerts)
    if not alerts:
        raise ValueError("Serve almeno un alert per aprire un caso.")
    actor = actor_name(user)
    main = alerts[0]
    title = (title or "").strip() or (main.title if len(alerts) == 1 else f"{main.title} (+{len(alerts) - 1} alert)")
    case = SecurityRemediationTicket.objects.create(
        source=main.source,
        alert=main,
        title=title[:255],
        description=description or "",
        status=Status.IN_PROGRESS if assignee else Status.OPEN,
        severity=_max_severity(alerts),
        origin=SecurityRemediationTicket.ORIGIN_MANUAL,
        created_by=user if getattr(user, "pk", None) else None,
        assignee=assignee,
        occurrence_count=len(alerts),
        # Un caso manuale non deduplica: hash univoco, così non collide con l'indice
        # "un solo ticket attivo per (sorgente, dedup)".
        dedup_hash=make_hash("manual_case", uuid.uuid4().hex),
    )
    _log(case, "case_opened", actor, alerts=[alert.pk for alert in alerts])
    if assignee:
        _log(case, "case_assigned", actor, assignee=assignee.get_username())
    for alert in alerts:
        _attach_alert(case, alert, actor)
    return case


def open_manual_case(*, source, title, user, description="", severity=Severity.WARNING, assignee=None, tasks=()):
    """Caso aperto a mano senza alert (es. dai PC selezionati nella pagina Backup), con le sue attività."""
    actor = actor_name(user)
    case = SecurityRemediationTicket.objects.create(
        source=source,
        title=(title or "Caso aperto a mano")[:255],
        description=description or "",
        status=Status.IN_PROGRESS if assignee else Status.OPEN,
        severity=severity,
        origin=SecurityRemediationTicket.ORIGIN_MANUAL,
        created_by=user if getattr(user, "pk", None) else None,
        assignee=assignee,
        dedup_hash=make_hash("manual_case", uuid.uuid4().hex),
    )
    _log(case, "case_opened", actor)
    if assignee:
        _log(case, "case_assigned", actor, assignee=assignee.get_username())
    for title_task in tasks:
        add_task(case, title_task, user=user)
    return case


def add_alerts_to_case(case, alerts, *, user):
    actor = actor_name(user)
    added = 0
    already = {alert.pk for alert in case_alerts(case)}
    for alert in alerts:
        if alert.pk in already:
            continue
        _attach_alert(case, alert, actor)
        added += 1
    if added:
        all_alerts = case_alerts(case)
        case.severity = _max_severity(all_alerts)
        case.occurrence_count = len(all_alerts)
        case.last_seen_at = timezone.now()
        case.save(update_fields=["severity", "occurrence_count", "last_seen_at", "updated_at"])
    return added


def _attach_alert(case, alert, actor):
    case.linked_alerts.add(alert)
    _log(case, "case_alert_linked", actor, alert=alert, alert_title=alert.title)
    if alert.status in (Status.NEW, Status.OPEN):
        acknowledge_alert(alert, actor=actor, reason=f"Inserito nel ticket #{case.pk}")


def assign_case(case, assignee, *, user):
    previous = case.assignee.get_username() if case.assignee_id else ""
    case.assignee = assignee
    fields = ["assignee", "updated_at"]
    if assignee and case.status in (Status.NEW, Status.OPEN):
        case.status = Status.IN_PROGRESS
        fields.append("status")
    case.save(update_fields=fields)
    _log(case, "case_assigned", actor_name(user), previous=previous, assignee=assignee.get_username() if assignee else "")
    return case


def set_case_status(case, new_status, *, user, reason="", close_alerts=False):
    """Cambia lo stato del caso. Chiudendo, può chiudere anche gli alert ancora aperti."""
    if new_status not in CASE_STATUSES:
        raise ValueError(f"Stato non valido per un caso: {new_status}")
    actor = actor_name(user)
    old_status = case.status
    case.status = new_status
    fields = ["status", "updated_at"]
    if new_status in CLOSED_CASE_STATUSES:
        case.closed_at = timezone.now()
        case.resolution = reason or case.resolution
        fields += ["closed_at", "resolution"]
    elif old_status in CLOSED_CASE_STATUSES:
        case.closed_at = None
        fields.append("closed_at")
    try:
        with transaction.atomic():
            case.save(update_fields=fields)
    except IntegrityError as exc:
        # Riaprire un ticket automatico quando il sistema ne ha già aperto un altro per
        # lo stesso problema violerebbe "un solo ticket attivo per (sorgente, dedup)".
        case.refresh_from_db()
        raise CaseConflict("Esiste già un caso attivo per lo stesso problema: lavora su quello.") from exc
    _log(case, "case_status_changed", actor, old_status=old_status, new_status=new_status, reason=reason)

    if close_alerts and new_status in CLOSED_CASE_STATUSES:
        closer = mark_false_positive if new_status == Status.FALSE_POSITIVE else close_alert
        for alert in case_alerts(case):
            if alert.status in ACTIVE_ALERT_STATUSES:
                if closer is mark_false_positive:
                    # Un caso chiuso come falso positivo conta una volta sola per la soppressione appresa.
                    closer(alert, actor=actor, reason=reason or f"Chiuso con il ticket #{case.pk}", batch=f"case-{case.pk}")
                else:
                    closer(alert, actor=actor, reason=reason or f"Chiuso con il ticket #{case.pk}")
    return case


def add_note(case, body, *, user):
    body = (body or "").strip()
    if not body:
        raise ValueError("La nota è vuota.")
    note = SecurityCaseNote.objects.create(ticket=case, author=user if getattr(user, "pk", None) else None, body=body)
    case.save(update_fields=["updated_at"])
    return note


def add_task(case, title, *, user):
    title = (title or "").strip()
    if not title:
        raise ValueError("L'attività non ha un titolo.")
    task = SecurityCaseTask.objects.create(ticket=case, title=title[:255], created_by=user if getattr(user, "pk", None) else None)
    _log(case, "case_task_added", actor_name(user), task=task.title)
    if case.status in (Status.NEW, Status.OPEN):
        case.status = Status.IN_PROGRESS
        case.save(update_fields=["status", "updated_at"])
    return task


def toggle_task(task, *, user):
    task.done = not task.done
    task.done_at = timezone.now() if task.done else None
    task.done_by = (user if getattr(user, "pk", None) else None) if task.done else None
    task.save(update_fields=["done", "done_at", "done_by"])
    _log(task.ticket, "case_task_done" if task.done else "case_task_reopened", actor_name(user), task=task.title)
    return task


def delete_task(task, *, user):
    case = task.ticket
    title = task.title
    task.delete()
    _log(case, "case_task_deleted", actor_name(user), task=title)


def case_timeline(case, limit=200):
    """Cronologia unica: azioni sul caso, azioni sugli alert collegati e note."""
    alert_ids = [alert.pk for alert in case_alerts(case)]
    logs = SecurityAlertActionLog.objects.filter(ticket=case)
    if alert_ids:
        logs = logs | SecurityAlertActionLog.objects.filter(alert_id__in=alert_ids)
    entries = [
        {"kind": "log", "at": log.created_at, "action": log.action, "actor": log.actor, "details": log.details or {}, "alert": log.alert}
        for log in logs.select_related("alert").distinct().order_by("-created_at")[:limit]
    ]
    entries += [
        {"kind": "note", "at": note.created_at, "action": "note", "actor": note.author.get_username() if note.author_id else "", "body": note.body}
        for note in case.notes.select_related("author")[:limit]
    ]
    entries.sort(key=lambda entry: entry["at"], reverse=True)
    return entries[:limit]
