"""Termini di correzione delle vulnerabilità (ISO/IEC 27001:2022, controllo 8.8).

Ogni esposizione (CVE × PC con esito «Impatta», ``SecurityCveImpact``) ha un termine che parte da
``aperta_dal`` e dipende dalla **classe** della CVE:

- ``kev``: sfruttata attivamente (CISA KEV) → la data chiesta da CISA (``kev_due``), altrimenti
  ``cve.sla.kev_giorni``;
- ``critica`` (CVSS ≥ 9 o severità critical), ``alta`` (≥ 7), ``media`` (≥ 4), ``bassa`` (il resto,
  anche senza punteggio): i giorni di Impostazioni › «Vulnerabilità: tempi di correzione».

Le esposizioni «da verificare» non hanno termine: prima si decide se impattano. Un'esposizione
coperta da un'accettazione del rischio attiva (``accettazione_rischio``) non fa scattare nulla.

Oltre il termine nasce un evento ``cve_sla_scaduta`` (una volta per CVE, PC e termine) che il motore
regole trasforma in alert; quando l'esposizione rientra o viene accettata, l'alert si chiude da solo.
Ogni passo è nell'audit sigillato (``traccia``). Contratto pubblico usato anche dal cruscotto di
conformità: ``classe``, ``scadenza``, ``riepilogo``, ``scadute``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from security.models import SecurityAlert, SecurityCveImpact, SecurityCveRisoluzione, SecurityEventRecord, Severity
from security.services import soc_settings, traccia
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

EVENT_SLA = "cve_sla_scaduta"
RULE_RIENTRO = "cve_sla_rientrata"
KEV, CRITICA, ALTA, MEDIA, BASSA = "kev", "critica", "alta", "media", "bassa"
CLASSI = (KEV, CRITICA, ALTA, MEDIA, BASSA)
ETICHETTE = {KEV: "Sfruttata (CISA KEV)", CRITICA: "Critica", ALTA: "Alta", MEDIA: "Media", BASSA: "Bassa"}
_CHIAVI = {KEV: "cve.sla.kev_giorni", CRITICA: "cve.sla.critica_giorni", ALTA: "cve.sla.alta_giorni",
           MEDIA: "cve.sla.media_giorni", BASSA: "cve.sla.bassa_giorni"}
_SEVERITA_TESTO = {"critical": CRITICA, "high": ALTA, "medium": MEDIA, "low": BASSA}
APERTE = (SecurityCveImpact.IMPACTS,)


def classe(record) -> str:
    """Classe della CVE: ``kev``, ``critica``, ``alta``, ``media`` o ``bassa``."""
    if record.kev:
        return KEV
    cvss = record.cvss
    if cvss is None:
        return _SEVERITA_TESTO.get((record.severity or "").lower(), BASSA)
    if cvss >= 9:
        return CRITICA
    if cvss >= 7:
        return ALTA
    if cvss >= 4:
        return MEDIA
    return BASSA


def giorni(cls) -> int:
    return soc_settings.value(_CHIAVI[cls])


def _giorno(valore) -> date:
    if isinstance(valore, datetime):
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore


def scadenza(record, aperta_dal) -> date:
    """Termine di correzione dell'esposizione aperta da ``aperta_dal`` (datetime o date)."""
    cls = classe(record)
    if cls == KEV and record.kev_due:
        return record.kev_due
    return _giorno(aperta_dal or timezone.now()) + timedelta(days=giorni(cls))


def stato(record, aperta_dal, oggi=None, accettata=None) -> dict:
    """Termine di un'esposizione per le pagine: classe, giorni, scadenza, ritardo, accettazione."""
    oggi = oggi or timezone.localdate()
    cls = classe(record)
    termine = scadenza(record, aperta_dal)
    ritardo = (oggi - termine).days
    return {
        "classe": cls, "etichetta": ETICHETTE[cls], "giorni": giorni(cls), "scadenza": termine,
        "giorni_ritardo": max(ritardo, 0), "giorni_restanti": max(-ritardo, 0), "scaduta": ritardo > 0,
        "accettata": accettata is not None, "accettazione": accettata,
    }


def _coperture(oggi):
    from security.services import accettazione_rischio

    return accettazione_rischio.attive(oggi)


def _voce(impatto, oggi, coperture):
    from security.services.accettazione_rischio import copre

    record = impatto.cve
    acc = copre(coperture, record.cve_id, impatto.host)
    info = stato(record, impatto.aperta_dal or impatto.computed_at, oggi, acc)
    return {
        "cve": record.cve_id, "host": impatto.host, "classe": info["classe"], "etichetta": info["etichetta"],
        "scadenza": info["scadenza"], "giorni_ritardo": info["giorni_ritardo"], "accettata": info["accettata"],
        "aperta_dal": impatto.aperta_dal or impatto.computed_at, "record": record, "impatto": impatto,
        "accettazione": acc,
    }


def esposizioni_aperte(oggi=None):
    """Tutte le esposizioni «Impatta» con il loro termine (voci come ``scadute``), nell'ordine del ritardo."""
    oggi = oggi or timezone.localdate()
    coperture = _coperture(oggi)
    voci = [_voce(i, oggi, coperture) for i in SecurityCveImpact.objects.filter(outcome__in=APERTE).select_related("cve")]
    voci.sort(key=lambda v: (-v["giorni_ritardo"], CLASSI.index(v["classe"]), v["cve"], v["host"]))
    return voci


def scadute(oggi=None) -> list:
    """Esposizioni aperte oltre il termine, adesso: ``{"cve","host","classe","scadenza","giorni_ritardo","accettata"}``."""
    return [v for v in esposizioni_aperte(oggi) if v["giorni_ritardo"] > 0]


def _aware(valore, fine=False):
    if isinstance(valore, datetime):
        return valore if timezone.is_aware(valore) else timezone.make_aware(valore)
    return timezone.make_aware(datetime.combine(valore, time.max if fine else time.min))


def riepilogo(dal, al) -> dict:
    """Per classe: corrette nel periodo (in tempo / in ritardo rispetto al termine), aperte, aperte scadute.

    ``dal``/``al`` sono date o datetime. Le correzioni sono le ``SecurityCveRisoluzione`` del periodo
    (programma aggiornato o rimosso, con «esposto dal»); le aperte sono le esposizioni di adesso.
    """
    oggi = timezone.localdate()
    righe = {cls: {"classe": cls, "etichetta": ETICHETTE[cls], "giorni": giorni(cls), "corrette": 0, "in_tempo": 0,
                   "in_ritardo": 0, "aperte": 0, "aperte_scadute": 0} for cls in CLASSI}
    corrette = (
        SecurityCveRisoluzione.objects.filter(risolta_il__gte=_aware(dal), risolta_il__lte=_aware(al, fine=True),
                                              come__in=SecurityCveRisoluzione.CORREZIONI, aperta_dal__isnull=False)
        .select_related("cve")
    )
    for r in corrette:
        riga = righe[classe(r.cve)]
        riga["corrette"] += 1
        if _giorno(r.risolta_il) <= scadenza(r.cve, r.aperta_dal):
            riga["in_tempo"] += 1
        else:
            riga["in_ritardo"] += 1
    aperte = esposizioni_aperte(oggi)
    for v in aperte:
        righe[v["classe"]]["aperte"] += 1
        if v["giorni_ritardo"] > 0:
            righe[v["classe"]]["aperte_scadute"] += 1
    totale = sum(r["corrette"] for r in righe.values())
    in_tempo = sum(r["in_tempo"] for r in righe.values())
    return {
        "dal": _giorno(dal), "al": _giorno(al),
        "classi": [righe[cls] for cls in CLASSI],
        "aperte_scadute": [v for v in aperte if v["giorni_ritardo"] > 0],
        "percentuale_in_tempo": round(100 * in_tempo / totale) if totale else None,
        "corrette": totale, "in_tempo": in_tempo, "in_ritardo": totale - in_tempo,
        "aperte": len(aperte), "accettate": sum(1 for v in aperte if v["accettata"]),
    }


# --- Automatismo: evento oltre il termine, chiusura al rientro -------------------------------

def _dedup(source, voce):
    return make_hash(source.pk, EVENT_SLA, voce["cve"], voce["host"], voce["scadenza"].isoformat())


def segnala_scadute(oggi=None):
    """Un evento ``cve_sla_scaduta`` per ogni esposizione oltre il termine non accettata (una volta per termine).

    Torna ``(eventi creati, alert chiusi perché rientrati)``. Chiamato dal ciclo del SOC prima
    della valutazione delle regole, così l'evento diventa alert nello stesso giro.
    """
    if not soc_settings.value("cve.sla.attivo"):
        return 0, 0
    from security.services.cve_impact import impact_source

    oggi = oggi or timezone.localdate()
    source = impact_source()
    voci = scadute(oggi)
    creati = 0
    for voce in voci:
        if voce["accettata"]:
            continue
        dedup = _dedup(source, voce)
        if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_SLA, dedup_hash=dedup).exists():
            continue
        record = voce["record"]
        severity = Severity.HIGH if voce["classe"] in (KEV, CRITICA) else Severity.MEDIUM
        payload = {
            "cve": record.cve_id, "host": voce["host"], "classe": voce["classe"], "etichetta": voce["etichetta"],
            "scadenza": voce["scadenza"].isoformat(), "giorni_ritardo": voce["giorni_ritardo"],
            "aperta_dal": voce["aperta_dal"].isoformat() if voce["aperta_dal"] else None,
            "giorni_termine": giorni(voce["classe"]), "cvss": record.cvss, "kev": record.kev,
            "kev_due": record.kev_due.isoformat() if record.kev_due else None,
            "affected_product": voce["impatto"].installation.product_raw if voce["impatto"].installation_id else "",
            "alert_candidate": True,
        }
        event = SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_SLA, severity=severity, occurred_at=timezone.now(),
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        )
        traccia.registra(traccia.CVE_TERMINE_SCADUTO, {
            "cve": record.cve_id, "host": voce["host"], "classe": voce["classe"], "scadenza": voce["scadenza"],
            "giorni_ritardo": voce["giorni_ritardo"], "evento_id": event.pk, "regola": EVENT_SLA,
        }, oggetto=record)
        creati += 1
    return creati, chiudi_rientrate(voci, source)


def chiudi_rientrate(voci_scadute=None, source=None):
    """Chiude gli alert «oltre il termine» la cui esposizione non è più aperta o è stata accettata."""
    from security.services.auto_resolution import resolve_alert
    from security.services.cve_impact import impact_source

    source = source or impact_source()
    voci = scadute() if voci_scadute is None else voci_scadute
    ancora = {_dedup(source, v) for v in voci if not v["accettata"]}
    accettate = {_dedup(source, v): v for v in voci if v["accettata"]}
    chiusi = 0
    alerts = SecurityAlert.objects.filter(source=source, status__in=ACTIVE_ALERT_STATUSES, event__event_type=EVENT_SLA).select_related("event")
    for alert in alerts:
        if alert.dedup_hash in ancora:
            continue
        payload = (alert.event.payload or {}) if alert.event_id else {}
        acc = accettate.get(alert.dedup_hash)
        if acc is not None:
            reason = (f"{payload.get('cve')} su {payload.get('host')}: rischio accettato fino al "
                      f"{acc['scadenza']:%d/%m/%Y} (accettazione #{acc['accettazione'].pk}).")
        else:
            reason = f"{payload.get('cve')} su {payload.get('host')}: il PC non risulta più esposto al ricalcolo degli impatti."
        resolve_alert(alert, reason, rule_code=RULE_RIENTRO)
        traccia.registra(traccia.CVE_TERMINE_RIENTRATO, {
            "cve": payload.get("cve"), "host": payload.get("host"), "alert_id": alert.pk, "motivo": reason, "regola": RULE_RIENTRO,
        }, oggetto=alert)
        chiusi += 1
    return chiusi


def alert_attivi_per_cve(cve_id):
    """Alert «oltre il termine» aperti di una CVE: {host: alert}."""
    from security.services.cve_impact import impact_source

    out = {}
    for alert in SecurityAlert.objects.filter(source=impact_source(), status__in=ACTIVE_ALERT_STATUSES,
                                              event__event_type=EVENT_SLA).select_related("event"):
        payload = alert.event.payload or {}
        if str(payload.get("cve") or "").upper() == cve_id.upper():
            out[str(payload.get("host") or "")] = alert
    return out


def titolo_evento(payload):
    cve, host = payload.get("cve"), payload.get("host")
    prodotto = f" ({payload['affected_product']})" if payload.get("affected_product") else ""
    return (f"Oltre il termine di correzione: {cve} su {host}{prodotto}, classe {str(payload.get('etichetta') or '').lower()}, "
            f"{payload.get('giorni_ritardo')} giorni di ritardo")[:255]
