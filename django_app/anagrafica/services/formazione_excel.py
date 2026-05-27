"""Servizi di import/export Excel per il modulo Formazione HR.

PATCH-05: stub `import_iscritti_from_xlsx` predisposto — implementazione in PATCH-07.
PATCH-07: implementare tutti gli 8 export definiti in BOZZA_MODULO_FORMAZIONE.md § F.
"""
from __future__ import annotations

from pathlib import Path


def import_iscritti_from_xlsx(file_path: str | Path, sessione_id: int, created_by_id: int) -> dict:
    """Importa iscrizioni a una sessione da file Excel.

    TODO PATCH-07 — da implementare.

    Colonne attese nel foglio "Iscritti":
        legacy_anagrafica_id | cognome_nome | note (opzionale)

    Returns:
        dict con chiavi: righe_lette, iscrizioni_create, iscrizioni_duplicate, errori
    """
    raise NotImplementedError(
        "import_iscritti_from_xlsx non ancora implementato — disponibile da PATCH-07. "
        "Per ora usare l'iscrizione manuale dalla UI."
    )
