"""«Segnalazioni»: alert, ticket e incidenti in un elenco solo, dal più urgente.

Sola lettura: non cambia nessun modello. Le pagine di dettaglio, l'anteprima laterale e le azioni
restano quelle di ogni tipo. Gli eventi non entrano nell'elenco (sono migliaia e per lo più «a posto»):
hanno la loro scheda.
"""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from security.models import SecurityAlert, SecurityIncident, SecurityRemediationTicket, Severity

from .alert_lifecycle import ACTIVE_ALERT_STATUSES
from .cases import ACTIVE_CASE_STATUSES
from .incidents import ACTIVE_STATUSES as ACTIVE_INCIDENT_STATUSES
from .incidents import next_open_deadline

KINDS = [("alert", "Alert"), ("ticket", "Ticket"), ("incident", "Incidenti")]
GRAVITA = [("critical", "Critico"), ("high", "Alto"), ("warning", "Attenzione"), ("medium", "Medio"), ("low", "Basso"), ("info", "Info")]
_RANK = {Severity.CRITICAL: 5, Severity.HIGH: 4, Severity.WARNING: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}
PER_KIND_LIMIT = 300


def _filtra(qs, *, severity, q, campi_testo):
    if severity:
        qs = qs.filter(severity=severity)
    if q:
        from django.db.models import Q

        cond = Q()
        for campo in campi_testo:
            cond |= Q(**{f"{campo}__icontains": q})
        qs = qs.filter(cond)
    return qs


def _alerts(stato, severity, q):
    qs = SecurityAlert.objects.select_related("source", "event", "event__asset")
    qs = qs.filter(status__in=ACTIVE_ALERT_STATUSES) if stato == "aperte" else (qs.exclude(status__in=ACTIVE_ALERT_STATUSES) if stato == "chiuse" else qs)
    qs = _filtra(qs, severity=severity, q=q, campi_testo=["title", "source__name", "event__asset__hostname"])
    for a in qs.order_by("-updated_at")[:PER_KIND_LIMIT]:
        yield {
            "kind": "alert", "kind_label": "Alert", "pk": a.pk, "title": a.title, "severity": a.severity, "status": a.status,
            "where": (a.event.asset.hostname if a.event_id and a.event.asset_id else "") or a.source.name,
            "since": a.created_at, "who": a.owner or "", "active": a.status in ACTIVE_ALERT_STATUSES, "boost": 0,
            "url": reverse("security:alert_detail", args=[a.pk]), "preview": reverse("security:preview", args=["alert", a.pk]),
        }


def _tickets(stato, severity, q):
    qs = SecurityRemediationTicket.objects.select_related("source", "assignee")
    qs = qs.filter(status__in=ACTIVE_CASE_STATUSES) if stato == "aperte" else (qs.exclude(status__in=ACTIVE_CASE_STATUSES) if stato == "chiuse" else qs)
    qs = _filtra(qs, severity=severity, q=q, campi_testo=["title", "cve", "affected_product", "source__name"])
    for t in qs.order_by("-updated_at")[:PER_KIND_LIMIT]:
        yield {
            "kind": "ticket", "kind_label": "Ticket", "pk": t.pk, "title": f"#{t.pk} · {t.title}", "severity": t.severity, "status": t.status,
            "where": t.affected_product or t.source.name,
            "since": t.first_seen_at, "who": t.assignee.get_username() if t.assignee_id else "", "active": t.status in ACTIVE_CASE_STATUSES, "boost": 0,
            "url": reverse("security:case_detail", args=[t.pk]), "preview": reverse("security:preview", args=["ticket", t.pk]),
        }


def _incidents(stato, severity, q, now):
    qs = SecurityIncident.objects.select_related("owner")
    qs = qs.filter(status__in=ACTIVE_INCIDENT_STATUSES) if stato == "aperte" else (qs.exclude(status__in=ACTIVE_INCIDENT_STATUSES) if stato == "chiuse" else qs)
    qs = _filtra(qs, severity=severity, q=q, campi_testo=["title", "code", "description"])
    for i in qs.order_by("-detected_at")[:PER_KIND_LIMIT]:
        active = i.status in ACTIVE_INCIDENT_STATUSES
        legale = i.is_significant or i.personal_data_breach
        deadline = next_open_deadline(i, now) if active and legale else None
        # una notifica NIS2/GDPR scaduta o in scadenza passa davanti a tutto: ha un termine di legge
        boost = 3 if deadline and deadline["state"] in {"overdue", "due_soon"} else (1 if deadline else 0)
        yield {
            "kind": "incident", "kind_label": "Incidente", "pk": i.pk, "title": f"{i.code} · {i.title}" if i.code else i.title,
            "severity": i.severity, "status": i.status, "where": i.get_category_display(),
            "since": i.detected_at, "who": i.owner.get_username() if i.owner_id else "", "active": active, "boost": boost,
            "deadline": deadline,
            "url": reverse("security:incident_detail", args=[i.pk]), "preview": reverse("security:preview", args=["incident", i.pk]),
        }


def conteggi():
    """Quante segnalazioni aperte per tipo: servono ai chip e alla scheda del menu."""
    return {
        "alert": SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES).count(),
        "ticket": SecurityRemediationTicket.objects.filter(status__in=ACTIVE_CASE_STATUSES).count(),
        "incident": SecurityIncident.objects.filter(status__in=ACTIVE_INCIDENT_STATUSES).count(),
    }


def _urgente(riga):
    return riga["active"] and (riga["severity"] in (Severity.CRITICAL, Severity.HIGH) or riga["boost"] >= 3)


def elenco(*, tipo="", stato="aperte", severity="", q="", urgenti=False, scadenza=False, now=None):
    """Segnalazioni ordinate: prima le aperte, poi per urgenza (termine di legge, gravità), poi le più vecchie.

    ``urgenti``: solo le aperte critiche/alte o con una notifica di legge scaduta o in scadenza (stessa
    definizione del riquadro «segnalazioni urgenti» e del numero sul menu). ``scadenza``: solo gli
    incidenti con una notifica scaduta o in scadenza.
    """
    now = now or timezone.now()
    if tipo not in {k for k, _l in KINDS}:
        tipo = ""
    if stato not in {"aperte", "chiuse", "tutte"}:
        stato = "aperte"
    if severity not in {v for v, _l in GRAVITA}:
        severity = ""
    righe = []
    if tipo in ("", "alert"):
        righe += list(_alerts(stato, severity, q))
    if tipo in ("", "ticket"):
        righe += list(_tickets(stato, severity, q))
    if tipo in ("", "incident"):
        righe += list(_incidents(stato, severity, q, now))
    for r in righe:
        r["urgente"] = _urgente(r)
    if urgenti:
        righe = [r for r in righe if r["urgente"]]
    if scadenza:
        righe = [r for r in righe if r["boost"] >= 3]
    righe.sort(key=lambda r: (not r["active"], -r["boost"], -_RANK.get(r["severity"], 0), r["since"]))
    return righe
