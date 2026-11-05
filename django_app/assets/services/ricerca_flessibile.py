"""Ricerca testuale «elastica» del modulo Assets.

Prima la ricerca era letterale: «dixi 80» trovava solo chi conteneva proprio
«dixi 80», non «DIXI80» ne' «Dixi-80». Qui un termine trova un oggetto se:

1. un campo contiene il termine cosi' com'e' (come prima);
2. un campo, tolti spazi, trattini, punti, barre e trattini bassi, contiene il
   termine compattato allo stesso modo («dixi 80» = «dixi80» = «DIXI-80»);
3. il termine ha piu' parole e ciascuna compare in almeno un campo, in
   qualunque ordine («80 dixi», «dixi reparto 3»).

Un solo punto per tutte le ricerche del modulo: la regola e' una sola.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from django.db.models import F, Q, Value
from django.db.models.functions import Replace
from django.db.models.lookups import IContains

# Separatori ignorati nel confronto «compatto».
_SEPARATORI = (" ", "-", ".", "/", "_")
_SPLIT = re.compile(r"[\s\-./_,;:]+")


def compatta(testo: str) -> str:
    return _SPLIT.sub("", (testo or "").strip())


def parole(testo: str) -> list[str]:
    return [p for p in _SPLIT.split((testo or "").strip()) if p]


def _campo_compatto(campo: str):
    espressione = F(campo)
    for separatore in _SEPARATORI:
        espressione = Replace(espressione, Value(separatore), Value(""))
    return espressione


def testo_q(termine: str, campi: Iterable[str], *, compatti: Iterable[str] | None = None) -> Q:
    """``Q`` che trova ``termine`` nei ``campi`` con le tre regole del modulo.

    ``compatti``: i campi su cui vale il confronto senza separatori (codici,
    nomi, modelli). Default: tutti i ``campi``. Per i testi lunghi (descrizioni,
    note) conviene escluderli: il confronto compatto costa di piu'.
    """
    termine = (termine or "").strip()
    campi = list(campi)
    if not termine or not campi:
        return Q()
    risultato = Q()
    for campo in campi:
        risultato |= Q(**{f"{campo}__icontains": termine})

    compatto = compatta(termine)
    if len(compatto) >= 2:
        for campo in (campi if compatti is None else list(compatti)):
            risultato |= Q(IContains(_campo_compatto(campo), compatto))

    elenco = parole(termine)
    if len(elenco) > 1:
        tutte = Q()
        for parola in elenco:
            una = Q()
            for campo in campi:
                una |= Q(**{f"{campo}__icontains": parola})
            tutte &= una
        risultato |= tutte
    return risultato
