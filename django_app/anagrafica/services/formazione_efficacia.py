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


def mesi_efficacia_richiesti(corso, record=None) -> int:
    """Mesi previsti: la regola del corso, se indicata; altrimenti, per i corsi in aula
    (completamento da una sessione non online), quelli del tipo di corso. 0 = non richiesta."""
    try:
        regola = corso.regola_superamento
    except Exception:
        regola = None
    if regola is not None and getattr(regola, "is_active", True) and regola.valutazione_efficacia_mesi:
        return int(regola.valutazione_efficacia_mesi)
    if record is None or not getattr(record, "sessione_id", None) or getattr(corso, "is_elearning", False):
        return 0
    if getattr(record.sessione, "modalita", "") == "ONLINE":
        return 0
    tipo = getattr(corso, "tipo", None)
    if tipo is not None:
        return int(getattr(tipo, "efficacia_mesi", 0) or 0)
    return mesi_efficacia_senza_tipo()


def mesi_efficacia_senza_tipo() -> int:
    """Mesi predefiniti per i corsi in aula senza tipo (Tipi di corso → «Corsi senza tipo»)."""
    try:
        from ..models_formazione import AttestatoFormazioneConfig
        return int(AttestatoFormazioneConfig.get_instance().efficacia_mesi_senza_tipo or 0)
    except Exception:  # noqa: BLE001 - configurazione illeggibile: meglio nessuna valutazione che un errore
        return 0


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

    mesi = mesi_efficacia_richiesti(record.corso, record) if record.corso_id else 0
    if not mesi:
        return None

    if record.valutazioni_efficacia.exists():
        return None

    return TrainingEfficacia.objects.create(
        record=record,
        legacy_anagrafica_id=record.legacy_anagrafica_id,
        attesa_dal=aggiungi_mesi(record.data_completamento, mesi),
    )


def valutazioni_da_fare(entro: date | None = None, legacy_anagrafica_id: int | None = None, *,
                        oggi: date | None = None, anticipo_giorni: int = 0):
    """Valutazioni dovute e non ancora compilate, le più vecchie per prime.

    Unica regola per «dovute» (pagina Efficacia, «Le mie attività», report): non compilate e
    attese entro ``entro`` (di default oggi + ``anticipo_giorni``). Senza anticipo si mostra
    ciò che è già dovuto; la pagina Efficacia e «Le mie attività» anticipano di 15 giorni
    (``formazione_aula.ANTICIPO_GIORNI_EFFICACIA``) e segnano «scaduta» ciò che è già dovuto.
    """
    from datetime import timedelta

    from django.utils import timezone as _tz

    from ..models_formazione import TrainingEfficacia

    if entro is None:
        entro = (oggi or _tz.localdate()) + timedelta(days=anticipo_giorni or 0)
    qs = (
        TrainingEfficacia.objects
        .filter(valutata_il__isnull=True, attesa_dal__lte=entro)
        .select_related("record", "record__corso")
    )
    if legacy_anagrafica_id is not None:
        qs = qs.filter(legacy_anagrafica_id=legacy_anagrafica_id)
    return qs.order_by("attesa_dal", "id")
