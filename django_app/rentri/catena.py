"""Catena dei riferimenti fra movimenti del registro (campo ``rif_op``).

``rif_op`` contiene uno o più ``id_registrazione`` separati da virgola. Può
citare direttamente i carichi (C) oppure il genitore immediato: lo scarico
originale O per un M, lo scarico effettivo M per un R. La catena completa è
``C ← O ← M ← R`` e per arrivare ai carichi va **risalita**.

Unico punto in cui si legge ``rif_op``: elenco a famiglie, validazione,
candidati del wizard e verifica di coerenza passano tutti da qui.
"""
from __future__ import annotations

__all__ = [
    "GENITORI_AMMESSI",
    "RIF_OP_MAX_DEPTH",
    "split_rif_op",
    "indice_per_id",
    "risali_a_carichi",
]

# Profondità massima di risalita della catena rif_op (protezione da catene assurde).
RIF_OP_MAX_DEPTH = 8

# Tipi che un movimento può citare in rif_op. Il genitore immediato è quello che
# propone il wizard; il carico C resta ammesso per M e R perché lo storico
# importato scrive spesso la catena dei carichi invece del genitore.
GENITORI_AMMESSI = {
    "O": frozenset({"C"}),
    "M": frozenset({"O", "C"}),
    "R": frozenset({"M", "C"}),
}


def split_rif_op(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def indice_per_id(records) -> dict[str, list]:
    """``id_registrazione`` → movimenti con quel numero (gli id storici possono ripetersi)."""
    by_id: dict[str, list] = {}
    for r in records:
        by_id.setdefault(str(r.id_registrazione or "").strip(), []).append(r)
    return by_id


def risali_a_carichi(rif: str, by_id: dict, depth: int = 0, visti: set | None = None) -> list[str]:
    """Risolve un ``rif_op`` negli id dei carichi (C) d'origine.

    Se un id cita un genitore O o M invece del carico, si risale il ``rif_op``
    del genitore; cicli e catene oltre :data:`RIF_OP_MAX_DEPTH` si fermano.
    """
    if depth > RIF_OP_MAX_DEPTH:
        return []
    visti = set() if visti is None else visti
    carichi: list[str] = []
    for rid in split_rif_op(rif):
        if rid in visti:
            continue
        visti.add(rid)
        candidati = by_id.get(rid) or []
        if any(r.tipo == "C" for r in candidati):
            carichi.append(rid)
            continue
        padre = next((r for r in candidati if str(r.rif_op or "").strip()), None)
        if padre is None:
            continue
        carichi.extend(risali_a_carichi(padre.rif_op, by_id, depth + 1, visti))
    return carichi
