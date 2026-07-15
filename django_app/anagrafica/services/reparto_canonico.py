"""Risoluzione canonica del reparto/area di un dipendente.

Prima della Fase 1 ogni modulo leggeva il *reparto* dal testo libero legacy
(`anagrafica_dipendenti.reparto`, esposto da `fetch_anagrafica_rows`) e lo
confrontava per stringa con `Reparto.nome`. È fragile: il testo non è
normalizzato e non segue l'inversione gerarchica Reparto→AreaAziendale.

La fonte unica è la catena canonica sul modello ``DipendenteAnagraficaAziendale``:
``dipendente → area_aziendale (FK) → reparto (FK)``, agganciata per
``legacy_anagrafica_id``. Questo modulo la espone come mappe pronte all'uso,
con **fallback** al testo legacy finché la copertura canonica non è completa,
così durante la transizione nessun dipendente sparisce.
"""
from __future__ import annotations

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto


def build_area_canonica_map(legacy_ids: list[int] | None = None) -> dict[int, AreaAziendale]:
    """``legacy_anagrafica_id`` → :class:`AreaAziendale` canonica assegnata."""
    qs = (
        DipendenteAnagraficaAziendale.objects
        .filter(area_aziendale__isnull=False)
        .select_related("area_aziendale", "area_aziendale__reparto")
    )
    if legacy_ids is not None:
        qs = qs.filter(legacy_anagrafica_id__in=list(legacy_ids))
    return {
        az.legacy_anagrafica_id: az.area_aziendale
        for az in qs
        if az.area_aziendale_id
    }


def build_reparto_canonico_map(legacy_ids: list[int] | None = None) -> dict[int, Reparto]:
    """``legacy_anagrafica_id`` → :class:`Reparto` canonico (via area_aziendale)."""
    result: dict[int, Reparto] = {}
    for legacy_id, area in build_area_canonica_map(legacy_ids).items():
        rep = area.reparto if area.reparto_id else None
        if rep is not None:
            result[legacy_id] = rep
    return result


def resolve_reparto_for_row(
    row: dict,
    *,
    canonico_map: dict[int, Reparto],
    reparto_by_name: dict[str, Reparto],
) -> Reparto | None:
    """Reparto di una riga legacy: prima il canonico, poi il testo legacy.

    ``canonico_map`` da :func:`build_reparto_canonico_map`; ``reparto_by_name``
    è ``{nome.casefold(): Reparto}`` per il fallback sul testo legacy. Ritorna
    ``None`` se nessuna delle due vie risolve (il chiamante lo tratta come
    "Non mappato").
    """
    try:
        legacy_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        legacy_id = 0
    rep = canonico_map.get(legacy_id) if legacy_id else None
    if rep is not None:
        return rep
    nome_rep = str(row.get("reparto") or "").strip()
    return reparto_by_name.get(nome_rep.casefold()) if nome_rep else None
