"""F6 — Refresh semestrale delle abilitazioni macchina (campagna CAR).

Il CAR rivaluta, sul **proprio reparto**, le abilitazioni in lista (① conferma
invariati / modifica livello / rimuovi dalla lista) e può aggiungere nuove
abilitazioni (② aggiunte manuali). Ogni conferma/modifica/aggiunta produce uno
**scatto** in ``AbilitazioneMacchinaStorico`` (fonte ``refresh``) e sposta in avanti
``prossima_revisione`` di ``periodicita_refresh_mesi``.

La **campagna** (``CampagnaRefresh``) è solo l'innesco (trigger) della tornata; il
merito della rivalutazione è del CAR. L'arretrato (revisione scaduta) è **visibile
ma non bloccante**.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CampagnaRefresh,
    CompetenzaSkm,
    LivelloSkm,
    SkillMatrixConfig,
)


def _asset_ids_reparto(reparto: str) -> list[int]:
    return list(
        CompetenzaSkm.objects
        .filter(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False, asset__reparto=reparto)
        .values_list("asset_id", flat=True)
    )


def abilitazioni_reparto(reparto: str):
    """Abilitazioni in lista sulle macchine del reparto (gruppo ① da rivalutare)."""
    ids = _asset_ids_reparto(reparto)
    if not ids:
        return AbilitazioneMacchina.objects.none()
    return (
        AbilitazioneMacchina.objects
        .filter(asset_id__in=ids, in_lista=True)
        .select_related("asset").order_by("legacy_anagrafica_id", "asset__name")
    )


def apri_campagna(reparto: str, *, periodo_inizio=None, avviatore_ruolo: str = "",
                  scadenza=None) -> CampagnaRefresh:
    """Apre (o riusa) la campagna aperta del reparto. Idempotente."""
    periodo_inizio = periodo_inizio or timezone.localdate()
    camp, _ = CampagnaRefresh.objects.get_or_create(
        reparto=reparto, stato=CampagnaRefresh.STATO_APERTA,
        defaults={"periodo_inizio": periodo_inizio, "avviatore_ruolo": avviatore_ruolo,
                  "scadenza": scadenza},
    )
    return camp


def _scatto(ab: AbilitazioneMacchina, data, car_legacy_id, note: str) -> None:
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=ab.legacy_anagrafica_id, asset_id=ab.asset_id,
        livello=ab.livello, data_rilevazione=data,
        fonte=AbilitazioneMacchinaStorico.FONTE_REFRESH,
        car_legacy_id=car_legacy_id, note=note,
    )


def _prossima_revisione(oggi, config: SkillMatrixConfig):
    return oggi + timedelta(days=int(config.periodicita_refresh_mesi * 30.44))


def applica_refresh(*, reparto: str, decisioni: dict, car_legacy_id=None, oggi=None,
                    apply: bool = True, campagna: CampagnaRefresh | None = None,
                    chiudi_campagna: bool = False) -> dict:
    """Applica la rivalutazione del gruppo ①.

    ``decisioni``: ``{abilitazione_id: {"azione": "conferma|modifica|rimuovi",
    "livello": "U"}}``. Scrive scatti storico e sposta ``prossima_revisione``.
    """
    oggi = oggi or timezone.localdate()
    config = SkillMatrixConfig.get_instance()
    nuova_rev = _prossima_revisione(oggi, config)
    stats = {"apply": apply, "confermate": 0, "modificate": 0, "rimosse": 0}
    abil = {a.id: a for a in abilitazioni_reparto(reparto)}

    with transaction.atomic():
        for ab_id, dec in decisioni.items():
            ab = abil.get(int(ab_id))
            if ab is None:
                continue
            azione = (dec.get("azione") or "conferma").strip()
            if azione == "rimuovi":
                stats["rimosse"] += 1
                if apply:
                    ab.in_lista = False
                    ab.prossima_revisione = nuova_rev
                    ab.save(update_fields=["in_lista", "prossima_revisione", "updated_at"])
                    _scatto(ab, oggi, car_legacy_id, "Refresh: rimosso dalla lista")
                continue
            nuovo = (dec.get("livello") or ab.livello).strip().upper()
            if nuovo not in dict(LivelloSkm.choices):
                nuovo = ab.livello
            cambiato = nuovo != ab.livello
            stats["modificate" if cambiato else "confermate"] += 1
            if apply:
                ab.livello = nuovo
                ab.prossima_revisione = nuova_rev
                ab.save(update_fields=["livello", "prossima_revisione", "updated_at"])
                _scatto(ab, oggi, car_legacy_id,
                        "Refresh: modifica livello" if cambiato else "Refresh: confermato invariato")
        if apply and chiudi_campagna and campagna is not None:
            campagna.stato = CampagnaRefresh.STATO_CHIUSA
            campagna.periodo_fine = oggi
            campagna.save(update_fields=["stato", "periodo_fine", "updated_at"])
    return stats


def aggiungi_abilitazione(*, legacy_anagrafica_id: int, asset_id: int, livello: str,
                          car_legacy_id=None, oggi=None, conteggiabile=True) -> AbilitazioneMacchina:
    """Aggiunta manuale (gruppo ②): crea/riattiva un'abilitazione + scatto storico."""
    oggi = oggi or timezone.localdate()
    config = SkillMatrixConfig.get_instance()
    livello = (livello or "").strip().upper()
    if livello not in dict(LivelloSkm.choices):
        raise ValueError(f"Livello non valido: {livello!r}")
    ab, _ = AbilitazioneMacchina.objects.update_or_create(
        legacy_anagrafica_id=legacy_anagrafica_id, asset_id=asset_id,
        defaults={
            "livello": livello, "in_lista": True,
            "stato": AbilitazioneMacchina.STATO_ATTIVA,
            "conteggiabile_nel_carico": conteggiabile,
            "car_legacy_id": car_legacy_id,
            "prossima_revisione": _prossima_revisione(oggi, config),
        },
    )
    _scatto(ab, oggi, car_legacy_id, "Refresh: aggiunta manuale")
    return ab


def arretrati_reparto(reparto: str, *, oggi=None) -> int:
    """Conteggio abilitazioni con revisione scaduta (arretrato, NON bloccante)."""
    oggi = oggi or timezone.localdate()
    return abilitazioni_reparto(reparto).filter(prossima_revisione__lt=oggi).count()
