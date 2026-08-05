"""Valutazione di efficacia della formazione (catena dell'evidenza, anello 8).

ISO 45001 §7.2 e ISO 9001 §7.2 non chiedono di aver *erogato* la formazione:
chiedono di sapere se ha prodotto competenza. Il modulo sapeva raccontare
benissimo la prima cosa e nulla della seconda.

Il ciclo è: al completamento nasce una valutazione **attesa** (se il corso la
prevede), a scadenza compare fra le pendenze del preposto, e viene compilata con
un esito. Se l'esito non è pieno si concorda un'azione e si può **rivalutare**:
le due valutazioni restano entrambe, perché entrambe sono storia.

Funzioni pure di dominio, nessuna dipendenza dalla request.
"""
from __future__ import annotations

from datetime import date

__all__ = [
    "aggiungi_mesi",
    "mesi_efficacia_richiesti",
    "pianifica_valutazione_efficacia",
    "valutazioni_da_fare",
]


def aggiungi_mesi(quando: date, mesi: int) -> date:
    """``quando`` + ``mesi``, senza dipendenze esterne.

    Il giorno viene arretrato all'ultimo valido del mese di arrivo: 31 gennaio
    più un mese è il 28 (o 29) febbraio, non un errore.
    """
    if not mesi:
        return quando
    anno = quando.year + (quando.month - 1 + mesi) // 12
    mese = (quando.month - 1 + mesi) % 12 + 1
    giorno = quando.day
    while giorno > 0:
        try:
            return date(anno, mese, giorno)
        except ValueError:
            giorno -= 1
    return quando


def mesi_efficacia_richiesti(corso) -> int:
    """Mesi previsti dalla regola di superamento del corso, 0 se non richiesta."""
    try:
        regola = corso.regola_superamento
    except Exception:
        return 0
    if not getattr(regola, "is_active", True):
        return 0
    return int(getattr(regola, "valutazione_efficacia_mesi", 0) or 0)


def pianifica_valutazione_efficacia(record) -> object | None:
    """Apre la valutazione attesa per un completamento, se il corso la prevede.

    Idempotente: chiamata due volte sullo stesso record non genera doppioni,
    perché il completamento va a buon fine una volta sola ma i flussi che lo
    creano sono più d'uno (aula, completamento diretto, import).

    Ritorna la valutazione creata, oppure ``None`` se non serviva.
    """
    from ..models_formazione import TrainingEfficacia

    if record is None or not record.data_completamento:
        return None
    # Una formazione non superata non si valuta sul campo: non c'è nulla di cui
    # misurare l'efficacia.
    if record.idoneo is False:
        return None

    mesi = mesi_efficacia_richiesti(record.corso) if record.corso_id else 0
    if not mesi:
        return None

    if record.valutazioni_efficacia.exists():
        return None

    return TrainingEfficacia.objects.create(
        record=record,
        legacy_anagrafica_id=record.legacy_anagrafica_id,
        attesa_dal=aggiungi_mesi(record.data_completamento, mesi),
    )


def valutazioni_da_fare(entro: date | None = None, legacy_anagrafica_id: int | None = None):
    """Valutazioni dovute e non ancora compilate, le più vecchie per prime.

    ``entro`` di default è oggi: si mostra ciò che è già dovuto, non ciò che lo
    sarà. Un elenco che anticipa le scadenze future si ignora in fretta.
    """
    from django.utils import timezone as _tz

    from ..models_formazione import TrainingEfficacia

    qs = (
        TrainingEfficacia.objects
        .filter(valutata_il__isnull=True, attesa_dal__lte=entro or _tz.localdate())
        .select_related("record", "record__corso")
    )
    if legacy_anagrafica_id is not None:
        qs = qs.filter(legacy_anagrafica_id=legacy_anagrafica_id)
    return qs.order_by("attesa_dal", "id")
