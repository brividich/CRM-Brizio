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


def enrich_rows_reparto_canonico(rows: list[dict], *, id_key: str = "id") -> list[dict]:
    """Arricchisce (in place) righe legacy con il reparto/area canonici.

    Per ogni riga con un'assegnazione canonica: sovrascrive ``row["reparto"]``
    col nome del :class:`Reparto` canonico (così le tabelle non mostrano più il
    testo legacy stantio) e imposta ``row["area_aziendale_nome"]``. Le righe
    senza canonico restano invariate (il chiamante decide i propri fallback).
    Ritorna la stessa lista per comodità di concatenamento.
    """
    all_ids = [int(r.get(id_key) or 0) for r in rows if int(r.get(id_key) or 0) > 0]
    canonico = build_reparto_canonico_map(all_ids)
    aree = build_area_canonica_map(all_ids)
    for row in rows:
        try:
            lid = int(row.get(id_key) or 0)
        except (TypeError, ValueError):
            lid = 0
        area = aree.get(lid)
        row["area_aziendale_nome"] = area.nome if area is not None else ""
        rep = canonico.get(lid)
        if rep is not None:
            row["reparto"] = rep.nome
    return rows


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


def resolve_responsabile_effettivo(*, area, reparto) -> int | None:
    """Responsabile effettivo di un dipendente: il responsabile dell'AREA
    AZIENDALE vince sul caporeparto del REPARTO quando differisce; il capo
    reparto è il fallback. ``None`` se nessuno dei due è valorizzato."""
    if area is not None and area.responsabile_legacy_id:
        return int(area.responsabile_legacy_id)
    if reparto is not None and reparto.caporeparto_legacy_id:
        return int(reparto.caporeparto_legacy_id)
    return None


def build_responsabile_effettivo_map(legacy_ids: list[int] | None = None) -> dict[int, int]:
    """``legacy_anagrafica_id`` → id legacy del responsabile effettivo."""
    result: dict[int, int] = {}
    for legacy_id, area in build_area_canonica_map(legacy_ids).items():
        rep = area.reparto if area.reparto_id else None
        resp = resolve_responsabile_effettivo(area=area, reparto=rep)
        if resp is not None:
            result[legacy_id] = resp
    return result
