"""Tempi di presa in carico e di chiusura degli alert (ISO 27001 5.25, 5.26).

La **presa in carico** è la prima azione di una persona sull'alert: presa in carico esplicita,
chiusura, falso positivo, silenzio, rinvio, riapertura, collegamento a un ticket. Si legge da
``SecurityAlertActionLog`` escludendo l'attore ``system`` e le voci scritte dal motore
(``alert_created``, ``alert_reused``, ``auto_*``). I tempi non si salvano: si calcolano dal log,
così correggere il log corregge il numero.

Obiettivi per gravità in /soc/impostazioni/ (sezione «Gestione degli incidenti»):
critica 1 h, alta 4 h, media 24 h, bassa 72 h; chiusura entro 30 giorni.
"""
from __future__ import annotations

from datetime import timedelta
from statistics import median

from django.db.models import Min, Q
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertActionLog, Severity
from security.services import soc_settings
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

# Gravità del SOC -> classe di obiettivo (le quattro soglie impostabili).
CLASSE = {
    Severity.CRITICAL: "critical",
    Severity.HIGH: "high",
    Severity.WARNING: "medium",
    Severity.MEDIUM: "medium",
    Severity.LOW: "low",
    Severity.INFO: "low",
}
CLASSE_LABEL = {"critical": "critica", "high": "alta", "medium": "media", "low": "bassa"}

AZIONI_MOTORE = ("alert_created", "alert_reused")


def target_ore() -> dict:
    """Obiettivo di presa in carico in ore per classe (``{"critical": 1, "high": 4, ...}``)."""
    return {classe: soc_settings.value(f"iso.triage.ore_{classe}") for classe in ("critical", "high", "medium", "low")}


def target_per_alert(alert, targets=None) -> int:
    targets = targets or target_ore()
    return targets[CLASSE.get(alert.severity, "low")]


def _filtro_umano():
    return ~Q(actor__in=["system", ""]) & ~Q(action__in=AZIONI_MOTORE) & ~Q(action__startswith="auto")


def prima_risposta(alert):
    """Momento della prima azione umana sull'alert, o None."""
    return SecurityAlertActionLog.objects.filter(alert=alert).filter(_filtro_umano()).aggregate(m=Min("created_at"))["m"]


def prime_risposte(alert_ids) -> dict:
    """``{alert_id: prima azione umana}`` per un gruppo di alert, in una sola interrogazione."""
    rows = (SecurityAlertActionLog.objects.filter(alert_id__in=list(alert_ids)).filter(_filtro_umano())
            .values("alert_id").annotate(m=Min("created_at")))
    return {row["alert_id"]: row["m"] for row in rows}


def _ore(delta) -> float:
    return round(delta.total_seconds() / 3600, 1)


def stato(alert, presa_in_carico=None, now=None, targets=None) -> dict:
    """Stato del triage di un alert: obiettivo, quando è stato preso in carico, se è in ritardo.

    ``presa_in_carico`` è la prima azione umana (``None`` = non ancora); se non viene passata
    si legge dal log.
    """
    now = now or timezone.now()
    if presa_in_carico is None:
        presa_in_carico = prima_risposta(alert)
    ore_target = target_per_alert(alert, targets)
    scadenza = alert.created_at + timedelta(hours=ore_target)
    chiusura_giorni = soc_settings.value("iso.triage.chiusura_giorni")
    chiuso = alert.closed_at if alert.status not in ACTIVE_ALERT_STATUSES else None
    fine = chiuso or now
    ore_presa = _ore(presa_in_carico - alert.created_at) if presa_in_carico else None
    if presa_in_carico:
        in_ritardo = presa_in_carico > scadenza
    else:
        in_ritardo = fine > scadenza
    return {
        "classe": CLASSE.get(alert.severity, "low"),
        "target_ore": ore_target,
        "scadenza": scadenza,
        "presa_in_carico_at": presa_in_carico,
        "ore_presa_in_carico": ore_presa,
        "in_ritardo": in_ritardo,
        "non_presa": presa_in_carico is None and chiuso is None,
        "ore_oltre": _ore(max(timedelta(0), (presa_in_carico or fine) - scadenza)),
        "ore_risoluzione": _ore(chiuso - alert.created_at) if chiuso else None,
        "chiusura_in_ritardo": (fine - alert.created_at) > timedelta(days=chiusura_giorni),
        "chiusura_giorni": chiusura_giorni,
    }


def decora(alerts, now=None):
    """Aggiunge ``alert.triage`` a ogni alert dell'elenco (una sola query sul log)."""
    alerts = list(alerts)
    if not alerts:
        return alerts
    now = now or timezone.now()
    targets = target_ore()
    prime = prime_risposte([a.pk for a in alerts])
    for alert in alerts:
        alert.triage = stato(alert, presa_in_carico=prime.get(alert.pk), now=now, targets=targets)
    return alerts


def alert_oltre_tempo(now=None):
    """Alert attivi mai presi in carico e già oltre l'obiettivo: da segnalare."""
    now = now or timezone.now()
    targets = target_ore()
    rows = []
    attivi = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES).select_related("source").order_by("created_at")
    # Nessun alert più giovane del target minimo può essere in ritardo.
    attivi = attivi.filter(created_at__lte=now - timedelta(hours=min(targets.values())))
    prime = prime_risposte(attivi.values_list("pk", flat=True))
    for alert in attivi:
        if prime.get(alert.pk):
            continue
        s = stato(alert, presa_in_carico=None, now=now, targets=targets)
        if s["in_ritardo"]:
            alert.triage = s
            rows.append(alert)
    return rows


def riepilogo(dal, al) -> dict:
    """Numeri del periodo (alert creati fra ``dal`` e ``al``): presi in tempo, in ritardo, non presi, mediana."""
    targets = target_ore()
    alerts = list(SecurityAlert.objects.filter(created_at__date__gte=dal, created_at__date__lte=al))
    prime = prime_risposte([a.pk for a in alerts])
    now = timezone.now()
    in_tempo = ritardo = non_presi = 0
    ore = []
    for alert in alerts:
        s = stato(alert, presa_in_carico=prime.get(alert.pk), now=now, targets=targets)
        if s["presa_in_carico_at"] is None:
            non_presi += 1
            continue
        ore.append(s["ore_presa_in_carico"])
        if s["in_ritardo"]:
            ritardo += 1
        else:
            in_tempo += 1
    return {
        "target": targets,
        "presi_in_tempo": in_tempo,
        "presi_in_ritardo": ritardo,
        "non_presi": non_presi,
        "mediana_ore": round(median(ore), 1) if ore else None,
    }
