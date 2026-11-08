"""Alert «simili»: lo stesso problema visto da più parti, per chiuderli insieme dal pannello laterale
e per dire a chi legge come sono già stati chiusi gli altri.

Per un alert «oltre il termine di correzione» (una CVE su un PC) i simili sono: gli alert della **stessa
CVE** sugli altri PC, quelli dello **stesso software** (tutte le CVE di Google Chrome, per dire) e quelli
dello **stesso PC**. Per gli altri alert vale il gruppo di ``alert_gruppi`` (stesso tipo, stesso soggetto).
Si guardano solo gli alert della stessa sorgente e dello stesso tipo di evento: «Chrome» in un alert del
firewall non c'entra con «Chrome» in una CVE.
"""
from __future__ import annotations

import uuid

from django.db.models import Q

from security.models import SecurityAlert, SecurityAlertActionLog, Status

from .alert_lifecycle import ACTIVE_ALERT_STATUSES, CLOSE_OUTCOMES

# Quanti alert, dal più recente, si confrontano: il resto è storia vecchia.
CANDIDATI = 1500
ULTIME_CHIUSURE = 3
ESITI = (
    ("resolved", "Risolto"),
    ("not_relevant", "Non rilevante"),
    ("accepted_risk", "Rischio accettato"),
    ("false_positive", "Falso positivo"),
)
_STATO_CHIUSO = {Status.CLOSED: "Chiuso", Status.FALSE_POSITIVE: "Falso positivo", Status.MUTED: "Silenziato",
                 Status.RESOLVED: "Risolto", Status.SUPPRESSED: "Soppresso"}
_AZIONI_CHIUSURA = ("close", "false_positive", "mute", "auto_resolved")


def _payload(alert):
    return ((alert.event.payload if alert.event_id else None) or {}) if alert else {}


def contesto(alert):
    """Che cosa dice l'alert: CVE, PC, software e i dati del termine di correzione (se è un alert CVE)."""
    from .investigation import entities

    payload = _payload(alert)
    ent = entities(alert)
    host = ent.get("computer") or str(payload.get("host") or "").strip()
    if not host and alert.event_id and alert.event.asset_id:
        host = alert.event.asset.hostname
    return {
        "cve": (ent.get("cve") or "").upper(),
        "host": host,
        "software": str(payload.get("affected_product") or "").strip(),
        "cvss": payload.get("cvss"),
        "kev": bool(payload.get("kev")),
        "classe": payload.get("etichetta") or payload.get("classe") or "",
        "giorni_termine": payload.get("giorni_termine"),
        "giorni_ritardo": payload.get("giorni_ritardo"),
        "scadenza": str(payload.get("scadenza") or "")[:10],
        "aperta_dal": str(payload.get("aperta_dal") or "")[:10],
    }


def _criteri(ctx):
    out = []
    if ctx["cve"]:
        out.append(("cve", f"Stessa CVE ({ctx['cve']}) su tutti i PC"))
    if ctx["software"]:
        out.append(("software", f"Stesso software ({ctx['software']})"))
    if ctx["cve"] and ctx["host"]:
        out.append(("pc", f"Stesso PC ({ctx['host']})"))
    if not ctx["cve"]:
        # Il gruppo è già «stesso problema sullo stesso PC/job/utente»: un criterio «stesso PC» a parte sarebbe un doppione.
        out.append(("gruppo", "Stesso problema sullo stesso soggetto"))
    return out


def _candidati(alert):
    qs = SecurityAlert.objects.filter(source_id=alert.source_id).exclude(pk=alert.pk).select_related("event", "event__asset", "source")
    if alert.event_id and alert.event:
        qs = qs.filter(event__event_type=alert.event.event_type)
    else:
        qs = qs.filter(Q(event__isnull=True) | Q(event__event_type=""))
    return list(qs.order_by("-pk")[:CANDIDATI])


def _corrisponde(criterio, ctx, altro_ctx, chiave, altra_chiave):
    if criterio == "cve":
        return altro_ctx["cve"] == ctx["cve"]
    if criterio == "software":
        return altro_ctx["software"].casefold() == ctx["software"].casefold()
    if criterio == "pc":
        return altro_ctx["host"].casefold() == ctx["host"].casefold()
    return chiave == altra_chiave


def _chiusure(alerts):
    """Come sono stati chiusi: esito, motivo, chi e quando, dall'ultima azione di chiusura registrata."""
    ids = [a.pk for a in alerts]
    ultimo = {}
    for log in SecurityAlertActionLog.objects.filter(alert_id__in=ids, action__in=_AZIONI_CHIUSURA).order_by("created_at"):
        ultimo[log.alert_id] = log
    out = []
    for a in alerts:
        log = ultimo.get(a.pk)
        esito = ""
        if a.status == Status.FALSE_POSITIVE:
            esito = "Falso positivo"
        elif log is not None and log.action == "auto_resolved":
            esito = "Risolto in automatico"
        elif log is not None:
            esito = CLOSE_OUTCOMES.get((log.details or {}).get("outcome") or "", "")
        out.append({
            "pk": a.pk, "title": a.title, "stato": _STATO_CHIUSO.get(a.status, a.status),
            "esito": esito or _STATO_CHIUSO.get(a.status, ""), "motivo": (a.status_reason or "").strip(),
            "chi": log.actor if log is not None else "", "quando": a.closed_at or a.updated_at,
            "host": contesto(a)["host"],
        })
    return out


def simili(alert):
    """I criteri di somiglianza con, per ciascuno, gli alert aperti e come sono stati chiusi gli altri.

    Ritorna ``{"contesto": ..., "criteri": [{codice, label, aperti: [alert], n_aperti, n_chiusi,
    per_esito: [(esito, n)], ultime: [chiusure]}], "max_pk": int}``. I criteri senza nessun simile non ci sono.
    """
    from .alert_gruppi import chiave_gruppo

    ctx = contesto(alert)
    criteri = _criteri(ctx)
    if not criteri:
        return {"contesto": ctx, "criteri": [], "max_pk": alert.pk}
    candidati = _candidati(alert)
    serve_gruppo = any(c == "gruppo" for c, _l in criteri)
    chiave = chiave_gruppo(alert) if serve_gruppo else ""
    per_cand = [(c, contesto(c), chiave_gruppo(c) if serve_gruppo else "") for c in candidati]
    out = []
    max_pk = alert.pk
    for codice, label in criteri:
        aperti, chiusi = [], []
        for cand, cctx, cchiave in per_cand:
            if not _corrisponde(codice, ctx, cctx, chiave, cchiave):
                continue
            (aperti if cand.status in ACTIVE_ALERT_STATUSES else chiusi).append(cand)
        if not aperti and not chiusi:
            continue
        chiusure = _chiusure(chiusi[:50])
        conteggio = {}
        for c in chiusure:
            conteggio[c["esito"]] = conteggio.get(c["esito"], 0) + 1
        max_pk = max([max_pk] + [a.pk for a in aperti])
        out.append({
            "codice": codice, "label": label, "aperti": aperti, "n_aperti": len(aperti), "n_chiusi": len(chiusi),
            "per_esito": sorted(conteggio.items(), key=lambda kv: -kv[1]),
            "ultime": sorted(chiusure, key=lambda c: c["quando"] or 0, reverse=True)[:ULTIME_CHIUSURE],
        })
    return {"contesto": ctx, "criteri": out, "max_pk": max_pk}


def chiudi_simili(alert, *, criterio, esito, motivo, user, max_pk=None):
    """Chiude l'alert e i suoi simili aperti secondo ``criterio``, a nome della persona. Ritorna quanti ne ha chiusi.

    ``max_pk`` è il più recente che la persona aveva davanti: un alert arrivato dopo resta aperto.
    Un'azione conta una volta sola per la soppressione appresa (stesso ``batch``).
    """
    from .alert_gruppi import _chiudi_uno

    if esito not in dict(ESITI):
        raise ValueError("esito non valido")
    dati = simili(alert)
    scelto = next((c for c in dati["criteri"] if c["codice"] == criterio), None)
    if scelto is None and criterio not in {c for c, _l in _criteri(dati["contesto"])}:
        raise ValueError("criterio non valido")
    da_chiudere = [alert] if alert.status in ACTIVE_ALERT_STATUSES else []
    for a in (scelto["aperti"] if scelto else []):
        if max_pk is None or a.pk <= max_pk:
            da_chiudere.append(a)
    actor = getattr(user, "username", "") or "ui"
    batch = f"simili-{uuid.uuid4().hex[:20]}"
    for a in da_chiudere:
        _chiudi_uno(a, esito, actor, motivo, batch, user)
    return len(da_chiudere)
