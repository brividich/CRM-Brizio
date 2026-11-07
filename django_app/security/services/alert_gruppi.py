"""Alert aperti raggruppati: lo stesso problema sullo stesso soggetto è una decisione sola, non cento.

Un gruppo è (sorgente, tipo di evento, soggetto), dove il soggetto è il PC, il job di backup o l'utente
dell'alert. Le vulnerabilità non hanno un soggetto: stanno tutte nel gruppo del loro tipo e si gestiscono
da Vulnerabilità. Senza nessuno di questi vale il titolo con i numeri tolti.

L'AI locale esamina un alert per gruppo, il più recente: con centinaia di alert aperti e poche risposte
per giro è l'unico modo di arrivare a tutti. Una conferma su un gruppo conta come una conferma sola
per la fiducia, anche se chiude cento alert.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict

from security.models import SecurityAlert, SecurityAlertProposta, Severity

APERTI = ("new", "open", "acknowledged", "in_progress")
RANGO = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.WARNING: 1, Severity.LOW: 0}
ESITI = (
    ("resolved", "Risolto"),
    ("not_relevant", "Non rilevante"),
    ("accepted_risk", "Rischio accettato"),
    ("false_positive", "Falso positivo"),
)
_NUMERI = re.compile(r"\d+(?:[.,]\d+)*")
# Il PC nel titolo, quando la sorgente non lo scrive nei dati: «Endpoint Security: 3 devices blocked su PC-DEMO».
_SU_PC = re.compile(r"\bsu\s+([\w.-]+)\s*$", re.I)


def _soggetto(alert):
    from security.services.investigation import entities

    trovati = entities(alert)
    for campo in ("computer", "job", "user"):
        if trovati.get(campo):
            return trovati[campo]
    if trovati.get("cve"):
        return ""
    pc = _SU_PC.search(alert.title or "")
    if pc:
        return pc.group(1)
    return _NUMERI.sub("#", alert.title or "")[:120]


def tipo_di(alert):
    """(chiave, etichetta) del tipo: sorgente + tipo di evento."""
    from security.services.ai_proposte import schema_di

    return schema_di(alert)


def chiave_gruppo(alert):
    tipo, _label = tipo_di(alert)
    return hashlib.sha256(f"{tipo}|{_soggetto(alert).casefold()}".encode()).hexdigest()[:24]


def _alert_aperti(**filtri):
    return list(SecurityAlert.objects.filter(status__in=APERTI, **filtri)
                .select_related("source", "event", "event__report").order_by("-created_at", "-pk"))


def gruppi_aperti(**filtri):
    """I gruppi, dal più grave e numeroso: ogni gruppo ha gli alert dal più recente al più vecchio."""
    gruppi = {}
    for alert in _alert_aperti(**filtri):
        chiave = chiave_gruppo(alert)
        gruppo = gruppi.get(chiave)
        if gruppo is None:
            tipo, label = tipo_di(alert)
            gruppo = gruppi[chiave] = {"chiave": chiave, "tipo": tipo, "tipo_label": label, "soggetto": _soggetto(alert), "alert": []}
        gruppo["alert"].append(alert)
    out = list(gruppi.values())
    for gruppo in out:
        alert = gruppo["alert"]
        gruppo.update({
            "n": len(alert),
            "titolo": alert[0].title,
            "severita": max((a.severity for a in alert), key=lambda s: RANGO.get(s, 0)),
            "primo": alert[-1].created_at,
            "ultimo": alert[0].created_at,
            "max_pk": max(a.pk for a in alert),
        })
    out.sort(key=lambda g: (-RANGO.get(g["severita"], 0), -g["n"], g["titolo"]))
    return out


def rappresentanti(**filtri):
    """Per il giro dell'AI: un alert per gruppo (il più recente), dai gruppi più grandi.

    Sull'alert restano ``_gruppo_alert``, gli alert del gruppo, per dire all'AI quanti sono e per chiuderli insieme.
    """
    gruppi = gruppi_aperti(**filtri)
    gruppi.sort(key=lambda g: (-g["n"], -RANGO.get(g["severita"], 0)))
    out = []
    for gruppo in gruppi:
        rappresentante = gruppo["alert"][0]
        rappresentante._gruppo_alert = gruppo["alert"]
        out.append(rappresentante)
    return out


def _con_proposte(gruppi):
    from security.services.ai_proposte import blocco_auto

    tutti = {a.pk: g for g in gruppi for a in g["alert"]}
    proposte = {}
    for proposta in SecurityAlertProposta.objects.filter(stato=SecurityAlertProposta.APERTA, alert_id__in=list(tutti)).order_by("creata_il"):
        proposte[tutti[proposta.alert_id]["chiave"]] = proposta  # la più recente del gruppo
    alert_di = {a.pk: a for g in gruppi for a in g["alert"]}
    for gruppo in gruppi:
        proposta = proposte.get(gruppo["chiave"])
        if proposta is not None:
            proposta.alert = alert_di[proposta.alert_id]
            proposta.blocco = blocco_auto(proposta.alert, {"esito": proposta.esito, "confidenza": proposta.confidenza,
                                                           "prove": proposta.prove, "schema": proposta.schema})
        gruppo["proposta"] = proposta
        gruppo["esempi"] = gruppo["alert"][:8]
        gruppo["esito_scelto"] = proposta.esito if proposta and proposta.esito != "aperto" else "resolved"
        gruppo["motivo"] = proposta.motivo if proposta and proposta.esito != "aperto" else ""
    return gruppi


def per_pagina():
    """Gli alert aperti per tipo e, dentro, per gruppo. Prima i tipi più gravi e numerosi."""
    gruppi = _con_proposte(gruppi_aperti())
    tipi = defaultdict(list)
    for gruppo in gruppi:
        tipi[gruppo["tipo"]].append(gruppo)
    righe = []
    for tipo, membri in tipi.items():
        righe.append({
            "tipo": tipo,
            "label": membri[0]["tipo_label"],
            "gruppi": membri,
            "n_gruppi": len(membri),
            "n": sum(g["n"] for g in membri),
            "severita": max((g["severita"] for g in membri), key=lambda s: RANGO.get(s, 0)),
            "max_pk": max(g["max_pk"] for g in membri),
            "proposte": sum(1 for g in membri if g["proposta"] is not None),
        })
    righe.sort(key=lambda t: (-RANGO.get(t["severita"], 0), -t["n"], t["label"]))
    return {"tipi": righe, "n_gruppi": len(gruppi), "n_alert": sum(g["n"] for g in gruppi), "esiti": ESITI}


def _chiudi_uno(alert, esito, actor, motivo, batch, user):
    from security.services.alert_lifecycle import close_alert, mark_false_positive
    from security.services.auto_resolution import _cases_of, maybe_resolve_case

    if esito == "false_positive":
        mark_false_positive(alert, actor=actor, reason=motivo, batch=batch, user=user)
    else:
        close_alert(alert, actor=actor, reason=motivo, outcome=esito, batch=batch, user=user)
    for case in _cases_of(alert):
        maybe_resolve_case(case)


def chiudi(*, esito, motivo, max_pk, user, chiave="", tipo=""):
    """Chiude gli alert di un gruppo o di un tipo, a nome della persona. Ritorna quanti ne ha chiusi.

    ``max_pk`` è il più recente che la persona aveva davanti: un alert arrivato dopo resta aperto.
    Un'azione conta una volta per la soppressione appresa (stesso ``batch``).
    """
    if esito not in dict(ESITI):
        raise ValueError("esito non valido")
    actor = getattr(user, "username", "") or "ui"
    batch = f"gruppo-{uuid.uuid4().hex[:20]}"
    fatti = 0
    for gruppo in gruppi_aperti(pk__lte=max_pk):
        if (chiave and gruppo["chiave"] != chiave) or (tipo and gruppo["tipo"] != tipo):
            continue
        for alert in gruppo["alert"]:
            _chiudi_uno(alert, esito, actor, motivo, batch, user)
            fatti += 1
    return fatti
