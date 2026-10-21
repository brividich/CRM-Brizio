"""Salvataggio di una scheda processo con la sua revisione.

Unico punto che scrive il catalogo processi: lo usano la scheda del Sistema di
Gestione e la Struttura organizzativa dell'Anagrafica (owner e tipo si modificano
da entrambe le parti, stessa riga e stessa storia delle revisioni).
"""
from __future__ import annotations

from django.db import transaction

from ..models import Processo, ProcessoRevisione


@transaction.atomic
def salva_processo(processo: Processo, *, motivo: str, user=None, nuovo: bool | None = None) -> Processo:
    motivo = (motivo or "").strip()[:500]
    if not motivo:
        raise ValueError("Scrivi il motivo della revisione.")
    if nuovo is None:
        nuovo = processo.pk is None
    if not nuovo:
        processo.revisione += 1
    processo.save()
    autore = user if getattr(user, "pk", None) else None
    ProcessoRevisione.objects.create(processo=processo, numero=processo.revisione, dati=processo.snapshot(),
                                     motivo=motivo, autore=autore)
    return processo
