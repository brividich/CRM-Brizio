"""Registro incidenti di sicurezza con le scadenze di notifica NIS2 e GDPR.

Le scadenze partono da ``detected_at`` (il momento in cui se ne è venuti a conoscenza):

- NIS2 (D.Lgs. 138/2024, art. 25), solo per gli incidenti *significativi*:
  pre-notifica al CSIRT Italia entro 24 h, notifica entro 72 h, relazione finale entro
  un mese dalla notifica;
- GDPR (art. 33), se l'incidente coinvolge dati personali: notifica al Garante entro 72 h.

Le scadenze non sono salvate: si ricalcolano, così correggere ``detected_at`` le sposta.
Ogni modifica scrive in ``SecurityIncidentLog``: la traccia è parte del registro.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from security.models import SecurityIncident, SecurityIncidentLog

EARLY_WARNING_HOURS = 24
NOTIFICATION_HOURS = 72
FINAL_REPORT_DAYS = 30
GDPR_HOURS = 72
DUE_SOON_HOURS = 12

ACTIVE_STATUSES = [SecurityIncident.STATUS_OPEN, SecurityIncident.STATUS_CONTAINED]

# Art. 25 c. 3 D.Lgs. 138/2024: basta uno dei due perché l'incidente sia significativo.
SIGNIFICANCE_CRITERIA = [
    (
        "service_disruption",
        "Ha causato o può causare una grave perturbazione operativa dei servizi o perdite finanziarie",
    ),
    (
        "harm_to_others",
        "Ha avuto o può avere ripercussioni su altre persone fisiche o giuridiche, con perdite materiali o immateriali considerevoli",
    ),
]
SIGNIFICANCE_LABELS = dict(SIGNIFICANCE_CRITERIA)

MILESTONES = {
    "early_warning": ("early_warning_at", "Pre-notifica CSIRT (24 h)"),
    "notification": ("notification_at", "Notifica CSIRT (72 h)"),
    "final_report": ("final_report_at", "Relazione finale (1 mese)"),
    "gdpr": ("gdpr_notified_at", "Notifica Garante privacy (72 h)"),
}

# Campi tracciati nel log quando cambiano dal modulo di modifica.
TRACKED_FIELDS = [
    "title", "description", "category", "severity", "status", "detected_at", "occurred_at", "resolved_at",
    "is_significant", "significance_criteria", "suspected_malicious", "cross_border", "personal_data_breach",
    "affected_services", "affected_users_count", "impact_description", "root_cause", "actions_taken",
    "lessons_learned", "csirt_reference", "owner",
]


FIELD_LABELS = {
    "title": "Titolo",
    "description": "Descrizione",
    "category": "Categoria",
    "severity": "Gravità",
    "status": "Stato",
    "detected_at": "Rilevato il (conoscenza)",
    "occurred_at": "Avvenuto il",
    "resolved_at": "Risolto il",
    "is_significant": "Incidente significativo NIS2",
    "significance_criteria": "Criteri di significatività",
    "suspected_malicious": "Sospetto atto illecito o malevolo",
    "cross_border": "Impatto transfrontaliero",
    "personal_data_breach": "Coinvolge dati personali",
    "affected_services": "Servizi coinvolti",
    "affected_users_count": "Utenti coinvolti",
    "impact_description": "Impatto",
    "root_cause": "Causa",
    "actions_taken": "Misure adottate",
    "lessons_learned": "Lezioni apprese",
    "csirt_reference": "Riferimento CSIRT",
    "owner": "Responsabile",
}


def actor_name(user):
    return getattr(user, "username", "") or "system"


def log(incident, action, actor, body="", **details):
    return SecurityIncidentLog.objects.create(incident=incident, action=action, actor=actor, body=body, details=details)


# --- Scadenze --------------------------------------------------------------------------

STATE_LABELS = {
    "done": "Inviata in tempo",
    "late": "Inviata in ritardo",
    "overdue": "Scaduta",
    "due_soon": "In scadenza",
    "pending": "Da inviare",
}
STATE_TONES = {"done": "success", "late": "warning", "overdue": "critical", "due_soon": "warning", "pending": "muted"}


def _remaining_label(delta):
    """«mancano 5 h», «mancano 31 giorni», «in ritardo di 6 h»: le ore oltre le 48 non si leggono."""
    hours = abs(delta.total_seconds()) / 3600
    amount = f"{round(hours)} h" if hours < 48 else f"{round(hours / 24)} giorni"
    return f"mancano {amount}" if delta.total_seconds() >= 0 else f"in ritardo di {amount}"


def _due_dates(incident):
    detected = incident.detected_at
    notification_base = incident.notification_at or detected + timedelta(hours=NOTIFICATION_HOURS)
    dues = []
    if incident.is_significant:
        dues += [
            ("early_warning", detected + timedelta(hours=EARLY_WARNING_HOURS)),
            ("notification", detected + timedelta(hours=NOTIFICATION_HOURS)),
            ("final_report", notification_base + timedelta(days=FINAL_REPORT_DAYS)),
        ]
    if incident.personal_data_breach:
        dues.append(("gdpr", detected + timedelta(hours=GDPR_HOURS)))
    return dues


def deadlines(incident, now=None):
    """Scadenze applicabili con lo stato: ``done``, ``late`` (fatta in ritardo), ``overdue``,
    ``due_soon`` (entro 12 h), ``pending``."""
    now = now or timezone.now()
    result = []
    for key, due_at in _due_dates(incident):
        field, label = MILESTONES[key]
        done_at = getattr(incident, field)
        if done_at:
            state = "late" if done_at > due_at else "done"
        elif now > due_at:
            state = "overdue"
        elif due_at - now <= timedelta(hours=DUE_SOON_HOURS):
            state = "due_soon"
        else:
            state = "pending"
        result.append({
            "key": key,
            "label": label,
            "due_at": due_at,
            "done_at": done_at,
            "state": state,
            "state_label": STATE_LABELS[state],
            "tone": STATE_TONES[state],
            "hours_left": round((due_at - now).total_seconds() / 3600, 1),
            "hours_late": round(max(0.0, (now - due_at).total_seconds()) / 3600, 1),
            "remaining_label": _remaining_label(due_at - now),
        })
    return result


def next_open_deadline(incident, now=None):
    """La prima scadenza non ancora rispettata (scaduta o in arrivo), o None."""
    pending = [d for d in deadlines(incident, now) if d["state"] in {"overdue", "due_soon", "pending"}]
    return min(pending, key=lambda d: d["due_at"]) if pending else None


def urgent_incidents(now=None):
    """Incidenti con una notifica scaduta o in scadenza entro 12 h (banner della panoramica)."""
    now = now or timezone.now()
    rows = []
    candidates = SecurityIncident.objects.filter(Q(is_significant=True) | Q(personal_data_breach=True))
    for incident in candidates.order_by("detected_at"):
        nxt = next_open_deadline(incident, now)
        if nxt and nxt["state"] in {"overdue", "due_soon"}:
            rows.append({"incident": incident, "deadline": nxt})
    return rows


# --- Scrittura -------------------------------------------------------------------------

def _assign_code(incident):
    year = timezone.localtime(incident.detected_at).year
    incident.code = f"INC-{year}-{incident.pk:04d}"
    incident.save(update_fields=["code"])


@transaction.atomic
def create_incident(user, *, tickets=(), alerts=(), **fields):
    incident = SecurityIncident.objects.create(created_by=user if getattr(user, "pk", None) else None, **fields)
    _assign_code(incident)
    if tickets:
        incident.tickets.add(*tickets)
    if alerts:
        incident.alerts.add(*alerts)
    log(incident, "created", actor_name(user), f"Incidente registrato: {incident.title}")
    if incident.is_significant:
        _mark_assessed(incident, user)
    return incident


def create_from_case(case, user):
    """Incidente aperto da un ticket SOC: eredita titolo, descrizione, severità e alert."""
    from security.services.cases import case_alerts

    alerts = case_alerts(case)
    first_seen = min([alert.created_at for alert in alerts] + [case.created_at])
    return create_incident(
        user,
        tickets=[case],
        alerts=alerts,
        title=case.title[:255],
        description=case.description or "",
        severity=case.severity,
        detected_at=first_seen,
        owner=case.assignee,
    )


def _mark_assessed(incident, user):
    incident.significance_assessed_at = timezone.now()
    incident.significance_assessed_by = user if getattr(user, "pk", None) else None
    incident.save(update_fields=["significance_assessed_at", "significance_assessed_by"])


def _display(value):
    if value is None or value == "":
        return "—"
    if hasattr(value, "isoformat"):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if timezone.is_aware(value) else value.isoformat()
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, list):
        return ", ".join(SIGNIFICANCE_LABELS.get(item, str(item))[:40] for item in value) or "—"
    return str(value)[:200]


@transaction.atomic
def save_changes(incident, before, user):
    """Registra nel log i campi cambiati rispetto a ``before`` (dizionario dei vecchi valori)."""
    changes = []
    for field in TRACKED_FIELDS:
        old, new = before.get(field), getattr(incident, field)
        if old != new:
            changes.append({"field": field, "label": FIELD_LABELS.get(field, field), "old": _display(old), "new": _display(new)})
    if not changes:
        return []
    if incident.status in {SecurityIncident.STATUS_RESOLVED, SecurityIncident.STATUS_CLOSED} and not incident.resolved_at:
        incident.resolved_at = timezone.now()
        incident.save(update_fields=["resolved_at"])
    if any(c["field"] == "is_significant" for c in changes):
        _mark_assessed(incident, user)
    body = "; ".join(f"{c['label']}: {c['old']} → {c['new']}" for c in changes)
    log(incident, "updated", actor_name(user), body, changes=changes)
    return changes


def snapshot(incident):
    return {field: getattr(incident, field) for field in TRACKED_FIELDS}


@transaction.atomic
def record_milestone(incident, key, user, when=None, reference=""):
    field, label = MILESTONES[key]
    when = when or timezone.now()
    setattr(incident, field, when)
    update_fields = [field, "updated_at"]
    if reference:
        incident.csirt_reference = reference[:120]
        update_fields.append("csirt_reference")
    incident.save(update_fields=update_fields)
    body = f"{label}: inviata il {_display(when)}"
    if reference:
        body += f" (riferimento {reference[:120]})"
    log(incident, f"milestone_{key}", actor_name(user), body, sent_at=when.isoformat(), reference=reference[:120])


@transaction.atomic
def clear_milestone(incident, key, user):
    field, label = MILESTONES[key]
    previous = getattr(incident, field)
    setattr(incident, field, None)
    incident.save(update_fields=[field, "updated_at"])
    log(incident, f"milestone_{key}_cleared", actor_name(user), f"{label}: data annullata (era {_display(previous)})")


def add_note(incident, user, body):
    body = (body or "").strip()
    if not body:
        return None
    return log(incident, "note", actor_name(user), body[:4000])


def link_case(incident, case, user):
    incident.tickets.add(case)
    from security.services.cases import case_alerts

    alerts = case_alerts(case)
    if alerts:
        incident.alerts.add(*alerts)
    log(incident, "case_linked", actor_name(user), f"Collegato il ticket #{case.pk}: {case.title}", ticket_id=case.pk)
