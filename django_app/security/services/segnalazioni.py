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


GRAVI = (Severity.CRITICAL, Severity.HIGH)


def _alerts(stato, severity, q, gravi=False):
    qs = SecurityAlert.objects.select_related("source", "event", "event__asset")
    qs = qs.filter(status__in=ACTIVE_ALERT_STATUSES) if stato == "aperte" else (qs.exclude(status__in=ACTIVE_ALERT_STATUSES) if stato == "chiuse" else qs)
    qs = _filtra(qs, severity=severity, q=q, campi_testo=["title", "source__name", "event__asset__hostname"])
    if gravi:
        # «Solo urgenti»: il filtro va sul queryset, prima del limite, o un
        # critico aggiornato tempo fa restava fuori dalle prime 300 righe.
        qs = qs.filter(severity__in=GRAVI)
    for a in qs.order_by("-updated_at")[:PER_KIND_LIMIT]:
        yield {
            "kind": "alert", "kind_label": "Alert", "pk": a.pk, "title": a.title, "severity": a.severity, "status": a.status,
            "where": (a.event.asset.hostname if a.event_id and a.event.asset_id else "") or a.source.name,
            "since": a.created_at, "who": a.owner or "", "active": a.status in ACTIVE_ALERT_STATUSES, "boost": 0,
            "url": reverse("security:alert_detail", args=[a.pk]), "preview": reverse("security:preview", args=["alert", a.pk]),
        }


def _tickets(stato, severity, q, gravi=False):
    qs = SecurityRemediationTicket.objects.select_related("source", "assignee")
    qs = qs.filter(status__in=ACTIVE_CASE_STATUSES) if stato == "aperte" else (qs.exclude(status__in=ACTIVE_CASE_STATUSES) if stato == "chiuse" else qs)
    qs = _filtra(qs, severity=severity, q=q, campi_testo=["title", "cve", "affected_product", "source__name"])
    if gravi:
        qs = qs.filter(severity__in=GRAVI)
    for t in qs.order_by("-updated_at")[:PER_KIND_LIMIT]:
        yield {
            "kind": "ticket", "kind_label": "Ticket", "pk": t.pk, "title": f"#{t.pk} · {t.title}", "severity": t.severity, "status": t.status,
            "where": t.affected_product or t.source.name,
            "since": t.first_seen_at, "who": t.assignee.get_username() if t.assignee_id else "", "active": t.status in ACTIVE_CASE_STATUSES, "boost": 0,
            "url": reverse("security:case_detail", args=[t.pk]), "preview": reverse("security:preview", args=["ticket", t.pk]),
        }


def _incidents(stato, severity, q, now, limite=PER_KIND_LIMIT):
    qs = SecurityIncident.objects.select_related("owner")
    qs = qs.filter(status__in=ACTIVE_INCIDENT_STATUSES) if stato == "aperte" else (qs.exclude(status__in=ACTIVE_INCIDENT_STATUSES) if stato == "chiuse" else qs)
    qs = _filtra(qs, severity=severity, q=q, campi_testo=["title", "code", "description"])
    for i in (qs.order_by("-detected_at")[:limite] if limite else qs.order_by("-detected_at")):
        active = i.status in ACTIVE_INCIDENT_STATUSES
        legale = i.is_significant or i.personal_data_breach
        # Il termine di legge vale anche a incidente chiuso (es. relazione finale
        # NIS2): stessa regola del riquadro «scadenze NIS2/GDPR».
        deadline = next_open_deadline(i, now) if legale else None
        # una notifica NIS2/GDPR scaduta o in scadenza passa davanti a tutto: ha un termine di legge
        boost = 3 if deadline and deadline["state"] in {"overdue", "due_soon"} else (1 if deadline else 0)
        yield {
            "kind": "incident", "kind_label": "Incidente", "pk": i.pk, "title": f"{i.code} · {i.title}" if i.code else i.title,
            "severity": i.severity, "status": i.status, "where": i.get_category_display(),
            "since": i.detected_at, "who": i.owner.get_username() if i.owner_id else "", "active": active, "boost": boost,
            "deadline": deadline,
            "url": reverse("security:incident_detail", args=[i.pk]), "preview": reverse("security:preview", args=["incident", i.pk]),
        }


def _per_stato(qs, stato, attivi):
    return qs.filter(status__in=attivi) if stato == "aperte" else (qs.exclude(status__in=attivi) if stato == "chiuse" else qs)


def conteggi(stato="aperte", severity="", q=""):
    """Quante segnalazioni per tipo con lo stato (aperte, chiuse, tutte), la gravità e la ricerca scelti.

    Senza argomenti: le aperte, il numero del riquadro «segnalazioni aperte». Con i filtri
    della pagina sono il totale vero dietro ogni chip, anche quando l'elenco si ferma a
    ``PER_KIND_LIMIT`` righe per tipo.
    """
    if stato not in {"aperte", "chiuse", "tutte"}:
        stato = "aperte"
    if severity not in {v for v, _l in GRAVITA}:
        severity = ""
    alert = _filtra(_per_stato(SecurityAlert.objects.all(), stato, ACTIVE_ALERT_STATUSES), severity=severity, q=q,
                    campi_testo=["title", "source__name", "event__asset__hostname"])
    ticket = _filtra(_per_stato(SecurityRemediationTicket.objects.all(), stato, ACTIVE_CASE_STATUSES), severity=severity, q=q,
                     campi_testo=["title", "cve", "affected_product", "source__name"])
    incident = _filtra(_per_stato(SecurityIncident.objects.all(), stato, ACTIVE_INCIDENT_STATUSES), severity=severity, q=q,
                       campi_testo=["title", "code", "description"])
    return {"alert": alert.count(), "ticket": ticket.count(), "incident": incident.count()}


def conta_urgenti(now=None) -> int:
    """Quante segnalazioni urgenti (stessa definizione di ``elenco(urgenti=True)``), contate per intero:
    alert e ticket con COUNT, incidenti aperti uno per uno (sono pochi e servono i termini di legge)."""
    now = now or timezone.now()
    n = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, severity__in=GRAVI).count()
    n += SecurityRemediationTicket.objects.filter(status__in=ACTIVE_CASE_STATUSES, severity__in=GRAVI).count()
    for riga in _incidents("aperte", "", "", now, limite=None):
        n += 1 if _urgente(riga) else 0
    return n


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
    if tipo in ("", "alert") and not scadenza:
        righe += list(_alerts(stato, severity, q, gravi=urgenti))
    if tipo in ("", "ticket") and not scadenza:
        righe += list(_tickets(stato, severity, q, gravi=urgenti))
    if tipo in ("", "incident"):
        # «In scadenza» = termini di legge: anche gli incidenti già chiusi che li hanno ancora aperti.
        righe += list(_incidents("tutte" if scadenza else stato, severity, q, now))
    for r in righe:
        r["urgente"] = _urgente(r)
    if urgenti:
        righe = [r for r in righe if r["urgente"]]
    if scadenza:
        righe = [r for r in righe if r["boost"] >= 3]
    righe.sort(key=lambda r: (not r["active"], -r["boost"], -_RANK.get(r["severity"], 0), r["since"]))
    return righe
