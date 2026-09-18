"""Numerazione del registro RENTRI: il progressivo si alloca, non si conta.

L'``id_registrazione`` ha forma ``<anno>/<progressivo>`` (``2025/1847``) ed è la
chiave con cui gli scarichi dichiarano da quale carico provengono (campo
``rif_op``): se due movimenti portano lo stesso numero, il riferimento diventa
ambiguo e qualcuno — programma o persona — deve indovinare.

Fino al 2026-09 il numero nasceva da ``COUNT(*)`` dei movimenti dell'anno:

    count = RegistroRifiuti.objects.filter(data__year=year).count()
    id_registrazione = f"{year}/{count + 1:03d}"

Il conteggio coincide con la sequenza solo finché nessuno cancella nulla. Dopo
un'eliminazione arretra e il numero successivo **ripete** uno già assegnato; due
salvataggi simultanei leggono lo stesso conteggio e ottengono lo stesso numero.

Qui il progressivo vive su :class:`~rentri.models.RentriRegistroCounter` (una
riga per anno), allocato in transazione con ``select_for_update``. Il contatore
di un anno mai allocato parte dal **massimo già assegnato** in quell'anno, non
da zero, così i numeri storici (import compresi) non vengono riusati; il ciclo
salta comunque i numeri occupati.

Questo modulo **non corregge lo storico**: i duplicati già a database restano
finché non si decide come trattarli (comando di sola lettura
``rentri_id_duplicati`` per l'elenco).
"""
from __future__ import annotations

import re

from django.db import transaction
from django.utils import timezone

__all__ = [
    "PAD",
    "progressivo_di",
    "massimo_assegnato",
    "anteprima_id_registrazione",
    "alloca_id_registrazione",
    "id_duplicati",
]

# Larghezza minima del progressivo: 2026/001. I numeri storici più lunghi
# (2025/1847) restano tali, lo zero-riempimento non li accorcia.
PAD = 3

_ID_RE = re.compile(r"^(?P<anno>\d{4})/(?P<progressivo>\d+)$")


def progressivo_di(id_registrazione: str, anno: int | None = None) -> int | None:
    """Progressivo numerico di un ``id_registrazione``, se ha la forma attesa.

    Ritorna ``None`` per gli id di forma diversa (importati da sistemi terzi) e
    per quelli di un anno diverso da `anno`, quando indicato.
    """
    match = _ID_RE.match(str(id_registrazione or "").strip())
    if not match:
        return None
    if anno is not None and int(match.group("anno")) != int(anno):
        return None
    return int(match.group("progressivo"))


def massimo_assegnato(anno: int) -> int:
    """Massimo progressivo già presente a database per l'anno (0 se nessuno)."""
    from .models import RegistroRifiuti

    valori = RegistroRifiuti.objects.filter(
        id_registrazione__startswith=f"{anno}/"
    ).values_list("id_registrazione", flat=True)
    progressivi = [p for p in (progressivo_di(v, anno) for v in valori) if p is not None]
    return max(progressivi, default=0)


def _counter_bloccato(anno: int):
    """Riga del contatore dell'anno, bloccata per l'aggiornamento.

    Alla prima allocazione dell'anno il contatore viene allineato al massimo già
    assegnato: senza questo, un database con storico ripartirebbe da 1.
    """
    from .models import RentriRegistroCounter

    RentriRegistroCounter.objects.get_or_create(anno=anno)
    counter = RentriRegistroCounter.objects.select_for_update().get(anno=anno)
    if counter.ultimo == 0:
        counter.ultimo = massimo_assegnato(anno)
    return counter


def anteprima_id_registrazione(anno: int | None = None) -> str:
    """Il numero che verrebbe assegnato adesso, **senza** consumarlo.

    Solo per mostrarlo a video: il valore definitivo è quello allocato al
    salvataggio e può differire se qualcun altro salva prima.
    """
    from .models import RentriRegistroCounter

    anno = int(anno or timezone.localdate().year)
    ultimo = (
        RentriRegistroCounter.objects.filter(anno=anno)
        .values_list("ultimo", flat=True)
        .first()
        or 0
    )
    return f"{anno}/{max(ultimo, massimo_assegnato(anno)) + 1:0{PAD}d}"


@transaction.atomic
def alloca_id_registrazione(anno: int | None = None) -> str:
    """Alloca e **consuma** il prossimo ``id_registrazione`` dell'anno.

    Il numero viene bruciato sul contatore, quindi va chiamata solo quando il
    movimento si sta davvero salvando (per la sola anteprima esiste
    :func:`anteprima_id_registrazione`).
    """
    from .models import RegistroRifiuti

    anno = int(anno or timezone.localdate().year)
    counter = _counter_bloccato(anno)
    while True:
        counter.ultimo += 1
        candidato = f"{anno}/{counter.ultimo:0{PAD}d}"
        if not RegistroRifiuti.objects.filter(id_registrazione=candidato).exists():
            counter.save(update_fields=["ultimo"])
            return candidato


def id_duplicati() -> list[dict]:
    """Numeri di registrazione usati da più di un movimento, con le loro righe.

    Sola lettura, per il comando di audit. Il caso di gran lunga più frequente in
    produzione è la coppia **R + M dello stesso giorno** (rettifica e scarico
    effettivo registrati insieme, importi opposti): è marcata a parte perché
    sembra un modo di lavorare deliberato, non un incidente di numerazione.
    """
    from collections import defaultdict

    from .models import RegistroRifiuti

    per_id: dict[str, list] = defaultdict(list)
    for r in RegistroRifiuti.objects.exclude(id_registrazione="").order_by("data", "id"):
        per_id[r.id_registrazione].append(r)

    gruppi = []
    for id_reg, righe in per_id.items():
        if len(righe) < 2:
            continue
        tipi = sorted(r.tipo for r in righe)
        date_uguali = len({r.data for r in righe}) == 1
        gruppi.append({
            "id_registrazione": id_reg,
            "righe": righe,
            "coppia_rm": len(righe) == 2 and tipi == ["M", "R"] and date_uguali,
            "codici": sorted({(r.codice or "").strip() for r in righe}),
        })
    gruppi.sort(key=lambda g: (g["coppia_rm"], g["id_registrazione"]))
    return gruppi
