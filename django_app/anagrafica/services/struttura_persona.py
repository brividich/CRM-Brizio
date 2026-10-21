"""Posizione di una persona nella struttura: ruoli, area, processi, mansioni e mansioni proposte.

Le mansioni si assegnano UNA A UNA (decisione 21/10/2026): qui il portale si
limita a proporre quelle previste dai ruoli della persona nella sua area; chi
gestisce le conferma una per una dal Mansionario.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AreaAziendale,
    CompetenzaSkm,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
)
from .mansionario_struttura import TIPI_MANSIONE


def proposte(ruoli_ids, *, area: AreaAziendale | None = None, escludi_ids=()) -> list[CompetenzaSkm]:
    """Mansioni attive dei ruoli dati, nell'area (se c'è), meno quelle da escludere."""
    ruoli_ids = [r for r in ruoli_ids if r]
    if not ruoli_ids:
        return []
    qs = (CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, attiva=True, ruoli__in=ruoli_ids,
                                       responsabilita_reparto__isnull=True)
          .exclude(pk__in=list(escludi_ids))
          .select_related("area", "processo_sgi").prefetch_related("ruoli").distinct())
    if area is not None:
        qs = qs.filter(Q(area=area) | Q(area__isnull=True, reparto_id=area.reparto_id) | Q(area__isnull=True,
                                                                                          reparto__isnull=True))
    return sorted(qs, key=lambda m: m.nome.casefold())


def posizione(legacy_id: int) -> dict:
    oggi = timezone.localdate()
    assegnazioni = list(
        DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
                                                legacy_anagrafica_id=legacy_id)
        .select_related("ruolo", "ruolo__ambito").order_by("ruolo__nome")
    )
    struttura = [a for a in assegnazioni if a.ruolo.alimenta_ruolo_principale]
    incarichi = [a for a in assegnazioni if not a.ruolo.alimenta_ruolo_principale]
    az = (DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id)
          .select_related("area_aziendale__reparto__ruolo_responsabile", "area_aziendale__ruolo_responsabile").first())
    area = az.area_aziendale if az and az.area_aziendale_id else None
    reparto = area.reparto if area and area.reparto_id else None
    responsabile = (area.ruolo_responsabile if area and area.ruolo_responsabile_id
                    else (reparto.ruolo_responsabile if reparto and reparto.ruolo_responsabile_id else None))
    abilitazioni = list(
        AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, in_lista=True, competenza__isnull=False)
        .select_related("competenza__area", "competenza__processo_sgi").order_by("competenza__display")
    )
    assegnate = {a.competenza_id for a in abilitazioni}
    da_proporre = proposte([a.ruolo_id for a in struttura], area=area, escludi_ids=assegnate)
    processi = sorted({a.competenza.processo_sgi.nome for a in abilitazioni if a.competenza.processo_sgi_id}
                      | {m.processo_sgi.nome for m in da_proporre if m.processo_sgi_id}, key=str.casefold)
    return {
        "ruoli": struttura, "incarichi": incarichi, "area": area, "reparto": reparto,
        "reparto_testo": (az.area if az else "") or "", "responsabile": responsabile,
        "abilitazioni": abilitazioni, "proposte": da_proporre, "processi": processi,
        "senza_area": area is None, "senza_ruolo": not struttura,
    }
