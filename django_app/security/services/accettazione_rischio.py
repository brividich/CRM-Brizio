"""Accettazione del rischio di una CVE (eccezione al termine di correzione, ISO/IEC 27001:2022 8.8).

Chi ha il permesso di configurazione del SOC accetta il rischio di una CVE su un PC (o su tutti),
con motivo di almeno ``MOTIVO_MIN`` caratteri, misure compensative e scadenza entro 12 mesi.
Effetti: finché è attiva l'esposizione non fa scattare l'alert «oltre il termine» e le pagine la
mostrano; alla scadenza (``controlla_scadenze``, ciclo del SOC) nasce l'evento
``accettazione_rischio`` fase ``scaduta`` e l'esposizione conta di nuovo; ``promemoria_giorni``
prima nasce lo stesso evento in fase ``in_scadenza``. Tutto nell'audit sigillato (``traccia``).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from security.models import SecurityAccettazioneRischio, SecurityEventRecord, Severity
from security.services import soc_settings, traccia
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

EVENT_ACCETTAZIONE = "accettazione_rischio"
FASE_IN_SCADENZA = "in_scadenza"
FASE_SCADUTA = "scaduta"


def _host(valore):
    return str(valore or "").strip().lower()[:255]


def attive(oggi=None):
    """{(CVE, host o ""): accettazione} delle accettazioni attive adesso."""
    oggi = oggi or timezone.localdate()
    out = {}
    for acc in SecurityAccettazioneRischio.objects.filter(revocata_il__isnull=True, scadenza__gte=oggi).select_related("cve").order_by("scadenza"):
        out.setdefault((acc.cve.cve_id.upper(), _host(acc.host)), acc)
    return out


def copre(coperture, cve_id, host):
    """L'accettazione che copre (CVE, host): quella del PC, altrimenti quella di tutti i PC."""
    cve_id = str(cve_id or "").upper()
    return coperture.get((cve_id, _host(host))) or coperture.get((cve_id, ""))


def per_cve(record, oggi=None):
    """Tutte le accettazioni della CVE (attive prima), per la scheda CVE."""
    oggi = oggi or timezone.localdate()
    righe = list(record.accettazioni.select_related("approvata_da", "revocata_da"))
    righe.sort(key=lambda a: (not a.attiva(oggi), a.scadenza))
    return righe


def crea(record, *, host, motivo, misure, scadenza, user, request=None):
    """Nuova accettazione: controlli, salvataggio, audit. Solleva ``ValueError`` con il testo per l'utente."""
    host = _host(host)
    motivo = str(motivo or "").strip()
    oggi = timezone.localdate()
    if len(motivo) < SecurityAccettazioneRischio.MOTIVO_MIN:
        raise ValueError(f"Scrivi il motivo dell'accettazione (almeno {SecurityAccettazioneRischio.MOTIVO_MIN} caratteri): resta nell'audit.")
    if scadenza is None:
        raise ValueError("Indica la scadenza dell'accettazione.")
    if scadenza <= oggi:
        raise ValueError("La scadenza deve essere una data futura.")
    if scadenza > oggi + timedelta(days=SecurityAccettazioneRischio.MESI_MASSIMI * 31):
        raise ValueError(f"Un'accettazione dura al massimo {SecurityAccettazioneRischio.MESI_MASSIMI} mesi: poi va riesaminata.")
    if host and not record.impacts.filter(host__iexact=host).exists():
        raise ValueError("Il PC non è tra quelli valutati per questa CVE.")
    if copre({k: v for k, v in attive(oggi).items() if k[1] == host}, record.cve_id, host):
        raise ValueError("C'è già un'accettazione attiva per questa CVE con lo stesso ambito: revocala prima di crearne un'altra.")
    with transaction.atomic():
        acc = SecurityAccettazioneRischio.objects.create(
            cve=record, host=host, motivo=motivo[:4000], misure_compensative=str(misure or "").strip()[:4000],
            approvata_da=user if getattr(user, "is_authenticated", False) else None, scadenza=scadenza,
        )
    traccia.registra(traccia.RISCHIO_ACCETTATO, {
        "accettazione_id": acc.pk, "cve": record.cve_id, "host": host or "tutti i PC", "scadenza": scadenza,
        "motivo": motivo, "misure_compensative": acc.misure_compensative, "classe": _classe(record),
    }, oggetto=acc, request=request, attore=_nome(user))
    try:
        # Gli alert «oltre il termine» della stessa esposizione si chiudono subito, con il riferimento.
        from security.services.cve_sla import chiudi_rientrate

        chiudi_rientrate()
    except Exception:  # noqa: BLE001 - l'accettazione vale anche se la chiusura si fa al ciclo dopo
        logger.exception("Chiusura degli alert oltre il termine dopo l'accettazione #%s non riuscita", acc.pk)
    return acc


def revoca(acc, *, user, motivo="", request=None):
    if acc.revocata_il is not None:
        raise ValueError("L'accettazione è già revocata.")
    acc.revocata_il = timezone.now()
    acc.revocata_da = user if getattr(user, "is_authenticated", False) else None
    acc.revoca_motivo = str(motivo or "").strip()[:500]
    acc.save(update_fields=["revocata_il", "revocata_da", "revoca_motivo"])
    traccia.registra(traccia.RISCHIO_REVOCATO, {
        "accettazione_id": acc.pk, "cve": acc.cve.cve_id, "host": acc.host or "tutti i PC", "motivo": acc.revoca_motivo,
    }, oggetto=acc, request=request, attore=_nome(user))
    return acc


def _nome(user):
    return user.get_username() if getattr(user, "is_authenticated", False) else "ui"


def _classe(record):
    from security.services.cve_sla import classe

    return classe(record)


def _source():
    from security.services.cve_impact import impact_source

    return impact_source()


def _evento(acc, fase, oggi):
    source = _source()
    dedup = make_hash(source.pk, EVENT_ACCETTAZIONE, acc.pk, fase)
    if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_ACCETTAZIONE, dedup_hash=dedup).exists():
        return None
    payload = {
        "accettazione_id": acc.pk, "fase": fase, "cve": acc.cve.cve_id, "host": acc.host or "", "scadenza": acc.scadenza.isoformat(),
        "giorni": abs((acc.scadenza - oggi).days), "approvata_da": acc.approvata_da.get_username() if acc.approvata_da_id else "",
        "motivo": acc.motivo[:300], "classe": _classe(acc.cve), "alert_candidate": True,
    }
    return SecurityEventRecord.objects.create(
        source=source, event_type=EVENT_ACCETTAZIONE, severity=Severity.WARNING if fase == FASE_IN_SCADENZA else Severity.MEDIUM,
        occurred_at=timezone.now(), fingerprint=dedup, dedup_hash=dedup, payload=payload,
    )


def controlla_scadenze(oggi=None):
    """Promemoria prima della scadenza e chiusura alla scadenza, una volta sola per accettazione.

    Torna ``{"promemoria": n, "scadute": n}``. L'esposizione scaduta torna a contare: il passo
    successivo del ciclo (``cve_sla.segnala_scadute``) apre l'alert «oltre il termine» se serve.
    """
    oggi = oggi or timezone.localdate()
    now = timezone.now()
    anticipo = timedelta(days=soc_settings.value("cve.sla.accettazione_promemoria_giorni"))
    esito = {"promemoria": 0, "scadute": 0}
    qs = SecurityAccettazioneRischio.objects.filter(revocata_il__isnull=True).select_related("cve", "approvata_da")
    for acc in qs.filter(scaduta_il__isnull=True, scadenza__lt=oggi):
        acc.scaduta_il = now
        acc.save(update_fields=["scaduta_il"])
        event = _evento(acc, FASE_SCADUTA, oggi)
        traccia.registra(traccia.RISCHIO_SCADUTO, {
            "accettazione_id": acc.pk, "cve": acc.cve.cve_id, "host": acc.host or "tutti i PC", "scadenza": acc.scadenza,
            "evento_id": event.pk if event else None,
        }, oggetto=acc)
        esito["scadute"] += 1
    for acc in qs.filter(promemoria_il__isnull=True, scadenza__gte=oggi, scadenza__lte=oggi + anticipo):
        acc.promemoria_il = now
        acc.save(update_fields=["promemoria_il"])
        event = _evento(acc, FASE_IN_SCADENZA, oggi)
        traccia.registra(traccia.RISCHIO_IN_SCADENZA, {
            "accettazione_id": acc.pk, "cve": acc.cve.cve_id, "host": acc.host or "tutti i PC", "scadenza": acc.scadenza,
            "giorni": (acc.scadenza - oggi).days, "evento_id": event.pk if event else None,
        }, oggetto=acc)
        esito["promemoria"] += 1
    return esito


def titolo_evento(payload):
    ambito = f"su {payload['host']}" if payload.get("host") else "su tutti i PC"
    if payload.get("fase") == FASE_SCADUTA:
        return f"Accettazione del rischio scaduta: {payload.get('cve')} {ambito} (dal {payload.get('scadenza')}): torna da correggere"[:255]
    return f"Accettazione del rischio in scadenza fra {payload.get('giorni')} giorni: {payload.get('cve')} {ambito}"[:255]
