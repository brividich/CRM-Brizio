"""Catena dei riferimenti fra movimenti del registro (campo ``rif_op``).

``rif_op`` contiene uno o più ``id_registrazione`` separati da virgola. Può
citare direttamente i carichi (C) oppure il genitore immediato: lo scarico
originale O per R e M. Sul registro l'ordine è ``C → O → R → M``: al rientro
della quarta copia la rettifica R storna lo scarico originale con il peso a
destino, poi lo scarico effettivo M lo registra (stesso numero della R). Lo
storico del portale ha anche R che cita l'M. Per arrivare ai carichi la catena
va **risalita**.

Unico punto in cui si legge ``rif_op``: elenco a famiglie, validazione,
candidati del wizard e verifica di coerenza passano tutti da qui.
"""
from __future__ import annotations

__all__ = [
    "GENITORI_AMMESSI",
    "ORDINE_CATENA",
    "RIF_OP_MAX_DEPTH",
    "TIPI_NUMERO_CONDIVISO",
    "numero_condivisibile",
    "split_rif_op",
    "indice_per_id",
    "risali_a_carichi",
]

# Profondità massima di risalita della catena rif_op (protezione da catene assurde).
RIF_OP_MAX_DEPTH = 8

# Tipi che un movimento può citare in rif_op. Il genitore immediato è quello che
# propone il wizard; il carico C resta ammesso per M e R perché lo storico
# importato scrive spesso la catena dei carichi invece del genitore. In
# produzione (10/2026) R cita lo stesso movimento del suo M (lo scarico
# originale O o il carico C), non l'M: per R sono ammessi tutti e tre.
GENITORI_AMMESSI = {
    "O": frozenset({"C"}),
    "M": frozenset({"O", "C"}),
    "R": frozenset({"M", "O", "C"}),
}


ORDINE_CATENA = {"C": 0, "O": 1, "R": 2, "M": 3}

# Sul registro lo scarico effettivo M può portare lo stesso numero del suo
# scarico originale O (registro di produzione, 11/2026) o della sua rettifica R
# (le coppie R+M dello storico). Mai due movimenti dello stesso tipo, mai un C.
TIPI_NUMERO_CONDIVISO = frozenset({"O", "M", "R"})


def numero_condivisibile(registro, altri) -> bool:
    """`registro` può portare lo stesso numero dei movimenti `altri`?

    Sì solo se insieme formano O+M, M+R oppure O+M+R dello stesso codice CER.
    """
    from .validazione import normalizza_cer

    tutti = [registro, *altri]
    tipi = [r.tipo for r in tutti]
    return (
        "M" in tipi
        and len(tipi) == len(set(tipi))
        and set(tipi) <= TIPI_NUMERO_CONDIVISO
        and len({normalizza_cer(r.codice) for r in tutti}) == 1
    )


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
        # Numero condiviso (O e M, M e R): si risale dal movimento più a monte,
        # perché la M che cita la sua O con lo stesso numero citerebbe sé stessa.
        ordinati = sorted(candidati, key=lambda r: ORDINE_CATENA.get(r.tipo, 9))
        padre = next((r for r in ordinati if str(r.rif_op or "").strip()), None)
        if padre is None:
            continue
        carichi.extend(risali_a_carichi(padre.rif_op, by_id, depth + 1, visti))
    return carichi
