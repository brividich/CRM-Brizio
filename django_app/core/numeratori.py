"""Progressivi «PREFISSO-ANNO-NNNN» letti in ordine numerico (audit 22/11, voce [50]).

Ordinare come testo un numero con zeri iniziali regge solo finché le cifre restano le stesse:
«RAIS-2026-99» viene dopo «RAIS-2026-100», e il progressivo successivo si ripete. Qui l'ultimo
numero si cerca prima per lunghezza e poi per valore, così 100 viene dopo 99 anche in SQL Server.
"""
from __future__ import annotations

import re

from django.db.models.functions import Length

_CODA_NUMERICA = re.compile(r"(\d+)$")


def prossimo_progressivo(queryset, campo: str, prefisso: str, *, cifre: int = 4) -> str:
    """Numero successivo all'ultimo che inizia con ``prefisso``, con almeno ``cifre`` cifre."""
    ultimo = (
        queryset.filter(**{f"{campo}__startswith": prefisso})
        .annotate(_lunghezza_numero=Length(campo))
        .order_by("-_lunghezza_numero", f"-{campo}")
        .values_list(campo, flat=True)
        .first()
    )
    progressivo = 1
    if ultimo:
        trovato = _CODA_NUMERICA.search(ultimo[len(prefisso):])
        if trovato:
            progressivo = int(trovato.group(1)) + 1
    return f"{prefisso}{progressivo:0{cifre}d}"
