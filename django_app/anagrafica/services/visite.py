"""Servizi di calcolo per le visite mediche dipendente.

Centralizza la logica di scadenza e di matching tipologie ↔ ruoli operativi
in modo che view, template e management command condividano un'unica fonte
di verità.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import Max
from django.utils import timezone

from ..models import (
    DipendenteRuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)


STATO_MANCANTE = "mancante"
STATO_VALIDA = "valida"
STATO_IN_SCADENZA = "in_scadenza"
STATO_SCADUTA = "scaduta"


def tipi_visita_richiesti_per_dipendente(legacy_id: int) -> list[TipoVisitaMedica]:
    """Ritorna i ``TipoVisitaMedica`` obbligatori per il dipendente.

    Il match avviene sui ruoli operativi attualmente assegnati al dipendente:
    tutte le tipologie ``is_active=True, obbligatoria=True`` che hanno
    almeno uno dei ruoli del dipendente nel proprio M2M ``ruoli_operativi``.
    """
    ruoli_ids = list(
        DipendenteRuoloOperativo.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .values_list("ruolo_id", flat=True)
    )
    tipi: dict[int, TipoVisitaMedica] = {}
    if ruoli_ids:
        for t in (
            TipoVisitaMedica.objects
            .filter(is_active=True, obbligatoria=True, ruoli_operativi__id__in=ruoli_ids)
            .distinct()
        ):
            tipi[t.id] = t

    # Sorgente MOD.128: visite richieste dai processi a cui la persona è abilitata.
    try:
        from .mpq_visite import tipi_visita_richiesti_da_processo
        extra_ids = tipi_visita_richiesti_da_processo(legacy_id) - set(tipi.keys())
    except Exception:
        extra_ids = set()
    if extra_ids:
        for t in TipoVisitaMedica.objects.filter(id__in=extra_ids, is_active=True):
            tipi[t.id] = t

    return sorted(tipi.values(), key=lambda t: t.nome)


def ultime_visite_per_tipo(legacy_id: int) -> dict[int, VisitaMedica]:
    """Restituisce, per ogni ``TipoVisitaMedica``, l'ultima ``VisitaMedica``
    svolta dal dipendente (per data_svolgimento).

    Implementato SQL Server-safe via subquery ``Max('data_svolgimento')`` per
    (legacy, tipo).
    """
    qs = VisitaMedica.objects.filter(legacy_anagrafica_id=legacy_id)
    if not qs.exists():
        return {}

    # Per ogni tipo, prendiamo data massima e poi recuperiamo l'oggetto con
    # quella data; nei rari casi di pareggio teniamo il pk più alto.
    max_per_tipo = (
        qs.values("tipo_id")
        .annotate(max_data=Max("data_svolgimento"))
    )
    out: dict[int, VisitaMedica] = {}
    for row in max_per_tipo:
        candidate = (
            qs.filter(tipo_id=row["tipo_id"], data_svolgimento=row["max_data"])
            .order_by("-pk")
            .select_related("tipo")
            .first()
        )
        if candidate:
            out[row["tipo_id"]] = candidate
    return out


def stato_visite(legacy_id: int, soglia_giorni_avviso: int = 60) -> list[dict[str, Any]]:
    """Ritorna lo stato delle visite richieste dal ruolo del dipendente.

    Ogni elemento ha forma::

        {
            "tipo": TipoVisitaMedica,
            "ultima": VisitaMedica | None,
            "data_scadenza": date | None,
            "stato": "mancante" | "valida" | "in_scadenza" | "scaduta",
            "giorni_a_scadenza": int | None,
        }
    """
    tipi = tipi_visita_richiesti_per_dipendente(legacy_id)
    if not tipi:
        return []
    ultime = ultime_visite_per_tipo(legacy_id)
    oggi = timezone.localdate()
    out: list[dict[str, Any]] = []
    for tipo in tipi:
        ultima = ultime.get(tipo.id)
        if ultima is None:
            out.append({
                "tipo": tipo,
                "ultima": None,
                "data_scadenza": None,
                "stato": STATO_MANCANTE,
                "giorni_a_scadenza": None,
            })
            continue
        scadenza = ultima.data_scadenza
        if scadenza is None:
            stato = STATO_VALIDA
            giorni = None
        else:
            giorni = (scadenza - oggi).days
            if giorni < 0:
                stato = STATO_SCADUTA
            elif giorni <= soglia_giorni_avviso:
                stato = STATO_IN_SCADENZA
            else:
                stato = STATO_VALIDA
        out.append({
            "tipo": tipo,
            "ultima": ultima,
            "data_scadenza": scadenza,
            "stato": stato,
            "giorni_a_scadenza": giorni,
        })
    return out


def visite_storico(legacy_id: int) -> list[VisitaMedica]:
    """Storico completo delle visite del dipendente, più recenti prima."""
    return list(
        VisitaMedica.objects
        .filter(legacy_anagrafica_id=legacy_id)
        .select_related("tipo", "referto_documento")
        .order_by("-data_svolgimento", "-id")
    )
