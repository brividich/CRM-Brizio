"""Numerazione automatica di corsi, edizioni e lezioni della formazione.

Il codice non si digita più a mano: si alloca. Tre livelli, una sola regola di
lettura — il codice dice *cosa* è, l'anno dice *quando*.

1. **Corso** — ``YYNNN`` a 5 cifre: le prime due sono l'anno di creazione, le
   ultime tre il progressivo di quell'anno. ``26066`` = 66° corso creato nel
   2026. Il contatore è una riga per anno (:class:`TrainingCourseCodeCounter`),
   allocata in transazione con ``select_for_update``: due utenti che salvano
   nello stesso istante non ottengono lo stesso numero.
2. **Edizione** — ``<codice corso>-<YY>E<N>``: il codice del corso, l'anno in
   cui l'edizione viene **erogata** e il progressivo di quell'anno per quel
   corso. ``26066-26E1``, ``26066-26E2``, poi ``26066-27E1`` a gennaio.

   *Perché l'anno anche sull'edizione.* Il codice corso porta l'anno di
   nascita del corso e non cambia più: un corso del 2026 ripetuto nel 2029
   resta ``26066``, altrimenti perderebbe identità (qualifiche, requisiti e
   attestati storici sono agganciati lì). Ma «quante edizioni abbiamo erogato
   nel 2027» è la domanda che si fa davvero, e senza l'anno sull'edizione la
   risposta richiede di aprire le date. Con ``26066-27E1`` il progressivo
   riparte ogni anno e si legge a colpo d'occhio.
3. **Lezione** — ``TrainingLesson.numero`` progressivo dentro l'edizione,
   assegnato in automatico al primo posto libero.

**Codici storici.** I corsi già esistenti conservano il loro codice (``SIC-1``,
sigle dal titolo, codici d'importazione): sono citati su attestati già emessi,
export e MOD.128. Lo schema nuovo vale solo per i corsi creati da qui in avanti,
e l'edizione di un corso storico usa comunque il formato nuovo agganciato al
codice storico (``SIC-1-27E1``).
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

__all__ = [
    "anno_corrente",
    "alloca_codice_corso",
    "anteprima_codice_corso",
    "genera_codice_sessione",
    "prossimo_numero_lezione",
]

# Larghezza del progressivo dentro l'anno: 26066 = anno 26, corso 066.
PAD_CORSO = 3


def anno_corrente() -> int:
    """Anno solare a 4 cifre secondo il fuso configurato."""
    return timezone.localdate().year


def _yy(anno: int) -> str:
    """Ultime due cifre dell'anno, zero-riempite: 2026 -> ``'26'``."""
    return f"{anno % 100:02d}"


@transaction.atomic
def alloca_codice_corso(anno: int | None = None) -> str:
    """Alloca e **consuma** il prossimo codice corso ``YYNNN`` per l'anno.

    Non è una "proposta": il numero viene bruciato sul contatore, quindi va
    chiamata solo quando il corso si sta davvero salvando (per la sola anteprima
    a video esiste :func:`anteprima_codice_corso`). ``select_for_update`` serializza
    i salvataggi concorrenti; il ciclo successivo salta i codici già occupati da
    dati importati o da un contatore disallineato.
    """
    from ..models_formazione import TrainingCourse, TrainingCourseCodeCounter

    anno = int(anno or anno_corrente())
    counter, _ = TrainingCourseCodeCounter.objects.get_or_create(anno=anno)
    counter = (
        TrainingCourseCodeCounter.objects.select_for_update().get(pk=counter.pk)
    )
    yy = _yy(anno)
    while True:
        counter.ultimo += 1
        codice = f"{yy}{counter.ultimo:0{PAD_CORSO}d}"
        if not TrainingCourse.objects.filter(codice=codice).exists():
            counter.save(update_fields=["ultimo"])
            return codice


def anteprima_codice_corso(anno: int | None = None) -> str:
    """Il codice che :func:`alloca_codice_corso` assegnerebbe adesso, **senza**
    consumarlo. Solo per mostrarlo nel form: il valore definitivo è quello
    allocato al salvataggio, e può differire se qualcun altro salva prima.
    """
    from ..models_formazione import TrainingCourse, TrainingCourseCodeCounter

    anno = int(anno or anno_corrente())
    ultimo = (
        TrainingCourseCodeCounter.objects.filter(anno=anno)
        .values_list("ultimo", flat=True)
        .first()
        or 0
    )
    yy = _yy(anno)
    n = ultimo + 1
    while TrainingCourse.objects.filter(codice=f"{yy}{n:0{PAD_CORSO}d}").exists():
        n += 1
    return f"{yy}{n:0{PAD_CORSO}d}"


def genera_codice_sessione(corso, anno: int | None = None) -> str:
    """Codice edizione ``<codice corso>-<YY>E<N>`` per l'anno di erogazione.

    ``anno`` è l'anno in cui l'edizione parte (in genere ``data_inizio.year``);
    omesso, vale l'anno corrente. ``N`` riparte da 1 a ogni anno solare per quel
    corso. Fallback su ``SESS`` se il corso non ha codice.

    Convive con i codici storici ``<CORSO>-E<N>``, che non vengono toccati: il
    prefisso è diverso (``-26E`` contro ``-E``), quindi i due schemi non si
    contendono gli stessi progressivi.
    """
    from ..models_formazione import TrainingSession

    if isinstance(anno, date):  # comodità: si può passare direttamente la data
        anno = anno.year
    anno = int(anno or anno_corrente())
    base = (getattr(corso, "codice", "") or "").strip().upper() or "SESS"
    prefix = f"{base}-{_yy(anno)}E"

    best = 0
    for c in TrainingSession.objects.filter(
        codice_sessione__startswith=prefix
    ).values_list("codice_sessione", flat=True):
        tail = str(c or "")[len(prefix):]
        if tail.isdigit() and int(tail) > best:
            best = int(tail)

    n = best + 1
    codice = f"{prefix}{n}"[:40]
    # Cintura e bretelle: il vincolo è unique, meglio un giro in più che un IntegrityError.
    while TrainingSession.objects.filter(codice_sessione=codice).exists():
        n += 1
        codice = f"{prefix}{n}"[:40]
    return codice


def prossimo_numero_lezione(sessione) -> int:
    """Primo ``numero`` libero fra le lezioni dell'edizione (parte da 1).

    ``(sessione, numero)`` è unique: si guarda il massimo in uso invece di
    contare le righe, così cancellare la lezione 2 di tre non fa rinascere un
    numero già stampato su un registro firme.
    """
    from ..models_formazione import TrainingLesson

    if sessione is None or not getattr(sessione, "pk", None):
        return 1
    massimo = (
        TrainingLesson.objects.filter(sessione=sessione)
        .order_by("-numero")
        .values_list("numero", flat=True)
        .first()
    )
    return (massimo or 0) + 1
