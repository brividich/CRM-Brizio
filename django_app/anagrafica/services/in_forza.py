"""Chi è un ex dipendente: una sola regola per tutto il modulo.

È la regola del motore dei report (``reportistica.dati.Dipendente.in_forza_al``)
applicata alla sola parte «cessazione»:

- conta la cessazione del rapporto **corrente**: se dopo la cessazione c'è una
  riassunzione (``data_assunzione_ultima`` / ``data_prima_assunzione`` successiva),
  la vecchia data appartiene al rapporto precedente e la persona è in forza;
- il giorno di cessazione è l'ultimo giorno di lavoro: la persona è ex dipendente
  solo dal giorno dopo (una cessazione futura già registrata non la toglie oggi).

Le funzioni storiche (``views._helpers._cessati_legacy_ids``,
``training_eligibility._cessati_ids``, ``organigramma_albero.cessati_legacy_ids``)
delegano qui: nomi e firme restano quelli di prima.
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone


def cessazione_effettiva(data_cessazione: date | None, data_assunzione: date | None) -> date | None:
    """Cessazione del rapporto corrente (None se una riassunzione la supera)."""
    if data_cessazione and data_assunzione and data_assunzione > data_cessazione:
        return None
    return data_cessazione


def cessati_ids(oggi: date | None = None) -> set[int]:
    """``legacy_anagrafica_id`` degli ex dipendenti alla data ``oggi`` (default: oggi)."""
    from ..models import DipendenteAnagraficaAziendale

    giorno = oggi or timezone.localdate()
    out: set[int] = set()
    righe = (
        DipendenteAnagraficaAziendale.objects
        .filter(data_cessazione__isnull=False, data_cessazione__lt=giorno)
        .values_list("legacy_anagrafica_id", "data_cessazione",
                     "data_assunzione_ultima", "data_prima_assunzione")
    )
    for lid, cessazione, ultima, prima in righe:
        if not lid:
            continue
        effettiva = cessazione_effettiva(cessazione, ultima or prima)
        if effettiva and effettiva < giorno:
            out.add(int(lid))
    return out


#: Alias con il nome storico usato nelle viste.
cessati_legacy_ids = cessati_ids
